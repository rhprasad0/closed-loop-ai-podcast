"""Unit tests for lambdas.mcp.tools.agents — 7 agent invocation tools.

Tests: invoke_discovery, invoke_research, invoke_script, invoke_producer,
       invoke_cover_art, invoke_tts, invoke_post_production.
"""

from __future__ import annotations

import asyncio
import json
from unittest.mock import MagicMock, patch


# ---------------------------------------------------------------------------
# Helper: build a mock Lambda invoke response
# ---------------------------------------------------------------------------


def _lambda_response(payload: dict) -> dict:
    """Build a mock boto3 Lambda.invoke() return value."""
    return {
        "StatusCode": 200,
        "Payload": MagicMock(read=lambda: json.dumps(payload).encode()),
    }


# ---------------------------------------------------------------------------
# invoke_discovery
# ---------------------------------------------------------------------------


def test_invoke_discovery_builds_synthetic_state():
    mock_client = MagicMock()
    mock_client.invoke.return_value = _lambda_response(
        {"repo_url": "https://github.com/user/repo", "star_count": 5}
    )

    with patch("lambdas.mcp.tools.agents.LAMBDA_CLIENT", mock_client):
        from lambdas.mcp.tools.agents import invoke_discovery

        result = asyncio.run(invoke_discovery())

    call_kwargs = mock_client.invoke.call_args.kwargs
    assert call_kwargs["FunctionName"] == "zerostars-discovery"
    assert call_kwargs["InvocationType"] == "RequestResponse"
    payload = json.loads(call_kwargs["Payload"])
    assert "metadata" in payload
    assert payload["metadata"]["execution_id"].startswith("mcp-standalone-")
    assert result["repo_url"] == "https://github.com/user/repo"


# ---------------------------------------------------------------------------
# invoke_research
# ---------------------------------------------------------------------------


def test_invoke_research_places_params_in_discovery_key():
    mock_client = MagicMock()
    mock_client.invoke.return_value = _lambda_response({"developer_name": "Test User"})

    with patch("lambdas.mcp.tools.agents.LAMBDA_CLIENT", mock_client):
        from lambdas.mcp.tools.agents import invoke_research

        asyncio.run(
            invoke_research(
                repo_url="https://github.com/user/repo",
                repo_name="repo",
                developer_github="user",
            )
        )

    payload = json.loads(mock_client.invoke.call_args.kwargs["Payload"])
    assert payload["discovery"]["repo_url"] == "https://github.com/user/repo"
    assert payload["discovery"]["developer_github"] == "user"


# ---------------------------------------------------------------------------
# invoke_script
# ---------------------------------------------------------------------------


def test_invoke_script_without_feedback(
    sample_discovery_output,
    sample_research_output,
):
    mock_client = MagicMock()
    mock_client.invoke.return_value = _lambda_response(
        {"text": "**Hype:** Hello!", "character_count": 15}
    )

    with patch("lambdas.mcp.tools.agents.LAMBDA_CLIENT", mock_client):
        from lambdas.mcp.tools.agents import invoke_script

        asyncio.run(
            invoke_script(
                discovery=sample_discovery_output,
                research=sample_research_output,
            )
        )

    payload = json.loads(mock_client.invoke.call_args.kwargs["Payload"])
    assert payload["metadata"]["script_attempt"] == 1
    assert "producer" not in payload


def test_invoke_script_with_feedback_sets_attempt_2(
    sample_discovery_output,
    sample_research_output,
):
    mock_client = MagicMock()
    mock_client.invoke.return_value = _lambda_response(
        {"text": "**Hype:** Improved!", "character_count": 18}
    )

    with patch("lambdas.mcp.tools.agents.LAMBDA_CLIENT", mock_client):
        from lambdas.mcp.tools.agents import invoke_script

        asyncio.run(
            invoke_script(
                discovery=sample_discovery_output,
                research=sample_research_output,
                producer_feedback="More jokes",
                producer_issues=["Not funny enough"],
            )
        )

    payload = json.loads(mock_client.invoke.call_args.kwargs["Payload"])
    assert payload["metadata"]["script_attempt"] == 2
    assert payload["producer"]["feedback"] == "More jokes"
    assert payload["producer"]["issues"] == ["Not funny enough"]


# ---------------------------------------------------------------------------
# invoke_producer
# ---------------------------------------------------------------------------


def test_invoke_producer_places_script_text(
    sample_discovery_output,
    sample_research_output,
):
    mock_client = MagicMock()
    mock_client.invoke.return_value = _lambda_response({"verdict": "PASS", "score": 8})

    with patch("lambdas.mcp.tools.agents.LAMBDA_CLIENT", mock_client):
        from lambdas.mcp.tools.agents import invoke_producer

        asyncio.run(
            invoke_producer(
                script_text="**Hype:** Hello!",
                discovery=sample_discovery_output,
                research=sample_research_output,
            )
        )

    payload = json.loads(mock_client.invoke.call_args.kwargs["Payload"])
    assert payload["script"]["text"] == "**Hype:** Hello!"


