> Part of the [Implementation Spec](../../IMPLEMENTATION_SPEC.md)

# MCP Server Testing

Tests for the [MCP Server](./mcp-server.md) — 26 tools, 5 resources, Lambda handler. Same conventions as [pipeline testing](./testing.md): `unittest.mock` for AWS services, `moto` for S3, `@pytest.mark.integration` for real services.

### Directory Structure

```
tests/
├── unit/
│   └── test_mcp/
│       ├── __init__.py
│       ├── conftest.py             # MCP-specific fixtures
│       ├── test_pipeline.py        # start_pipeline, stop_pipeline, get_execution_status, list_executions, retry_from_step
│       ├── test_agents.py          # invoke_discovery through invoke_post_production
│       ├── test_observation.py     # get_agent_logs, get_execution_history, get_pipeline_health
│       ├── test_data.py            # query_episodes, get_episode_detail, query_metrics, query_featured_developers, run_sql, upsert_metrics
│       ├── test_assets.py          # get_episode_assets, list_s3_assets, get_presigned_url
│       ├── test_site.py            # invalidate_cache, get_site_status
│       ├── test_resources.py       # MCP resource handlers
│       └── test_handler.py         # Transport setup, tool registration, routing
├── integration/
│   ├── test_mcp_pipeline_live.py   # Real Step Functions API (read-only)
│   ├── test_mcp_data_live.py       # Real Postgres queries
│   └── test_mcp_assets_live.py     # Real S3 operations
└── e2e/
    └── test_mcp_e2e.py             # Full tool chain: start → observe → stop
```

### MCP Fixtures (`tests/unit/test_mcp/conftest.py`)

```python
import json
from unittest.mock import MagicMock, patch

import pytest


STATE_MACHINE_ARN = "arn:aws:states:us-east-1:123456789:stateMachine:zerostars-pipeline"
EXECUTION_ARN = "arn:aws:states:us-east-1:123456789:execution:zerostars-pipeline:mcp-20250713T090000Z"
S3_BUCKET = "zerostars-episodes-123456789"
CLOUDFRONT_DIST_ID = "E1234567890"
ACM_CERT_ARN = "arn:aws:acm:us-east-1:123456789:certificate/abc-123"
SITE_DOMAIN = "podcast.ryans-lab.click"


@pytest.fixture(autouse=True)
def mcp_env(monkeypatch):
    """Set environment variables that the MCP Lambda reads at import time."""
    monkeypatch.setenv("STATE_MACHINE_ARN", STATE_MACHINE_ARN)
    monkeypatch.setenv("S3_BUCKET", S3_BUCKET)
    monkeypatch.setenv("CLOUDFRONT_DISTRIBUTION_ID", CLOUDFRONT_DIST_ID)
    monkeypatch.setenv("ACM_CERTIFICATE_ARN", ACM_CERT_ARN)
    monkeypatch.setenv("SITE_DOMAIN", SITE_DOMAIN)
    monkeypatch.setenv("POWERTOOLS_SERVICE_NAME", "mcp")
    monkeypatch.setenv("POWERTOOLS_LOG_LEVEL", "INFO")
    monkeypatch.setenv("POWERTOOLS_METRICS_NAMESPACE", "ZeroStars")
    monkeypatch.setenv("POWERTOOLS_TRACER_CAPTURE_RESPONSE", "false")
    monkeypatch.setenv("DB_CONNECTION_STRING", "postgresql://test:test@localhost:5432/testdb")


@pytest.fixture
def mock_sfn_client():
    """Mock Step Functions boto3 client."""
    with patch("lambdas.mcp.tools.pipeline.boto3.client") as mock:
        client = MagicMock()
        mock.return_value = client
        yield client


@pytest.fixture
def mock_lambda_client():
    """Mock Lambda boto3 client for agent invocations."""
    with patch("lambdas.mcp.tools.agents.boto3.client") as mock:
        client = MagicMock()
        mock.return_value = client
        yield client


@pytest.fixture
def mock_logs_client():
    """Mock CloudWatch Logs boto3 client."""
    with patch("lambdas.mcp.tools.observation.boto3.client") as mock:
        client = MagicMock()
        mock.return_value = client
        yield client


@pytest.fixture
def mock_observation_clients():
    """Mock boto3 clients for observation module — dispatches SFN and Logs.

    The observation module creates its own boto3 clients for Step Functions
    and CloudWatch Logs. This fixture patches at the observation module path
    (not the pipeline module path) to correctly intercept both.
    """
    sfn_client = MagicMock()
    logs_client = MagicMock()

    def client_factory(service_name, **kwargs):
        if service_name == "stepfunctions":
            return sfn_client
        elif service_name == "logs":
            return logs_client
        raise ValueError(f"Unexpected service: {service_name}")

    with patch("lambdas.mcp.tools.observation.boto3.client", side_effect=client_factory):
        yield sfn_client, logs_client


@pytest.fixture
def mock_s3_client():
    """Mock S3 boto3 client for asset tools."""
    with patch("lambdas.mcp.tools.assets.boto3.client") as mock:
        client = MagicMock()
        mock.return_value = client
        yield client


@pytest.fixture
def mock_site_boto3_clients():
    """Mock boto3.client for site tools — dispatches by service name.

    CloudFront and ACM are separate AWS services. The site module calls
    boto3.client("cloudfront") and boto3.client("acm") separately.
    This fixture uses side_effect to return different mocks for each.
    """
    cf_client = MagicMock()
    acm_client = MagicMock()

    def client_factory(service_name, **kwargs):
        if service_name == "cloudfront":
            return cf_client
        elif service_name == "acm":
            return acm_client
        raise ValueError(f"Unexpected service: {service_name}")

    with patch("lambdas.mcp.tools.site.boto3.client", side_effect=client_factory):
        yield cf_client, acm_client


@pytest.fixture
def mock_mcp_db(mock_db_connection):
    """Patches get_connection at the MCP data module's import path.

    The assets module (assets.py) delegates database queries through the data
    module's functions, so patching data.get_connection covers both data and
    asset tool tests that need DB access.
    """
    with patch("lambdas.mcp.tools.data.get_connection") as mock:
        conn = MagicMock()
        cursor = MagicMock()
        conn.cursor.return_value = cursor
        cursor.__enter__ = lambda s: s
        cursor.__exit__ = MagicMock(return_value=False)
        conn.__enter__ = lambda s: s
        conn.__exit__ = MagicMock(return_value=False)
        mock.return_value = conn
        yield conn, cursor


@pytest.fixture
def sample_execution_running():
    """DescribeExecution response for a RUNNING execution."""
    return {
        "executionArn": EXECUTION_ARN,
        "stateMachineArn": STATE_MACHINE_ARN,
        "name": "mcp-20250713T090000Z",
        "status": "RUNNING",
        "startDate": "2025-07-13T09:00:00.000Z",
        "input": json.dumps({
            "metadata": {"execution_id": EXECUTION_ARN, "script_attempt": 1},
            "discovery": {"repo_url": "https://github.com/user/repo", "star_count": 7},
        }),
        "inputDetails": {"included": True},
    }


@pytest.fixture
def sample_execution_succeeded():
    """DescribeExecution response for a SUCCEEDED execution."""
    return {
        "executionArn": EXECUTION_ARN,
        "stateMachineArn": STATE_MACHINE_ARN,
        "name": "mcp-20250713T090000Z",
        "status": "SUCCEEDED",
        "startDate": "2025-07-13T09:00:00.000Z",
        "stopDate": "2025-07-13T09:12:34.000Z",
        "input": json.dumps({"metadata": {"execution_id": EXECUTION_ARN, "script_attempt": 1}}),
        "output": json.dumps({
            "metadata": {"execution_id": EXECUTION_ARN, "script_attempt": 1},
            "discovery": {"repo_url": "https://github.com/user/repo"},
            "research": {"developer_name": "Test User"},
            "script": {"text": "**Hype:** Hello!", "character_count": 15},
            "producer": {"verdict": "PASS", "score": 8},
            "cover_art": {"s3_key": "episodes/test/cover.png"},
            "tts": {"s3_key": "episodes/test/episode.mp3", "duration_seconds": 180},
            "post_production": {"s3_mp4_key": "episodes/test/episode.mp4", "episode_id": 1},
        }),
        "outputDetails": {"included": True},
    }


@pytest.fixture
def sample_execution_failed():
    """DescribeExecution response for a FAILED execution."""
    return {
        "executionArn": EXECUTION_ARN,
        "stateMachineArn": STATE_MACHINE_ARN,
        "name": "mcp-20250713T090000Z",
        "status": "FAILED",
        "startDate": "2025-07-13T09:00:00.000Z",
        "stopDate": "2025-07-13T09:05:00.000Z",
        "input": json.dumps({
            "metadata": {"execution_id": EXECUTION_ARN, "script_attempt": 1},
            "discovery": {"repo_url": "https://github.com/user/repo", "star_count": 7},
            "research": {"developer_name": "Test User"},
        }),
        "error": "States.TaskFailed",
        "cause": "TTS Lambda timed out after 300 seconds",
    }


@pytest.fixture
def sample_execution_history_events():
    """GetExecutionHistory response events for a completed Discovery step."""
    return {
        "events": [
            {
                "timestamp": "2025-07-13T09:00:01.000Z",
                "type": "TaskStateEntered",
                "id": 1,
                "stateEnteredEventDetails": {
                    "name": "Discovery",
                    "input": '{"metadata": {}}',
                },
            },
            {
                "timestamp": "2025-07-13T09:01:30.000Z",
                "type": "TaskSucceeded",
                "id": 2,
                "taskSucceededEventDetails": {
                    "output": '{"repo_url": "https://github.com/user/repo"}',
                },
            },
            {
                "timestamp": "2025-07-13T09:01:31.000Z",
                "type": "TaskStateEntered",
                "id": 3,
                "stateEnteredEventDetails": {
                    "name": "Research",
                    "input": '{"metadata": {}, "discovery": {}}',
                },
            },
        ],
    }
```

