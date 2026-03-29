"""Integration test for the Discovery Lambda handler.

Calls the handler directly against real AWS Bedrock (Haiku override) and
behavioral twins for Exa and GitHub APIs.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest


@pytest.mark.integration
@pytest.mark.flaky(reruns=2)  # type: ignore[misc]
@pytest.mark.timeout(120)
def test_discovery_produces_valid_output(
    seed_featured_developers: None,
    pipeline_metadata: dict[str, Any],
    lambda_context: MagicMock,
) -> None:
    """Discovery handler runs the full agentic loop and returns a valid DiscoveryOutput."""
    from lambdas.discovery.handler import lambda_handler

    event = {"metadata": pipeline_metadata}
    result = lambda_handler(event, lambda_context)

    # All required DiscoveryOutput fields must be present
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
        assert key in result, f"Missing required key: {key}"

    assert isinstance(result["star_count"], int)
    assert result["star_count"] < 10
    assert result["repo_url"].startswith("https://github.com/")
    assert isinstance(result["key_files"], list)
    assert isinstance(result["technical_highlights"], list)
