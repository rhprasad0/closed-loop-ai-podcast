"""Site management tools for the MCP server.

Tools: invalidate_cache, get_site_status.
"""

from __future__ import annotations

import os
from datetime import UTC, datetime
from typing import Any

import boto3

import shared.db as db

_cf = boto3.client("cloudfront")
_acm = boto3.client("acm", region_name="us-east-1")  # ACM certs for CloudFront must be in us-east-1

CLOUDFRONT_DISTRIBUTION_ID: str = os.environ.get("CLOUDFRONT_DISTRIBUTION_ID", "")
ACM_CERTIFICATE_ARN: str = os.environ.get("ACM_CERTIFICATE_ARN", "")
SITE_DOMAIN: str = os.environ.get("SITE_DOMAIN", "")


def _now_ref() -> str:
    """Return a unique caller reference string based on current timestamp."""
    return datetime.now(tz=UTC).strftime("%Y%m%dT%H%M%S%fZ")


async def invalidate_cache(paths: list[str] | None = None) -> dict[str, Any]:
    """Create a CloudFront cache invalidation for the podcast website.

    Defaults to invalidating all paths (/*) if none are specified.
    """
    if paths is None:
        paths = ["/*"]

    resp = _cf.create_invalidation(
        DistributionId=CLOUDFRONT_DISTRIBUTION_ID,
        InvalidationBatch={
            "Paths": {
                "Quantity": len(paths),
                "Items": paths,
            },
            "CallerReference": _now_ref(),
        },
    )
    invalidation = resp["Invalidation"]
    return {
        "invalidation_id": invalidation["Id"],
        "status": invalidation["Status"],
        "paths": paths,
    }


async def get_site_status() -> dict[str, Any]:
    """Aggregate site health: CloudFront distribution status, ACM certificate status,
    and episode count from Postgres.
    """
    # CloudFront distribution status
    cf_resp = _cf.get_distribution(Id=CLOUDFRONT_DISTRIBUTION_ID)
    distribution = cf_resp["Distribution"]
    dist_status: str = distribution["Status"]
    cf_id: str = distribution["Id"]

    # ACM certificate status
    acm_resp = _acm.describe_certificate(CertificateArn=ACM_CERTIFICATE_ARN)
    ssl_status: str = acm_resp["Certificate"]["Status"]

    # Episode count and latest episode from Postgres
    episode_count: int = 0
    latest_episode: dict[str, Any] | None = None
    conn = db.get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM episodes")
            count_row = cur.fetchone()
            if count_row:
                episode_count = int(count_row[0])

            cur.execute(
                "SELECT episode_id, repo_name, air_date "
                "FROM episodes ORDER BY air_date DESC LIMIT 1"
            )
            ep_row = cur.fetchone()
            if ep_row:
                latest_episode = {
                    "episode_id": ep_row[0],
                    "repo_name": ep_row[1],
                    "air_date": ep_row[2].isoformat() if ep_row[2] else None,
                }
    finally:
        conn.close()

    return {
        "distribution_status": dist_status,
        "domain": SITE_DOMAIN,
        "ssl_status": ssl_status,
        "episode_count": episode_count,
        "latest_episode": latest_episode,
        "cloudfront_id": cf_id,
    }
