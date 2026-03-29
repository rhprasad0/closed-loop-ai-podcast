"""E2E test conftest — deployed infrastructure fixtures.

Sets up session-scoped fixtures for testing against real AWS infrastructure.
Runs a single pipeline execution per session and shares the results across
all assertion tests. Does NOT inherit or conflict with integration fixtures.
"""

from __future__ import annotations

import json
import os
from collections.abc import Generator
from typing import Any
from uuid import uuid4

import boto3
import pytest
from botocore.exceptions import ClientError

from tests.e2e.helpers import PipelineExecutionResult, poll_execution

# ---------------------------------------------------------------------------
# Mark all tests in this package as e2e tests
# ---------------------------------------------------------------------------

pytestmark = pytest.mark.e2e

# ---------------------------------------------------------------------------
# Module-level skip guards — checked once at collection time
# ---------------------------------------------------------------------------

try:
    boto3.client("sts").get_caller_identity()
except Exception:
    pytest.skip("AWS credentials unavailable", allow_module_level=True)

_REQUIRED_ENV_VARS = ["STATE_MACHINE_ARN", "S3_BUCKET", "DB_CONNECTION_STRING"]

for _var in _REQUIRED_ENV_VARS:
    if not os.environ.get(_var):
        pytest.skip(f"{_var} not set", allow_module_level=True)


# ---------------------------------------------------------------------------
# Session-scoped infrastructure fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session")
def deployed_resources() -> dict[str, str]:
    """Frozen dict of deployed resource identifiers from environment variables."""
    return {
        "state_machine_arn": os.environ["STATE_MACHINE_ARN"],
        "s3_bucket": os.environ["S3_BUCKET"],
        "site_url": os.environ.get("SITE_URL", ""),
        "mcp_function_name": os.environ.get("MCP_FUNCTION_NAME", "zerostars-mcp"),
        "db_connection_string": os.environ["DB_CONNECTION_STRING"],
    }


@pytest.fixture(scope="session")
def sfn_client() -> Any:
    """Session-scoped Step Functions client."""
    return boto3.client("stepfunctions")


@pytest.fixture(scope="session")
def s3_client() -> Any:
    """Session-scoped S3 client."""
    return boto3.client("s3")


@pytest.fixture(scope="session")
def lambda_client() -> Any:
    """Session-scoped Lambda client."""
    return boto3.client("lambda")


# ---------------------------------------------------------------------------
# Pipeline execution fixture — THE critical session fixture
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session")
def pipeline_execution(
    sfn_client: Any,
    s3_client: Any,
    deployed_resources: dict[str, str],
) -> Generator[PipelineExecutionResult, None, None]:
    """Start a full pipeline execution, poll to completion, yield the result.

    This fixture runs the pipeline ONCE per session. All e2e assertion tests
    share the same execution result. Teardown deletes S3 objects and DB records.
    """
    state_machine_arn = deployed_resources["state_machine_arn"]
    execution_name = f"e2e-test-{uuid4().hex[:12]}"

    # Start the execution
    try:
        start_resp = sfn_client.start_execution(
            stateMachineArn=state_machine_arn,
            name=execution_name,
            input=json.dumps({}),
        )
    except ClientError as exc:
        error_code = exc.response.get("Error", {}).get("Code", "")
        if error_code == "StateMachineDoesNotExist":
            pytest.skip(f"State machine not deployed: {state_machine_arn}")
        raise

    execution_arn: str = start_resp["executionArn"]

    # Poll until completion
    try:
        result = poll_execution(sfn_client, execution_arn, timeout=900, interval=15)
    except TimeoutError:
        # If the execution timed out, abort it and yield a TIMED_OUT result
        sfn_client.stop_execution(
            executionArn=execution_arn,
            error="E2ETimeout",
            cause="E2E test polling timed out after 900s",
        )
        result = PipelineExecutionResult(
            execution_arn=execution_arn,
            status="TIMED_OUT",
            final_state={},
            duration_seconds=900.0,
        )

    yield result

    # -----------------------------------------------------------------------
    # Teardown: clean up S3 objects and DB records created by the pipeline
    # -----------------------------------------------------------------------
    _cleanup_execution_artifacts(
        s3_client=s3_client,
        bucket=deployed_resources["s3_bucket"],
        result=result,
    )


def _cleanup_execution_artifacts(
    s3_client: Any,
    bucket: str,
    result: PipelineExecutionResult,
) -> None:
    """Delete S3 objects and DB records from a pipeline execution."""
    # Clean up S3 objects
    execution_id = result.final_state.get("metadata", {}).get("execution_id", "")
    if execution_id:
        s3_keys = [
            f"episodes/{execution_id}/cover.png",
            f"episodes/{execution_id}/episode.mp3",
            f"episodes/{execution_id}/episode.mp4",
        ]
        for key in s3_keys:
            try:
                s3_client.delete_object(Bucket=bucket, Key=key)
            except ClientError:
                pass  # Object may not exist if pipeline failed early

    # Clean up DB records
    try:
        from shared.db import execute

        post_prod = result.final_state.get("post_production", {})
        episode_id = post_prod.get("episode_id")
        if episode_id:
            execute("DELETE FROM episode_metrics WHERE episode_id = %s", (episode_id,))
            execute(
                "DELETE FROM featured_developers WHERE episode_id = %s", (episode_id,)
            )
            execute("DELETE FROM episodes WHERE episode_id = %s", (episode_id,))
    except Exception:
        pass  # DB may be unavailable; don't fail teardown


# ---------------------------------------------------------------------------
# Safety-net cleanup — catches leaked rows from crashed test runs
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session", autouse=True)
def e2e_cleanup() -> Generator[None, None, None]:
    """Delete any orphaned e2e test rows after all tests complete."""
    yield
    try:
        from shared.db import execute

        # Execution IDs for e2e tests contain "e2e-test-" in the name part
        # The full execution_id is the ARN which contains the execution name
        execute(
            "DELETE FROM featured_developers WHERE episode_id IN "
            "(SELECT episode_id FROM episodes WHERE execution_id LIKE '%%e2e-test-%%')"
        )
        execute("DELETE FROM episodes WHERE execution_id LIKE '%%e2e-test-%%'")
    except Exception:
        pass
