from __future__ import annotations

import os
from typing import Any

from aws_lambda_powertools.utilities.typing import LambdaContext
from jinja2 import Environment, FileSystemLoader

from shared.db import get_connection
from shared.logging import get_logger
from shared.metrics import get_metrics
from shared.s3 import generate_presigned_url
from shared.tracing import get_tracer

logger = get_logger("site")
tracer = get_tracer("site")
metrics = get_metrics("site")

# --- Module-level constants ---
PRESIGNED_URL_EXPIRY: int = 3600  # 1 hour for audio player URLs

# SQL to fetch episode listing (excludes large fields)
EPISODES_QUERY: str = """
    SELECT
        episode_id,
        repo_name,
        developer_name,
        developer_github,
        air_date,
        star_count_at_recording,
        language,
        s3_cover_art_path,
        s3_mp3_path
    FROM episodes
    ORDER BY air_date DESC
"""


def _get_episodes() -> list[dict[str, Any]]:
    """Query episodes table, ordered by air_date DESC (most recent first).

    Returns list of dicts with episode metadata for the listing page.
    Excludes large fields (script_text, research_json, cover_art_prompt).
    On DB error, the handler returns a 500 response (not an unhandled exception).
    """
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(EPISODES_QUERY)
            columns = [desc[0] for desc in cur.description]
            rows = cur.fetchall()
            return [dict(zip(columns, row)) for row in rows]
    finally:
        conn.close()


def _render_template(template_name: str, **context: Any) -> str:
    """Render a Jinja2 template from the templates/ directory.

    Uses FileSystemLoader with the templates directory resolved via
    LAMBDA_TASK_ROOT (falling back to handler directory for local testing).
    """
    base_dir = os.environ.get("LAMBDA_TASK_ROOT", os.path.dirname(__file__))
    templates_dir = os.path.join(base_dir, "templates")
    env = Environment(loader=FileSystemLoader(templates_dir), autoescape=True)
    template = env.get_template(template_name)
    return template.render(**context)


def _build_response(
    status_code: int,
    body: str,
    content_type: str = "text/html",
) -> dict[str, object]:
    """Build a Lambda Function URL response dict.

    Returns {"statusCode": int, "headers": {"Content-Type": content_type}, "body": str}.
    """
    return {
        "statusCode": status_code,
        "headers": {"Content-Type": content_type},
        "body": body,
    }


@logger.inject_lambda_context(clear_state=True)
@tracer.capture_lambda_handler
@metrics.log_metrics
def lambda_handler(event: dict[str, object], context: LambdaContext) -> dict[str, object]:
    """Handle Lambda Function URL requests.

    Routing:
    - "/" -> episode listing page (200 with HTML)
    - All other paths -> 404

    Event format: Lambda Function URL events use rawPath for the request path,
    requestContext for metadata. See AWS docs for full event schema.
    """
    raw_path = str(event.get("rawPath", "/"))

    if raw_path != "/":
        logger.info("Unknown path, returning 404", extra={"path": raw_path})
        return _build_response(404, "<html><body><h1>404 Not Found</h1></body></html>")

    try:
        episodes = _get_episodes()
    except Exception:
        logger.exception("Failed to fetch episodes from database")
        return _build_response(500, "<html><body><h1>500 Internal Server Error</h1></body></html>")

    # Generate presigned URLs for MP3 audio playback
    s3_bucket = os.environ.get("S3_BUCKET", "")
    cloudfront_domain = os.environ.get("CLOUDFRONT_DOMAIN", "")  # e.g. "d123.cloudfront.net"

    for episode in episodes:
        mp3_key = episode.get("s3_mp3_path", "")
        if mp3_key and s3_bucket:
            try:
                episode["audio_url"] = generate_presigned_url(
                    s3_bucket, str(mp3_key), PRESIGNED_URL_EXPIRY
                )
            except Exception:
                logger.warning("Failed to generate presigned URL", extra={"key": mp3_key})
                episode["audio_url"] = ""
        else:
            episode["audio_url"] = ""

        # Cover art served via CloudFront /episodes/* path (not presigned URLs)
        cover_art_key = episode.get("s3_cover_art_path", "")
        if cover_art_key and cloudfront_domain:
            episode["cover_art_url"] = f"https://{cloudfront_domain}/{cover_art_key}"
        elif cover_art_key:
            # Fallback: use the S3 key directly as the path component
            episode["cover_art_url"] = f"/{cover_art_key}"
        else:
            episode["cover_art_url"] = ""

    try:
        html = _render_template("index.html", episodes=episodes)
    except Exception:
        logger.exception("Failed to render template")
        return _build_response(500, "<html><body><h1>500 Internal Server Error</h1></body></html>")

    return _build_response(200, html)