### Unit Tests: Pipeline Control (`test_pipeline.py`)

```python
import json
from unittest.mock import ANY

from tests.unit.test_mcp.conftest import STATE_MACHINE_ARN, EXECUTION_ARN


def test_start_pipeline_calls_start_execution(mock_sfn_client):
    from lambdas.mcp.tools.pipeline import start_pipeline
    mock_sfn_client.start_execution.return_value = {
        "executionArn": EXECUTION_ARN,
        "startDate": "2025-07-13T09:00:00.000Z",
    }

    result = start_pipeline()

    mock_sfn_client.start_execution.assert_called_once()
    call_kwargs = mock_sfn_client.start_execution.call_args.kwargs
    assert call_kwargs["stateMachineArn"] == STATE_MACHINE_ARN
    assert call_kwargs["name"].startswith("mcp-")
    assert result["execution_arn"] == EXECUTION_ARN


def test_start_pipeline_name_format(mock_sfn_client):
    mock_sfn_client.start_execution.return_value = {
        "executionArn": EXECUTION_ARN, "startDate": "2025-07-13T09:00:00.000Z",
    }
    start_pipeline()
    name = mock_sfn_client.start_execution.call_args.kwargs["name"]
    assert len(name) <= 80
    assert all(c in "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz-_T" for c in name)


def test_stop_pipeline_passes_cause(mock_sfn_client):
    from lambdas.mcp.tools.pipeline import stop_pipeline
    mock_sfn_client.stop_execution.return_value = {"stopDate": "2025-07-13T09:05:00.000Z"}

    result = stop_pipeline(execution_arn=EXECUTION_ARN, cause="Bad repo pick")

    mock_sfn_client.stop_execution.assert_called_once_with(
        executionArn=EXECUTION_ARN,
        error="MCP.UserAborted",
        cause="Bad repo pick",
    )
    assert result["status"] == "ABORTED"


def test_stop_pipeline_without_cause(mock_sfn_client):
    from lambdas.mcp.tools.pipeline import stop_pipeline
    mock_sfn_client.stop_execution.return_value = {"stopDate": "2025-07-13T09:05:00.000Z"}

    stop_pipeline(execution_arn=EXECUTION_ARN)

    call_kwargs = mock_sfn_client.stop_execution.call_args.kwargs
    assert "cause" not in call_kwargs or call_kwargs["cause"] is None


def test_get_execution_status_running_includes_current_step(
    mock_sfn_client, sample_execution_running, sample_execution_history_events,
):
    from lambdas.mcp.tools.pipeline import get_execution_status
    mock_sfn_client.describe_execution.return_value = sample_execution_running
    mock_sfn_client.get_execution_history.return_value = sample_execution_history_events

    result = get_execution_status(execution_arn=EXECUTION_ARN)

    assert result["status"] == "RUNNING"
    assert result["current_step"] == "Research"
    assert "discovery" in result["state_object"]
    mock_sfn_client.get_execution_history.assert_called_once()


def test_get_execution_status_succeeded_uses_output(mock_sfn_client, sample_execution_succeeded):
    from lambdas.mcp.tools.pipeline import get_execution_status
    mock_sfn_client.describe_execution.return_value = sample_execution_succeeded

    result = get_execution_status(execution_arn=EXECUTION_ARN)

    assert result["status"] == "SUCCEEDED"
    assert result["current_step"] is None
    assert "post_production" in result["state_object"]
    mock_sfn_client.get_execution_history.assert_not_called()


def test_get_execution_status_failed_includes_error(mock_sfn_client, sample_execution_failed):
    from lambdas.mcp.tools.pipeline import get_execution_status
    mock_sfn_client.describe_execution.return_value = sample_execution_failed

    result = get_execution_status(execution_arn=EXECUTION_ARN)

    assert result["status"] == "FAILED"
    assert result["error"] == "States.TaskFailed"
    assert "TTS" in result["cause"]


def test_list_executions_with_status_filter(mock_sfn_client):
    from lambdas.mcp.tools.pipeline import list_executions
    mock_sfn_client.list_executions.return_value = {"executions": []}

    list_executions(status_filter="FAILED", max_results=5)

    mock_sfn_client.list_executions.assert_called_once_with(
        stateMachineArn=STATE_MACHINE_ARN,
        statusFilter="FAILED",
        maxResults=5,
    )


def test_list_executions_without_filter(mock_sfn_client):
    from lambdas.mcp.tools.pipeline import list_executions
    mock_sfn_client.list_executions.return_value = {"executions": []}

    list_executions()

    call_kwargs = mock_sfn_client.list_executions.call_args.kwargs
    assert "statusFilter" not in call_kwargs


def test_retry_from_step_carries_state(mock_sfn_client, sample_execution_failed):
    from lambdas.mcp.tools.pipeline import retry_from_step
    mock_sfn_client.describe_execution.return_value = sample_execution_failed
    mock_sfn_client.start_execution.return_value = {
        "executionArn": "arn:aws:states:us-east-1:123456789:execution:zerostars-pipeline:mcp-retry-20250713T091500Z",
        "startDate": "2025-07-13T09:15:00.000Z",
    }

    result = retry_from_step(failed_execution_arn=EXECUTION_ARN, retry_from="Script")

    # Verify the new execution input carries discovery + research but adds resume_from
    call_kwargs = mock_sfn_client.start_execution.call_args.kwargs
    new_input = json.loads(call_kwargs["input"])
    assert new_input["metadata"]["resume_from"] == "Script"
    assert "discovery" in new_input
    assert "research" in new_input
    assert "script" not in new_input  # Script and later steps should not be carried
    assert result["carried_state_keys"] == ["discovery", "research"]
    assert result["retry_from"] == "Script"


def test_retry_from_step_name_format(mock_sfn_client, sample_execution_failed):
    from lambdas.mcp.tools.pipeline import retry_from_step
    mock_sfn_client.describe_execution.return_value = sample_execution_failed
    mock_sfn_client.start_execution.return_value = {
        "executionArn": EXECUTION_ARN, "startDate": "2025-07-13T09:15:00.000Z",
    }

    retry_from_step(failed_execution_arn=EXECUTION_ARN, retry_from="TTS")

    name = mock_sfn_client.start_execution.call_args.kwargs["name"]
    assert name.startswith("mcp-retry-")
```

