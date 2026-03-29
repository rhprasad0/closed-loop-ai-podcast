"""E2E tests: MCP tool invocation via deployed Lambda.

Invokes the MCP Lambda via boto3 lambda.invoke() with Lambda Function URL v2
event payloads containing MCP JSON-RPC bodies. This exercises the full stack:
Lambda handler → ASGI adapter → FastMCP → tool execution → AWS service calls.
"""

from __future__ import annotations

from typing import Any

import pytest
from botocore.exceptions import ClientError

from tests.e2e.helpers import PipelineExecutionResult, invoke_mcp_tool

pytestmark = [pytest.mark.e2e, pytest.mark.timeout(60)]


@pytest.fixture(scope="module")
def mcp_function_name(deployed_resources: dict[str, str]) -> str:
    """Get the MCP Lambda function name, skipping if not available."""
    return deployed_resources["mcp_function_name"]


@pytest.fixture(scope="module")
def mcp_available(lambda_client: Any, mcp_function_name: str) -> bool:
    """Check if the MCP Lambda exists. Skip all tests if not deployed."""
    try:
        lambda_client.get_function(FunctionName=mcp_function_name)
        return True
    except ClientError as exc:
        if exc.response["Error"]["Code"] == "ResourceNotFoundException":
            pytest.skip(f"MCP Lambda {mcp_function_name} not deployed")
        raise


def _require_pipeline(result: PipelineExecutionResult) -> dict[str, Any]:
    """Skip the test if the pipeline did not succeed."""
    if result.status != "SUCCEEDED":
        pytest.skip(f"Pipeline did not succeed (status={result.status})")
    return result.final_state


# ---------------------------------------------------------------------------
# Pipeline observation tools
# ---------------------------------------------------------------------------


def test_list_executions(
    lambda_client: Any,
    mcp_function_name: str,
    mcp_available: bool,
) -> None:
    """list_executions returns a list of executions."""
    result = invoke_mcp_tool(
        lambda_client,
        mcp_function_name,
        "list_executions",
        {"max_results": 5},
    )

    assert "executions" in result or isinstance(result, list), (
        f"Unexpected list_executions response: {result}"
    )


def test_get_execution_status(
    lambda_client: Any,
    mcp_function_name: str,
    mcp_available: bool,
    pipeline_execution: PipelineExecutionResult,
) -> None:
    """get_execution_status returns details for the e2e execution."""
    _require_pipeline(pipeline_execution)

    result = invoke_mcp_tool(
        lambda_client,
        mcp_function_name,
        "get_execution_status",
        {"execution_arn": pipeline_execution.execution_arn},
    )

    assert result.get("status") == "SUCCEEDED", (
        f"Expected SUCCEEDED, got {result.get('status')}"
    )


def test_get_pipeline_health(
    lambda_client: Any,
    mcp_function_name: str,
    mcp_available: bool,
) -> None:
    """get_pipeline_health returns aggregate stats."""
    result = invoke_mcp_tool(
        lambda_client,
        mcp_function_name,
        "get_pipeline_health",
        {"days": 7},
    )

    assert "total_executions" in result or "success_rate" in result, (
        f"Unexpected health response: {result}"
    )


# ---------------------------------------------------------------------------
# Data query tools
# ---------------------------------------------------------------------------


def test_query_episodes(
    lambda_client: Any,
    mcp_function_name: str,
    mcp_available: bool,
    pipeline_execution: PipelineExecutionResult,
) -> None:
    """query_episodes returns episodes including the e2e episode."""
    _require_pipeline(pipeline_execution)

    result = invoke_mcp_tool(
        lambda_client,
        mcp_function_name,
        "query_episodes",
        {"limit": 10},
    )

    # Result should contain episodes
    episodes = result.get("episodes", result if isinstance(result, list) else [])
    assert len(episodes) > 0, "No episodes returned"


def test_get_episode_detail(
    lambda_client: Any,
    mcp_function_name: str,
    mcp_available: bool,
    pipeline_execution: PipelineExecutionResult,
) -> None:
    """get_episode_detail returns the full record for the e2e episode."""
    state = _require_pipeline(pipeline_execution)
    episode_id = state["post_production"]["episode_id"]

    result = invoke_mcp_tool(
        lambda_client,
        mcp_function_name,
        "get_episode_detail",
        {"episode_id": episode_id},
    )

    # Should include the full text fields
    assert result.get("script_text") or result.get("repo_name"), (
        f"Episode detail missing expected fields: {list(result.keys())}"
    )


# ---------------------------------------------------------------------------
# Asset tools
# ---------------------------------------------------------------------------


def test_get_episode_assets(
    lambda_client: Any,
    mcp_function_name: str,
    mcp_available: bool,
    pipeline_execution: PipelineExecutionResult,
) -> None:
    """get_episode_assets returns S3 keys for the e2e episode."""
    state = _require_pipeline(pipeline_execution)
    episode_id = state["post_production"]["episode_id"]

    result = invoke_mcp_tool(
        lambda_client,
        mcp_function_name,
        "get_episode_assets",
        {"episode_id": episode_id},
    )

    assert "s3_keys" in result or "cover_art_url" in result, (
        f"Unexpected assets response: {result}"
    )


@pytest.mark.flaky(reruns=1)  # type: ignore[misc]
def test_get_presigned_url(
    lambda_client: Any,
    mcp_function_name: str,
    mcp_available: bool,
    pipeline_execution: PipelineExecutionResult,
) -> None:
    """get_presigned_url returns a valid HTTPS URL."""
    state = _require_pipeline(pipeline_execution)
    s3_key = state["cover_art"]["s3_key"]

    result = invoke_mcp_tool(
        lambda_client,
        mcp_function_name,
        "get_presigned_url",
        {"s3_key": s3_key},
    )

    url = result.get("url", "")
    assert url.startswith("https://"), f"Expected HTTPS URL, got {url!r}"
