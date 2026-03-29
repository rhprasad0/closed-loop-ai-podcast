from __future__ import annotations

import asyncio
import json
import time
from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock, patch

import pytest

from tests.unit.test_mcp.conftest import EXECUTION_ARN, STATE_MACHINE_ARN


# ---------------------------------------------------------------------------
# get_agent_logs
# ---------------------------------------------------------------------------


def test_get_agent_logs_correct_log_group():
    mock_logs = MagicMock()
    mock_logs.filter_log_events.return_value = {"events": []}

    with patch("lambdas.mcp.tools.observation._logs", mock_logs):
        from lambdas.mcp.tools.observation import get_agent_logs

        asyncio.run(get_agent_logs(agent="discovery"))

    call_kwargs = mock_logs.filter_log_events.call_args.kwargs
    assert call_kwargs["logGroupName"] == "/aws/lambda/zerostars-discovery"


def test_get_agent_logs_cover_art_log_group():
    """cover_art maps to zerostars-cover-art (hyphenated)."""
    mock_logs = MagicMock()
    mock_logs.filter_log_events.return_value = {"events": []}

    with patch("lambdas.mcp.tools.observation._logs", mock_logs):
        from lambdas.mcp.tools.observation import get_agent_logs

        asyncio.run(get_agent_logs(agent="cover_art"))

    call_kwargs = mock_logs.filter_log_events.call_args.kwargs
    assert call_kwargs["logGroupName"] == "/aws/lambda/zerostars-cover-art"


def test_get_agent_logs_post_production_log_group():
    """post_production maps to zerostars-post-production (hyphenated)."""
    mock_logs = MagicMock()
    mock_logs.filter_log_events.return_value = {"events": []}

    with patch("lambdas.mcp.tools.observation._logs", mock_logs):
        from lambdas.mcp.tools.observation import get_agent_logs

        asyncio.run(get_agent_logs(agent="post_production"))

    call_kwargs = mock_logs.filter_log_events.call_args.kwargs
    assert call_kwargs["logGroupName"] == "/aws/lambda/zerostars-post-production"


def test_get_agent_logs_start_time_from_since_minutes():
    mock_logs = MagicMock()
    mock_logs.filter_log_events.return_value = {"events": []}
    before = int(time.time() * 1000) - (30 * 60 * 1000)

    with patch("lambdas.mcp.tools.observation._logs", mock_logs):
        from lambdas.mcp.tools.observation import get_agent_logs

        asyncio.run(get_agent_logs(agent="script", since_minutes=30))

    start_time = mock_logs.filter_log_events.call_args.kwargs["startTime"]
    assert abs(start_time - before) < 5000  # within 5 seconds tolerance


def test_get_agent_logs_filters_by_execution_id():
    mock_logs = MagicMock()
    mock_logs.filter_log_events.return_value = {"events": []}

    with patch("lambdas.mcp.tools.observation._logs", mock_logs):
        from lambdas.mcp.tools.observation import get_agent_logs

        asyncio.run(get_agent_logs(agent="tts", execution_id="arn:aws:states:test"))

    call_kwargs = mock_logs.filter_log_events.call_args.kwargs
    assert "arn:aws:states:test" in call_kwargs["filterPattern"]


def test_get_agent_logs_no_filter_pattern_without_execution_id():
    mock_logs = MagicMock()
    mock_logs.filter_log_events.return_value = {"events": []}

    with patch("lambdas.mcp.tools.observation._logs", mock_logs):
        from lambdas.mcp.tools.observation import get_agent_logs

        asyncio.run(get_agent_logs(agent="discovery"))

    call_kwargs = mock_logs.filter_log_events.call_args.kwargs
    assert "filterPattern" not in call_kwargs


