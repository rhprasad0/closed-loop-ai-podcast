"""MCP resource handlers for the zerostars:// URI scheme.

Each function is synchronous and returns a Python object (list or dict).
Handlers are registered in handler.py via @server.resource() wrappers.

DB-backed resources call get_connection via tools.data so mock fixtures
that patch lambdas.mcp.tools.data.get_connection intercept correctly.
Pipeline status uses boto3.client lazily so the mock_sfn_client fixture
(which patches lambdas.mcp.tools.pipeline.boto3.client) intercepts it.
"""

from __future__ import annotations

import os
from typing import Any

import boto3

from .tools import data as data_tools


def _serialize(value: object) -> object:
    """Convert non-JSON-serializable DB values (dates, datetimes) to strings."""
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return value


def read_episodes_resource() -> list[dict[str, Any]]:
    """zerostars://episodes — summary list of all episodes, newest first."""
    conn = data_tools.get_connection()
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT episode_id, air_date, repo_name, developer_github,
                   star_count_at_recording, producer_attempts
            FROM episodes
            ORDER BY air_date DESC
            """
        )
        rows = cur.fetchall()
        columns = [desc[0] for desc in (cur.description or [])]
    return [{col: _serialize(val) for col, val in zip(columns, row)} for row in rows]


def read_episode_detail_resource(episode_id: int) -> dict[str, Any]:
    """zerostars://episodes/{episode_id} — full episode detail including script and research."""
    conn = data_tools.get_connection()
    with conn.cursor() as cur:
        cur.execute(
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
        row = cur.fetchone()
        columns = [desc[0] for desc in (cur.description or [])]
    if row is None:
        return {"error": f"Episode {episode_id} not found"}
    return {col: _serialize(val) for col, val in zip(columns, row)}


def read_metrics_resource() -> list[dict[str, Any]]:
    """zerostars://metrics — latest engagement metrics per episode, ordered by views desc."""
    conn = data_tools.get_connection()
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT m.episode_id, e.repo_name, e.developer_github,
                   m.linkedin_post_url, m.views, m.likes, m.comments, m.shares,
                   m.snapshot_date
            FROM episode_metrics m
            JOIN episodes e ON m.episode_id = e.episode_id
            ORDER BY m.views DESC
            """
        )
        rows = cur.fetchall()
        columns = [desc[0] for desc in (cur.description or [])]
    return [{col: _serialize(val) for col, val in zip(columns, row)} for row in rows]


def read_pipeline_status_resource() -> dict[str, Any]:
    """zerostars://pipeline/status — currently running executions + last 5 completed."""
    sfn = boto3.client("stepfunctions")
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
            "startDate": e["startDate"],
        }
        for e in running_resp.get("executions", [])
    ]

    recent_resp: dict[str, Any] = sfn.list_executions(
        stateMachineArn=state_machine_arn,
        maxResults=5,
    )
    recent = [
        {
            "executionArn": e["executionArn"],
            "name": e["name"],
            "status": e["status"],
            "startDate": e["startDate"],
            "stopDate": e.get("stopDate"),
        }
        for e in recent_resp.get("executions", [])
        if e["status"] != "RUNNING"
    ][:5]

    return {"currently_running": currently_running, "recent": recent}


def read_featured_developers_resource() -> list[dict[str, Any]]:
    """zerostars://featured-developers — all featured developers with episode context."""
    conn = data_tools.get_connection()
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT fd.developer_github, fd.episode_id, fd.featured_date, e.repo_name
            FROM featured_developers fd
            JOIN episodes e ON fd.episode_id = e.episode_id
            ORDER BY fd.featured_date DESC
            """
        )
        rows = cur.fetchall()
        columns = [desc[0] for desc in (cur.description or [])]
    return [{col: _serialize(val) for col, val in zip(columns, row)} for row in rows]
