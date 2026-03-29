"""Integration test for the Producer Lambda handler.

Calls the handler directly against real AWS Bedrock (Haiku override via
the bedrock_model_override session fixture in conftest.py). No external API
twins are needed — Producer uses invoke_model (single-turn, not tool-use).

Producer also calls shared.db.query to fetch benchmark scripts. The
cleanup_test_data fixture handles DB state. If no benchmark scripts exist,
Producer handles empty benchmarks gracefully.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest


@pytest.mark.integration
@pytest.mark.flaky(reruns=2)  # type: ignore[misc]
@pytest.mark.timeout(120)
def test_producer_produces_valid_output(
    pipeline_metadata: dict[str, Any],
    lambda_context: MagicMock,
) -> None:
    """Producer handler returns a valid ProducerOutput given fixture discovery + research + script data."""
    from lambdas.producer.handler import lambda_handler

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

    sample_script: dict[str, Any] = {
        "text": (
            "**Hype:** Welcome back to 0 Stars, 10 out of 10! Today we found ptyme by iximiuz.\n"
            "**Roast:** A Go profiler that uses ptrace. Because obviously the existing twelve weren't enough.\n"
            "**Phil:** But what is profiling, really? Is it not just asking a process to confess its sins?\n"
            "**Hype:** The brilliant part — zero instrumentation. Attach to any running binary without recompiling.\n"
            "**Roast:** Assuming you have ptrace permissions. Which in a container, you likely do not.\n"
            "**Phil:** Constraints breed creativity. Every permission boundary is a philosophical puzzle.\n"
            "**Hype:** Ivan blogs deeply about every kernel primitive he touches. Ptrace internals, explained.\n"
            "**Roast:** A developer who documents what they build. Rare as a project with a sensible changelog.\n"
            "**Phil:** Documentation is an act of empathy toward the future reader, who may be yourself.\n"
            "**Hype:** Hiring managers: Linux syscall fluency, Go systems programming, zero fluff.\n"
            "**Roast:** Nineteen repos, one interesting one. But that one is genuinely interesting.\n"
            "**Phil:** Quality over quantity. Perhaps that is the lesson ptyme teaches us about our own work.\n"
            "**Hype:** Find ptyme on GitHub. Zero stars, ten out of ten.\n"
            "**Roast:** Go give it a star. It will not make it less obscure, but at least you will feel better.\n"
            "**Phil:** And is that not what we are all here for?"
        ),
        "character_count": 1203,
        "segments": [
            "intro",
            "core_debate",
            "developer_deep_dive",
            "technical_appreciation",
            "hiring_manager",
            "outro",
        ],
        "featured_repo": "ptyme",
        "featured_developer": "iximiuz",
        "cover_art_suggestion": "Three robots gathered around a terminal showing a flame graph.",
    }

    event: dict[str, Any] = {
        "metadata": pipeline_metadata,
        "discovery": sample_discovery,
        "research": sample_research,
        "script": sample_script,
    }

    result = lambda_handler(event, lambda_context)

    # verdict must be one of the two valid values — non-deterministic, validate structure only
    assert result["verdict"] in ("PASS", "FAIL"), f"Unexpected verdict: {result['verdict']!r}"

    # score must be an integer in range [1, 10]
    assert isinstance(result["score"], int), f"score is not int: {type(result['score'])}"
    assert 1 <= result["score"] <= 10, f"score out of range: {result['score']}"

    if result["verdict"] == "PASS":
        # PASS: required keys are verdict and score; notes is optional but common
        assert "verdict" in result
        assert "score" in result
    else:
        # FAIL: must include feedback and a non-empty issues list
        assert "verdict" in result
        assert "score" in result
        assert "feedback" in result, "FAIL verdict missing 'feedback'"
        assert "issues" in result, "FAIL verdict missing 'issues'"
        assert isinstance(result["issues"], list), f"issues is not a list: {type(result['issues'])}"
        assert len(result["issues"]) > 0, "FAIL verdict has empty issues list"
        assert all(isinstance(issue, str) for issue in result["issues"]), (
            "issues list contains non-string elements"
        )
