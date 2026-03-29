"""Bedrock API behavioral twin for integration tests.

Returns deterministic, schema-valid responses for each Lambda handler.
Monkeypatches shared.bedrock._get_bedrock_client so that invoke_model and
invoke_with_tools never hit the real Bedrock endpoint.

The mock always returns stop_reason="end_turn" (skipping the agentic tool-use
loop) with a pre-crafted JSON payload matching each handler's output schema.
"""

from __future__ import annotations

import io
import json
from typing import Any


# ---------------------------------------------------------------------------
# Pre-crafted valid handler responses
# ---------------------------------------------------------------------------

_DISCOVERY_RESPONSE = json.dumps(
    {
        "repo_url": "https://github.com/iximiuz/ptyme",
        "repo_name": "ptyme",
        "repo_description": (
            "A lightweight ptrace-based time profiler for Linux. "
            "No instrumentation required."
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
)

_RESEARCH_RESPONSE = json.dumps(
    {
        "developer_name": "Ivan Velichko",
        "developer_github": "iximiuz",
        "developer_bio": "Container and Linux internals. Writing labs and tools for engineers.",
        "public_repos_count": 19,
        "notable_repos": [
            {
                "name": "ptyme",
                "description": "ptrace-based time profiler for Linux",
                "stars": 7,
                "language": "Go",
            },
            {
                "name": "cdebug",
                "description": "Container debugging swiss army knife",
                "stars": 1240,
                "language": "Go",
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
        ],
    }
)

_SCRIPT_RESPONSE = json.dumps(
    {
        "text": (
            "**Hype:** Welcome to 0 Stars, 10 out of 10! Today: ptyme by iximiuz.\n"
            "**Roast:** A Go profiler using ptrace. Because we needed another one.\n"
            "**Phil:** Profiling is just asking a process to confess its sins.\n"
            "**Hype:** Zero instrumentation — attach to any running binary without recompiling.\n"
            "**Roast:** Assuming ptrace permissions. In a container, that is unlikely.\n"
            "**Phil:** Constraints breed creativity. Every permission boundary is a puzzle.\n"
            "**Hype:** Ivan blogs about every kernel primitive he touches. Ptrace internals.\n"
            "**Roast:** A developer who documents their work. Rare as a sensible changelog.\n"
            "**Phil:** Documentation is empathy toward the future reader, who may be yourself.\n"
            "**Hype:** Hiring managers: Linux syscall fluency, Go systems programming, no fluff.\n"
            "**Roast:** Nineteen repos, one interesting one. That one is genuinely good.\n"
            "**Phil:** Quality over quantity. The lesson ptyme teaches about our own work.\n"
            "**Hype:** Find ptyme on GitHub. Zero stars, ten out of ten.\n"
            "**Roast:** Give it a star. You will feel better about yourself.\n"
            "**Phil:** And is that not what we are all here for?"
        ),
        "character_count": 900,
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
)

_PRODUCER_RESPONSE = json.dumps(
    {
        "verdict": "PASS",
        "score": 8,
        "notes": "Well-crafted script with good technical depth and appropriate humor.",
    }
)


# ---------------------------------------------------------------------------
# Routing: determine which handler response to return
# ---------------------------------------------------------------------------


def _route_response(body_dict: dict[str, Any]) -> str:
    """Return the pre-crafted response string for the given request body."""
    messages: list[dict[str, Any]] = body_dict.get("messages", [])
    has_tools = "tools" in body_dict

    # Extract the first user message text for routing
    user_text = ""
    for msg in messages:
        if msg.get("role") == "user":
            content = msg.get("content", "")
            if isinstance(content, str):
                user_text = content
            elif isinstance(content, list):
                for part in content:
                    if isinstance(part, dict) and part.get("type") == "text":
                        user_text = part.get("text", "")
                        break
            break

    if has_tools:
        # Agentic calls — discovery or research
        if "Find one underrated GitHub repository" in user_text:
            return _DISCOVERY_RESPONSE
        return _RESEARCH_RESPONSE

    # Single-turn calls — script or producer
    if "Write the podcast script" in user_text:
        return _SCRIPT_RESPONSE
    # Script handler user message starts with "Attempt N\n\n## Discovery Data"
    if user_text.startswith("Attempt ") and "## Discovery Data" in user_text:
        return _SCRIPT_RESPONSE
    return _PRODUCER_RESPONSE


# ---------------------------------------------------------------------------
# Mock Bedrock client
# ---------------------------------------------------------------------------


class _MockBedrockClient:
    """Minimal mock for the botocore BedrockRuntime client.

    invoke_model always returns stop_reason="end_turn" with the appropriate
    pre-crafted payload, skipping the real agentic tool-use loop.
    """

    def invoke_model(self, **kwargs: Any) -> dict[str, Any]:
        body_raw = kwargs.get("body", b"{}")
        if isinstance(body_raw, (bytes, bytearray)):
            body_str = body_raw.decode()
        else:
            body_str = str(body_raw)
        body_dict = json.loads(body_str)

        text = _route_response(body_dict)
        response_payload = json.dumps(
            {
                "id": "msg_bedrock_twin",
                "type": "message",
                "role": "assistant",
                "content": [{"type": "text", "text": text}],
                "stop_reason": "end_turn",
                "model": "claude-3-haiku-20240307",
                "usage": {"input_tokens": 100, "output_tokens": 200},
            }
        ).encode()
        return {"body": io.BytesIO(response_payload), "contentType": "application/json"}


def setup_bedrock_twin() -> _MockBedrockClient:
    """Return a configured mock Bedrock client."""
    return _MockBedrockClient()