def test_get_agent_logs_respects_limit():
    mock_logs = MagicMock()
    events = [
        {"timestamp": i, "message": json.dumps({"level": "INFO", "message": f"msg {i}"})}
        for i in range(100)
    ]
    mock_logs.filter_log_events.return_value = {"events": events}

    with patch("lambdas.mcp.tools.observation._logs", mock_logs):
        from lambdas.mcp.tools.observation import get_agent_logs

        result = asyncio.run(get_agent_logs(agent="discovery", limit=20))

    # limit is passed to the CloudWatch API, and the result will contain
    # up to that many events (log-level filtering may reduce further).
    # The API call itself should have limit=20.
    assert mock_logs.filter_log_events.call_args.kwargs["limit"] == 20


def test_get_agent_logs_clamps_limit_to_200():
    mock_logs = MagicMock()
    mock_logs.filter_log_events.return_value = {"events": []}

    with patch("lambdas.mcp.tools.observation._logs", mock_logs):
        from lambdas.mcp.tools.observation import get_agent_logs

        asyncio.run(get_agent_logs(agent="discovery", limit=999))

    assert mock_logs.filter_log_events.call_args.kwargs["limit"] == 200


def test_get_agent_logs_clamps_limit_minimum_to_1():
    mock_logs = MagicMock()
    mock_logs.filter_log_events.return_value = {"events": []}

    with patch("lambdas.mcp.tools.observation._logs", mock_logs):
        from lambdas.mcp.tools.observation import get_agent_logs

        asyncio.run(get_agent_logs(agent="discovery", limit=-5))

    assert mock_logs.filter_log_events.call_args.kwargs["limit"] == 1


def test_get_agent_logs_filters_by_log_level():
    mock_logs = MagicMock()
    events = [
        {"timestamp": 1000, "message": json.dumps({"level": "INFO", "message": "ok"})},
        {"timestamp": 2000, "message": json.dumps({"level": "ERROR", "message": "fail"})},
        {"timestamp": 3000, "message": json.dumps({"level": "DEBUG", "message": "trace"})},
    ]
    mock_logs.filter_log_events.return_value = {"events": events}

    with patch("lambdas.mcp.tools.observation._logs", mock_logs):
        from lambdas.mcp.tools.observation import get_agent_logs

        result = asyncio.run(get_agent_logs(agent="discovery", log_level="ERROR"))

    levels = [log["level"] for log in result["logs"]]
    assert "DEBUG" not in levels
    assert "INFO" not in levels
    assert "ERROR" in levels


def test_get_agent_logs_parses_structured_json():
    mock_logs = MagicMock()
    events = [
        {
            "timestamp": 1000,
            "message": json.dumps(
                {
                    "level": "INFO",
                    "message": "Discovery complete",
                    "service": "discovery",
                    "correlation_id": "exec-123",
                    "extra_field": "extra_value",
                }
            ),
        },
    ]
    mock_logs.filter_log_events.return_value = {"events": events}

    with patch("lambdas.mcp.tools.observation._logs", mock_logs):
        from lambdas.mcp.tools.observation import get_agent_logs

        result = asyncio.run(get_agent_logs(agent="discovery"))

    log = result["logs"][0]
    assert log["message"] == "Discovery complete"
    assert log["service"] == "discovery"
    assert log["correlation_id"] == "exec-123"
    assert log["extra"]["extra_field"] == "extra_value"


def test_get_agent_logs_handles_non_json_message():
    mock_logs = MagicMock()
    events = [
        {"timestamp": 1000, "message": "plain text log line"},
    ]
    mock_logs.filter_log_events.return_value = {"events": events}

    with patch("lambdas.mcp.tools.observation._logs", mock_logs):
        from lambdas.mcp.tools.observation import get_agent_logs

        result = asyncio.run(get_agent_logs(agent="discovery"))

    log = result["logs"][0]
    assert log["message"] == "plain text log line"
    assert log["level"] == "INFO"  # default level for non-JSON
    assert log["service"] == "discovery"  # falls back to agent name


def test_get_agent_logs_invalid_agent_raises():
    from lambdas.mcp.tools.observation import get_agent_logs

    with pytest.raises(ValueError, match="agent must be one of"):
        asyncio.run(get_agent_logs(agent="invalid_agent"))


