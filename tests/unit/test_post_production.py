from __future__ import annotations

import os
import subprocess
from collections.abc import Generator
from typing import Any
from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_post_production_s3() -> Generator[tuple[MagicMock, MagicMock], None, None]:
    """Mock S3 download and upload for Post-Production."""
    with (
        patch("lambdas.post_production.handler.download_file") as mock_dl,
        patch("lambdas.post_production.handler.upload_file") as mock_ul,
    ):
        yield mock_dl, mock_ul


@pytest.fixture
def mock_post_production_db() -> Generator[tuple[MagicMock, MagicMock], None, None]:
    """Mock Postgres connection for Post-Production inserts."""
    with patch("lambdas.post_production.handler.get_connection") as mock:
        conn = MagicMock()
        cursor = MagicMock()
        conn.cursor.return_value = cursor
        cursor.__enter__ = lambda s: s
        cursor.__exit__ = MagicMock(return_value=False)
        conn.__enter__ = lambda s: s
        conn.__exit__ = MagicMock(return_value=False)
        cursor.fetchone.return_value = (42,)  # episode_id from RETURNING
        mock.return_value = conn
        yield conn, cursor


@pytest.fixture
def mock_ffmpeg() -> Generator[MagicMock, None, None]:
    """Mock subprocess.run for ffmpeg."""
    with patch("lambdas.post_production.handler.subprocess.run") as mock:
        mock.return_value = MagicMock(returncode=0)
        yield mock


@pytest.fixture
def full_pipeline_event(
    pipeline_metadata: dict[str, Any],
    sample_discovery_output: dict[str, Any],
    sample_research_output: dict[str, Any],
    sample_script_output: dict[str, Any],
) -> dict[str, Any]:
    """Full pipeline state for Post-Production handler input."""
    return {
        "metadata": pipeline_metadata,
        "discovery": sample_discovery_output,
        "research": sample_research_output,
        "script": sample_script_output,
        "producer": {"verdict": "PASS", "score": 8, "notes": "Good"},
        "cover_art": {"s3_key": "episodes/test-exec/cover.png", "prompt_used": "robots"},
        "tts": {
            "s3_key": "episodes/test-exec/episode.mp3",
            "duration_seconds": 180,
            "character_count": 4200,
        },
    }


# ---------------------------------------------------------------------------
# ffmpeg Tests
# ---------------------------------------------------------------------------


def test_run_ffmpeg_calls_subprocess(mock_ffmpeg: MagicMock) -> None:
    from lambdas.post_production.handler import _run_ffmpeg

    _run_ffmpeg("/tmp/episode.mp3", "/tmp/cover.png", "/tmp/episode.mp4")

    mock_ffmpeg.assert_called_once()
    args = mock_ffmpeg.call_args[0][0]
    assert "/opt/bin/ffmpeg" in args[0] or "ffmpeg" in args[0]
    assert "-shortest" in args
    assert "-c:v" in args
    assert "-tune" in args


def test_run_ffmpeg_raises_on_nonzero_exit(mock_ffmpeg: MagicMock) -> None:
    from lambdas.post_production.handler import _run_ffmpeg

    mock_ffmpeg.side_effect = subprocess.CalledProcessError(1, "ffmpeg")
    with pytest.raises((RuntimeError, subprocess.CalledProcessError)):
        _run_ffmpeg("/tmp/episode.mp3", "/tmp/cover.png", "/tmp/episode.mp4")


# ---------------------------------------------------------------------------
# Database Tests
# ---------------------------------------------------------------------------


def test_insert_episode_returns_episode_id(
    mock_post_production_db: tuple[MagicMock, MagicMock],
) -> None:
    from lambdas.post_production.handler import _insert_episode

    conn, cursor = mock_post_production_db
    result = _insert_episode(
        conn,
        execution_id="test",
        repo_url="https://github.com/u/r",
        repo_name="r",
        developer_github="u",
        developer_name="User",
        star_count=5,
        language="Python",
        script_text="text",
        research_json="{}",
        cover_art_prompt="art",
        s3_cover_art_path="cover.png",
        s3_mp3_path="ep.mp3",
        s3_mp4_path="ep.mp4",
        producer_attempts=1,
        air_date="2025-07-13",
    )
    assert result == 42


def test_insert_featured_developer_executes(
    mock_post_production_db: tuple[MagicMock, MagicMock],
) -> None:
    from lambdas.post_production.handler import _insert_featured_developer

    conn, cursor = mock_post_production_db
    _insert_featured_developer(
        conn, developer_github="user", episode_id=42, featured_date="2025-07-13"
    )
    assert cursor.execute.called


# ---------------------------------------------------------------------------
# Full Post-Production Handler Tests
# ---------------------------------------------------------------------------


def test_handler_returns_valid_output(
    lambda_context: MagicMock,
    full_pipeline_event: dict[str, Any],
    mock_post_production_s3: tuple[MagicMock, MagicMock],
    mock_post_production_db: tuple[MagicMock, MagicMock],
    mock_ffmpeg: MagicMock,
) -> None:
    with patch.dict(os.environ, {"S3_BUCKET": "test-bucket"}):
        from lambdas.post_production.handler import lambda_handler

        result = lambda_handler(full_pipeline_event, lambda_context)

    assert "s3_mp4_key" in result
    assert "episode_id" in result
    assert "air_date" in result
    assert result["episode_id"] == 42


def test_handler_s3_key_contains_execution_id(
    lambda_context: MagicMock,
    full_pipeline_event: dict[str, Any],
    mock_post_production_s3: tuple[MagicMock, MagicMock],
    mock_post_production_db: tuple[MagicMock, MagicMock],
    mock_ffmpeg: MagicMock,
) -> None:
    with patch.dict(os.environ, {"S3_BUCKET": "test-bucket"}):
        from lambdas.post_production.handler import lambda_handler

        result = lambda_handler(full_pipeline_event, lambda_context)

    exec_id = full_pipeline_event["metadata"]["execution_id"]
    assert exec_id in result["s3_mp4_key"]
    assert result["s3_mp4_key"].endswith(".mp4")


def test_handler_air_date_is_iso_format(
    lambda_context: MagicMock,
    full_pipeline_event: dict[str, Any],
    mock_post_production_s3: tuple[MagicMock, MagicMock],
    mock_post_production_db: tuple[MagicMock, MagicMock],
    mock_ffmpeg: MagicMock,
) -> None:
    with patch.dict(os.environ, {"S3_BUCKET": "test-bucket"}):
        from lambdas.post_production.handler import lambda_handler

        result = lambda_handler(full_pipeline_event, lambda_context)

    # YYYY-MM-DD format
    assert len(result["air_date"]) == 10
    assert result["air_date"].count("-") == 2


def test_handler_downloads_cover_art_and_mp3(
    lambda_context: MagicMock,
    full_pipeline_event: dict[str, Any],
    mock_post_production_s3: tuple[MagicMock, MagicMock],
    mock_post_production_db: tuple[MagicMock, MagicMock],
    mock_ffmpeg: MagicMock,
) -> None:
    mock_dl, _ = mock_post_production_s3
    with patch.dict(os.environ, {"S3_BUCKET": "test-bucket"}):
        from lambdas.post_production.handler import lambda_handler

        lambda_handler(full_pipeline_event, lambda_context)

    assert mock_dl.call_count == 2  # cover art + MP3
