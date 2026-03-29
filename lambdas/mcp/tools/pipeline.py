"""Pipeline control tools for the MCP server.

Tools: start_pipeline, stop_pipeline, get_execution_status,
       list_executions, retry_from_step.
"""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from typing import Any

import boto3

_sfn = boto3.client("stepfunctions")

STATEMACHINE_ARN: str = os.environ.get("STATEMACHINE_ARN", "")

_VALID_STEPS = {
    "Discovery",
    "Research",
    "Script",
    "Producer",
    "CoverArt",
    "TTS",
    "PostProduction",
}


def _now_tag() -> str:
    """Return a timestamp string safe for Step Functions execution names."""
    return datetime.now(tz=UTC).strftime("%Y%m%dT%H%M%SZ")


def _fmt_dt(dt: datetime | None) -> str | None:
    """Convert a datetime to an ISO 8601 string, or return None."""
    if dt is None:
        return None
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


async def start_pipeline() -> dict[str, Any]:
    """Start a new full pipeline execution.

    Returns execution_arn and start_date. Execution name is auto-generated
    as mcp-{iso-timestamp}.
    """
    name = f"mcp-{_now_tag()}"
    resp = _sfn.start_execution(
        stateMachineArn=STATEMACHINE_ARN,
        name=name,
    )
    return {
        "execution_arn": resp["executionArn"],
        "start_date": _fmt_dt(resp["startDate"]),
    }


async def stop_pipeline(
    execution_arn: str,
    cause: str | None = None,
) -> dict[str, Any]:
    """Stop a running pipeline execution with ABORTED status.

    Args:
        execution_arn: ARN of the execution to stop.
        cause: Optional reason recorded in execution history.
    """
    kwargs: dict[str, Any] = {
        "executionArn": execution_arn,
        "error": "MCP.UserAborted",
    }
    if cause is not None:
        kwargs["cause"] = cause
    resp = _sfn.stop_execution(**kwargs)
    return {
        "status": "ABORTED",
        "stop_date": _fmt_dt(resp["stopDate"]),
    }


async def get_execution_status(execution_arn: str) -> dict[str, Any]:
    """Get the current status and accumulated state of a pipeline execution.

    For completed executions state_object comes from the output field.
    For running executions it comes from the input field (state accumulated so far).
    current_step is found by scanning the most recent TaskStateEntered event.

    Args:
        execution_arn: The execution to inspect.
    """
    desc = _sfn.describe_execution(executionArn=execution_arn)
    status: str = desc["status"]

    # Determine the state object to return.
    if status != "RUNNING" and desc.get("output"):
        raw_state = desc["output"]
    else:
        raw_state = desc.get("input") or "{}"
    state_object: Any = json.loads(raw_state) if isinstance(raw_state, str) else raw_state

    # Find current step for running executions.
    current_step: str | None = None
    if status == "RUNNING":
        history_resp = _sfn.get_execution_history(
            executionArn=execution_arn,
            reverseOrder=True,
            maxResults=5,
            includeExecutionData=False,
        )
        for event in history_resp.get("events", []):
            if event.get("type") == "TaskStateEntered":
                details = event.get("stateEnteredEventDetails") or {}
                current_step = details.get("name")
                break

    return {
        "status": status,
        "name": desc.get("name"),
        "current_step": current_step,
        "start_date": _fmt_dt(desc.get("startDate")),
        "stop_date": _fmt_dt(desc.get("stopDate")),
        "state_object": state_object,
        "error": desc.get("cause") and desc.get("error") or desc.get("error"),
        "cause": desc.get("cause"),
    }


async def list_executions(
    status_filter: str | None = None,
    max_results: int = 10,
) -> dict[str, Any]:
    """List recent pipeline executions.

    Args:
        status_filter: One of RUNNING, SUCCEEDED, FAILED, ABORTED, TIMED_OUT.
                       Omit to return all statuses.
        max_results: Default 10, max 50.
    """
    max_results = min(max(1, max_results), 50)

    kwargs: dict[str, Any] = {
        "stateMachineArn": STATEMACHINE_ARN,
        "maxResults": max_results,
    }
    if status_filter:
        kwargs["statusFilter"] = status_filter

    resp = _sfn.list_executions(**kwargs)

    executions = [
        {
            "execution_arn": ex["executionArn"],
            "name": ex["name"],
            "status": ex["status"],
            "start_date": _fmt_dt(ex.get("startDate")),
            "stop_date": _fmt_dt(ex.get("stopDate")),
        }
        for ex in resp.get("executions", [])
    ]
    return {"executions": executions}


async def retry_from_step(
    failed_execution_arn: str,
    retry_from: str,
) -> dict[str, Any]:
    """Start a new execution carrying forward state from a failed run.

    Extracts accumulated state from the failed execution, sets
    metadata.resume_from, and starts a new execution. The state machine's
    ResumeRouter Choice state routes to the correct step.

    Args:
        failed_execution_arn: ARN of the failed execution to retry from.
        retry_from: Step to resume at. One of: Discovery, Research, Script,
                    Producer, CoverArt, TTS, PostProduction.
    """
    if retry_from not in _VALID_STEPS:
        raise ValueError(f"retry_from must be one of: {', '.join(sorted(_VALID_STEPS))}")

    desc = _sfn.describe_execution(executionArn=failed_execution_arn)

    # Use output if available (partial output on failed run), otherwise input.
    if desc.get("output"):
        raw_state = desc["output"]
    else:
        raw_state = desc.get("input") or "{}"

    state: dict[str, Any] = json.loads(raw_state) if isinstance(raw_state, str) else raw_state

    # Inject the resume pointer into metadata.
    metadata: dict[str, Any] = state.get("metadata") or {}
    metadata["resume_from"] = retry_from
    state["metadata"] = metadata

    # Determine which state keys were carried forward (everything except metadata).
    carried_keys = [k for k in state if k != "metadata"]

    name = f"mcp-retry-{_now_tag()}"
    resp = _sfn.start_execution(
        stateMachineArn=STATEMACHINE_ARN,
        name=name,
        input=json.dumps(state),
    )

    return {
        "new_execution_arn": resp["executionArn"],
        "carried_state_keys": carried_keys,
        "retry_from": retry_from,
    }
