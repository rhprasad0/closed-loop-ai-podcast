from __future__ import annotations

import json
import os
import subprocess
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from aws_lambda_powertools.utilities.typing import LambdaContext

from shared.db import get_connection
from shared.logging import get_logger
from shared.metrics import get_metrics
from shared.s3 import download_file, upload_file
from shared.tracing import get_tracer
from shared.types import PipelineState, PostProductionOutput

logger = get_logger("post_production")
tracer = get_tracer("post_production")
metrics = get_metrics("post_production")

# --- Module-level constants ---
EASTERN_TZ: ZoneInfo = ZoneInfo("America/New_York")
FFMPEG_PATH: str = "/opt/bin/ffmpeg"  # from the ffmpeg Lambda Layer


def _download_s3_file(bucket: str, key: str, local_path: str) -> None:
    """Download an S3 object to a local file path using shared.s3.download_file."""
    download_file(bucket, key, local_path)


def _run_ffmpeg(mp3_path: str, png_path: str, mp4_path: str) -> None:
    """Run ffmpeg to combine MP3 audio + PNG cover art into MP4 video.

    Command: ffmpeg -loop 1 -i {png_path} -i {mp3_path}
             -c:v libx264 -tune stillimage -c:a aac -b:a 128k
             -pix_fmt yuv420p -shortest {mp4_path}

    Uses subprocess.run with check=True.
    Raises RuntimeError on non-zero exit code.
    """
    cmd = [
        FFMPEG_PATH,
        "-loop",
        "1",
        "-i",
        png_path,
        "-i",
        mp3_path,
        "-c:v",
        "libx264",
        "-tune",
        "stillimage",
        "-c:a",
        "aac",
        "-b:a",
        "128k",
        "-pix_fmt",
        "yuv420p",
        "-shortest",
        mp4_path,
    ]
    result = subprocess.run(cmd, check=False, capture_output=True)
    if result.returncode != 0:
        stderr = result.stderr.decode("utf-8", errors="replace")
        raise RuntimeError(f"ffmpeg exited with code {result.returncode}: {stderr}")


def _insert_episode(
    conn: Any,
    execution_id: str,
    repo_url: str,
    repo_name: str,
    developer_github: str,
    developer_name: str,
    star_count: int,
    language: str,
    script_text: str,
    research_json: str,
    cover_art_prompt: str,
    s3_cover_art_path: str,
    s3_mp3_path: str,
    s3_mp4_path: str,
    producer_attempts: int,
    air_date: str,
) -> int:
    """INSERT into episodes table. Returns episode_id via RETURNING clause.

    Uses the connection's cursor directly (not shared.db.query) because this
    runs inside a transaction with _insert_featured_developer.
    """
    sql = """
        INSERT INTO episodes (
            execution_id,
            repo_url,
            repo_name,
            developer_github,
            developer_name,
            star_count_at_recording,
            language,
            script_text,
            research_json,
            cover_art_prompt,
            s3_cover_art_path,
            s3_mp3_path,
            s3_mp4_path,
            producer_attempts,
            air_date
        ) VALUES (
            %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
        )
        RETURNING episode_id
    """
    params = (
        execution_id,
        repo_url,
        repo_name,
        developer_github,
        developer_name,
        star_count,
        language,
        script_text,
        research_json,
        cover_art_prompt,
        s3_cover_art_path,
        s3_mp3_path,
        s3_mp4_path,
        producer_attempts,
        air_date,
    )
    with conn.cursor() as cur:
        cur.execute(sql, params)
        row = cur.fetchone()
    episode_id: int = row[0]
    return episode_id


def _insert_featured_developer(
    conn: Any,
    developer_github: str,
    episode_id: int,
    featured_date: str,
) -> None:
    """INSERT into featured_developers table.

    Uses the same connection/transaction as _insert_episode.
    """
    sql = """
        INSERT INTO featured_developers (developer_github, episode_id, featured_date)
        VALUES (%s, %s, %s)
    """
    with conn.cursor() as cur:
        cur.execute(sql, (developer_github, episode_id, featured_date))


@tracer.capture_lambda_handler
@metrics.log_metrics
@logger.inject_lambda_context(clear_state=True)
def lambda_handler(event: PipelineState, context: LambdaContext) -> PostProductionOutput:
    bucket = os.environ["S3_BUCKET"]
    execution_id = event["metadata"]["execution_id"]

    # S3 keys from upstream pipeline steps
    cover_art_key = event["cover_art"]["s3_key"]
    tts_key = event["tts"]["s3_key"]

    # Local /tmp paths for ffmpeg processing
    png_path = "/tmp/cover.png"
    mp3_path = "/tmp/episode.mp3"
    mp4_path = "/tmp/episode.mp4"

    logger.info("Downloading cover art and audio from S3")
    _download_s3_file(bucket, cover_art_key, png_path)
    _download_s3_file(bucket, tts_key, mp3_path)

    logger.info("Running ffmpeg to assemble MP4")
    _run_ffmpeg(mp3_path, png_path, mp4_path)

    # Upload MP4 to S3
    s3_mp4_key = f"episodes/{execution_id}/episode.mp4"
    logger.info("Uploading MP4 to S3", extra={"s3_key": s3_mp4_key})
    upload_file(bucket, s3_mp4_key, mp4_path, "video/mp4")

    # Compute air_date in Eastern Time
    air_date: str = datetime.now(EASTERN_TZ).strftime("%Y-%m-%d")

    # Serialize research object to JSON string for the jsonb column
    research_json: str = json.dumps(event["research"])

    # Gather all episode fields
    discovery = event["discovery"]
    research = event["research"]
    script = event["script"]
    cover_art = event["cover_art"]
    metadata = event["metadata"]

    logger.info("Writing episode record to Postgres")
    conn = get_connection()
    try:
        episode_id = _insert_episode(
            conn=conn,
            execution_id=execution_id,
            repo_url=discovery["repo_url"],
            repo_name=discovery["repo_name"],
            developer_github=discovery["developer_github"],
            developer_name=research["developer_name"],
            star_count=discovery["star_count"],
            language=discovery["language"],
            script_text=script["text"],
            research_json=research_json,
            cover_art_prompt=cover_art["prompt_used"],
            s3_cover_art_path=cover_art_key,
            s3_mp3_path=tts_key,
            s3_mp4_path=s3_mp4_key,
            producer_attempts=metadata["script_attempt"],
            air_date=air_date,
        )
        _insert_featured_developer(
            conn=conn,
            developer_github=discovery["developer_github"],
            episode_id=episode_id,
            featured_date=air_date,
        )
        conn.commit()
    finally:
        conn.close()

    logger.info("Post-production complete", extra={"episode_id": episode_id, "air_date": air_date})

    return PostProductionOutput(
        s3_mp4_key=s3_mp4_key,
        episode_id=episode_id,
        air_date=air_date,
    )
