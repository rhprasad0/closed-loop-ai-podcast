from __future__ import annotations

import asyncio
from unittest.mock import MagicMock, patch

from tests.unit.test_mcp.conftest import CLOUDFRONT_DIST_ID, ACM_CERT_ARN, SITE_DOMAIN


def test_invalidate_cache_default_paths(mock_site_boto3_clients):
    """No paths argument defaults to invalidating /*."""
    cf_client, _ = mock_site_boto3_clients

    with patch("lambdas.mcp.tools.site._cf", cf_client):
        from lambdas.mcp.tools.site import invalidate_cache

        cf_client.create_invalidation.return_value = {
            "Invalidation": {"Id": "I123", "Status": "InProgress"},
        }

        result = asyncio.run(invalidate_cache())

    call_kwargs = cf_client.create_invalidation.call_args.kwargs
    paths = call_kwargs["InvalidationBatch"]["Paths"]["Items"]
    assert paths == ["/*"]
    assert result["invalidation_id"] == "I123"
    assert result["status"] == "InProgress"


def test_invalidate_cache_custom_paths(mock_site_boto3_clients):
    """Custom paths are forwarded to CloudFront."""
    cf_client, _ = mock_site_boto3_clients

    with patch("lambdas.mcp.tools.site._cf", cf_client):
        from lambdas.mcp.tools.site import invalidate_cache

        cf_client.create_invalidation.return_value = {
            "Invalidation": {"Id": "I456", "Status": "InProgress"},
        }

        result = asyncio.run(invalidate_cache(paths=["/", "/episodes/1"]))

    paths = cf_client.create_invalidation.call_args.kwargs["InvalidationBatch"]["Paths"]["Items"]
    assert paths == ["/", "/episodes/1"]
    assert result["invalidation_id"] == "I456"


def test_invalidate_cache_passes_distribution_id(mock_site_boto3_clients):
    """DistributionId from environment is used in the API call."""
    cf_client, _ = mock_site_boto3_clients

    with patch("lambdas.mcp.tools.site._cf", cf_client):
        from lambdas.mcp.tools.site import invalidate_cache

        cf_client.create_invalidation.return_value = {
            "Invalidation": {"Id": "I789", "Status": "InProgress"},
        }

        asyncio.run(invalidate_cache())

    call_kwargs = cf_client.create_invalidation.call_args.kwargs
    assert call_kwargs["DistributionId"] == CLOUDFRONT_DIST_ID


def test_invalidate_cache_returns_paths_in_response(mock_site_boto3_clients):
    """Response includes the paths that were invalidated."""
    cf_client, _ = mock_site_boto3_clients

    with patch("lambdas.mcp.tools.site._cf", cf_client):
        from lambdas.mcp.tools.site import invalidate_cache

        cf_client.create_invalidation.return_value = {
            "Invalidation": {"Id": "I101", "Status": "InProgress"},
        }

        result = asyncio.run(invalidate_cache(paths=["/index.html"]))

    assert result["paths"] == ["/index.html"]


def test_get_site_status_aggregates_sources(mock_site_boto3_clients, mock_mcp_db):
    """Site status aggregates CloudFront, ACM, and DB data."""
    cf_client, acm_client = mock_site_boto3_clients
    conn, cursor = mock_mcp_db

    with (
        patch("lambdas.mcp.tools.site._cf", cf_client),
        patch("lambdas.mcp.tools.site._acm", acm_client),
        patch("lambdas.mcp.tools.site.db.get_connection", return_value=conn),
    ):
        from lambdas.mcp.tools.site import get_site_status

        cursor.fetchone.side_effect = [
            (11,),
            (11, "cool-project", MagicMock(isoformat=MagicMock(return_value="2025-07-06"))),
        ]

        cf_client.get_distribution.return_value = {
            "Distribution": {"Id": "E123", "Status": "Deployed"},
        }
        acm_client.describe_certificate.return_value = {
            "Certificate": {"Status": "ISSUED"},
        }

        result = asyncio.run(get_site_status())

    assert result["distribution_status"] == "Deployed"
    assert result["ssl_status"] == "ISSUED"
    assert result["episode_count"] == 11
    assert result["cloudfront_id"] == "E123"
    assert result["domain"] == SITE_DOMAIN


def test_get_site_status_no_episodes(mock_site_boto3_clients, mock_mcp_db):
    """Site status with zero episodes returns count 0 and no latest episode."""
    cf_client, acm_client = mock_site_boto3_clients
    conn, cursor = mock_mcp_db

    with (
        patch("lambdas.mcp.tools.site._cf", cf_client),
        patch("lambdas.mcp.tools.site._acm", acm_client),
        patch("lambdas.mcp.tools.site.db.get_connection", return_value=conn),
    ):
        from lambdas.mcp.tools.site import get_site_status

        cursor.fetchone.side_effect = [(0,), None]

        cf_client.get_distribution.return_value = {
            "Distribution": {"Id": "E123", "Status": "Deployed"},
        }
        acm_client.describe_certificate.return_value = {
            "Certificate": {"Status": "ISSUED"},
        }

        result = asyncio.run(get_site_status())

    assert result["episode_count"] == 0
    assert result["latest_episode"] is None


def test_get_site_status_uses_correct_arns(mock_site_boto3_clients, mock_mcp_db):
    """Correct distribution ID and certificate ARN are used in API calls."""
    cf_client, acm_client = mock_site_boto3_clients
    conn, cursor = mock_mcp_db

    with (
        patch("lambdas.mcp.tools.site._cf", cf_client),
        patch("lambdas.mcp.tools.site._acm", acm_client),
        patch("lambdas.mcp.tools.site.db.get_connection", return_value=conn),
    ):
        from lambdas.mcp.tools.site import get_site_status

        cursor.fetchone.side_effect = [(0,), None]

        cf_client.get_distribution.return_value = {
            "Distribution": {"Id": CLOUDFRONT_DIST_ID, "Status": "Deployed"},
        }
        acm_client.describe_certificate.return_value = {
            "Certificate": {"Status": "ISSUED"},
        }

        asyncio.run(get_site_status())

    cf_client.get_distribution.assert_called_once_with(Id=CLOUDFRONT_DIST_ID)
    acm_client.describe_certificate.assert_called_once_with(CertificateArn=ACM_CERT_ARN)