# ---------------------------------------------------------------------------
# get_execution_history
# ---------------------------------------------------------------------------


def test_get_execution_history_passes_include_flag():
    mock_sfn = MagicMock()
    mock_sfn.get_execution_history.return_value = {"events": []}

    with patch("lambdas.mcp.tools.observation._sfn", mock_sfn):
        from lambdas.mcp.tools.observation import get_execution_history

        asyncio.run(get_execution_history(execution_arn=EXECUTION_ARN, include_input_output=False))

    call_kwargs = mock_sfn.get_execution_history.call_args.kwargs
    assert call_kwargs["includeExecutionData"] is False


def test_get_execution_history_paginates():
    mock_sfn = MagicMock()
    ts1 = datetime(2025, 7, 13, 9, 0, 1, tzinfo=UTC)
    ts2 = datetime(2025, 7, 13, 9, 1, 30, tzinfo=UTC)
    mock_sfn.get_execution_history.side_effect = [
        {
            "events": [
                {"type": "TaskStateEntered", "id": 1, "timestamp": ts1},
            ],
            "nextToken": "page2",
        },
        {
            "events": [
                {"type": "TaskSucceeded", "id": 2, "timestamp": ts2},
            ],
        },
    ]

    with patch("lambdas.mcp.tools.observation._sfn", mock_sfn):
        from lambdas.mcp.tools.observation import get_execution_history

        result = asyncio.run(get_execution_history(execution_arn=EXECUTION_ARN))

    assert len(result["events"]) == 2
    assert mock_sfn.get_execution_history.call_count == 2


def test_get_execution_history_computes_duration_ms():
    """TaskStateEntered -> TaskSucceeded computes duration_ms for the state."""
    mock_sfn = MagicMock()
    enter_ts = datetime(2025, 7, 13, 9, 0, 0, tzinfo=UTC)
    exit_ts = datetime(2025, 7, 13, 9, 1, 30, tzinfo=UTC)  # 90 seconds later
    mock_sfn.get_execution_history.return_value = {
        "events": [
            {
                "type": "TaskStateEntered",
                "id": 1,
                "timestamp": enter_ts,
                "stateEnteredEventDetails": {
                    "name": "Discovery",
                    "input": '{"metadata": {}}',
                },
            },
            {
                "type": "TaskSucceeded",
                "id": 2,
                "timestamp": exit_ts,
                "taskSucceededEventDetails": {
                    "output": '{"repo_url": "https://github.com/user/repo"}',
                },
            },
        ],
    }

    with patch("lambdas.mcp.tools.observation._sfn", mock_sfn):
        from lambdas.mcp.tools.observation import get_execution_history

        result = asyncio.run(get_execution_history(execution_arn=EXECUTION_ARN))

    # The TaskSucceeded event should carry the duration_ms
    succeeded_event = result["events"][1]
    assert succeeded_event["duration_ms"] == 90000
    assert succeeded_event["output"]["repo_url"] == "https://github.com/user/repo"


def test_get_execution_history_parses_input_output():
    """TaskStateEntered input and TaskSucceeded output are JSON-parsed."""
    mock_sfn = MagicMock()
    ts = datetime(2025, 7, 13, 9, 0, 0, tzinfo=UTC)
    mock_sfn.get_execution_history.return_value = {
        "events": [
            {
                "type": "TaskStateEntered",
                "id": 1,
                "timestamp": ts,
                "stateEnteredEventDetails": {
                    "name": "Discovery",
                    "input": json.dumps({"metadata": {"key": "val"}}),
                },
            },
        ],
    }

    with patch("lambdas.mcp.tools.observation._sfn", mock_sfn):
        from lambdas.mcp.tools.observation import get_execution_history

        result = asyncio.run(
            get_execution_history(execution_arn=EXECUTION_ARN, include_input_output=True)
        )

    event = result["events"][0]
    assert event["input"] == {"metadata": {"key": "val"}}
    assert event["state_name"] == "Discovery"


