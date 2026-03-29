from __future__ import annotations

import os
from collections.abc import Generator
from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture
def mock_site_db() -> Generator[tuple[MagicMock, MagicMock], None, None]:
    """Mock Postgres connection for Site handler."""
    with patch("lambdas.site.handler.get_connection") as mock:
        conn = MagicMock()
        cursor = MagicMock()
        conn.cursor.return_value = cursor
        cursor.__enter__ = lambda s: s
        cursor.__exit__ = MagicMock(return_value=False)
        conn.__enter__ = lambda s: s
        conn.__exit__ = MagicMock(return_value=False)
        mock.return_value = conn
        yield conn, cursor


@pytest.fixture
def mock_site_presigned() -> Generator[MagicMock, None, None]:
    """Mock S3 presigned URL generation for Site handler."""
    with patch("lambdas.site.handler.generate_presigned_url") as mock:
        mock.return_value = "https://s3.presigned.example/episode.mp3"
        yield mock


def test_handler_returns_200_for_root(
    mock_site_db: tuple[MagicMock, MagicMock],
    mock_site_presigned: MagicMock,
    lambda_context: MagicMock,
) -> None:
    conn, cursor = mock_site_db
    cursor.description = [("episode_id",), ("repo_name",), ("air_date",)]
    cursor.fetchall.return_value = []

    from lambdas.site.handler import lambda_handler

    result = lambda_handler({"rawPath": "/"}, lambda_context)

    assert result["statusCode"] == 200
    assert "text/html" in result["headers"]["Content-Type"]


def test_handler_returns_404_for_unknown_path(
    mock_site_db: tuple[MagicMock, MagicMock],
    lambda_context: MagicMock,
) -> None:
    from lambdas.site.handler import lambda_handler

    result = lambda_handler({"rawPath": "/nonexistent"}, lambda_context)
    assert result["statusCode"] == 404


def test_handler_handles_empty_episodes(
    mock_site_db: tuple[MagicMock, MagicMock],
    mock_site_presigned: MagicMock,
    lambda_context: MagicMock,
) -> None:
    conn, cursor = mock_site_db
    cursor.description = [("episode_id",)]
    cursor.fetchall.return_value = []

    from lambdas.site.handler import lambda_handler

    result = lambda_handler({"rawPath": "/"}, lambda_context)

    assert result["statusCode"] == 200
    assert isinstance(result["body"], str)


def test_handler_returns_500_on_db_error(
    mock_site_db: tuple[MagicMock, MagicMock],
    lambda_context: MagicMock,
) -> None:
    conn, cursor = mock_site_db
    cursor.execute.side_effect = Exception("connection refused")

    from lambdas.site.handler import lambda_handler

    result = lambda_handler({"rawPath": "/"}, lambda_context)

    assert result["statusCode"] == 500


def test_episodes_in_reverse_chronological_order(
    mock_site_db: tuple[MagicMock, MagicMock],
    mock_site_presigned: MagicMock,
    lambda_context: MagicMock,
) -> None:
    conn, cursor = mock_site_db
    cursor.description = [
        ("episode_id",),
        ("repo_name",),
        ("air_date",),
        ("developer_github",),
        ("star_count_at_recording",),
        ("s3_mp3_path",),
        ("s3_cover_art_path",),
    ]
    cursor.fetchall.return_value = [
        (2, "newer-repo", "2025-07-13", "user2", 3, "ep2.mp3", "cover2.png"),
        (1, "older-repo", "2025-07-06", "user1", 5, "ep1.mp3", "cover1.png"),
    ]

    from lambdas.site.handler import lambda_handler

    result = lambda_handler({"rawPath": "/"}, lambda_context)

    body = result["body"]
    newer_pos = body.find("newer-repo")
    older_pos = body.find("older-repo")
    assert newer_pos < older_pos  # newer episode appears first


def test_episode_data_in_html(
    mock_site_db: tuple[MagicMock, MagicMock],
    mock_site_presigned: MagicMock,
    lambda_context: MagicMock,
) -> None:
    conn, cursor = mock_site_db
    cursor.description = [
        ("episode_id",),
        ("repo_name",),
        ("air_date",),
        ("developer_github",),
        ("star_count_at_recording",),
        ("s3_mp3_path",),
        ("s3_cover_art_path",),
    ]
    cursor.fetchall.return_value = [
        (1, "cool-project", "2025-07-06", "testuser", 7, "ep.mp3", "cover.png"),
    ]

    from lambdas.site.handler import lambda_handler

    result = lambda_handler({"rawPath": "/"}, lambda_context)

    assert "cool-project" in result["body"]
    assert "testuser" in result["body"]
    assert "2025-07-06" in result["body"]


def test_audio_player_has_presigned_url(
    mock_site_db: tuple[MagicMock, MagicMock],
    mock_site_presigned: MagicMock,
    lambda_context: MagicMock,
) -> None:
    conn, cursor = mock_site_db
    cursor.description = [
        ("episode_id",),
        ("repo_name",),
        ("air_date",),
        ("developer_github",),
        ("star_count_at_recording",),
        ("s3_mp3_path",),
        ("s3_cover_art_path",),
    ]
    cursor.fetchall.return_value = [
        (1, "repo", "2025-07-06", "user", 5, "episodes/test/episode.mp3", "cover.png"),
    ]

    with patch.dict(os.environ, {"S3_BUCKET": "test-bucket"}):
        from lambdas.site.handler import lambda_handler

        result = lambda_handler({"rawPath": "/"}, lambda_context)

    assert "https://s3.presigned.example/episode.mp3" in result["body"]
    mock_site_presigned.assert_called()