### Unit Tests: Agent Invocation (`test_agents.py`)

```python
import json
from unittest.mock import MagicMock

import pytest

from tests.unit.test_mcp.conftest import EXECUTION_ARN


def test_invoke_discovery_builds_synthetic_state(mock_lambda_client):
    from lambdas.mcp.tools.agents import invoke_discovery
    mock_lambda_client.invoke.return_value = {
        "StatusCode": 200,
        "Payload": MagicMock(read=lambda: json.dumps({
            "repo_url": "https://github.com/user/repo",
            "star_count": 5,
        }).encode()),
    }

    result = invoke_discovery()

    call_kwargs = mock_lambda_client.invoke.call_args.kwargs
    assert call_kwargs["FunctionName"] == "zerostars-discovery"
    assert call_kwargs["InvocationType"] == "RequestResponse"
    payload = json.loads(call_kwargs["Payload"])
    assert "metadata" in payload
    assert payload["metadata"]["execution_id"].startswith("mcp-standalone-")
    assert result["repo_url"] == "https://github.com/user/repo"


def test_invoke_research_places_params_in_discovery_key(mock_lambda_client):
    from lambdas.mcp.tools.agents import invoke_research
    mock_lambda_client.invoke.return_value = {
        "StatusCode": 200,
        "Payload": MagicMock(read=lambda: json.dumps({
            "developer_name": "Test User",
        }).encode()),
    }

    invoke_research(
        repo_url="https://github.com/user/repo",
        repo_name="repo",
        developer_github="user",
    )

    payload = json.loads(mock_lambda_client.invoke.call_args.kwargs["Payload"])
    assert payload["discovery"]["repo_url"] == "https://github.com/user/repo"
    assert payload["discovery"]["developer_github"] == "user"


def test_invoke_script_without_feedback(mock_lambda_client, sample_discovery_output, sample_research_output):
    from lambdas.mcp.tools.agents import invoke_script
    mock_lambda_client.invoke.return_value = {
        "StatusCode": 200,
        "Payload": MagicMock(read=lambda: json.dumps({
            "text": "**Hype:** Hello!", "character_count": 15,
        }).encode()),
    }

    invoke_script(discovery=sample_discovery_output, research=sample_research_output)

    payload = json.loads(mock_lambda_client.invoke.call_args.kwargs["Payload"])
    assert payload["metadata"]["script_attempt"] == 1
    assert "producer" not in payload


def test_invoke_script_with_feedback_sets_attempt_2(
    mock_lambda_client, sample_discovery_output, sample_research_output,
):
    from lambdas.mcp.tools.agents import invoke_script
    mock_lambda_client.invoke.return_value = {
        "StatusCode": 200,
        "Payload": MagicMock(read=lambda: json.dumps({
            "text": "**Hype:** Improved!", "character_count": 18,
        }).encode()),
    }

    invoke_script(
        discovery=sample_discovery_output,
        research=sample_research_output,
        producer_feedback="More jokes",
        producer_issues=["Not funny enough"],
    )

    payload = json.loads(mock_lambda_client.invoke.call_args.kwargs["Payload"])
    assert payload["metadata"]["script_attempt"] == 2
    assert payload["producer"]["feedback"] == "More jokes"
    assert payload["producer"]["issues"] == ["Not funny enough"]


def test_invoke_producer_places_script_text(
    mock_lambda_client, sample_discovery_output, sample_research_output,
):
    from lambdas.mcp.tools.agents import invoke_producer
    mock_lambda_client.invoke.return_value = {
        "StatusCode": 200,
        "Payload": MagicMock(read=lambda: json.dumps({
            "verdict": "PASS", "score": 8,
        }).encode()),
    }

    invoke_producer(
        script_text="**Hype:** Hello!",
        discovery=sample_discovery_output,
        research=sample_research_output,
    )

    payload = json.loads(mock_lambda_client.invoke.call_args.kwargs["Payload"])
    assert payload["script"]["text"] == "**Hype:** Hello!"


def test_invoke_cover_art_auto_generates_execution_id(mock_lambda_client):
    from lambdas.mcp.tools.agents import invoke_cover_art
    mock_lambda_client.invoke.return_value = {
        "StatusCode": 200,
        "Payload": MagicMock(read=lambda: json.dumps({
            "s3_key": "episodes/test/cover.png",
        }).encode()),
    }

    invoke_cover_art(cover_art_suggestion="Robots coding", repo_name="testrepo")

    payload = json.loads(mock_lambda_client.invoke.call_args.kwargs["Payload"])
    assert payload["metadata"]["execution_id"].startswith("mcp-standalone-")


def test_invoke_cover_art_uses_provided_execution_id(mock_lambda_client):
    from lambdas.mcp.tools.agents import invoke_cover_art
    mock_lambda_client.invoke.return_value = {
        "StatusCode": 200,
        "Payload": MagicMock(read=lambda: json.dumps({
            "s3_key": "episodes/custom-id/cover.png",
        }).encode()),
    }

    invoke_cover_art(
        cover_art_suggestion="Robots coding", repo_name="testrepo", execution_id="custom-id",
    )

    payload = json.loads(mock_lambda_client.invoke.call_args.kwargs["Payload"])
    assert payload["metadata"]["execution_id"] == "custom-id"


def test_invoke_tts_passes_script_text(mock_lambda_client):
    from lambdas.mcp.tools.agents import invoke_tts
    mock_lambda_client.invoke.return_value = {
        "StatusCode": 200,
        "Payload": MagicMock(read=lambda: json.dumps({
            "s3_key": "episodes/test/episode.mp3",
            "duration_seconds": 180,
            "character_count": 4200,
        }).encode()),
    }

    invoke_tts(script_text="**Hype:** Welcome back!")

    payload = json.loads(mock_lambda_client.invoke.call_args.kwargs["Payload"])
    assert payload["script"]["text"] == "**Hype:** Welcome back!"


def test_invoke_tts_auto_generates_execution_id(mock_lambda_client):
    from lambdas.mcp.tools.agents import invoke_tts
    mock_lambda_client.invoke.return_value = {
        "StatusCode": 200,
        "Payload": MagicMock(read=lambda: json.dumps({
            "s3_key": "episodes/test/episode.mp3",
            "duration_seconds": 180,
            "character_count": 4200,
        }).encode()),
    }

    invoke_tts(script_text="**Hype:** Hello!")

    payload = json.loads(mock_lambda_client.invoke.call_args.kwargs["Payload"])
    assert payload["metadata"]["execution_id"].startswith("mcp-standalone-")


def test_invoke_post_production_passes_all_agent_outputs(
    mock_lambda_client, sample_discovery_output, sample_research_output,
):
    from lambdas.mcp.tools.agents import invoke_post_production
    sample_script = {
        "text": "**Hype:** Hello!", "character_count": 15,
        "segments": ["intro"], "featured_repo": "repo",
        "featured_developer": "user", "cover_art_suggestion": "art",
    }
    sample_cover_art = {"s3_key": "episodes/test/cover.png", "prompt_used": "prompt"}
    sample_tts = {
        "s3_key": "episodes/test/episode.mp3",
        "duration_seconds": 180, "character_count": 4200,
    }

    mock_lambda_client.invoke.return_value = {
        "StatusCode": 200,
        "Payload": MagicMock(read=lambda: json.dumps({
            "s3_mp4_key": "episodes/test/episode.mp4",
            "episode_id": 1,
            "air_date": "2025-07-13",
        }).encode()),
    }

    invoke_post_production(
        discovery=sample_discovery_output,
        research=sample_research_output,
        script=sample_script,
        cover_art=sample_cover_art,
        tts=sample_tts,
    )

    payload = json.loads(mock_lambda_client.invoke.call_args.kwargs["Payload"])
    assert "discovery" in payload
    assert "research" in payload
    assert "script" in payload
    assert "cover_art" in payload
    assert "tts" in payload
    assert payload["script"]["text"] == "**Hype:** Hello!"
    assert payload["cover_art"]["s3_key"] == "episodes/test/cover.png"
    assert payload["tts"]["s3_key"] == "episodes/test/episode.mp3"


def test_invoke_agent_lambda_error_raises(mock_lambda_client):
    from lambdas.mcp.tools.agents import invoke_discovery
    mock_lambda_client.invoke.return_value = {
        "StatusCode": 200,
        "FunctionError": "Unhandled",
        "Payload": MagicMock(read=lambda: json.dumps({
            "errorMessage": "KeyError: 'metadata'",
        }).encode()),
    }

    with pytest.raises(RuntimeError, match="Lambda invocation failed"):
        invoke_discovery()
```

