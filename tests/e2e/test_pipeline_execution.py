"""E2E tests: pipeline execution output validation.

All tests consume the session-scoped pipeline_execution fixture. The pipeline
has already completed by the time these run — assertions are fast.
"""

from __future__ import annotations

import re
from typing import Any

import pytest

from tests.e2e.helpers import PipelineExecutionResult

pytestmark = [pytest.mark.e2e, pytest.mark.timeout(60)]


def _require_success(result: PipelineExecutionResult) -> dict[str, Any]:
    """Skip the test if the pipeline did not succeed."""
    if result.status != "SUCCEEDED":
        pytest.skip(f"Pipeline did not succeed (status={result.status})")
    return result.final_state


# ---------------------------------------------------------------------------
# Pipeline completion
# ---------------------------------------------------------------------------


@pytest.mark.flaky(reruns=1)  # type: ignore[misc]
def test_pipeline_succeeds(pipeline_execution: PipelineExecutionResult) -> None:
    """The pipeline completes with SUCCEEDED status within a sane time range."""
    assert pipeline_execution.status == "SUCCEEDED", (
        f"Pipeline failed with status {pipeline_execution.status}. "
        f"State: {pipeline_execution.final_state}"
    )
    assert pipeline_execution.duration_seconds > 30, "Suspiciously fast execution"
    assert pipeline_execution.duration_seconds < 900, "Execution took too long"


# ---------------------------------------------------------------------------
# State structure
# ---------------------------------------------------------------------------


def test_state_has_all_keys(pipeline_execution: PipelineExecutionResult) -> None:
    """The accumulated state has all 8 top-level keys from the pipeline stages."""
    state = _require_success(pipeline_execution)

    expected_keys = {
        "metadata",
        "discovery",
        "research",
        "script",
        "producer",
        "cover_art",
        "tts",
        "post_production",
    }
    missing = expected_keys - set(state.keys())
    assert not missing, f"Missing state keys: {missing}"


# ---------------------------------------------------------------------------
# Per-stage output validation
# ---------------------------------------------------------------------------


def test_discovery_output(pipeline_execution: PipelineExecutionResult) -> None:
    """Discovery output has all 9 required fields with correct types."""
    state = _require_success(pipeline_execution)
    discovery = state["discovery"]

    required_keys = [
        "repo_url",
        "repo_name",
        "repo_description",
        "developer_github",
        "star_count",
        "language",
        "discovery_rationale",
        "key_files",
        "technical_highlights",
    ]
    for key in required_keys:
        assert key in discovery, f"Discovery: missing required key: {key}"

    assert isinstance(discovery["star_count"], int)
    assert discovery["star_count"] < 10, f"star_count {discovery['star_count']} >= 10"
    assert discovery["repo_url"].startswith("https://github.com/")
    assert isinstance(discovery["key_files"], list)
    assert isinstance(discovery["technical_highlights"], list)


def test_research_output(pipeline_execution: PipelineExecutionResult) -> None:
    """Research output has all 9 required fields with correct types."""
    state = _require_success(pipeline_execution)
    research = state["research"]

    required_keys = [
        "developer_name",
        "developer_github",
        "developer_bio",
        "public_repos_count",
        "notable_repos",
        "commit_patterns",
        "technical_profile",
        "interesting_findings",
        "hiring_signals",
    ]
    for key in required_keys:
        assert key in research, f"Research: missing required key: {key}"

    assert isinstance(research["public_repos_count"], int)
    assert isinstance(research["notable_repos"], list)
    assert isinstance(research["developer_bio"], str)

    for i, repo in enumerate(research["notable_repos"]):
        for field in ("name", "description", "stars", "language"):
            assert field in repo, (
                f"Research: notable_repos[{i}] missing required field: {field}"
            )


