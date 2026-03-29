"""Unit tests for lambdas.mcp.tools.pipeline — 5 Step Functions tools.

Tests: start_pipeline, stop_pipeline, get_execution_status,
       list_executions, retry_from_step.
"""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime
from unittest.mock import MagicMock, patch

import pytest

from tests.unit.test_mcp.conftest import EXECUTION_ARN, STATE_MACHINE_ARN

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_T0 = datetime(2025, 7, 13, 9, 0, 0, tzinfo=UTC)
_T1 = datetime(2025, 7, 13, 9, 5, 0, tzinfo=UTC)
_T2 = datetime(2025, 7, 13, 9, 12, 34, tzinfo=UTC)
_T3 = datetime(2025, 7, 13, 9, 15, 0, tzinfo=UTC)


def _patch_dates(fixture: dict, **replacements: datetime) -> dict:
    """Return a copy of *fixture* with string dates replaced by datetime objects.

    The conftest sample fixtures store dates as strings for readability,
    but the real boto3 describe_execution returns datetime objects. The
    pipeline module's _fmt_dt helper expects datetime | None, so tests
    must supply datetime values for any date field that _fmt_dt touches.
    """
    out = dict(fixture)
    for key, value in replacements.items():
        out[key] = value
    return out


# ---------------------------------------------------------------------------
# start_pipeline
# ---------------------------------------------------------------------------


def test_start_pipeline_calls_start_execution():
    mock_sfn = MagicMock()
    mock_sfn.start_execution.return_value = {
        "executionArn": EXECUTION_ARN,
        "startDate": _T0,
    }

    with patch("lambdas.mcp.tools.pipeline._sfn", mock_sfn):
        from lambdas.mcp.tools.pipeline import start_pipeline

        result = asyncio.run(start_pipeline())

    mock_sfn.start_execution.assert_called_once()
    call_kwargs = mock_sfn.start_execution.call_args.kwargs
    assert call_kwargs["stateMachineArn"] == STATE_MACHINE_ARN
    assert call_kwargs["name"].startswith("mcp-")
    assert result["execution_arn"] == EXECUTION_ARN


def test_start_pipeline_name_format():
    mock_sfn = MagicMock()
    mock_sfn.start_execution.return_value = {
        "executionArn": EXECUTION_ARN,
        "startDate": _T0,
    }

    with patch("lambdas.mcp.tools.pipeline._sfn", mock_sfn):
        from lambdas.mcp.tools.pipeline import start_pipeline

        asyncio.run(start_pipeline())

    name = mock_sfn.start_execution.call_args.kwargs["name"]
    assert len(name) <= 80
    assert all(
        c in "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz-_T" for c in name
    )


# ---------------------------------------------------------------------------
# stop_pipeline
# ---------------------------------------------------------------------------


def test_stop_pipeline_passes_cause():
    mock_sfn = MagicMock()
    mock_sfn.stop_execution.return_value = {"stopDate": _T1}

    with patch("lambdas.mcp.tools.pipeline._sfn", mock_sfn):
        from lambdas.mcp.tools.pipeline import stop_pipeline

        result = asyncio.run(stop_pipeline(execution_arn=EXECUTION_ARN, cause="Bad repo pick"))

    mock_sfn.stop_execution.assert_called_once_with(
        executionArn=EXECUTION_ARN,
        error="MCP.UserAborted",
        cause="Bad repo pick",
    )
    assert result["status"] == "ABORTED"


def test_stop_pipeline_without_cause():
    mock_sfn = MagicMock()
    mock_sfn.stop_execution.return_value = {"stopDate": _T1}

    with patch("lambdas.mcp.tools.pipeline._sfn", mock_sfn):
        from lambdas.mcp.tools.pipeline import stop_pipeline

        asyncio.run(stop_pipeline(execution_arn=EXECUTION_ARN))

    call_kwargs = mock_sfn.stop_execution.call_args.kwargs
    assert "cause" not in call_kwargs


# ---------------------------------------------------------------------------
# get_execution_status
# ---------------------------------------------------------------------------


def test_get_execution_status_running_includes_current_step(
    sample_execution_running,
    sample_execution_history_events,
):
    desc = _patch_dates(sample_execution_running, startDate=_T0)
    # The code calls get_execution_history with reverseOrder=True, so the
    # mock must return events newest-first. The conftest fixture stores them
    # in chronological order, so we reverse them here.
    reversed_events = {"events": list(reversed(sample_execution_history_events["events"]))}
    mock_sfn = MagicMock()
    mock_sfn.describe_execution.return_value = desc
    mock_sfn.get_execution_history.return_value = reversed_events

    with patch("lambdas.mcp.tools.pipeline._sfn", mock_sfn):
        from lambdas.mcp.tools.pipeline import get_execution_status

        result = asyncio.run(get_execution_status(execution_arn=EXECUTION_ARN))

    assert result["status"] == "RUNNING"
    assert result["current_step"] == "Research"
    assert "discovery" in result["state_object"]
    mock_sfn.get_execution_history.assert_called_once()