### Unit Tests: Observation (`test_observation.py`)

```python
import time

import pytest

from tests.unit.test_mcp.conftest import EXECUTION_ARN


def test_get_agent_logs_correct_log_group(mock_observation_clients):
    _, mock_logs_client = mock_observation_clients
    from lambdas.mcp.tools.observation import get_agent_logs
    mock_logs_client.filter_log_events.return_value = {"events": []}

    get_agent_logs(agent="discovery")

    call_kwargs = mock_logs_client.filter_log_events.call_args.kwargs
    assert call_kwargs["logGroupName"] == "/aws/lambda/zerostars-discovery"


def test_get_agent_logs_start_time_from_since_minutes(mock_observation_clients):
    _, mock_logs_client = mock_observation_clients
    from lambdas.mcp.tools.observation import get_agent_logs
    mock_logs_client.filter_log_events.return_value = {"events": []}
    before = int(time.time() * 1000) - (30 * 60 * 1000)

    get_agent_logs(agent="script", since_minutes=30)

    start_time = mock_logs_client.filter_log_events.call_args.kwargs["startTime"]
    assert abs(start_time - before) < 5000  # within 5 seconds tolerance


def test_get_agent_logs_filters_by_execution_id(mock_observation_clients):
    _, mock_logs_client = mock_observation_clients
    from lambdas.mcp.tools.observation import get_agent_logs
    mock_logs_client.filter_log_events.return_value = {"events": []}

    get_agent_logs(agent="tts", execution_id="arn:aws:states:test")

    call_kwargs = mock_logs_client.filter_log_events.call_args.kwargs
    assert "arn:aws:states:test" in call_kwargs["filterPattern"]


def test_get_agent_logs_respects_limit(mock_observation_clients):
    _, mock_logs_client = mock_observation_clients
    from lambdas.mcp.tools.observation import get_agent_logs
    events = [{"timestamp": i, "message": f'{{"level": "INFO"}}'} for i in range(100)]
    mock_logs_client.filter_log_events.return_value = {"events": events}

    result = get_agent_logs(agent="discovery", limit=20)

    assert len(result["logs"]) <= 20


def test_get_agent_logs_filters_by_log_level(mock_observation_clients):
    _, mock_logs_client = mock_observation_clients
    from lambdas.mcp.tools.observation import get_agent_logs
    events = [
        {"timestamp": 1, "message": '{"level": "INFO", "message": "ok"}'},
        {"timestamp": 2, "message": '{"level": "ERROR", "message": "fail"}'},
        {"timestamp": 3, "message": '{"level": "DEBUG", "message": "trace"}'},
    ]
    mock_logs_client.filter_log_events.return_value = {"events": events}

    result = get_agent_logs(agent="discovery", log_level="ERROR")

    levels = [log["level"] for log in result["logs"]]
    assert "DEBUG" not in levels
    assert "INFO" not in levels
    assert "ERROR" in levels


def test_get_execution_history_passes_include_flag(mock_observation_clients):
    mock_sfn_client, _ = mock_observation_clients
    from lambdas.mcp.tools.observation import get_execution_history
    mock_sfn_client.get_execution_history.return_value = {"events": []}

    get_execution_history(execution_arn=EXECUTION_ARN, include_input_output=False)

    call_kwargs = mock_sfn_client.get_execution_history.call_args.kwargs
    assert call_kwargs["includeExecutionData"] is False


def test_get_execution_history_paginates(mock_observation_clients):
    mock_sfn_client, _ = mock_observation_clients
    from lambdas.mcp.tools.observation import get_execution_history
    mock_sfn_client.get_execution_history.side_effect = [
        {"events": [{"type": "TaskStateEntered", "id": 1}], "nextToken": "page2"},
        {"events": [{"type": "TaskSucceeded", "id": 2}]},
    ]

    result = get_execution_history(execution_arn=EXECUTION_ARN)

    assert len(result["events"]) == 2
    assert mock_sfn_client.get_execution_history.call_count == 2


def test_get_pipeline_health_calculates_success_rate(mock_observation_clients, mock_mcp_db):
    mock_sfn_client, _ = mock_observation_clients
    from lambdas.mcp.tools.observation import get_pipeline_health
    conn, cursor = mock_mcp_db
    cursor.fetchone.return_value = (1, "cool-project", "2025-07-06")

    mock_sfn_client.list_executions.side_effect = [
        {"executions": [{"status": "SUCCEEDED"}] * 8},  # SUCCEEDED
        {"executions": [{"status": "FAILED"}] * 2},      # FAILED
        {"executions": []},                               # ABORTED
        {"executions": []},                               # RUNNING
    ]

    result = get_pipeline_health(days=30)

    assert result["succeeded"] == 8
    assert result["failed"] == 2
    assert result["success_rate"] == "80%"
    assert result["total_executions"] == 10
```