def test_script_output(pipeline_execution: PipelineExecutionResult) -> None:
    """Script output meets character limits, has all segments, and cross-references discovery."""
    state = _require_success(pipeline_execution)
    script = state["script"]

    required_keys = [
        "text",
        "character_count",
        "segments",
        "featured_repo",
        "featured_developer",
        "cover_art_suggestion",
    ]
    for key in required_keys:
        assert key in script, f"Script: missing required key: {key}"

    assert isinstance(script["text"], str)
    assert len(script["text"]) > 0
    assert script["character_count"] > 0
    assert script["character_count"] < 5000, (
        f"Script character_count {script['character_count']} >= 5000 (ElevenLabs limit)"
    )

    required_segments = {
        "intro",
        "core_debate",
        "developer_deep_dive",
        "technical_appreciation",
        "hiring_manager",
        "outro",
    }
    assert required_segments.issubset(set(script["segments"])), (
        f"Script: missing segments: {required_segments - set(script['segments'])}"
    )

    # Cross-step contract: script references the repo from discovery
    assert script["featured_repo"] == state["discovery"]["repo_name"], (
        f"Script featured_repo {script['featured_repo']!r} does not match "
        f"discovery repo_name {state['discovery']['repo_name']!r}"
    )


def test_producer_verdict(pipeline_execution: PipelineExecutionResult) -> None:
    """Producer returns PASS with a valid score (pipeline succeeded → must be PASS)."""
    state = _require_success(pipeline_execution)
    producer = state["producer"]

    assert producer["verdict"] == "PASS", (
        f"Pipeline succeeded but producer verdict is {producer['verdict']!r}"
    )
    assert isinstance(producer["score"], int)
    assert 1 <= producer["score"] <= 10, (
        f"Producer score {producer['score']} out of range [1, 10]"
    )


def test_cover_art_output(pipeline_execution: PipelineExecutionResult) -> None:
    """Cover art output has valid S3 key and non-empty prompt."""
    state = _require_success(pipeline_execution)
    cover_art = state["cover_art"]

    assert "s3_key" in cover_art
    assert "prompt_used" in cover_art

    execution_id = state["metadata"]["execution_id"]
    expected_key = f"episodes/{execution_id}/cover.png"
    assert cover_art["s3_key"] == expected_key, (
        f"CoverArt s3_key {cover_art['s3_key']!r} != expected {expected_key!r}"
    )
    assert len(cover_art["prompt_used"]) > 0


def test_tts_output(pipeline_execution: PipelineExecutionResult) -> None:
    """TTS output has valid S3 key and positive duration."""
    state = _require_success(pipeline_execution)
    tts = state["tts"]

    assert "s3_key" in tts
    assert "duration_seconds" in tts
    assert "character_count" in tts

    assert tts["duration_seconds"] > 0, "TTS duration_seconds must be positive"
    assert tts["character_count"] > 0, "TTS character_count must be positive"

    execution_id = state["metadata"]["execution_id"]
    expected_key = f"episodes/{execution_id}/episode.mp3"
    assert tts["s3_key"] == expected_key


def test_post_production_output(pipeline_execution: PipelineExecutionResult) -> None:
    """Post-production output has valid episode_id, S3 key, and air_date."""
    state = _require_success(pipeline_execution)
    post_prod = state["post_production"]

    assert "episode_id" in post_prod
    assert "s3_mp4_key" in post_prod
    assert "air_date" in post_prod

    assert isinstance(post_prod["episode_id"], int)
    assert post_prod["episode_id"] > 0

    execution_id = state["metadata"]["execution_id"]
    expected_key = f"episodes/{execution_id}/episode.mp4"
    assert post_prod["s3_mp4_key"] == expected_key

    # air_date should be YYYY-MM-DD format
    assert re.match(r"^\d{4}-\d{2}-\d{2}$", post_prod["air_date"]), (
        f"air_date {post_prod['air_date']!r} does not match YYYY-MM-DD"
    )


def test_metadata_script_attempts(
    pipeline_execution: PipelineExecutionResult,
) -> None:
    """Metadata tracks script_attempt as an int between 1 and 3."""
    state = _require_success(pipeline_execution)
    metadata = state["metadata"]

    assert "script_attempt" in metadata
    attempt = metadata["script_attempt"]
    assert isinstance(attempt, int)
    assert 1 <= attempt <= 3, f"script_attempt {attempt} out of range [1, 3]"
