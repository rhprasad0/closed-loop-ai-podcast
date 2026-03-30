"""E2E tests: Step Functions control flow — resume, stop, error handling.

These tests start their own executions (separate from the main pipeline_execution
fixture) to exercise control flow paths. They include their own cleanup.
"""

from __future__ import annotations

import json
import time
from typing import Any
from uuid import uuid4

import pytest
from botocore.exceptions import ClientError

from tests.e2e.helpers import PipelineExecutionResult, poll_execution

pytestmark = [pytest.mark.e2e, pytest.mark.timeout(600)]


# ---------------------------------------------------------------------------
# Resume from a mid-pipeline step
# ---------------------------------------------------------------------------


def test_resume_from_cover_art(
    sfn_client: Any,
    s3_client: Any,
    deployed_resources: dict[str, str],
    pipeline_execution: PipelineExecutionResult,
) -> None:
    """Resume from CoverArt using accumulated state from the main pipeline run.

    Validates the ResumeRouter Choice state routes correctly when
    metadata.resume_from is set.
    """
    if pipeline_execution.status != "SUCCEEDED":
        pytest.skip("Main pipeline did not succeed — cannot test resume")

    state = pipeline_execution.final_state

    # Skip if the original script exceeds the ElevenLabs character limit
    # (the resume will re-run TTS which enforces this strictly)
    script_chars = state.get("script", {}).get("character_count", 0)
    if script_chars >= 5000:
        pytest.skip(f"Script character_count {script_chars} >= 5000 — resume would fail at TTS")

    # Build input with resume_from and all upstream state carried forward
    resume_input = {
        "metadata": {
            "execution_id": state["metadata"]["execution_id"],
            "script_attempt": state["metadata"]["script_attempt"],
            "resume_from": "CoverArt",
        },
        "discovery": state["discovery"],
        "research": state["research"],
        "script": state["script"],
        "producer": state["producer"],
    }

    execution_name = f"e2e-test-resume-{uuid4().hex[:12]}"

    start_resp = sfn_client.start_execution(
        stateMachineArn=deployed_resources["state_machine_arn"],
        name=execution_name,
        input=json.dumps(resume_input),
    )
    resume_arn = start_resp["executionArn"]

    try:
        result = poll_execution(sfn_client, resume_arn, timeout=600, interval=10)

        assert result.status == "SUCCEEDED", (
            f"Resume execution failed with status {result.status}"
        )

        # Verify the resumed execution produced the expected outputs
        assert "cover_art" in result.final_state
        assert "tts" in result.final_state
        assert "post_production" in result.final_state
        assert result.final_state["post_production"]["episode_id"] > 0
    finally:
        # Clean up artifacts from the resume execution
        _cleanup_resume_artifacts(
            s3_client, deployed_resources["s3_bucket"], resume_arn, sfn_client
        )


def _cleanup_resume_artifacts(
    s3_client: Any,
    bucket: str,
    execution_arn: str,
    sfn_client: Any,
) -> None:
    """Clean up S3 objects and DB records from a resume test execution."""
    try:
        resp = sfn_client.describe_execution(executionArn=execution_arn)
        output_raw = resp.get("output")
        if not output_raw:
            return
        state = json.loads(output_raw)

        # Delete S3 objects
        execution_id = state.get("metadata", {}).get("execution_id", "")
        if execution_id:
            for suffix in ("cover.png", "episode.mp3", "episode.mp4"):
                try:
                    s3_client.delete_object(
                        Bucket=bucket, Key=f"episodes/{execution_id}/{suffix}"
                    )
                except ClientError:
                    pass

        # Delete DB records
        episode_id = state.get("post_production", {}).get("episode_id")
        if episode_id:
            from shared.db import execute

            execute(
                "DELETE FROM featured_developers WHERE episode_id = %s", (episode_id,)
            )
            execute("DELETE FROM episodes WHERE episode_id = %s", (episode_id,))
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Stop a running execution
# ---------------------------------------------------------------------------


def test_stop_running_execution(
    sfn_client: Any,
    deployed_resources: dict[str, str],
) -> None:
    """Start a pipeline execution, confirm it enters RUNNING, then stop it."""
    execution_name = f"e2e-test-stop-{uuid4().hex[:12]}"

    start_resp = sfn_client.start_execution(
        stateMachineArn=deployed_resources["state_machine_arn"],
        name=execution_name,
        input=json.dumps({}),
    )
    execution_arn = start_resp["executionArn"]

    try:
        # Wait briefly for the execution to start processing
        time.sleep(3)

        # Verify it is running
        desc = sfn_client.describe_execution(executionArn=execution_arn)
        assert desc["status"] == "RUNNING", (
            f"Expected RUNNING, got {desc['status']}"
        )

        # Stop the execution
        sfn_client.stop_execution(
            executionArn=execution_arn,
            error="E2ETest",
            cause="Testing stop_execution",
        )

        # Verify it is now ABORTED
        desc = sfn_client.describe_execution(executionArn=execution_arn)
        assert desc["status"] == "ABORTED"

    except Exception:
        # Safety: ensure the execution is stopped even if assertions fail
        try:
            sfn_client.stop_execution(
                executionArn=execution_arn,
                error="E2ECleanup",
                cause="Cleanup after failed test",
            )
        except ClientError:
            pass
        raise


# ---------------------------------------------------------------------------
# Error handling: missing upstream state
# ---------------------------------------------------------------------------


def test_stop_confirms_aborted_status(
    sfn_client: Any,
    deployed_resources: dict[str, str],
) -> None:
    """A stopped execution shows ABORTED when described after stopping.

    This complements test_stop_running_execution by verifying the describe
    response matches the expected terminal state.
    """
    execution_name = f"e2e-test-abort-confirm-{uuid4().hex[:12]}"

    start_resp = sfn_client.start_execution(
        stateMachineArn=deployed_resources["state_machine_arn"],
        name=execution_name,
        input=json.dumps({}),
    )
    execution_arn = start_resp["executionArn"]

    try:
        time.sleep(5)

        sfn_client.stop_execution(
            executionArn=execution_arn,
            error="E2EAbortTest",
            cause="Testing abort confirmation",
        )

        # Describe and verify terminal state details
        desc = sfn_client.describe_execution(executionArn=execution_arn)
        assert desc["status"] == "ABORTED"
        assert "stopDate" in desc

    except Exception:
        try:
            sfn_client.stop_execution(
                executionArn=execution_arn,
                error="E2ECleanup",
                cause="Cleanup after failed test",
            )
        except ClientError:
            pass
        raise
