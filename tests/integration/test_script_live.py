"""Integration test for the Script Lambda handler.

Calls the handler directly against real AWS Bedrock (Haiku override via
the bedrock_model_override session fixture in conftest.py). No external API
twins are needed — Script uses invoke_model (single-turn, not tool-use).
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest


@pytest.mark.integration
@pytest.mark.flaky(reruns=2)  # type: ignore[misc]
@pytest.mark.timeout(120)
def test_script_produces_valid_output(
    pipeline_metadata: dict[str, Any],
    lambda_context: MagicMock,
) -> None:
    """Script handler returns a valid ScriptOutput given fixture discovery + research data."""
    from lambdas.script.handler import lambda_handler

    sample_discovery: dict[str, Any] = {
        "repo_url": "https://github.com/iximiuz/ptyme",
        "repo_name": "ptyme",
        "repo_description": (
            "ptyme attaches to a running Linux process via ptrace and samples its call stack "
            "at configurable intervals."
        ),
        "developer_github": "iximiuz",
        "star_count": 7,
        "language": "Go",
        "discovery_rationale": "Lightweight ptrace profiler with no instrumentation required.",
        "key_files": ["main.go", "README.md"],
        "technical_highlights": [
            "Uses ptrace syscall to attach to running processes",
            "No instrumentation or recompilation required",
            "Outputs flame-graph compatible profiles",
        ],
    }

    sample_research: dict[str, Any] = {
        "developer_name": "Ivan Velichko",
        "developer_github": "iximiuz",
        "developer_bio": "Container and Linux internals. Writing labs and tools for engineers.",
        "public_repos_count": 19,
        "notable_repos": [
            {
                "name": "ptyme",
                "description": "Attaches to a running Linux process via ptrace to sample call stacks.",
                "stars": 7,
                "language": "Go",
            },
            {
                "name": "labs.iximiuz.com",
                "description": "Interactive labs on containers and Linux internals.",
                "stars": 3,
                "language": "JavaScript",
            },
        ],
        "commit_patterns": "Active on weekdays, focused bursts around new blog posts.",
        "technical_profile": "Go, Linux internals, containers, ptrace, observability tooling.",
        "interesting_findings": [
            "Built a profiler that needs zero changes to the target binary",
            "Writes detailed technical blog posts explaining internals behind each tool",
        ],
        "hiring_signals": [
            "Deep Linux systems knowledge — comfortable at the syscall layer",
            "Ships production-quality tooling with clear documentation",
            "Strong communicator who translates kernel internals for broad audiences",
        ],
    }

    event: dict[str, Any] = {
        "metadata": pipeline_metadata,
        "discovery": sample_discovery,
        "research": sample_research,
    }

    result = lambda_handler(event, lambda_context)

    # All ScriptOutput required keys must be present
    required_keys = [
        "text",
        "character_count",
        "segments",
        "featured_repo",
        "featured_developer",
        "cover_art_suggestion",
    ]
    for key in required_keys:
        assert key in result, f"Missing required key: {key}"

    # Character count must be within valid bounds
    assert result["character_count"] > 0
    assert result["character_count"] < 5000

    # All 6 required segments must be present
    required_segments = {
        "intro",
        "core_debate",
        "developer_deep_dive",
        "technical_appreciation",
        "hiring_manager",
        "outro",
    }
    assert required_segments.issubset(set(result["segments"])), (
        f"Missing segments: {required_segments - set(result['segments'])}"
    )

    # featured_repo must match the input discovery repo_name
    assert result["featured_repo"] == sample_discovery["repo_name"]

    # text must be a non-empty string
    assert isinstance(result["text"], str)
    assert len(result["text"]) > 0
