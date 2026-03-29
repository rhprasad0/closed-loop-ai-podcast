"""Agent invocation tools for the MCP server.

Tools: invoke_discovery, invoke_research, invoke_script, invoke_producer,
       invoke_cover_art, invoke_tts, invoke_post_production.

Each tool synchronously invokes the corresponding pipeline Lambda via
boto3 (InvocationType=RequestResponse) and returns the parsed response payload.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

import boto3
from botocore.client import BaseClient

# Module-level client — reassign at module scope in tests to inject a mock.
LAMBDA_CLIENT: BaseClient = boto3.client("lambda")


def _now_tag() -> str:
    """Return a compact UTC timestamp for synthetic execution IDs."""
    return datetime.now(tz=UTC).strftime("%Y%m%dT%H%M%SZ")


def _invoke(function_name: str, payload: dict[str, Any]) -> dict[str, Any]:
    """Invoke a Lambda synchronously and return its parsed response payload."""
    resp = LAMBDA_CLIENT.invoke(
        FunctionName=function_name,
        InvocationType="RequestResponse",
        Payload=json.dumps(payload).encode(),
    )
    raw: bytes = resp["Payload"].read()
    return json.loads(raw)  # type: ignore[no-any-return]


def _base_state(execution_id: str | None = None) -> dict[str, Any]:
    """Return a minimal synthetic PipelineState with metadata."""
    eid = execution_id or f"mcp-standalone-{_now_tag()}"
    return {
        "metadata": {
            "execution_id": eid,
            "script_attempt": 1,
        }
    }


async def invoke_discovery() -> dict[str, Any]:
    """Run the Discovery agent to find an underrated GitHub repo.

    Queries Postgres internally to exclude previously featured developers.
    Returns the full Discovery output.
    """
    state = _base_state()
    return _invoke("zerostars-discovery", state)


async def invoke_research(
    repo_url: str,
    repo_name: str,
    developer_github: str,
) -> dict[str, Any]:
    """Build a developer profile from GitHub.

    Args:
        repo_url: GitHub repo URL, e.g. https://github.com/user/repo.
        repo_name: The repo name.
        developer_github: GitHub username.
    """
    state = _base_state()
    state["discovery"] = {
        "repo_url": repo_url,
        "repo_name": repo_name,
        "developer_github": developer_github,
    }
    return _invoke("zerostars-research", state)


async def invoke_script(
    discovery: dict[str, Any],
    research: dict[str, Any],
    producer_feedback: str | None = None,
    producer_issues: list[str] | None = None,
) -> dict[str, Any]:
    """Write a 3-persona comedy podcast script.

    Args:
        discovery: Full Discovery output.
        research: Full Research output.
        producer_feedback: Optional feedback from a previous Producer evaluation.
        producer_issues: Optional specific issues from a previous evaluation.
    """
    state = _base_state()
    state["discovery"] = discovery
    state["research"] = research

    if producer_feedback is not None:
        # Signal a revision pass — script_attempt 2 triggers the rewrite prompt.
        state["metadata"]["script_attempt"] = 2
        producer: dict[str, Any] = {"feedback": producer_feedback}
        if producer_issues is not None:
            producer["issues"] = producer_issues
        state["producer"] = producer

    return _invoke("zerostars-script", state)


async def invoke_producer(
    script_text: str,
    discovery: dict[str, Any],
    research: dict[str, Any],
) -> dict[str, Any]:
    """Evaluate a script's quality. Returns PASS/FAIL with score and feedback.

    Args:
        script_text: Full script text with speaker labels.
        discovery: Discovery output (to verify script specificity).
        research: Research output (to verify hiring segment).
    """
    state = _base_state()
    state["discovery"] = discovery
    state["research"] = research
    state["script"] = {"text": script_text}
    return _invoke("zerostars-producer", state)


async def invoke_cover_art(
    cover_art_suggestion: str,
    repo_name: str,
    language: str | None = None,
    execution_id: str | None = None,
) -> dict[str, Any]:
    """Generate episode cover art via Bedrock Nova Canvas.

    Args:
        cover_art_suggestion: Visual concept description.
        repo_name: For the episode subtitle overlay.
        language: Primary language, informs visual theme.
        execution_id: S3 key prefix. Auto-generated if omitted.
    """
    state = _base_state(execution_id)
    # Cover art lambda reads suggestion from $.script and repo context from $.discovery.
    state["script"] = {"cover_art_suggestion": cover_art_suggestion}
    state["discovery"] = {"repo_name": repo_name, "language": language}
    return _invoke("zerostars-cover-art", state)


async def invoke_tts(
    script_text: str,
    execution_id: str | None = None,
) -> dict[str, Any]:
    """Generate podcast audio from a script via ElevenLabs text-to-dialogue.

    Args:
        script_text: Approved script with **Hype:**, **Roast:**, **Phil:** labels.
        execution_id: S3 key prefix. Auto-generated if omitted.
    """
    state = _base_state(execution_id)
    state["script"] = {"text": script_text}
    return _invoke("zerostars-tts", state)


async def invoke_post_production(
    discovery: dict[str, Any],
    research: dict[str, Any],
    script: dict[str, Any],
    cover_art: dict[str, Any],
    tts: dict[str, Any],
    execution_id: str | None = None,
) -> dict[str, Any]:
    """Combine MP3 + PNG into MP4, write episode record to Postgres.

    Args:
        discovery: Full Discovery output.
        research: Full Research output.
        script: Full Script output.
        cover_art: Full Cover Art output.
        tts: Full TTS output.
        execution_id: Auto-generated if omitted.
    """
    state = _base_state(execution_id)
    state["discovery"] = discovery
    state["research"] = research
    state["script"] = script
    state["cover_art"] = cover_art
    state["tts"] = tts
    return _invoke("zerostars-post-production", state)
