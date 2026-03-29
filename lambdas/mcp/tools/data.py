"""Data query tools for the MCP server.

Tools: query_episodes, get_episode_detail, query_metrics,
       query_featured_developers, run_sql, upsert_metrics.

All tools connect to Postgres via shared.db using DB_CONNECTION_STRING.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

import shared.db as db

_VALID_EPISODE_ORDER_BY = {"created_at", "air_date", "episode_id", "star_count_at_recording"}
_VALID_METRICS_ORDER_BY = {"views", "likes", "comments", "shares", "snapshot_date"}


def _serialize(value: Any) -> Any:
    """Convert date/datetime to ISO string for JSON-safe output."""
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    return value


async def query_episodes(
    episode_id: int | None = None,
    developer_github: str | None = None,
    language: str | None = None,
    limit: int = 10,
    offset: int = 0,
    order_by: str = "created_at",
    order: str = "desc",
) -> dict[str, Any]:
    """Query the episodes table with filtering and pagination.

    Excludes script_text, research_json, and cover_art_prompt to keep
    response size manageable. Use get_episode_detail for full text.

    Args:
        episode_id: Get a specific episode.
        developer_github: Filter by developer.
        language: Filter by primary language (from the language column).
        limit: Default 10, max 50.
        offset: Pagination offset. Default 0.
        order_by: One of: created_at, air_date, episode_id, star_count_at_recording.
        order: asc or desc. Default desc.
    """
    limit = min(max(1, limit), 50)
    offset = max(0, offset)

    if order_by not in _VALID_EPISODE_ORDER_BY:
        order_by = "created_at"
    if order.lower() not in {"asc", "desc"}:
        order = "desc"

    # Build query with safe column interpolation (validated above, no user strings).
    conditions: list[str] = []
    params: list[Any] = []

    if episode_id is not None:
        conditions.append("episode_id = %s")
        params.append(episode_id)
    if developer_github is not None:
        conditions.append("developer_github = %s")
        params.append(developer_github)
    if language is not None:
        conditions.append("language = %s")
        params.append(language)

    where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""

    count_sql = f"SELECT COUNT(*) FROM episodes {where_clause}"
    count_rows = db.query(count_sql, tuple(params) if params else None)
    total_count: int = int(count_rows[0][0]) if count_rows else 0

    # order_by and order are validated above — safe to interpolate directly.
    select_sql = f"""
        SELECT episode_id, air_date, repo_url, repo_name, developer_github,
               developer_name, star_count_at_recording, producer_attempts,
               s3_mp3_path, s3_mp4_path, s3_cover_art_path, created_at
        FROM episodes
        {where_clause}
        ORDER BY {order_by} {order}
        LIMIT %s OFFSET %s
    """
    params.extend([limit, offset])
    rows = db.query(select_sql, tuple(params))

    columns = [
        "episode_id",
        "air_date",
        "repo_url",
        "repo_name",
        "developer_github",
        "developer_name",
        "star_count_at_recording",
        "producer_attempts",
        "s3_mp3_path",
        "s3_mp4_path",
        "s3_cover_art_path",
        "created_at",
    ]
    episodes = [{col: _serialize(val) for col, val in zip(columns, row)} for row in rows]

    return {"episodes": episodes, "total_count": total_count}


async def get_episode_detail(episode_id: int) -> dict[str, Any]:
    """Full details for a single episode including script text and research JSON.

    Args:
        episode_id: The episode ID.
    """
    rows = db.query(
        """
        SELECT episode_id, air_date, repo_url, repo_name, developer_github,
               developer_name, star_count_at_recording, language,
               script_text, research_json, cover_art_prompt,
               s3_mp3_path, s3_mp4_path, s3_cover_art_path,
               producer_attempts, execution_id, created_at
        FROM episodes
        WHERE episode_id = %s
        """,
        (episode_id,),
    )
    if not rows:
        raise ValueError(f"Episode {episode_id} not found")

    row = rows[0]
    columns = [
        "episode_id",
        "air_date",
        "repo_url",
        "repo_name",
        "developer_github",
        "developer_name",
        "star_count_at_recording",
        "language",
        "script_text",
        "research_json",
        "cover_art_prompt",
        "s3_mp3_path",
        "s3_mp4_path",
        "s3_cover_art_path",
        "producer_attempts",
        "execution_id",
        "created_at",
    ]
    return {col: _serialize(val) for col, val in zip(columns, row)}


async def query_metrics(
    episode_id: int | None = None,
    order_by: str = "views",
    limit: int = 10,
) -> dict[str, Any]:
    """Query engagement metrics for episodes.

    Joins episode_metrics with episodes for repo_name/developer_github context.

    Args:
        episode_id: Filter to specific episode.
        order_by: One of: views, likes, comments, shares, snapshot_date. Default views.
        limit: Default 10.
    """
    limit = max(1, limit)
    if order_by not in _VALID_METRICS_ORDER_BY:
        order_by = "views"

    conditions: list[str] = []
    params: list[Any] = []

    if episode_id is not None:
        conditions.append("m.episode_id = %s")
        params.append(episode_id)

    where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""

    # order_by validated above — safe to interpolate.
    sql = f"""
        SELECT m.episode_id, e.repo_name, e.developer_github,
               m.linkedin_post_url, m.views, m.likes, m.comments, m.shares,
               m.snapshot_date
        FROM episode_metrics m
        JOIN episodes e ON e.episode_id = m.episode_id
        {where_clause}
        ORDER BY m.{order_by} DESC
        LIMIT %s
    """
    params.append(limit)
    rows = db.query(sql, tuple(params))

    columns = [
        "episode_id",
        "repo_name",
        "developer_github",
        "linkedin_post_url",
        "views",
        "likes",
        "comments",
        "shares",
        "snapshot_date",
    ]
    metrics = [{col: _serialize(val) for col, val in zip(columns, row)} for row in rows]
    return {"metrics": metrics}


async def query_featured_developers(limit: int = 100) -> dict[str, Any]:
    """List all previously featured developers.

    Joins featured_developers with episodes for repo_name context.

    Args:
        limit: Default 100.
    """
    limit = max(1, limit)
    rows = db.query(
        """
        SELECT fd.developer_github, fd.episode_id, fd.featured_date, e.repo_name
        FROM featured_developers fd
        JOIN episodes e ON e.episode_id = fd.episode_id
        ORDER BY fd.featured_date DESC
        LIMIT %s
        """,
        (limit,),
    )

    columns = ["developer_github", "episode_id", "featured_date", "repo_name"]
    developers = [{col: _serialize(val) for col, val in zip(columns, row)} for row in rows]
    return {"developers": developers}


async def run_sql(sql: str) -> dict[str, Any]:
    """Execute a read-only SQL query. Only SELECT statements allowed.

    Safety: Rejects any statement not starting with SELECT. Sets a 15-second
    statement_timeout on the Postgres session to prevent long-running queries.

    Args:
        sql: A SELECT query.
    """
    if not sql.strip().upper().startswith("SELECT"):
        raise ValueError("Only SELECT statements are allowed")

    conn = db.get_connection()
    try:
        with conn.cursor() as cur:
            # Set timeout directly on the cursor's session before executing user SQL.
            cur.execute("SET LOCAL statement_timeout = '15s'")
            cur.execute(sql)
            rows: list[tuple[object, ...]] = cur.fetchall()
            columns: list[str] = [desc[0] for desc in (cur.description or [])]
    finally:
        conn.close()

    return {
        "columns": columns,
        "rows": [list(row) for row in rows],
        "row_count": len(rows),
    }


async def upsert_metrics(
    episode_id: int,
    linkedin_post_url: str | None = None,
    views: int = 0,
    likes: int = 0,
    comments: int = 0,
    shares: int = 0,
) -> dict[str, Any]:
    """Insert or update engagement metrics for an episode.

    Snapshot date is set to the current date. ON CONFLICT (episode_id, snapshot_date)
    updates the existing row's metrics.

    Args:
        episode_id: The episode to record metrics for.
        linkedin_post_url: URL of the LinkedIn post.
        views: Default 0.
        likes: Default 0.
        comments: Default 0.
        shares: Default 0.
    """
    # Use a raw connection so we can read xmax within the same transaction that
    # performs the upsert, then commit. db.query() never commits, so it cannot
    # be used for INSERT here.
    conn = db.get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO episode_metrics
                    (episode_id, linkedin_post_url, views, likes, comments, shares, snapshot_date)
                VALUES (%s, %s, %s, %s, %s, %s, CURRENT_DATE)
                ON CONFLICT (episode_id, snapshot_date) DO UPDATE SET
                    linkedin_post_url = EXCLUDED.linkedin_post_url,
                    views             = EXCLUDED.views,
                    likes             = EXCLUDED.likes,
                    comments          = EXCLUDED.comments,
                    shares            = EXCLUDED.shares
                RETURNING metric_id, (xmax = 0) AS is_insert
                """,
                (episode_id, linkedin_post_url, views, likes, comments, shares),
            )
            row = cur.fetchone()
        conn.commit()
    finally:
        conn.close()

    metric_id: int = int(row[0]) if row else 0
    # xmax = 0 means no prior transaction has updated this row — fresh insert.
    is_insert: bool = bool(row[1]) if row else True
    return {"metric_id": metric_id, "action": "inserted" if is_insert else "updated"}
