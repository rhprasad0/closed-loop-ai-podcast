"""MCP resource handlers for the zerostars:// URI scheme.

Each function is async and returns a JSON string. Handlers are registered
in handler.py via @server.resource() wrappers.

DB-backed resources query Postgres directly; once tools/data.py and
tools/pipeline.py exist, these should delegate to those modules instead.
"""

from __future__ import annotations

import json
import os
from typing import Any

import boto3

from shared.db import query

# boto3 Step Functions client — cached across warm invocations
_sfn_client: Any = None


def _get_sfn_client() -> Any:
    global _sfn_client
    if _sfn_client is None:
        _sfn_client = boto3.client("stepfunctions")
    return _sfn_client


def _serialize(value: object) -> object:
    """Convert non-JSON-serializable DB values (dates, datetimes) to strings."""
    if hasattr(value, "isoformat"):
        return value.isoformat()  # type: ignore[union-attr]
    return value


async def read_episodes_resource() -> str:
    """zerostars://episodes — summary list of all episodes, newest first."""
    rows = query(
        """
        SELECT episode_id, air_date, repo_name, developer_github,
               star_count_at_recording, producer_attempts
        FROM episodes
        ORDER BY air_date DESC
        """
    )
    episodes = [
        {
            "episode_id": row[0],
            "air_date": _serialize(row[1]),
            "repo_name": row[2],
            "developer_github": row[3],
            "star_count_at_recording": row[4],
            "producer_attempts": row[5],
        }
        for row in rows
    ]
    return json.dumps(episodes)


async def read_episode_detail_resource(episode_id: int) -> str:
    """zerostars://episodes/{episode_id} — full episode detail including script and research."""
    rows = query(
        """
        SELECT episode_id, air_date, repo_name, developer_github, developer_name,
               star_count_at_recording, language, script_text, research_json,
               cover_art_prompt, s3_cover_art_path, s3_mp3_path, s3_mp4_path,
               producer_attempts, execution_id
        FROM episodes
        WHERE episode_id = %s
        """,
        (episode_id,),
    )
    if not rows:
        return json.dumps({"error": f"Episode {episode_id} not found"})
    row = rows[0]
    episode: dict[str, object] = {
        "episode_id": row[0],
        "air_date": _serialize(row[1]),
        "repo_name": row[2],
        "developer_github": row[3],
        "developer_name": row[4],
        "star_count_at_recording": row[5],
        "language": row[6],
        "script_text": row[7],
        "research_json": row[8],
        "cover_art_prompt": row[9],
        "s3_cover_art_path": row[10],
        "s3_mp3_path": row[11],
        "s3_mp4_path": row[12],
        "producer_attempts": row[13],
        "execution_id": row[14],
    }
    return json.dumps(episode)


async def read_metrics_resource() -> str:
    """zerostars://metrics — latest engagement metrics per episode, ordered by views desc."""
    rows = query(
        """
        SELECT m.episode_id, e.repo_name, e.developer_github,
               m.linkedin_post_url, m.views, m.likes, m.comments, m.shares,
               m.snapshot_date
        FROM episode_metrics m
        JOIN episodes e ON m.episode_id = e.episode_id
        ORDER BY m.views DESC
        """
    )
    metrics = [
        {
            "episode_id": row[0],
            "repo_name": row[1],
            "developer_github": row[2],
            "linkedin_post_url": row[3],
            "views": row[4],
            "likes": row[5],
            "comments": row[6],
            "shares": row[7],
            "snapshot_date": _serialize(row[8]),
        }
        for row in rows
    ]
    return json.dumps(metrics)


async def read_pipeline_status_resource() -> str:
    """zerostars://pipeline/status — currently running executions + last 5 completed."""
    sfn = _get_sfn_client()
    state_machine_arn = os.environ["STATE_MACHINE_ARN"]

    running_resp: dict[str, Any] = sfn.list_executions(
        stateMachineArn=state_machine_arn,
        statusFilter="RUNNING",
    )
    currently_running = [
        {
            "executionArn": e["executionArn"],
            "name": e["name"],
            "status": e["status"],
            "startDate": e["startDate"].isoformat(),
        }
        for e in running_resp.get("executions", [])
    ]

    # Fetch recent executions across all terminal statuses; API returns newest first.
    recent_resp: dict[str, Any] = sfn.list_executions(
        stateMachineArn=state_machine_arn,
        maxResults=5,
    )
    recent = [
        {
            "executionArn": e["executionArn"],
            "name": e["name"],
            "status": e["status"],
            "startDate": e["startDate"].isoformat(),
            "stopDate": e["stopDate"].isoformat() if e.get("stopDate") else None,
        }
        for e in recent_resp.get("executions", [])
        if e["status"] != "RUNNING"
    ][:5]

    return json.dumps({"currently_running": currently_running, "recent": recent})


async def read_featured_developers_resource() -> str:
    """zerostars://featured-developers — all featured developers with episode context."""
    rows = query(
        """
        SELECT fd.developer_github, fd.episode_id, fd.featured_date, e.repo_name
        FROM featured_developers fd
        JOIN episodes e ON fd.episode_id = e.episode_id
        ORDER BY fd.featured_date DESC
        """
    )
    developers = [
        {
            "developer_github": row[0],
            "episode_id": row[1],
            "featured_date": _serialize(row[2]),
            "repo_name": row[3],
        }
        for row in rows
    ]
    return json.dumps(developers)
