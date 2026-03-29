"""Observation tools for the MCP server.

Tools: get_agent_logs, get_execution_history, get_pipeline_health.

Queries CloudWatch Logs and Step Functions to expose pipeline observability
data in a convenient form for interactive inspection.
"""

from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from typing import Any

import boto3

import shared.db as db

_logs = boto3.client("logs")
_sfn = boto3.client("stepfunctions")

STATE_MACHINE_ARN: str = os.environ.get("STATE_MACHINE_ARN", "")

_VALID_AGENTS = {
    "discovery",
    "research",
    "script",
    "producer",
    "cover_art",
    "tts",
    "post_production",
    "site",
}

# Map agent names (underscores) to Lambda function name suffixes (hyphens).
_AGENT_TO_FUNCTION_SUFFIX: dict[str, str] = {
    "cover_art": "cover-art",
    "post_production": "post-production",
}

_LOG_LEVEL_ORDER = {"DEBUG": 0, "INFO": 1, "WARNING": 2, "ERROR": 3}


def _agent_log_group(agent: str) -> str:
    """Return the CloudWatch log group name for a pipeline agent."""
    suffix = _AGENT_TO_FUNCTION_SUFFIX.get(agent, agent.replace("_", "-"))
    return f"/aws/lambda/zerostars-{suffix}"


def _fmt_dt(dt: datetime | None) -> str | None:
    """Convert a datetime to an ISO 8601 string, or return None."""
    if dt is None:
        return None
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


