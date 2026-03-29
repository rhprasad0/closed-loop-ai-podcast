"""Integration test for the Post-Production Lambda handler.

Uses real S3, real Postgres, and real ffmpeg (installed in devcontainer at /usr/bin/ffmpeg).
Pre-uploads a 1-second silent MP3 and 1x1 PNG to S3 before invoking the handler.
"""

from __future__ import annotations

import io
import struct
import subprocess
import zlib
from typing import Any
from unittest.mock import MagicMock

import boto3
import pytest


# ---------------------------------------------------------------------------
# Helpers to generate minimal valid test media files
# ---------------------------------------------------------------------------


def _make_1x1_png() -> bytes:
    """Return a minimal valid 1x1 white PNG as bytes.

    Constructed manually per the PNG spec — no external dependencies.
    """

    def _chunk(chunk_type: bytes, data: bytes) -> bytes:
        length = struct.pack(">I", len(data))
        crc = struct.pack(">I", zlib.crc32(chunk_type + data) & 0xFFFFFFFF)
        return length + chunk_type + data + crc

    signature = b"\x89PNG\r\n\x1a\n"
    ihdr = _chunk(b"IHDR", struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0))  # 1x1 RGB8
    # Raw image data: filter byte 0x00, then RGB(255,255,255)
    raw = zlib.compress(b"\x00\xff\xff\xff")
    idat = _chunk(b"IDAT", raw)
    iend = _chunk(b"IEND", b"")
    return signature + ihdr + idat + iend


def _make_silent_mp3() -> bytes:
    """Generate a ~1-second silent MP3 using ffmpeg (available in devcontainer)."""
    result = subprocess.run(
        [
            "/usr/bin/ffmpeg",
            "-f",
            "lavfi",
            "-i",
            "anullsrc=r=44100:cl=mono",
            "-t",
            "1",
            "-q:a",
            "9",
            "-acodec",
            "libmp3lame",
            "-f",
            "mp3",
            "pipe:1",
        ],
        capture_output=True,
        check=True,
    )
    return result.stdout


# ---------------------------------------------------------------------------
# Test
# ---------------------------------------------------------------------------


@pytest.mark.integration
@pytest.mark.timeout(120)
def test_post_production_produces_valid_output(
    pipeline_metadata: dict[str, Any],
    lambda_context: MagicMock,
    test_s3_bucket: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Post-Production handler combines MP3 + PNG via ffmpeg, writes DB rows, uploads MP4."""
    import lambdas.post_production.handler as pp_handler
    from lambdas.post_production.handler import lambda_handler

    # Patch FFMPEG_PATH to the devcontainer binary (Lambda Layer not present here)
    monkeypatch.setattr(pp_handler, "FFMPEG_PATH", "/usr/bin/ffmpeg")

    execution_id: str = pipeline_metadata["execution_id"]
    s3 = boto3.client("s3")

    # --- Pre-upload test media files to expected S3 keys ---
    cover_art_key = f"episodes/{execution_id}/cover.png"
    tts_key = f"episodes/{execution_id}/episode.mp3"

    s3.put_object(Bucket=test_s3_bucket, Key=cover_art_key, Body=_make_1x1_png())
    s3.put_object(Bucket=test_s3_bucket, Key=tts_key, Body=_make_silent_mp3())

    # --- Build a full pipeline event ---
    script_text = (
        "**Hype:** Welcome to 0 Stars, 10 out of 10!\n"
        "**Roast:** It's a test. Nobody cares.\n"
        "**Phil:** But what is a test, really?"
    )

    event: dict[str, Any] = {
        "metadata": pipeline_metadata,
        "discovery": {
            "repo_url": "https://github.com/integration-test/test-repo",
            "repo_name": "test-repo",
            "repo_description": "A test repository for integration tests.",
            "developer_github": f"integration-test-{execution_id[-8:]}",
            "star_count": 3,
            "language": "Python",
            "discovery_rationale": "Selected for integration testing.",
            "key_files": ["README.md"],
            "technical_highlights": ["Pure Python, no dependencies."],
        },
        "research": {
            "developer_name": "Integration Tester",
            "developer_github": f"integration-test-{execution_id[-8:]}",
            "developer_bio": "Writes tests.",
            "public_repos_count": 1,
            "notable_repos": [],
            "commit_patterns": "Commits on weekdays.",
            "technical_profile": "Python generalist.",
            "interesting_findings": ["Builds integration tests."],
            "hiring_signals": ["Writes tests proactively."],
        },
        "script": {
            "text": script_text,
            "character_count": len(script_text),
            "segments": [
                "intro",
                "core_debate",
                "developer_deep_dive",
                "technical_appreciation",
                "hiring_manager",
                "outro",
            ],
            "featured_repo": "test-repo",
            "featured_developer": f"integration-test-{execution_id[-8:]}",
            "cover_art_suggestion": "Abstract terminal glow.",
        },
        "producer": {
            "verdict": "PASS",
            "score": 8,
            "notes": "Solid test script.",
        },
        "cover_art": {
            "s3_key": cover_art_key,
            "prompt_used": "A glowing terminal in the dark.",
        },
        "tts": {
            "s3_key": tts_key,
            "duration_seconds": 1,
            "character_count": len(script_text),
        },
    }

    # --- Invoke handler ---
    result = lambda_handler(event, lambda_context)

    # --- Structural assertions ---
    assert "episode_id" in result, "result missing 'episode_id'"
    assert "s3_mp4_key" in result, "result missing 's3_mp4_key'"

    assert isinstance(result["episode_id"], int) and result["episode_id"] > 0, (
        f"episode_id must be a positive integer, got {result['episode_id']!r}"
    )

    expected_mp4_key = f"episodes/{execution_id}/episode.mp4"
    assert result["s3_mp4_key"] == expected_mp4_key, (
        f"s3_mp4_key {result['s3_mp4_key']!r} does not match expected {expected_mp4_key!r}"
    )

    # --- Verify episode row exists in Postgres ---
    from shared.db import query as db_query

    rows = db_query(
        "SELECT episode_id FROM episodes WHERE execution_id = %s",
        (execution_id,),
    )
    assert len(rows) == 1, (
        f"Expected 1 episode row for execution_id {execution_id!r}, found {len(rows)}"
    )
    assert int(rows[0][0]) == result["episode_id"], (
        f"DB episode_id {rows[0][0]} does not match returned episode_id {result['episode_id']}"
    )

    # --- Verify MP4 object exists in S3 ---
    s3.head_object(Bucket=test_s3_bucket, Key=result["s3_mp4_key"])
