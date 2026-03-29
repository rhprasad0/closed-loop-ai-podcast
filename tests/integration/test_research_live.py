"""Integration test for the Research Lambda handler.

Calls the handler directly against real AWS Bedrock (Haiku override) and
behavioral twins for GitHub API.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest

from tests.integration.twins.fixtures import GITHUB_REPOS, GITHUB_USERS


@pytest.mark.integration
@pytest.mark.flaky(reruns=2)  # type: ignore[misc]
@pytest.mark.timeout(120)
def test_research_produces_valid_output(
    pipeline_metadata: dict[str, Any],
    lambda_context: MagicMock,
) -> None:
    """Research handler runs the full agentic loop and returns a valid ResearchOutput."""
    from lambdas.research.handler import lambda_handler

    # Use iximiuz/ptyme — a developer/repo present in GITHUB_USERS and GITHUB_REPOS fixtures
    developer_github = "iximiuz"
    repo_key = "iximiuz/ptyme"
    repo = GITHUB_REPOS[repo_key]

    sample_discovery_output: dict[str, Any] = {
        "repo_url": str(repo["html_url"]),
        "repo_name": str(repo["name"]),
        "repo_description": str(repo["description"]),
        "developer_github": developer_github,
        "star_count": int(repo["stargazers_count"]),  # type: ignore[arg-type]
        "language": str(repo["language"]),
        "discovery_rationale": "Lightweight ptrace profiler with no instrumentation required.",
        "key_files": ["main.go", "README.md"],
        "technical_highlights": ["Uses ptrace syscall", "Flame-graph output"],
    }

    event: dict[str, Any] = {
        "metadata": pipeline_metadata,
        "discovery": sample_discovery_output,
    }

    result = lambda_handler(event, lambda_context)

    # All required ResearchOutput fields must be present
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
        assert key in result, f"Missing required key: {key}"

    # developer_github in output must match the input
    assert result["developer_github"] == developer_github

    # notable_repos must be a non-empty list (iximiuz has repos in fixtures)
    assert isinstance(result["notable_repos"], list)
    assert len(result["notable_repos"]) > 0, "notable_repos should be non-empty for iximiuz"

    # Each notable_repo must have the 4 required sub-fields
    for i, repo_entry in enumerate(result["notable_repos"]):
        for sub_field in ("name", "description", "stars", "language"):
            assert sub_field in repo_entry, (
                f"notable_repos[{i}] missing required field: {sub_field}"
            )
