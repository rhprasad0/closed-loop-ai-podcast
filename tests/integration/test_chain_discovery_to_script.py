"""Chain integration test: Discovery -> Research -> Script.

Feeds real output from each handler into the next, catching schema
mismatches between handlers. This is the highest-value integration test
in the suite — it validates the full data contract across three agents.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest


@pytest.mark.integration
@pytest.mark.flaky(reruns=2)  # type: ignore[misc]
@pytest.mark.timeout(300)
def test_chain_discovery_through_script(
    seed_featured_developers: None,
    pipeline_metadata: dict[str, Any],
    lambda_context: MagicMock,
) -> None:
    """Run Discovery -> Research -> Script end-to-end using real Bedrock (Haiku) calls.

    Each step's output becomes the next step's input, exactly as Step Functions
    would wire them via ResultPath.
    """
    from lambdas.discovery.handler import lambda_handler as discovery_handler
    from lambdas.research.handler import lambda_handler as research_handler
    from lambdas.script.handler import lambda_handler as script_handler

    # ------------------------------------------------------------------
    # Step 1: Discovery
    # ------------------------------------------------------------------
    discovery_event: dict[str, Any] = {"metadata": pipeline_metadata}
    discovery_result: dict[str, Any] = discovery_handler(discovery_event, lambda_context)

    # Structural assertions for DiscoveryOutput
    discovery_required_keys = [
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
    for key in discovery_required_keys:
        assert key in discovery_result, f"Discovery: missing required key: {key}"

    assert isinstance(discovery_result["star_count"], int)
    assert discovery_result["star_count"] < 10
    assert discovery_result["repo_url"].startswith("https://github.com/")
    assert isinstance(discovery_result["key_files"], list)
    assert isinstance(discovery_result["technical_highlights"], list)

    # ------------------------------------------------------------------
    # Step 2: Research — receives the full state with $.discovery populated
    # ------------------------------------------------------------------
    research_event: dict[str, Any] = {
        "metadata": pipeline_metadata,
        "discovery": discovery_result,
    }
    research_result: dict[str, Any] = research_handler(research_event, lambda_context)

    # Structural assertions for ResearchOutput
    research_required_keys = [
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
    for key in research_required_keys:
        assert key in research_result, f"Research: missing required key: {key}"

    assert isinstance(research_result["notable_repos"], list)
    assert isinstance(research_result["public_repos_count"], int)
    assert isinstance(research_result["developer_bio"], str)

    # Each notable_repo entry must have all 4 sub-fields
    for i, notable_repo in enumerate(research_result["notable_repos"]):
        for sub_field in ("name", "description", "stars", "language"):
            assert sub_field in notable_repo, (
                f"Research: notable_repos[{i}] missing required field: {sub_field}"
            )

    # ------------------------------------------------------------------
    # Step 3: Script — receives the full state with both $.discovery and $.research
    # ------------------------------------------------------------------
    script_event: dict[str, Any] = {
        "metadata": pipeline_metadata,
        "discovery": discovery_result,
        "research": research_result,
    }
    script_result: dict[str, Any] = script_handler(script_event, lambda_context)

    # Structural assertions for ScriptOutput
    script_required_keys = [
        "text",
        "character_count",
        "segments",
        "featured_repo",
        "featured_developer",
        "cover_art_suggestion",
    ]
    for key in script_required_keys:
        assert key in script_result, f"Script: missing required key: {key}"

    assert isinstance(script_result["text"], str)
    assert len(script_result["text"]) > 0
    assert script_result["character_count"] > 0
    assert script_result["character_count"] < 5000

    required_segments = {
        "intro",
        "core_debate",
        "developer_deep_dive",
        "technical_appreciation",
        "hiring_manager",
        "outro",
    }
    assert required_segments.issubset(set(script_result["segments"])), (
        f"Script: missing segments: {required_segments - set(script_result['segments'])}"
    )

    # ------------------------------------------------------------------
    # Final cross-step assertion: script references the repo from discovery
    # ------------------------------------------------------------------
    assert script_result["featured_repo"] == discovery_result["repo_name"], (
        f"Script featured_repo {script_result['featured_repo']!r} does not match "
        f"discovery repo_name {discovery_result['repo_name']!r}"
    )
