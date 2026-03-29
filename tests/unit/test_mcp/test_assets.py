from __future__ import annotations

import asyncio
from unittest.mock import MagicMock, patch

from tests.unit.test_mcp.conftest import S3_BUCKET


def test_get_episode_assets_returns_presigned_urls(mock_s3_client, mock_mcp_db):
    """Episode with all three assets returns presigned URLs for each."""
    conn, cursor = mock_mcp_db

    with patch("lambdas.mcp.tools.assets.db.get_connection", return_value=conn):
        with patch(
            "lambdas.mcp.tools.assets.generate_presigned_url",
            return_value="https://presigned-url",
        ) as mock_presign:
            from lambdas.mcp.tools.assets import get_episode_assets

            cursor.fetchone.return_value = (
                "episodes/test/cover.png",
                "episodes/test/episode.mp3",
                "episodes/test/episode.mp4",
            )

            result = asyncio.run(get_episode_assets(episode_id=1))

            assert result["cover_art_url"] == "https://presigned-url"
            assert result["mp3_url"] == "https://presigned-url"
            assert result["mp4_url"] == "https://presigned-url"
            assert mock_presign.call_count == 3


def test_get_episode_assets_not_found(mock_s3_client, mock_mcp_db):
    """Non-existent episode returns error dict."""
    conn, cursor = mock_mcp_db

    with patch("lambdas.mcp.tools.assets.db.get_connection", return_value=conn):
        from lambdas.mcp.tools.assets import get_episode_assets

        cursor.fetchone.return_value = None

        result = asyncio.run(get_episode_assets(episode_id=999))

        assert "error" in result
        assert "999" in result["error"]


def test_get_episode_assets_null_for_missing(mock_s3_client, mock_mcp_db):
    """Episode with only cover art returns None for missing mp3/mp4."""
    conn, cursor = mock_mcp_db

    with patch("lambdas.mcp.tools.assets.db.get_connection", return_value=conn):
        with patch(
            "lambdas.mcp.tools.assets.generate_presigned_url",
            return_value="https://presigned-url",
        ):
            from lambdas.mcp.tools.assets import get_episode_assets

            cursor.fetchone.return_value = ("episodes/test/cover.png", None, None)

            result = asyncio.run(get_episode_assets(episode_id=1))

            assert result["cover_art_url"] == "https://presigned-url"
            assert result["mp3_url"] is None
            assert result["mp4_url"] is None


def test_get_episode_assets_returns_s3_keys(mock_s3_client, mock_mcp_db):
    """Response includes raw S3 keys alongside presigned URLs."""
    conn, cursor = mock_mcp_db

    with patch("lambdas.mcp.tools.assets.db.get_connection", return_value=conn):
        with patch(
            "lambdas.mcp.tools.assets.generate_presigned_url",
            return_value="https://presigned-url",
        ):
            from lambdas.mcp.tools.assets import get_episode_assets

            cursor.fetchone.return_value = (
                "episodes/test/cover.png",
                "episodes/test/episode.mp3",
                "episodes/test/episode.mp4",
            )

            result = asyncio.run(get_episode_assets(episode_id=1))

            assert result["s3_keys"]["cover"] == "episodes/test/cover.png"
            assert result["s3_keys"]["mp3"] == "episodes/test/episode.mp3"
            assert result["s3_keys"]["mp4"] == "episodes/test/episode.mp4"


def test_list_s3_assets_passes_prefix(mock_s3_client):
    """Prefix is forwarded to S3 ListObjectsV2."""
    from lambdas.mcp.tools.assets import list_s3_assets

    mock_s3_client.list_objects_v2.return_value = {
        "Contents": [
            {
                "Key": "episodes/test/cover.png",
                "Size": 1024,
                "LastModified": MagicMock(strftime=MagicMock(return_value="2025-07-13T09:00:00.000Z")),
            },
        ],
    }

    with patch("lambdas.mcp.tools.assets._s3", mock_s3_client):
        result = asyncio.run(list_s3_assets(prefix="episodes/test/"))

    mock_s3_client.list_objects_v2.assert_called_once()
    call_kwargs = mock_s3_client.list_objects_v2.call_args.kwargs
    assert call_kwargs["Prefix"] == "episodes/test/"
    assert len(result["objects"]) == 1


def test_list_s3_assets_empty_bucket(mock_s3_client):
    """Empty bucket (no Contents key) returns empty list."""
    from lambdas.mcp.tools.assets import list_s3_assets

    mock_s3_client.list_objects_v2.return_value = {}  # No Contents key

    with patch("lambdas.mcp.tools.assets._s3", mock_s3_client):
        result = asyncio.run(list_s3_assets())

    assert result["objects"] == []


def test_list_s3_assets_respects_limit(mock_s3_client):
    """Custom limit is forwarded as MaxKeys."""
    from lambdas.mcp.tools.assets import list_s3_assets

    mock_s3_client.list_objects_v2.return_value = {"Contents": []}

    with patch("lambdas.mcp.tools.assets._s3", mock_s3_client):
        asyncio.run(list_s3_assets(limit=10))

    call_kwargs = mock_s3_client.list_objects_v2.call_args.kwargs
    assert call_kwargs["MaxKeys"] == 10


def test_get_presigned_url_default_expiry(mock_s3_client):
    """Default expiry is 3600 seconds."""
    with patch(
        "lambdas.mcp.tools.assets.generate_presigned_url",
        return_value="https://presigned-url",
    ) as mock_presign:
        from lambdas.mcp.tools.assets import get_presigned_url

        result = asyncio.run(get_presigned_url(s3_key="episodes/test/cover.png"))

        mock_presign.assert_called_once_with(S3_BUCKET, "episodes/test/cover.png", expiry=3600)
        assert result["url"] == "https://presigned-url"
        assert "expires_at" in result


def test_get_presigned_url_custom_expiry(mock_s3_client):
    """Custom expiry is passed through."""
    with patch(
        "lambdas.mcp.tools.assets.generate_presigned_url",
        return_value="https://presigned-url",
    ) as mock_presign:
        from lambdas.mcp.tools.assets import get_presigned_url

        asyncio.run(get_presigned_url(s3_key="episodes/test/cover.png", expires_in=7200))

        mock_presign.assert_called_once_with(S3_BUCKET, "episodes/test/cover.png", expiry=7200)


def test_get_presigned_url_caps_at_max(mock_s3_client):
    """Expiry exceeding 43200 is capped to 43200."""
    with patch(
        "lambdas.mcp.tools.assets.generate_presigned_url",
        return_value="https://presigned-url",
    ) as mock_presign:
        from lambdas.mcp.tools.assets import get_presigned_url

        asyncio.run(get_presigned_url(s3_key="episodes/test/cover.png", expires_in=999999))

        call_args = mock_presign.call_args
        assert call_args.kwargs["expiry"] <= 43200