def test_get_execution_status_succeeded_uses_output(
    sample_execution_succeeded,
):
    desc = _patch_dates(sample_execution_succeeded, startDate=_T0, stopDate=_T2)
    mock_sfn = MagicMock()
    mock_sfn.describe_execution.return_value = desc

    with patch("lambdas.mcp.tools.pipeline._sfn", mock_sfn):
        from lambdas.mcp.tools.pipeline import get_execution_status

        result = asyncio.run(get_execution_status(execution_arn=EXECUTION_ARN))

    assert result["status"] == "SUCCEEDED"
    assert result["current_step"] is None
    assert "post_production" in result["state_object"]
    mock_sfn.get_execution_history.assert_not_called()


def test_get_execution_status_failed_includes_error(
    sample_execution_failed,
):
    desc = _patch_dates(sample_execution_failed, startDate=_T0, stopDate=_T1)
    mock_sfn = MagicMock()
    mock_sfn.describe_execution.return_value = desc

    with patch("lambdas.mcp.tools.pipeline._sfn", mock_sfn):
        from lambdas.mcp.tools.pipeline import get_execution_status

        result = asyncio.run(get_execution_status(execution_arn=EXECUTION_ARN))

    assert result["status"] == "FAILED"
    assert result["error"] == "States.TaskFailed"
    assert "TTS" in result["cause"]


# ---------------------------------------------------------------------------
# list_executions
# ---------------------------------------------------------------------------


def test_list_executions_with_status_filter():
    mock_sfn = MagicMock()
    mock_sfn.list_executions.return_value = {"executions": []}

    with patch("lambdas.mcp.tools.pipeline._sfn", mock_sfn):
        from lambdas.mcp.tools.pipeline import list_executions

        asyncio.run(list_executions(status_filter="FAILED", max_results=5))

    mock_sfn.list_executions.assert_called_once_with(
        stateMachineArn=STATE_MACHINE_ARN,
        statusFilter="FAILED",
        maxResults=5,
    )


def test_list_executions_without_filter():
    mock_sfn = MagicMock()
    mock_sfn.list_executions.return_value = {"executions": []}

    with patch("lambdas.mcp.tools.pipeline._sfn", mock_sfn):
        from lambdas.mcp.tools.pipeline import list_executions

        asyncio.run(list_executions())

    call_kwargs = mock_sfn.list_executions.call_args.kwargs
    assert "statusFilter" not in call_kwargs


# ---------------------------------------------------------------------------
# retry_from_step
# ---------------------------------------------------------------------------


def test_retry_from_step_carries_state(sample_execution_failed):
    mock_sfn = MagicMock()
    mock_sfn.describe_execution.return_value = sample_execution_failed
    mock_sfn.start_execution.return_value = {
        "executionArn": "arn:aws:states:us-east-1:123456789:execution:zerostars-pipeline:mcp-retry-20250713T091500Z",
        "startDate": _T3,
    }

    with patch("lambdas.mcp.tools.pipeline._sfn", mock_sfn):
        from lambdas.mcp.tools.pipeline import retry_from_step

        result = asyncio.run(
            retry_from_step(
                failed_execution_arn=EXECUTION_ARN,
                retry_from="Script",
            )
        )

    # Verify the new execution input carries discovery + research but adds resume_from
    call_kwargs = mock_sfn.start_execution.call_args.kwargs
    new_input = json.loads(call_kwargs["input"])
    assert new_input["metadata"]["resume_from"] == "Script"
    assert "discovery" in new_input
    assert "research" in new_input
    # Script and later steps should not be carried (they were not in the failed input)
    assert "script" not in new_input
    assert result["carried_state_keys"] == ["discovery", "research"]
    assert result["retry_from"] == "Script"


def test_retry_from_step_name_format(sample_execution_failed):
    mock_sfn = MagicMock()
    mock_sfn.describe_execution.return_value = sample_execution_failed
    mock_sfn.start_execution.return_value = {
        "executionArn": EXECUTION_ARN,
        "startDate": _T3,
    }

    with patch("lambdas.mcp.tools.pipeline._sfn", mock_sfn):
        from lambdas.mcp.tools.pipeline import retry_from_step

        asyncio.run(
            retry_from_step(
                failed_execution_arn=EXECUTION_ARN,
                retry_from="TTS",
            )
        )

    name = mock_sfn.start_execution.call_args.kwargs["name"]
    assert name.startswith("mcp-retry-")


def test_retry_from_step_invalid_step_raises():
    """retry_from_step rejects step names not in _VALID_STEPS."""
    from lambdas.mcp.tools.pipeline import retry_from_step

    with pytest.raises(ValueError, match="retry_from must be one of"):
        asyncio.run(
            retry_from_step(
                failed_execution_arn=EXECUTION_ARN,
                retry_from="InvalidStep",
            )
        )