def test_get_execution_history_excludes_io_when_disabled():
    """When include_input_output=False, input/output should be None."""
    mock_sfn = MagicMock()
    ts = datetime(2025, 7, 13, 9, 0, 0, tzinfo=UTC)
    mock_sfn.get_execution_history.return_value = {
        "events": [
            {
                "type": "TaskStateEntered",
                "id": 1,
                "timestamp": ts,
                "stateEnteredEventDetails": {
                    "name": "Discovery",
                    "input": json.dumps({"metadata": {}}),
                },
            },
        ],
    }

    with patch("lambdas.mcp.tools.observation._sfn", mock_sfn):
        from lambdas.mcp.tools.observation import get_execution_history

        result = asyncio.run(
            get_execution_history(execution_arn=EXECUTION_ARN, include_input_output=False)
        )

    event = result["events"][0]
    assert event["input"] is None


# ---------------------------------------------------------------------------
# get_pipeline_health
# ---------------------------------------------------------------------------


def test_get_pipeline_health_calculates_success_rate():
    mock_sfn = MagicMock()

    now = datetime.now(tz=UTC)
    recent_start = now - timedelta(days=5)

    def make_executions(status, count):
        return [
            {
                "executionArn": f"arn:exec:{status}:{i}",
                "name": f"{status.lower()}-{i}",
                "status": status,
                "startDate": recent_start,
                "stopDate": recent_start + timedelta(minutes=10),
            }
            for i in range(count)
        ]

    # list_executions is called once per status: RUNNING, SUCCEEDED, FAILED, ABORTED, TIMED_OUT
    mock_sfn.list_executions.side_effect = [
        {"executions": []},  # RUNNING
        {"executions": make_executions("SUCCEEDED", 8)},  # SUCCEEDED
        {"executions": make_executions("FAILED", 2)},  # FAILED
        {"executions": []},  # ABORTED
        {"executions": []},  # TIMED_OUT
    ]
    mock_sfn.describe_execution.return_value = {
        "executionArn": "arn:exec:FAILED:0",
        "error": "States.TaskFailed",
        "cause": "Lambda timeout",
    }

    with (
        patch("lambdas.mcp.tools.observation._sfn", mock_sfn),
        patch("lambdas.mcp.tools.observation.db.query") as mock_db_query,
    ):
        mock_db_query.return_value = [(1, "cool-project", datetime(2025, 7, 6))]

        from lambdas.mcp.tools.observation import get_pipeline_health

        result = asyncio.run(get_pipeline_health(days=30))

    assert result["succeeded"] == 8
    assert result["failed"] == 2
    assert result["success_rate"] == "80%"
    assert result["total_executions"] == 10


def test_get_pipeline_health_includes_running_executions():
    mock_sfn = MagicMock()

    now = datetime.now(tz=UTC)
    running_exec = {
        "executionArn": "arn:exec:running:0",
        "name": "run-0",
        "status": "RUNNING",
        "startDate": now - timedelta(minutes=5),
    }

    mock_sfn.list_executions.side_effect = [
        {"executions": [running_exec]},  # RUNNING
        {"executions": []},  # SUCCEEDED
        {"executions": []},  # FAILED
        {"executions": []},  # ABORTED
        {"executions": []},  # TIMED_OUT
    ]

    with (
        patch("lambdas.mcp.tools.observation._sfn", mock_sfn),
        patch("lambdas.mcp.tools.observation.db.query") as mock_db_query,
    ):
        mock_db_query.return_value = []

        from lambdas.mcp.tools.observation import get_pipeline_health

        result = asyncio.run(get_pipeline_health(days=30))

    assert len(result["currently_running"]) == 1
    assert result["currently_running"][0]["name"] == "run-0"


