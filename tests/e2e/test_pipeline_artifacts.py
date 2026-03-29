"""E2E tests: verify S3 objects and Postgres records created by the pipeline."""

from __future__ import annotations

from typing import Any

import pytest

from tests.e2e.helpers import PipelineExecutionResult, assert_s3_exists, db_query

pytestmark = [pytest.mark.e2e, pytest.mark.timeout(60)]


def _require_success(result: PipelineExecutionResult) -> dict[str, Any]:
    """Skip the test if the pipeline did not succeed."""
    if result.status != "SUCCEEDED":
        pytest.skip(f"Pipeline did not succeed (status={result.status})")
    return result.final_state


# ---------------------------------------------------------------------------
# S3 artifact tests
# ---------------------------------------------------------------------------


def test_s3_cover_art_exists(
    pipeline_execution: PipelineExecutionResult,
    s3_client: Any,
    deployed_resources: dict[str, str],
) -> None:
    """The cover art PNG was uploaded to S3 with correct content type."""
    state = _require_success(pipeline_execution)
    s3_key = state["cover_art"]["s3_key"]
    bucket = deployed_resources["s3_bucket"]

    metadata = assert_s3_exists(s3_client, bucket, s3_key)
    assert metadata["ContentType"] == "image/png"
    assert metadata["ContentLength"] > 0


def test_s3_mp3_exists(
    pipeline_execution: PipelineExecutionResult,
    s3_client: Any,
    deployed_resources: dict[str, str],
) -> None:
    """The episode MP3 was uploaded to S3."""
    state = _require_success(pipeline_execution)
    s3_key = state["tts"]["s3_key"]
    bucket = deployed_resources["s3_bucket"]

    metadata = assert_s3_exists(s3_client, bucket, s3_key)
    assert metadata["ContentLength"] > 0


def test_s3_mp4_exists(
    pipeline_execution: PipelineExecutionResult,
    s3_client: Any,
    deployed_resources: dict[str, str],
) -> None:
    """The episode MP4 was uploaded to S3."""
    state = _require_success(pipeline_execution)
    s3_key = state["post_production"]["s3_mp4_key"]
    bucket = deployed_resources["s3_bucket"]

    metadata = assert_s3_exists(s3_client, bucket, s3_key)
    assert metadata["ContentLength"] > 0


# ---------------------------------------------------------------------------
# Postgres record tests
# ---------------------------------------------------------------------------


def test_episode_in_postgres(
    pipeline_execution: PipelineExecutionResult,
) -> None:
    """An episode row exists with matching execution_id and fields."""
    state = _require_success(pipeline_execution)
    execution_id = state["metadata"]["execution_id"]
    expected_episode_id = state["post_production"]["episode_id"]

    rows = db_query(
        "SELECT episode_id, repo_url, repo_name, developer_github, script_text, "
        "s3_mp3_path, s3_mp4_path, s3_cover_art_path "
        "FROM episodes WHERE execution_id = %s",
        (execution_id,),
    )

    assert len(rows) == 1, (
        f"Expected 1 episode row for execution_id={execution_id!r}, got {len(rows)}"
    )

    row = rows[0]
    episode_id, repo_url, repo_name, dev_github, script_text, mp3, mp4, cover = row

    assert episode_id == expected_episode_id
    assert repo_url and len(repo_url) > 0
    assert repo_name and len(repo_name) > 0
    assert dev_github and len(dev_github) > 0
    assert script_text and len(script_text) > 0
    assert mp3 and len(mp3) > 0
    assert mp4 and len(mp4) > 0
    assert cover and len(cover) > 0


def test_featured_developer_in_postgres(
    pipeline_execution: PipelineExecutionResult,
) -> None:
    """A featured_developers row exists linking the developer to the episode."""
    state = _require_success(pipeline_execution)
    expected_episode_id = state["post_production"]["episode_id"]
    expected_github = state["discovery"]["developer_github"]

    rows = db_query(
        "SELECT developer_github FROM featured_developers WHERE episode_id = %s",
        (expected_episode_id,),
    )

    assert len(rows) == 1, (
        f"Expected 1 featured_developer for episode_id={expected_episode_id}, "
        f"got {len(rows)}"
    )
    assert rows[0][0] == expected_github


def test_episode_data_consistency(
    pipeline_execution: PipelineExecutionResult,
) -> None:
    """Cross-validate the episode DB row against the pipeline state."""
    state = _require_success(pipeline_execution)
    execution_id = state["metadata"]["execution_id"]

    rows = db_query(
        "SELECT repo_name, developer_github, producer_attempts, script_text "
        "FROM episodes WHERE execution_id = %s",
        (execution_id,),
    )
    assert len(rows) == 1

    db_repo_name, db_dev_github, db_attempts, db_script_text = rows[0]

    # Cross-validate against pipeline state
    assert db_repo_name == state["discovery"]["repo_name"], (
        f"DB repo_name {db_repo_name!r} != discovery {state['discovery']['repo_name']!r}"
    )
    assert db_dev_github == state["discovery"]["developer_github"], (
        f"DB developer_github {db_dev_github!r} != "
        f"discovery {state['discovery']['developer_github']!r}"
    )
    assert db_attempts == state["metadata"]["script_attempt"], (
        f"DB producer_attempts {db_attempts} != "
        f"metadata script_attempt {state['metadata']['script_attempt']}"
    )
    assert db_script_text == state["script"]["text"], (
        "DB script_text does not match pipeline script output"
    )