### Unit Tests: Data (`test_data.py`)

```python
import pytest


def test_query_episodes_excludes_large_fields(mock_mcp_db):
    from lambdas.mcp.tools.data import query_episodes
    conn, cursor = mock_mcp_db
    cursor.description = [("episode_id",), ("repo_name",), ("air_date",)]
    cursor.fetchall.return_value = [(1, "repo", "2025-07-06")]
    cursor.fetchone.return_value = (1,)  # total count

    result = query_episodes()

    sql = cursor.execute.call_args_list[0][0][0]
    assert "script_text" not in sql
    assert "research_json" not in sql
    assert "cover_art_prompt" not in sql


def test_query_episodes_applies_filters(mock_mcp_db):
    from lambdas.mcp.tools.data import query_episodes
    conn, cursor = mock_mcp_db
    cursor.description = [("episode_id",)]
    cursor.fetchall.return_value = []
    cursor.fetchone.return_value = (0,)

    query_episodes(developer_github="testuser", limit=5, offset=10, order_by="air_date", order="asc")

    sql = cursor.execute.call_args_list[0][0][0]
    assert "testuser" in str(cursor.execute.call_args_list[0])
    assert "ORDER BY air_date ASC" in sql or "order by air_date asc" in sql.lower()
    assert "LIMIT" in sql
    assert "OFFSET" in sql


def test_query_episodes_rejects_invalid_order_by(mock_mcp_db):
    from lambdas.mcp.tools.data import query_episodes
    with pytest.raises(ValueError, match="order_by"):
        query_episodes(order_by="DROP TABLE episodes; --")


def test_get_episode_detail_returns_full_row(mock_mcp_db):
    from lambdas.mcp.tools.data import get_episode_detail
    conn, cursor = mock_mcp_db
    cursor.description = [
        ("episode_id",), ("script_text",), ("research_json",), ("cover_art_prompt",),
    ]
    cursor.fetchone.return_value = (1, "**Hype:** Hello!", '{"key": "val"}', "art prompt")

    result = get_episode_detail(episode_id=1)

    assert result["script_text"] == "**Hype:** Hello!"
    assert result["research_json"] == '{"key": "val"}'


def test_run_sql_allows_select(mock_mcp_db):
    from lambdas.mcp.tools.data import run_sql
    conn, cursor = mock_mcp_db
    cursor.description = [("count",)]
    cursor.fetchall.return_value = [(11,)]

    result = run_sql(sql="SELECT count(*) FROM episodes")

    assert result["columns"] == ["count"]
    assert result["rows"] == [[11]]
    assert result["row_count"] == 1


def test_run_sql_rejects_insert(mock_mcp_db):
    from lambdas.mcp.tools.data import run_sql
    with pytest.raises(ValueError, match="SELECT"):
        run_sql(sql="INSERT INTO episodes (repo_name) VALUES ('x')")


def test_run_sql_rejects_delete(mock_mcp_db):
    from lambdas.mcp.tools.data import run_sql
    with pytest.raises(ValueError, match="SELECT"):
        run_sql(sql="DELETE FROM episodes")


def test_run_sql_rejects_drop(mock_mcp_db):
    from lambdas.mcp.tools.data import run_sql
    with pytest.raises(ValueError, match="SELECT"):
        run_sql(sql="DROP TABLE episodes")


def test_run_sql_rejects_update(mock_mcp_db):
    from lambdas.mcp.tools.data import run_sql
    with pytest.raises(ValueError, match="SELECT"):
        run_sql(sql="UPDATE episodes SET repo_name = 'x'")


def test_run_sql_leading_whitespace_select(mock_mcp_db):
    from lambdas.mcp.tools.data import run_sql
    conn, cursor = mock_mcp_db
    cursor.description = [("x",)]
    cursor.fetchall.return_value = [(1,)]

    result = run_sql(sql="   SELECT 1")

    assert result["row_count"] == 1


def test_run_sql_case_insensitive(mock_mcp_db):
    from lambdas.mcp.tools.data import run_sql
    conn, cursor = mock_mcp_db
    cursor.description = [("x",)]
    cursor.fetchall.return_value = [(1,)]

    result = run_sql(sql="select 1")

    assert result["row_count"] == 1


def test_run_sql_sets_statement_timeout(mock_mcp_db):
    from lambdas.mcp.tools.data import run_sql
    conn, cursor = mock_mcp_db
    cursor.description = [("x",)]
    cursor.fetchall.return_value = [(1,)]

    run_sql(sql="SELECT 1")

    # Verify statement_timeout was set before the query
    execute_calls = [str(c) for c in cursor.execute.call_args_list]
    assert any("statement_timeout" in c for c in execute_calls)


def test_upsert_metrics_inserts(mock_mcp_db):
    from lambdas.mcp.tools.data import upsert_metrics
    conn, cursor = mock_mcp_db
    cursor.fetchone.return_value = (5,)

    result = upsert_metrics(episode_id=1, views=100, likes=10)

    sql = cursor.execute.call_args_list[-1][0][0]
    assert "INSERT" in sql
    assert "ON CONFLICT" in sql
    assert result["metric_id"] == 5


def test_query_featured_developers_joins_episodes(mock_mcp_db):
    from lambdas.mcp.tools.data import query_featured_developers
    conn, cursor = mock_mcp_db
    cursor.description = [("developer_github",), ("episode_id",), ("featured_date",), ("repo_name",)]
    cursor.fetchall.return_value = [("user", 1, "2025-07-06", "repo")]

    result = query_featured_developers()

    sql = cursor.execute.call_args[0][0]
    assert "JOIN" in sql or "join" in sql.lower()
    assert result["developers"][0]["repo_name"] == "repo"


def test_query_metrics_joins_episodes(mock_mcp_db):
    from lambdas.mcp.tools.data import query_metrics
    conn, cursor = mock_mcp_db
    cursor.description = [
        ("episode_id",), ("repo_name",), ("developer_github",),
        ("linkedin_post_url",), ("views",), ("likes",),
        ("comments",), ("shares",), ("snapshot_date",),
    ]
    cursor.fetchall.return_value = [
        (1, "repo", "user", "https://linkedin.com/post/1", 1200, 45, 12, 8, "2025-07-10")
    ]

    result = query_metrics()

    sql = cursor.execute.call_args[0][0]
    assert "JOIN" in sql or "join" in sql.lower()
    assert result["metrics"][0]["repo_name"] == "repo"
    assert result["metrics"][0]["views"] == 1200
```

### Unit Tests: Assets (`test_assets.py`)

