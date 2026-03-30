"""E2E tests: MCP tool functions against deployed infrastructure.

Imports tool functions from lambdas/mcp/tools/ and calls them with real
boto3 clients against deployed AWS resources. This validates the tool logic
works against real infrastructure without the ASGI transport complexity.
"""

from __future__ import annotations

import asyncio
import os
import sys
from typing import Any

import pytest

from tests.e2e.helpers import PipelineExecutionResult

# Add lambdas/mcp to sys.path so `from tools import ...` works locally
# (in Lambda, the zip root provides this; locally, we need it explicit)
_mcp_dir = os.path.join(os.path.dirname(__file__), "..", "..", "lambdas", "mcp")
if os.path.isdir(_mcp_dir) and _mcp_dir not in sys.path:
    sys.path.insert(0, os.path.abspath(_mcp_dir))

pytestmark = [pytest.mark.e2e, pytest.mark.timeout(60)]


def _run(coro: Any) -> Any:
    """Run an async MCP tool function synchronously."""
    return asyncio.run(coro)


def _require_pipeline(result: PipelineExecutionResult) -> dict[str, Any]:
    """Skip the test if the pipeline did not succeed."""
    if result.status != "SUCCEEDED":
        pytest.skip(f"Pipeline did not succeed (status={result.status})")
    return result.final_state


@pytest.fixture(scope="module", autouse=True)
def mcp_env(deployed_resources: dict[str, str]) -> None:
    """Set environment variables needed by MCP tool functions."""
    os.environ.setdefault("STATE_MACHINE_ARN", deployed_resources["state_machine_arn"])
    os.environ.setdefault("S3_BUCKET", deployed_resources["s3_bucket"])


# ---------------------------------------------------------------------------
# Pipeline observation tools
# ---------------------------------------------------------------------------


def test_list_executions() -> None:
    """list_executions returns a list of executions."""
    from lambdas.mcp.tools.pipeline import list_executions

    result = _run(list_executions(max_results=5))
    assert "executions" in result
    assert isinstance(result["executions"], list)
    assert len(result["executions"]) > 0


def test_get_execution_status(
    pipeline_execution: PipelineExecutionResult,
) -> None:
    """get_execution_status returns details for the e2e execution."""
    _require_pipeline(pipeline_execution)

    from lambdas.mcp.tools.pipeline import get_execution_status

    result = _run(get_execution_status(execution_arn=pipeline_execution.execution_arn))
    assert result["status"] == "SUCCEEDED"


def test_get_pipeline_health() -> None:
    """get_pipeline_health returns aggregate stats."""
    from lambdas.mcp.tools.observation import get_pipeline_health

    result = _run(get_pipeline_health(days=7))
    assert "total_executions" in result
    assert result["total_executions"] > 0


# ---------------------------------------------------------------------------
# Data query tools
# ---------------------------------------------------------------------------


def test_query_episodes(
    pipeline_execution: PipelineExecutionResult,
) -> None:
    """query_episodes returns episodes including the e2e episode."""
    _require_pipeline(pipeline_execution)

    from lambdas.mcp.tools.data import query_episodes

    result = _run(query_episodes(limit=10))
    assert "episodes" in result
    assert len(result["episodes"]) > 0


def test_get_episode_detail(
    pipeline_execution: PipelineExecutionResult,
) -> None:
    """get_episode_detail returns the full record for the e2e episode."""
    state = _require_pipeline(pipeline_execution)
    episode_id = state["post_production"]["episode_id"]

    from lambdas.mcp.tools.data import get_episode_detail

    result = _run(get_episode_detail(episode_id=episode_id))
    assert result is not None
    assert "script_text" in result


# ---------------------------------------------------------------------------
# Asset tools
# ---------------------------------------------------------------------------


def test_get_episode_assets(
    pipeline_execution: PipelineExecutionResult,
) -> None:
    """get_episode_assets returns S3 keys for the e2e episode."""
    state = _require_pipeline(pipeline_execution)
    episode_id = state["post_production"]["episode_id"]

    from lambdas.mcp.tools.assets import get_episode_assets

    result = _run(get_episode_assets(episode_id=episode_id))
    assert "s3_keys" in result


@pytest.mark.flaky(reruns=1)  # type: ignore[misc]
def test_get_presigned_url(
    pipeline_execution: PipelineExecutionResult,
) -> None:
    """get_presigned_url returns a valid HTTPS URL."""
    state = _require_pipeline(pipeline_execution)
    s3_key = state["cover_art"]["s3_key"]

    from lambdas.mcp.tools.assets import get_presigned_url

    result = _run(get_presigned_url(s3_key=s3_key))
    assert result["url"].startswith("https://")
