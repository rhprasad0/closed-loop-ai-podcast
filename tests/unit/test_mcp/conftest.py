import json
from collections.abc import Generator
from unittest.mock import MagicMock, patch

import pytest

STATE_MACHINE_ARN = "arn:aws:states:us-east-1:123456789:stateMachine:zerostars-pipeline"
EXECUTION_ARN = (
    "arn:aws:states:us-east-1:123456789:execution:zerostars-pipeline:mcp-20250713T090000Z"
)
S3_BUCKET = "zerostars-episodes-123456789"
CLOUDFRONT_DIST_ID = "E1234567890"
ACM_CERT_ARN = "arn:aws:acm:us-east-1:123456789:certificate/abc-123"
SITE_DOMAIN = "podcast.ryans-lab.click"


@pytest.fixture(autouse=True)
def mcp_env(monkeypatch: pytest.MonkeyPatch) -> None:
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
def mock_sfn_client() -> Generator[MagicMock, None, None]:
    """Mock Step Functions boto3 client."""
    with patch("lambdas.mcp.tools.pipeline.boto3.client") as mock:
        client = MagicMock()
        mock.return_value = client
        yield client


@pytest.fixture
def mock_lambda_client() -> Generator[MagicMock, None, None]:
    """Mock Lambda boto3 client for agent invocations."""
    with patch("lambdas.mcp.tools.agents.boto3.client") as mock:
        client = MagicMock()
        mock.return_value = client
        yield client


@pytest.fixture
def mock_logs_client() -> Generator[MagicMock, None, None]:
    """Mock CloudWatch Logs boto3 client."""
    with patch("lambdas.mcp.tools.observation.boto3.client") as mock:
        client = MagicMock()
        mock.return_value = client
        yield client


@pytest.fixture
def mock_observation_clients() -> Generator[tuple[MagicMock, MagicMock], None, None]:
    """Mock boto3 clients for observation module — dispatches SFN and Logs.

    The observation module creates its own boto3 clients for Step Functions
    and CloudWatch Logs. This fixture patches at the observation module path
    (not the pipeline module path) to correctly intercept both.
    """
    sfn_client = MagicMock()
    logs_client = MagicMock()

    def client_factory(service_name: str, **kwargs: object) -> MagicMock:
        if service_name == "stepfunctions":
            return sfn_client
        elif service_name == "logs":
            return logs_client
        raise ValueError(f"Unexpected service: {service_name}")

    with patch("lambdas.mcp.tools.observation.boto3.client", side_effect=client_factory):
        yield sfn_client, logs_client


@pytest.fixture
def mock_s3_client() -> Generator[MagicMock, None, None]:
    """Mock S3 boto3 client for asset tools."""
    with patch("lambdas.mcp.tools.assets.boto3.client") as mock:
        client = MagicMock()
        mock.return_value = client
        yield client


@pytest.fixture
def mock_site_boto3_clients() -> Generator[tuple[MagicMock, MagicMock], None, None]:
    """Mock boto3.client for site tools — dispatches by service name.

    CloudFront and ACM are separate AWS services. The site module calls
    boto3.client("cloudfront") and boto3.client("acm") separately.
    This fixture uses side_effect to return different mocks for each.
    """
    cf_client = MagicMock()
    acm_client = MagicMock()

    def client_factory(service_name: str, **kwargs: object) -> MagicMock:
        if service_name == "cloudfront":
            return cf_client
        elif service_name == "acm":
            return acm_client
        raise ValueError(f"Unexpected service: {service_name}")

    with patch("lambdas.mcp.tools.site.boto3.client", side_effect=client_factory):
        yield cf_client, acm_client


@pytest.fixture
def mock_mcp_db(
    mock_db_connection: MagicMock,
) -> Generator[tuple[MagicMock, MagicMock], None, None]:
    """Patches get_connection at the MCP data module's import path.

    All MCP modules that need DB access delegate through the data module's
    functions rather than importing get_connection from shared.db directly.
    This applies to: data tools, asset tools (get_episode_assets), observation
    tools (get_pipeline_health), site tools (get_site_status), and all resource
    handlers. Patching data.get_connection covers all of them.
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
def sample_execution_running() -> dict:
    """DescribeExecution response for a RUNNING execution."""
    return {
        "executionArn": EXECUTION_ARN,
        "stateMachineArn": STATE_MACHINE_ARN,
        "name": "mcp-20250713T090000Z",
        "status": "RUNNING",
        "startDate": "2025-07-13T09:00:00.000Z",
        "input": json.dumps(
            {
                "metadata": {"execution_id": EXECUTION_ARN, "script_attempt": 1},
                "discovery": {"repo_url": "https://github.com/user/repo", "star_count": 7},
            }
        ),
        "inputDetails": {"included": True},
    }


@pytest.fixture
def sample_execution_succeeded() -> dict:
    """DescribeExecution response for a SUCCEEDED execution."""
    return {
        "executionArn": EXECUTION_ARN,
        "stateMachineArn": STATE_MACHINE_ARN,
        "name": "mcp-20250713T090000Z",
        "status": "SUCCEEDED",
        "startDate": "2025-07-13T09:00:00.000Z",
        "stopDate": "2025-07-13T09:12:34.000Z",
        "input": json.dumps({"metadata": {"execution_id": EXECUTION_ARN, "script_attempt": 1}}),
        "output": json.dumps(
            {
                "metadata": {"execution_id": EXECUTION_ARN, "script_attempt": 1},
                "discovery": {"repo_url": "https://github.com/user/repo"},
                "research": {"developer_name": "Test User"},
                "script": {"text": "**Hype:** Hello!", "character_count": 15},
                "producer": {"verdict": "PASS", "score": 8},
                "cover_art": {"s3_key": "episodes/test/cover.png"},
                "tts": {"s3_key": "episodes/test/episode.mp3", "duration_seconds": 180},
                "post_production": {"s3_mp4_key": "episodes/test/episode.mp4", "episode_id": 1},
            }
        ),
        "outputDetails": {"included": True},
    }


@pytest.fixture
def sample_execution_failed() -> dict:
    """DescribeExecution response for a FAILED execution."""
    return {
        "executionArn": EXECUTION_ARN,
        "stateMachineArn": STATE_MACHINE_ARN,
        "name": "mcp-20250713T090000Z",
        "status": "FAILED",
        "startDate": "2025-07-13T09:00:00.000Z",
        "stopDate": "2025-07-13T09:05:00.000Z",
        "input": json.dumps(
            {
                "metadata": {"execution_id": EXECUTION_ARN, "script_attempt": 1},
                "discovery": {"repo_url": "https://github.com/user/repo", "star_count": 7},
                "research": {"developer_name": "Test User"},
            }
        ),
        "error": "States.TaskFailed",
        "cause": "TTS Lambda timed out after 300 seconds",
    }


@pytest.fixture
def sample_execution_history_events() -> dict:
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