# ---------------------------------------------------------------------------
# invoke_cover_art
# ---------------------------------------------------------------------------


def test_invoke_cover_art_auto_generates_execution_id():
    mock_client = MagicMock()
    mock_client.invoke.return_value = _lambda_response({"s3_key": "episodes/test/cover.png"})

    with patch("lambdas.mcp.tools.agents.LAMBDA_CLIENT", mock_client):
        from lambdas.mcp.tools.agents import invoke_cover_art

        asyncio.run(
            invoke_cover_art(
                cover_art_suggestion="Robots coding",
                repo_name="testrepo",
            )
        )

    payload = json.loads(mock_client.invoke.call_args.kwargs["Payload"])
    assert payload["metadata"]["execution_id"].startswith("mcp-standalone-")


def test_invoke_cover_art_uses_provided_execution_id():
    mock_client = MagicMock()
    mock_client.invoke.return_value = _lambda_response({"s3_key": "episodes/custom-id/cover.png"})

    with patch("lambdas.mcp.tools.agents.LAMBDA_CLIENT", mock_client):
        from lambdas.mcp.tools.agents import invoke_cover_art

        asyncio.run(
            invoke_cover_art(
                cover_art_suggestion="Robots coding",
                repo_name="testrepo",
                execution_id="custom-id",
            )
        )

    payload = json.loads(mock_client.invoke.call_args.kwargs["Payload"])
    assert payload["metadata"]["execution_id"] == "custom-id"


# ---------------------------------------------------------------------------
# invoke_tts
# ---------------------------------------------------------------------------


def test_invoke_tts_passes_script_text():
    mock_client = MagicMock()
    mock_client.invoke.return_value = _lambda_response(
        {"s3_key": "episodes/test/episode.mp3", "duration_seconds": 180, "character_count": 4200}
    )

    with patch("lambdas.mcp.tools.agents.LAMBDA_CLIENT", mock_client):
        from lambdas.mcp.tools.agents import invoke_tts

        asyncio.run(invoke_tts(script_text="**Hype:** Welcome back!"))

    payload = json.loads(mock_client.invoke.call_args.kwargs["Payload"])
    assert payload["script"]["text"] == "**Hype:** Welcome back!"


def test_invoke_tts_auto_generates_execution_id():
    mock_client = MagicMock()
    mock_client.invoke.return_value = _lambda_response(
        {"s3_key": "episodes/test/episode.mp3", "duration_seconds": 180, "character_count": 4200}
    )

    with patch("lambdas.mcp.tools.agents.LAMBDA_CLIENT", mock_client):
        from lambdas.mcp.tools.agents import invoke_tts

        asyncio.run(invoke_tts(script_text="**Hype:** Hello!"))

    payload = json.loads(mock_client.invoke.call_args.kwargs["Payload"])
    assert payload["metadata"]["execution_id"].startswith("mcp-standalone-")


# ---------------------------------------------------------------------------
# invoke_post_production
# ---------------------------------------------------------------------------


def test_invoke_post_production_passes_all_agent_outputs(
    sample_discovery_output,
    sample_research_output,
):
    sample_script = {
        "text": "**Hype:** Hello!",
        "character_count": 15,
        "segments": ["intro"],
        "featured_repo": "repo",
        "featured_developer": "user",
        "cover_art_suggestion": "art",
    }
    sample_cover_art = {"s3_key": "episodes/test/cover.png", "prompt_used": "prompt"}
    sample_tts = {
        "s3_key": "episodes/test/episode.mp3",
        "duration_seconds": 180,
        "character_count": 4200,
    }

    mock_client = MagicMock()
    mock_client.invoke.return_value = _lambda_response(
        {"s3_mp4_key": "episodes/test/episode.mp4", "episode_id": 1, "air_date": "2025-07-13"}
    )

    with patch("lambdas.mcp.tools.agents.LAMBDA_CLIENT", mock_client):
        from lambdas.mcp.tools.agents import invoke_post_production

        asyncio.run(
            invoke_post_production(
                discovery=sample_discovery_output,
                research=sample_research_output,
                script=sample_script,
                cover_art=sample_cover_art,
                tts=sample_tts,
            )
        )

    payload = json.loads(mock_client.invoke.call_args.kwargs["Payload"])
    assert "discovery" in payload
    assert "research" in payload
    assert "script" in payload
    assert "cover_art" in payload
    assert "tts" in payload
    assert payload["script"]["text"] == "**Hype:** Hello!"
    assert payload["cover_art"]["s3_key"] == "episodes/test/cover.png"
    assert payload["tts"]["s3_key"] == "episodes/test/episode.mp3"