```python
from unittest.mock import MagicMock

from moto import mock_aws
import boto3


def test_get_episode_assets_returns_presigned_urls(mock_s3_client, mock_mcp_db):
    from lambdas.mcp.tools.assets import get_episode_assets
    conn, cursor = mock_mcp_db
    cursor.fetchone.return_value = (
        "episodes/test/cover.png",
        "episodes/test/episode.mp3",
        "episodes/test/episode.mp4",
    )
    mock_s3_client.generate_presigned_url.return_value = "https://presigned-url"

    result = get_episode_assets(episode_id=1)

    assert result["cover_art_url"] == "https://presigned-url"
    assert result["mp3_url"] == "https://presigned-url"
    assert result["mp4_url"] == "https://presigned-url"
    assert mock_s3_client.generate_presigned_url.call_count == 3


def test_get_episode_assets_null_for_missing(mock_s3_client, mock_mcp_db):
    from lambdas.mcp.tools.assets import get_episode_assets
    conn, cursor = mock_mcp_db
    cursor.fetchone.return_value = ("episodes/test/cover.png", None, None)
    mock_s3_client.generate_presigned_url.return_value = "https://presigned-url"

    result = get_episode_assets(episode_id=1)

    assert result["cover_art_url"] == "https://presigned-url"
    assert result["mp3_url"] is None
    assert result["mp4_url"] is None


def test_list_s3_assets_passes_prefix(mock_s3_client):
    from lambdas.mcp.tools.assets import list_s3_assets
    mock_s3_client.list_objects_v2.return_value = {
        "Contents": [
            {"Key": "episodes/test/cover.png", "Size": 1024, "LastModified": "2025-07-13T09:00:00Z"},
        ],
    }

    result = list_s3_assets(prefix="episodes/test/")

    mock_s3_client.list_objects_v2.assert_called_once()
    call_kwargs = mock_s3_client.list_objects_v2.call_args.kwargs
    assert call_kwargs["Prefix"] == "episodes/test/"
    assert len(result["objects"]) == 1


def test_list_s3_assets_empty_bucket(mock_s3_client):
    from lambdas.mcp.tools.assets import list_s3_assets
    mock_s3_client.list_objects_v2.return_value = {}  # No Contents key

    result = list_s3_assets()

    assert result["objects"] == []


def test_get_presigned_url_default_expiry(mock_s3_client):
    from lambdas.mcp.tools.assets import get_presigned_url
    mock_s3_client.generate_presigned_url.return_value = "https://presigned-url"

    get_presigned_url(s3_key="episodes/test/cover.png")

    call_kwargs = mock_s3_client.generate_presigned_url.call_args.kwargs
    assert call_kwargs["ExpiresIn"] == 3600


def test_get_presigned_url_custom_expiry(mock_s3_client):
    from lambdas.mcp.tools.assets import get_presigned_url
    mock_s3_client.generate_presigned_url.return_value = "https://presigned-url"

    get_presigned_url(s3_key="episodes/test/cover.png", expires_in=7200)

    call_kwargs = mock_s3_client.generate_presigned_url.call_args.kwargs
    assert call_kwargs["ExpiresIn"] == 7200


def test_get_presigned_url_caps_at_max(mock_s3_client):
    from lambdas.mcp.tools.assets import get_presigned_url
    mock_s3_client.generate_presigned_url.return_value = "https://presigned-url"

    get_presigned_url(s3_key="episodes/test/cover.png", expires_in=999999)

    call_kwargs = mock_s3_client.generate_presigned_url.call_args.kwargs
    assert call_kwargs["ExpiresIn"] <= 43200
```

### Unit Tests: Site (`test_site.py`)

```python
def test_invalidate_cache_default_paths(mock_site_boto3_clients):
    mock_cloudfront_client, _ = mock_site_boto3_clients
    from lambdas.mcp.tools.site import invalidate_cache
    mock_cloudfront_client.create_invalidation.return_value = {
        "Invalidation": {"Id": "I123", "Status": "InProgress"},
    }

    result = invalidate_cache()

    call_kwargs = mock_cloudfront_client.create_invalidation.call_args.kwargs
    paths = call_kwargs["InvalidationBatch"]["Paths"]["Items"]
    assert paths == ["/*"]
    assert result["invalidation_id"] == "I123"


def test_invalidate_cache_custom_paths(mock_site_boto3_clients):
    mock_cloudfront_client, _ = mock_site_boto3_clients
    from lambdas.mcp.tools.site import invalidate_cache
    mock_cloudfront_client.create_invalidation.return_value = {
        "Invalidation": {"Id": "I456", "Status": "InProgress"},
    }

    result = invalidate_cache(paths=["/", "/episodes/1"])

    paths = mock_cloudfront_client.create_invalidation.call_args.kwargs[
        "InvalidationBatch"
    ]["Paths"]["Items"]
    assert paths == ["/", "/episodes/1"]


def test_get_site_status_aggregates_sources(mock_site_boto3_clients, mock_mcp_db):
    mock_cloudfront_client, mock_acm_client = mock_site_boto3_clients
    from lambdas.mcp.tools.site import get_site_status
    conn, cursor = mock_mcp_db
    cursor.fetchone.side_effect = [(11,), (11, "cool-project", "2025-07-06")]

    mock_cloudfront_client.get_distribution.return_value = {
        "Distribution": {"Id": "E123", "Status": "Deployed"},
    }
    mock_acm_client.describe_certificate.return_value = {
        "Certificate": {"Status": "ISSUED"},
    }

    result = get_site_status()

    assert result["distribution_status"] == "Deployed"
    assert result["ssl_status"] == "ISSUED"
    assert result["episode_count"] == 11
    assert result["cloudfront_id"] == "E123"
```

### Unit Tests: Resources (`test_resources.py`)

```python
def test_episodes_resource_returns_list(mock_mcp_db):
    from lambdas.mcp.resources import read_episodes_resource
    conn, cursor = mock_mcp_db
    cursor.description = [("episode_id",), ("air_date",), ("repo_name",)]
    cursor.fetchall.return_value = [(1, "2025-07-06", "repo")]

    result = read_episodes_resource()

    assert len(result) == 1
    assert result[0]["episode_id"] == 1


def test_pipeline_status_resource(mock_sfn_client):
    from lambdas.mcp.resources import read_pipeline_status_resource
    mock_sfn_client.list_executions.side_effect = [
        {"executions": []},  # RUNNING
        {"executions": [
            {"executionArn": "arn:...", "name": "test", "status": "SUCCEEDED",
             "startDate": "2025-07-13T09:00:00Z", "stopDate": "2025-07-13T09:12:00Z"},
        ]},  # recent completed
    ]

    result = read_pipeline_status_resource()

    assert result["currently_running"] == []
    assert len(result["recent"]) == 1


def test_featured_developers_resource(mock_mcp_db):
    from lambdas.mcp.resources import read_featured_developers_resource
    conn, cursor = mock_mcp_db
    cursor.description = [("developer_github",), ("episode_id",), ("featured_date",)]
    cursor.fetchall.return_value = [("user1", 1, "2025-07-06")]

    result = read_featured_developers_resource()

    assert result[0]["developer_github"] == "user1"


def test_episode_detail_resource_returns_full_row(mock_mcp_db):
    from lambdas.mcp.resources import read_episode_detail_resource
    conn, cursor = mock_mcp_db
    cursor.description = [
        ("episode_id",), ("script_text",), ("research_json",),
        ("cover_art_prompt",), ("air_date",), ("repo_name",),
    ]
    cursor.fetchone.return_value = (
        1, "**Hype:** Hello!", '{"key": "val"}', "art prompt", "2025-07-06", "repo",
    )

    result = read_episode_detail_resource(episode_id=1)

    assert result["episode_id"] == 1
    assert result["script_text"] == "**Hype:** Hello!"
    assert result["research_json"] == '{"key": "val"}'


def test_metrics_resource_returns_list(mock_mcp_db):
    from lambdas.mcp.resources import read_metrics_resource
    conn, cursor = mock_mcp_db
    cursor.description = [("episode_id",), ("repo_name",), ("views",), ("likes",)]
    cursor.fetchall.return_value = [(1, "repo", 1200, 45)]

    result = read_metrics_resource()

    assert len(result) == 1
    assert result[0]["views"] == 1200
```