def test_get_pipeline_health_includes_recent_failures():
    mock_sfn = MagicMock()

    now = datetime.now(tz=UTC)
    failed_exec = {
        "executionArn": "arn:exec:FAILED:0",
        "name": "fail-0",
        "status": "FAILED",
        "startDate": now - timedelta(days=1),
        "stopDate": now - timedelta(days=1) + timedelta(minutes=5),
    }

    mock_sfn.list_executions.side_effect = [
        {"executions": []},  # RUNNING
        {"executions": []},  # SUCCEEDED
        {"executions": [failed_exec]},  # FAILED
        {"executions": []},  # ABORTED
        {"executions": []},  # TIMED_OUT
    ]
    mock_sfn.describe_execution.return_value = {
        "executionArn": "arn:exec:FAILED:0",
        "error": "States.TaskFailed",
        "cause": "TTS Lambda timed out",
    }

    with (
        patch("lambdas.mcp.tools.observation._sfn", mock_sfn),
        patch("lambdas.mcp.tools.observation.db.query") as mock_db_query,
    ):
        mock_db_query.return_value = []

        from lambdas.mcp.tools.observation import get_pipeline_health

        result = asyncio.run(get_pipeline_health(days=30))

    assert len(result["recent_failures"]) == 1
    assert result["recent_failures"][0]["error"] == "States.TaskFailed"
    assert result["recent_failures"][0]["cause"] == "TTS Lambda timed out"


def test_get_pipeline_health_last_successful_episode():
    mock_sfn = MagicMock()

    mock_sfn.list_executions.side_effect = [
        {"executions": []},  # RUNNING
        {"executions": []},  # SUCCEEDED
        {"executions": []},  # FAILED
        {"executions": []},  # ABORTED
        {"executions": []},  # TIMED_OUT
    ]

    with (
        patch("lambdas.mcp.tools.observation._sfn", mock_sfn),
        patch("lambdas.mcp.tools.observation.db.query") as mock_db_query,
    ):
        mock_db_query.return_value = [(1, "cool-project", datetime(2025, 7, 6).date())]

        from lambdas.mcp.tools.observation import get_pipeline_health

        result = asyncio.run(get_pipeline_health(days=30))

    assert result["last_successful_episode"] is not None
    assert result["last_successful_episode"]["episode_id"] == 1
    assert result["last_successful_episode"]["repo_name"] == "cool-project"


def test_get_pipeline_health_no_executions_zero_rate():
    mock_sfn = MagicMock()

    mock_sfn.list_executions.side_effect = [
        {"executions": []},  # RUNNING
        {"executions": []},  # SUCCEEDED
        {"executions": []},  # FAILED
        {"executions": []},  # ABORTED
        {"executions": []},  # TIMED_OUT
    ]

    with (
        patch("lambdas.mcp.tools.observation._sfn", mock_sfn),
        patch("lambdas.mcp.tools.observation.db.query") as mock_db_query,
    ):
        mock_db_query.return_value = []

        from lambdas.mcp.tools.observation import get_pipeline_health

        result = asyncio.run(get_pipeline_health(days=30))

    assert result["total_executions"] == 0
    assert result["success_rate"] == "0%"
    assert result["currently_running"] == []
    assert result["recent_failures"] == []
    assert result["last_successful_episode"] is None


def test_get_pipeline_health_db_failure_omits_episode():
    """If Postgres is unreachable, last_successful_episode is None (no crash)."""
    mock_sfn = MagicMock()

    mock_sfn.list_executions.side_effect = [
        {"executions": []},
        {"executions": []},
        {"executions": []},
        {"executions": []},
        {"executions": []},
    ]

    with (
        patch("lambdas.mcp.tools.observation._sfn", mock_sfn),
        patch("lambdas.mcp.tools.observation.db.query", side_effect=Exception("DB down")),
    ):
        from lambdas.mcp.tools.observation import get_pipeline_health

        result = asyncio.run(get_pipeline_health(days=30))

    assert result["last_successful_episode"] is None
