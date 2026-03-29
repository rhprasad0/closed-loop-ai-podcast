"""Asset management tools for the MCP server.

Tools: get_episode_assets, list_s3_assets, get_presigned_url.
"""

from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta
from typing import Any

import boto3

import shared.db as db
from shared.s3 import generate_presigned_url

_s3 = boto3.client("s3")

S3_BUCKET: str = os.environ.get("S3_BUCKET", "")


async def get_episode_assets(episode_id: int) -> dict[str, Any]:
    """Get presigned download URLs for an episode's S3 assets.

    Fetches S3 paths from the episodes table, then generates presigned
    URLs with 1-hour expiry. Returns None for any asset that doesn't exist.
    """
    row: dict[str, Any] | None = None
    conn = db.get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT s3_cover_art_path, s3_mp3_path, s3_mp4_path "
                "FROM episodes WHERE episode_id = %s",
                (episode_id,),
            )
            result = cur.fetchone()
            if result:
                row = {
                    "cover": result[0],
                    "mp3": result[1],
                    "mp4": result[2],
                }
    finally:
        conn.close()

    if row is None:
        return {"error": f"Episode {episode_id} not found"}

    def _presign(key: str | None) -> str | None:
        if not key:
            return None
        return generate_presigned_url(S3_BUCKET, key, expiry=3600)

    return {
        "cover_art_url": _presign(row["cover"]),
        "mp3_url": _presign(row["mp3"]),
        "mp4_url": _presign(row["mp4"]),
        "s3_keys": {
            "cover": row["cover"],
            "mp3": row["mp3"],
            "mp4": row["mp4"],
        },
    }


async def list_s3_assets(prefix: str | None = None, limit: int = 50) -> dict[str, Any]:
    """List objects in the episode assets bucket.

    Uses s3:ListObjectsV2. Returns key, size_bytes, and last_modified per object.
    """
    kwargs: dict[str, Any] = {
        "Bucket": S3_BUCKET,
        "MaxKeys": limit,
    }
    if prefix:
        kwargs["Prefix"] = prefix

    resp = _s3.list_objects_v2(**kwargs)
    objects = [
        {
            "key": obj["Key"],
            "size_bytes": obj["Size"],
            "last_modified": obj["LastModified"].strftime("%Y-%m-%dT%H:%M:%S.000Z"),
        }
        for obj in resp.get("Contents", [])
    ]
    return {"objects": objects}


async def get_presigned_url(s3_key: str, expires_in: int = 3600) -> dict[str, Any]:
    """Generate a presigned GET URL for a specific S3 object.

    Expiry is capped at 43200 seconds (12 hours).
    """
    # Cap expiry to 12 hours per spec
    expires_in = min(expires_in, 43200)
    url = generate_presigned_url(S3_BUCKET, s3_key, expiry=expires_in)
    expires_at = (datetime.now(tz=UTC) + timedelta(seconds=expires_in)).strftime(
        "%Y-%m-%dT%H:%M:%S.000Z"
    )
    return {"url": url, "expires_at": expires_at}