### Unit Tests: Handler (`test_handler.py`)

```python
def test_handler_registers_all_tools():
    """Verify the MCP server registers all 26 tools."""
    from lambdas.mcp.handler import create_mcp_server
    server = create_mcp_server()
    tool_names = {t.name for t in server.list_tools()}

    expected = {
        "start_pipeline", "stop_pipeline", "get_execution_status", "list_executions", "retry_from_step",
        "invoke_discovery", "invoke_research", "invoke_script", "invoke_producer",
        "invoke_cover_art", "invoke_tts", "invoke_post_production",
        "get_agent_logs", "get_execution_history", "get_pipeline_health",
        "query_episodes", "get_episode_detail", "query_metrics",
        "query_featured_developers", "run_sql", "upsert_metrics",
        "get_episode_assets", "list_s3_assets", "get_presigned_url",
        "invalidate_cache", "get_site_status",
    }
    assert tool_names == expected


def test_handler_registers_all_resources():
    """Verify the MCP server registers all 5 resources."""
    from lambdas.mcp.handler import create_mcp_server
    server = create_mcp_server()
    resource_uris = {r.uri for r in server.list_resources()}

    expected = {
        "zerostars://episodes",
        "zerostars://episodes/{episode_id}",
        "zerostars://metrics",
        "zerostars://pipeline/status",
        "zerostars://featured-developers",
    }
    assert resource_uris == expected
```

### Integration Tests

Integration tests hit real AWS services. They require AWS credentials and are excluded from CI by default. They perform read-only operations to avoid side effects.

#### Step Functions (`tests/integration/test_mcp_pipeline_live.py`)

```python
import os

import boto3
import pytest


@pytest.mark.integration
def test_list_executions_returns_valid_shape():
    """ListExecutions against the real state machine returns expected fields."""
    sfn = boto3.client("stepfunctions")
    arn = os.environ.get("STATE_MACHINE_ARN")
    assert arn, "STATE_MACHINE_ARN env var required"

    response = sfn.list_executions(stateMachineArn=arn, maxResults=5)

    assert "executions" in response
    for exc in response["executions"]:
        assert "executionArn" in exc
        assert "status" in exc
        assert exc["status"] in {"RUNNING", "SUCCEEDED", "FAILED", "ABORTED", "TIMED_OUT", "PENDING_REDRIVE"}


@pytest.mark.integration
def test_describe_execution_if_any_exist():
    """DescribeExecution on the most recent execution returns expected fields."""
    sfn = boto3.client("stepfunctions")
    arn = os.environ.get("STATE_MACHINE_ARN")
    assert arn, "STATE_MACHINE_ARN env var required"

    executions = sfn.list_executions(stateMachineArn=arn, maxResults=1)
    if not executions["executions"]:
        pytest.skip("No executions to describe")

    exc_arn = executions["executions"][0]["executionArn"]
    detail = sfn.describe_execution(executionArn=exc_arn)

    assert detail["status"] in {"RUNNING", "SUCCEEDED", "FAILED", "ABORTED", "TIMED_OUT", "PENDING_REDRIVE"}
    assert "startDate" in detail
    if detail["status"] == "SUCCEEDED":
        assert detail["output"] is not None
```

#### Postgres (`tests/integration/test_mcp_data_live.py`)

```python
import os

import psycopg2
import pytest


@pytest.mark.integration
def test_query_episodes_table():
    """SELECT from episodes table succeeds and returns expected columns."""
    conn_str = os.environ["DB_CONNECTION_STRING"]

    conn = psycopg2.connect(conn_str)
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT episode_id, repo_name, air_date, star_count_at_recording "
                "FROM episodes ORDER BY episode_id DESC LIMIT 5"
            )
            columns = [desc[0] for desc in cur.description]
            assert "episode_id" in columns
            assert "repo_name" in columns
    finally:
        conn.close()


@pytest.mark.integration
def test_query_featured_developers_table():
    """SELECT from featured_developers succeeds."""
    conn_str = os.environ["DB_CONNECTION_STRING"]

    conn = psycopg2.connect(conn_str)
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT developer_github, episode_id FROM featured_developers LIMIT 5")
            columns = [desc[0] for desc in cur.description]
            assert "developer_github" in columns
    finally:
        conn.close()


@pytest.mark.integration
def test_statement_timeout_works():
    """Verify statement_timeout prevents long queries."""
    conn_str = os.environ["DB_CONNECTION_STRING"]

    conn = psycopg2.connect(conn_str)
    try:
        with conn.cursor() as cur:
            cur.execute("SET statement_timeout = '1s'")
            with pytest.raises(psycopg2.errors.QueryCanceled):
                cur.execute("SELECT pg_sleep(10)")
    finally:
        conn.close()
```

#### S3 (`tests/integration/test_mcp_assets_live.py`)

```python
import os

import boto3
import pytest


@pytest.mark.integration
def test_list_objects_in_episodes_bucket():
    """ListObjectsV2 on the real bucket returns valid response."""
    s3 = boto3.client("s3")
    bucket = os.environ.get("S3_BUCKET")
    assert bucket, "S3_BUCKET env var required"

    response = s3.list_objects_v2(Bucket=bucket, Prefix="episodes/", MaxKeys=5)

    assert response["ResponseMetadata"]["HTTPStatusCode"] == 200
    if "Contents" in response:
        for obj in response["Contents"]:
            assert "Key" in obj
            assert "Size" in obj


@pytest.mark.integration
def test_generate_presigned_url():
    """Presigned URL generation succeeds for an existing object."""
    s3 = boto3.client("s3")
    bucket = os.environ.get("S3_BUCKET")
    assert bucket, "S3_BUCKET env var required"

    response = s3.list_objects_v2(Bucket=bucket, Prefix="episodes/", MaxKeys=1)
    if "Contents" not in response:
        pytest.skip("No objects in bucket to generate presigned URL for")

    key = response["Contents"][0]["Key"]
    url = s3.generate_presigned_url(
        "get_object", Params={"Bucket": bucket, "Key": key}, ExpiresIn=60,
    )
    assert url.startswith("https://")
```

### End-to-End Tests (`tests/e2e/test_mcp_e2e.py`)

E2E tests exercise the full MCP tool chain against real AWS. They start a pipeline execution, observe it, and stop it before it consumes expensive resources (Bedrock, ElevenLabs). The Discovery agent is the first step and takes 30-60 seconds, so stopping during Discovery avoids most cost.