async def get_agent_logs(
    agent: str,
    execution_id: str | None = None,
    since_minutes: int = 60,
    log_level: str | None = None,
    limit: int = 50,
) -> dict[str, Any]:
    """Retrieve CloudWatch logs for a specific pipeline agent.

    Args:
        agent: One of: discovery, research, script, producer, cover_art, tts,
               post_production, site.
        execution_id: Filter by correlation_id field. Omit for all recent logs.
        since_minutes: How far back to look. Default 60.
        log_level: Minimum level: DEBUG, INFO, WARNING, ERROR.
        limit: Max log lines. Default 50, max 200.
    """
    if agent not in _VALID_AGENTS:
        raise ValueError(f"agent must be one of: {', '.join(sorted(_VALID_AGENTS))}")

    limit = min(max(1, limit), 200)
    log_group = _agent_log_group(agent)

    start_time_ms = int(
        (datetime.now(tz=timezone.utc) - timedelta(minutes=since_minutes)).timestamp() * 1000
    )

    kwargs: dict[str, Any] = {
        "logGroupName": log_group,
        "startTime": start_time_ms,
        "limit": limit,
    }
    if execution_id:
        kwargs["filterPattern"] = execution_id

    resp = _logs.filter_log_events(**kwargs)
    raw_events: list[dict[str, Any]] = resp.get("events", [])

    # Minimum log level filter is done client-side after retrieval.
    min_level_order = _LOG_LEVEL_ORDER.get(log_level or "DEBUG", 0)

    logs: list[dict[str, Any]] = []
    for event in raw_events:
        message_str: str = event.get("message", "")

        # Powertools emits structured JSON; fall back to raw string.
        import json as _json

        try:
            parsed: dict[str, Any] = _json.loads(message_str)
        except (ValueError, TypeError):
            parsed = {}

        level: str = parsed.get("level", "INFO").upper()
        if _LOG_LEVEL_ORDER.get(level, 0) < min_level_order:
            continue

        ts_ms: int = event.get("timestamp", 0)
        ts_dt = datetime.fromtimestamp(ts_ms / 1000, tz=timezone.utc)
        timestamp_str = ts_dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{ts_dt.microsecond // 1000:03d}Z"

        logs.append(
            {
                "timestamp": timestamp_str,
                "level": level,
                "message": parsed.get("message", message_str),
                "service": parsed.get("service", agent),
                "correlation_id": parsed.get("correlation_id"),
                "extra": {
                    k: v
                    for k, v in parsed.items()
                    if k not in {"level", "message", "service", "correlation_id", "timestamp"}
                },
            }
        )

    return {"logs": logs}


async def get_execution_history(
    execution_arn: str,
    include_input_output: bool = True,
) -> dict[str, Any]:
    """Get the full event history for a pipeline execution.

    Returns every state transition, input/output, and timing. Paginates
    through all pages to return a consolidated list.

    Args:
        execution_arn: The execution to inspect.
        include_input_output: Include full I/O JSON at each step. Default true.
    """
    events: list[dict[str, Any]] = []

    # Track TaskStateEntered timestamps keyed by state name to compute duration_ms.
    entered_at: dict[str, datetime] = {}

    paginator_kwargs: dict[str, Any] = {
        "executionArn": execution_arn,
        "includeExecutionData": include_input_output,
    }

    # Manual pagination — the SFN client supports nextToken on GetExecutionHistory.
    next_token: str | None = None
    while True:
        if next_token:
            paginator_kwargs["nextToken"] = next_token
        resp = _sfn.get_execution_history(**paginator_kwargs)
        raw_events: list[dict[str, Any]] = resp.get("events", [])

        for ev in raw_events:
            event_type: str = ev.get("type", "")
            ts: datetime = ev["timestamp"]

            state_name: str | None = None
            input_data: Any = None
            output_data: Any = None
            duration_ms: int | None = None

            if event_type == "TaskStateEntered":
                details: dict[str, Any] = ev.get("stateEnteredEventDetails") or {}
                state_name = details.get("name")
                if include_input_output and details.get("input"):
                    import json as _json

                    try:
                        input_data = _json.loads(details["input"])
                    except (ValueError, TypeError):
                        input_data = details["input"]
                if state_name:
                    entered_at[state_name] = ts

            elif event_type in {"TaskSucceeded", "TaskFailed", "TaskTimedOut", "TaskAborted"}:
                # Find the state name from stateEnteredEventDetails via id lookup is complex;
                # use previousEventId chain — simpler: track the most recently entered state.
                if event_type == "TaskSucceeded":
                    details_key = "taskSucceededEventDetails"
                elif event_type == "TaskFailed":
                    details_key = "taskFailedEventDetails"
                else:
                    details_key = ""

                details = ev.get(details_key) or {}
                if include_input_output and details.get("output"):
                    import json as _json

                    try:
                        output_data = _json.loads(details["output"])
                    except (ValueError, TypeError):
                        output_data = details["output"]

                # Match to the last entered state that hasn't yet been exited.
                # The SFN history lists events in order; the most recently entered
                # unresolved state is the one that just completed.
                if entered_at:
                    # Pick the state entered most recently (last key inserted in Python 3.7+).
                    state_name = next(reversed(entered_at))
                    enter_ts = entered_at.pop(state_name)
                    duration_ms = int((ts - enter_ts).total_seconds() * 1000)

            elif event_type == "TaskStateExited":
                details = ev.get("stateExitedEventDetails") or {}
                state_name = details.get("name")
                if include_input_output and details.get("output"):
                    import json as _json

                    try:
                        output_data = _json.loads(details["output"])
                    except (ValueError, TypeError):
                        output_data = details["output"]
                if state_name and state_name in entered_at:
                    enter_ts = entered_at.pop(state_name)
                    duration_ms = int((ts - enter_ts).total_seconds() * 1000)

            events.append(
                {
                    "timestamp": _fmt_dt(ts),
                    "type": event_type,
                    "state_name": state_name,
                    "input": input_data,
                    "output": output_data,
                    "duration_ms": duration_ms,
                }
            )

        next_token = resp.get("nextToken")
        if not next_token:
            break

    return {"events": events}


async def get_pipeline_health(days: int = 30) -> dict[str, Any]:
    """Health check across the pipeline: success/failure rates, running executions, recent failures.

    Args:
        days: Look-back period in days. Default 30.
    """
    cutoff = datetime.now(tz=timezone.utc) - timedelta(days=days)

    statuses = ["RUNNING", "SUCCEEDED", "FAILED", "ABORTED", "TIMED_OUT"]
    all_executions: list[dict[str, Any]] = []

    for status_filter in statuses:
        kwargs: dict[str, Any] = {
            "stateMachineArn": STATE_MACHINE_ARN,
            "statusFilter": status_filter,
            "maxResults": 100,
        }
        # Paginate to collect all executions within the look-back window.
        while True:
            resp = _sfn.list_executions(**kwargs)
            batch: list[dict[str, Any]] = resp.get("executions", [])
            for ex in batch:
                start: datetime | None = ex.get("startDate")
                if start is not None and start.tzinfo is None:
                    start = start.replace(tzinfo=timezone.utc)
                if start is None or start < cutoff:
                    break
                all_executions.append(ex)
            else:
                next_token: str | None = resp.get("nextToken")
                if next_token:
                    kwargs["nextToken"] = next_token
                    continue
            break

    # Tally counts.
    counts: dict[str, int] = {
        "RUNNING": 0,
        "SUCCEEDED": 0,
        "FAILED": 0,
        "ABORTED": 0,
        "TIMED_OUT": 0,
    }
    total_duration_ms = 0
    duration_count = 0

    for ex in all_executions:
        s: str = ex.get("status", "")
        if s in counts:
            counts[s] += 1

        start_dt: datetime | None = ex.get("startDate")
        stop_dt: datetime | None = ex.get("stopDate")
        if start_dt and stop_dt:
            if start_dt.tzinfo is None:
                start_dt = start_dt.replace(tzinfo=timezone.utc)
            if stop_dt.tzinfo is None:
                stop_dt = stop_dt.replace(tzinfo=timezone.utc)
            total_duration_ms += int((stop_dt - start_dt).total_seconds() * 1000)
            duration_count += 1

    total = sum(counts.values())
    succeeded = counts["SUCCEEDED"]
    success_rate = f"{round(succeeded / total * 100)}%" if total > 0 else "0%"
    avg_duration_seconds = (
        round(total_duration_ms / duration_count / 1000) if duration_count > 0 else 0
    )

    # Collect currently running execution summaries (no describe needed for status resource).
    currently_running = [
        {
            "execution_arn": ex["executionArn"],
            "name": ex["name"],
            "status": ex["status"],
            "start_date": _fmt_dt(ex.get("startDate")),
        }
        for ex in all_executions
        if ex.get("status") == "RUNNING"
    ]

    # Recent failures — describe each to extract error/cause.
    failed_execs = [ex for ex in all_executions if ex.get("status") in {"FAILED", "TIMED_OUT"}][:5]
    recent_failures: list[dict[str, Any]] = []
    for ex in failed_execs:
        try:
            desc = _sfn.describe_execution(executionArn=ex["executionArn"])
            recent_failures.append(
                {
                    "execution_arn": ex["executionArn"],
                    "name": ex["name"],
                    "error": desc.get("error"),
                    "cause": desc.get("cause"),
                }
            )
        except Exception:
            # If describe fails, include basic info without error detail.
            recent_failures.append(
                {
                    "execution_arn": ex["executionArn"],
                    "name": ex["name"],
                    "error": None,
                    "cause": None,
                }
            )

    # Last successful episode from Postgres.
    last_successful_episode: dict[str, Any] | None = None
    try:
        rows = db.query(
            """
            SELECT episode_id, repo_name, air_date
            FROM episodes
            ORDER BY episode_id DESC
            LIMIT 1
            """
        )
        if rows:
            row = rows[0]
            air_date_val = row[2]
            last_successful_episode = {
                "episode_id": row[0],
                "repo_name": row[1],
                "air_date": air_date_val.isoformat()
                if hasattr(air_date_val, "isoformat")
                else str(air_date_val),
            }
    except Exception:
        # DB unavailable — omit last_successful_episode rather than crashing.
        pass

    return {
        "total_executions": total,
        "succeeded": succeeded,
        "failed": counts["FAILED"],
        "aborted": counts["ABORTED"],
        "success_rate": success_rate,
        "avg_duration_seconds": avg_duration_seconds,
        "currently_running": currently_running,
        "recent_failures": recent_failures,
        "last_successful_episode": last_successful_episode,
    }