```python
import json
import os
import time

import boto3
import pytest


STATE_MACHINE_ARN = os.environ.get("STATE_MACHINE_ARN", "")


@pytest.mark.e2e
@pytest.mark.skip(reason="E2E: starts a real execution (costs Bedrock $). Run manually.")
class TestMCPEndToEnd:
    """Full tool chain: start → status → logs → stop.

    Run with:
        STATE_MACHINE_ARN=arn:... S3_BUCKET=... \
        PYTHONPATH=lambdas/shared/python \
        pytest tests/e2e/test_mcp_e2e.py -v -m e2e \
        --override-ini='addopts='
    """

    def test_start_observe_stop_cycle(self):
        """Start a pipeline, observe it running, then abort it."""
        from lambdas.mcp.tools.pipeline import start_pipeline, get_execution_status, stop_pipeline, list_executions
        from lambdas.mcp.tools.observation import get_agent_logs

        # 1. Start
        start_result = start_pipeline()
        execution_arn = start_result["execution_arn"]
        assert execution_arn.startswith("arn:aws:states:")

        try:
            # 2. Wait for it to enter RUNNING
            time.sleep(3)

            # 3. Get status — should be RUNNING in Discovery
            status = get_execution_status(execution_arn=execution_arn)
            assert status["status"] == "RUNNING"
            assert status["current_step"] in ("Discovery", "InitializeMetadata", "ResumeRouter")

            # 4. List executions — our execution should appear
            executions = list_executions(status_filter="RUNNING")
            running_arns = [e["execution_arn"] for e in executions["executions"]]
            assert execution_arn in running_arns

            # 5. Get logs (may be empty if Discovery hasn't logged yet)
            logs = get_agent_logs(agent="discovery", since_minutes=5)
            assert "logs" in logs  # shape is valid even if empty

        finally:
            # 6. Stop — always stop to avoid wasting Bedrock/Exa credits
            stop_result = stop_pipeline(execution_arn=execution_arn, cause="E2E test cleanup")
            assert stop_result["status"] == "ABORTED"

        # 7. Verify stopped
        final_status = get_execution_status(execution_arn=execution_arn)
        assert final_status["status"] == "ABORTED"

    def test_list_and_describe_historical_execution(self):
        """List past executions and describe one — no new execution started."""
        from lambdas.mcp.tools.pipeline import list_executions, get_execution_status
        from lambdas.mcp.tools.observation import get_execution_history

        executions = list_executions(max_results=3)
        if not executions["executions"]:
            pytest.skip("No historical executions to describe")

        exc = executions["executions"][0]
        status = get_execution_status(execution_arn=exc["execution_arn"])
        assert status["name"] == exc["name"]

        if exc["status"] != "RUNNING":
            history = get_execution_history(
                execution_arn=exc["execution_arn"], include_input_output=False,
            )
            assert len(history["events"]) > 0

    def test_query_episodes_and_assets(self):
        """Query episodes from Postgres and get presigned URLs for the latest."""
        from lambdas.mcp.tools.data import query_episodes
        from lambdas.mcp.tools.assets import get_episode_assets

        episodes = query_episodes(limit=1)
        if episodes["total_count"] == 0:
            pytest.skip("No episodes in database")

        episode = episodes["episodes"][0]
        assert "episode_id" in episode
        assert "repo_name" in episode

        assets = get_episode_assets(episode_id=episode["episode_id"])
        assert "s3_keys" in assets
        # At least one asset should exist for a real episode
        has_asset = any([assets["cover_art_url"], assets["mp3_url"], assets["mp4_url"]])
        assert has_asset, "Expected at least one S3 asset for the episode"

    def test_site_status(self):
        """Get site status — verifies CloudFront and ACM integration."""
        from lambdas.mcp.tools.site import get_site_status

        status = get_site_status()

        assert status["distribution_status"] in ("Deployed", "InProgress")
        assert status["ssl_status"] == "ISSUED"
        assert status["domain"] == os.environ.get("SITE_DOMAIN", "podcast.ryans-lab.click")
```

### Per-Tool Test Requirements

| Tool | Required unit test cases |
|------|------------------------|
| `start_pipeline` | Calls `StartExecution` with correct ARN; name matches `mcp-{timestamp}` format; name <= 80 chars and valid characters; returns `execution_arn` + `start_date`. |
| `stop_pipeline` | Passes `executionArn`, `error`, `cause`; works without `cause`; returns `ABORTED` status. |
| `get_execution_status` | RUNNING: calls `GetExecutionHistory` to find `current_step`; SUCCEEDED: uses `output` for state, no history call; FAILED: includes `error` + `cause`; state_object parsed from JSON. |
| `list_executions` | Passes `statusFilter` when provided; omits `statusFilter` when not; respects `maxResults`. |
| `retry_from_step` | Extracts state from failed execution; carries only keys before retry point; sets `metadata.resume_from`; name starts with `mcp-retry-`; does not carry keys at or after retry point. |
| `invoke_discovery` | Calls `zerostars-discovery` with `RequestResponse`; builds synthetic state with `metadata`; returns parsed payload. |
| `invoke_research` | Places `repo_url`, `repo_name`, `developer_github` under `$.discovery`. |
| `invoke_script` | Without feedback: `script_attempt=1`, no `producer` key; with feedback: `script_attempt=2`, `producer.feedback` + `producer.issues` set. |
| `invoke_producer` | Places `script_text` at `$.script.text`, discovery and research in correct keys. |
| `invoke_cover_art` | Auto-generates `execution_id` when omitted; uses provided `execution_id` when given. |
| `invoke_tts` | Passes `script_text` at `$.script.text`; auto-generates `execution_id`. |
| `invoke_post_production` | Passes all 5 agent outputs in correct state keys. |
| All `invoke_*` | Returns error when Lambda returns `FunctionError`. |
| `get_agent_logs` | Correct log group name per agent; `startTime` from `since_minutes`; `filterPattern` from `execution_id`; respects `limit`; filters by `log_level` client-side. |
| `get_execution_history` | Passes `includeExecutionData`; paginates through `nextToken`. |
| `get_pipeline_health` | Aggregates counts from multiple `ListExecutions` calls; calculates success rate; includes last successful episode from Postgres. |
| `query_episodes` | Excludes `script_text`, `research_json`, `cover_art_prompt`; applies filter params; validates `order_by` against allowlist; rejects SQL injection in `order_by`. |
| `get_episode_detail` | Returns full row including `script_text` and `research_json`. |
| `query_metrics` | Joins with `episodes` for context fields. |
| `query_featured_developers` | Joins with `episodes` for `repo_name`. |
| `run_sql` | Allows SELECT; rejects INSERT, DELETE, DROP, UPDATE; handles leading whitespace; case-insensitive check; sets `statement_timeout`; returns `columns`, `rows`, `row_count`. |
| `upsert_metrics` | Generates `INSERT ... ON CONFLICT` SQL; returns `metric_id` and action. |
| `get_episode_assets` | Queries DB for S3 paths; generates presigned URLs; returns null for missing assets. |
| `list_s3_assets` | Passes prefix; handles empty bucket (no `Contents` key); respects limit. |
| `get_presigned_url` | Default expiry 3600s; accepts custom expiry; caps at 43200s. |
| `invalidate_cache` | Default paths `["/*"]`; accepts custom paths; auto-generates `CallerReference`. |
| `get_site_status` | Aggregates CloudFront status + ACM status + episode count from Postgres. |

### Running MCP Tests

```bash
# Unit tests only
PYTHONPATH=lambdas/shared/python pytest tests/unit/test_mcp/ -v

# Integration tests (requires AWS credentials + env vars)
STATE_MACHINE_ARN=arn:... S3_BUCKET=zerostars-episodes-... \
PYTHONPATH=lambdas/shared/python pytest tests/integration/test_mcp_*_live.py -v -m integration

# E2E (costs money — run manually)
STATE_MACHINE_ARN=arn:... S3_BUCKET=zerostars-episodes-... SITE_DOMAIN=podcast.ryans-lab.click \
PYTHONPATH=lambdas/shared/python pytest tests/e2e/test_mcp_e2e.py -v -m e2e \
--override-ini='addopts='
```
