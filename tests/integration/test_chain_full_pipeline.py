"""Chain integration test: Discovery -> Research -> Script -> Producer -> CoverArt.

Exercises the Producer retry loop — the most complex control flow in the pipeline.
PostProduction and TTS are skipped (TTS twin returns fake audio; ffmpeg would fail on it).
"""

from __future__ import annotations

import base64
import io
import json
import struct
import zlib
from typing import Any
from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# PNG helper — reused from test_cover_art_live pattern
# ---------------------------------------------------------------------------


def _make_minimal_png() -> bytes:
    """Build a 1x1 white PNG — smallest valid PNG that passes PNG_MAGIC_BYTES check."""
    sig = b"\x89PNG\r\n\x1a\n"

    def chunk(tag: bytes, data: bytes) -> bytes:
        length = struct.pack(">I", len(data))
        crc = struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)
        return length + tag + data + crc

    ihdr_data = struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0)
    ihdr = chunk(b"IHDR", ihdr_data)

    raw_scanline = b"\x00\xff\xff\xff"
    compressed = zlib.compress(raw_scanline)
    idat = chunk(b"IDAT", compressed)

    iend = chunk(b"IEND", b"")

    return sig + ihdr + idat + iend


def _make_nova_canvas_response(image_bytes: bytes) -> MagicMock:
    """Return a mock Bedrock invoke_model response shaped like Nova Canvas output."""
    encoded = base64.b64encode(image_bytes).decode("utf-8")
    body_json = json.dumps({"images": [encoded]})
    body_stream = MagicMock()
    body_stream.read.return_value = body_json.encode("utf-8")

    response = MagicMock()
    response.__getitem__ = lambda self, key: body_stream if key == "body" else MagicMock()
    return response


# ---------------------------------------------------------------------------
# Main chain test
# ---------------------------------------------------------------------------


@pytest.mark.integration
@pytest.mark.flaky(reruns=1)  # type: ignore[misc]
@pytest.mark.timeout(600)
def test_chain_full_pipeline_through_cover_art(
    seed_featured_developers: None,
    pipeline_metadata: dict[str, Any],
    lambda_context: MagicMock,
    test_s3_bucket: str,
) -> None:
    """Run Discovery -> Research -> Script -> Producer -> CoverArt end-to-end.

    Uses real Bedrock (Haiku) calls for all text agents. Nova Canvas is mocked
    to avoid image generation costs and avoid needing real Nova Canvas access.

    The Producer retry loop is exercised: if Producer returns FAIL and
    script_attempt < 3, Script reruns with feedback. The loop continues
    until PASS or max 3 attempts (matching the Step Functions ASL logic).
    """
    from lambdas.cover_art.handler import lambda_handler as cover_art_handler
    from lambdas.discovery.handler import lambda_handler as discovery_handler
    from lambdas.producer.handler import lambda_handler as producer_handler
    from lambdas.research.handler import lambda_handler as research_handler
    from lambdas.script.handler import lambda_handler as script_handler

    # ------------------------------------------------------------------
    # Step 1: Discovery
    # ------------------------------------------------------------------
    discovery_event: dict[str, Any] = {"metadata": pipeline_metadata}
    discovery_result: dict[str, Any] = discovery_handler(discovery_event, lambda_context)

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
    # Step 2: Research
    # ------------------------------------------------------------------
    research_event: dict[str, Any] = {
        "metadata": pipeline_metadata,
        "discovery": discovery_result,
    }
    research_result: dict[str, Any] = research_handler(research_event, lambda_context)

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

    for i, notable_repo in enumerate(research_result["notable_repos"]):
        for sub_field in ("name", "description", "stars", "language"):
            assert sub_field in notable_repo, (
                f"Research: notable_repos[{i}] missing required field: {sub_field}"
            )

    # ------------------------------------------------------------------
    # Steps 3–5: Script -> Producer with retry loop
    #
    # Mirrors the Step Functions EvaluateVerdict / IncrementAttempt logic:
    #   - PASS → proceed to CoverArt
    #   - FAIL + attempt < 3 → rerun Script with feedback (increment script_attempt)
    #   - FAIL + attempt >= 3 → fail the test (pipeline would halt)
    # ------------------------------------------------------------------
    MAX_SCRIPT_ATTEMPTS: int = 3

    # script_attempt is tracked locally; pipeline_metadata starts at 1
    script_attempt: int = int(pipeline_metadata.get("script_attempt", 1))

    script_result: dict[str, Any] | None = None
    producer_result: dict[str, Any] | None = None

    while True:
        # Build the script event — include producer feedback on retry attempts
        script_event: dict[str, Any] = {
            "metadata": {**pipeline_metadata, "script_attempt": script_attempt},
            "discovery": discovery_result,
            "research": research_result,
        }
        if script_attempt > 1 and producer_result is not None:
            # Pass Producer feedback into the state, matching Step Functions wiring
            script_event["producer"] = producer_result

        # Step 3: Script
        script_result = script_handler(script_event, lambda_context)

        script_required_keys = [
            "text",
            "character_count",
            "segments",
            "featured_repo",
            "featured_developer",
            "cover_art_suggestion",
        ]
        for key in script_required_keys:
            assert key in script_result, (
                f"Script (attempt {script_attempt}): missing required key: {key}"
            )

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
            f"Script (attempt {script_attempt}): missing segments: "
            f"{required_segments - set(script_result['segments'])}"
        )

        # Step 4: Producer
        producer_event: dict[str, Any] = {
            "metadata": {**pipeline_metadata, "script_attempt": script_attempt},
            "discovery": discovery_result,
            "research": research_result,
            "script": script_result,
        }
        producer_result = producer_handler(producer_event, lambda_context)

        assert "verdict" in producer_result, "Producer: missing 'verdict'"
        assert "score" in producer_result, "Producer: missing 'score'"
        assert producer_result["verdict"] in ("PASS", "FAIL"), (
            f"Producer: unexpected verdict {producer_result['verdict']!r}"
        )

        # Step 5: Evaluate verdict — mirror EvaluateVerdict Choice state
        if producer_result["verdict"] == "PASS":
            break

        # FAIL path
        assert script_attempt < MAX_SCRIPT_ATTEMPTS, (
            f"Producer returned FAIL on all {MAX_SCRIPT_ATTEMPTS} script attempts. "
            f"Last score: {producer_result.get('score')}. "
            f"Last feedback: {producer_result.get('feedback')}"
        )

        # FAIL + attempts remaining — increment and loop (mirrors IncrementAttempt Pass state)
        script_attempt += 1

    # At this point we have a PASS verdict and valid script_result / producer_result
    assert script_result is not None
    assert producer_result is not None
    assert producer_result["verdict"] == "PASS"

    # Cross-step assertion: script references the repo from discovery
    assert script_result["featured_repo"] == discovery_result["repo_name"], (
        f"Script featured_repo {script_result['featured_repo']!r} does not match "
        f"discovery repo_name {discovery_result['repo_name']!r}"
    )

    # ------------------------------------------------------------------
    # Step 6: CoverArt — mock Nova Canvas to avoid image generation costs
    # ------------------------------------------------------------------
    png_bytes = _make_minimal_png()
    nova_response = _make_nova_canvas_response(png_bytes)

    mock_bedrock = MagicMock()
    mock_bedrock.invoke_model.return_value = nova_response

    cover_art_event: dict[str, Any] = {
        "metadata": {**pipeline_metadata, "script_attempt": script_attempt},
        "discovery": discovery_result,
        "research": research_result,
        "script": script_result,
        "producer": producer_result,
    }

    with patch("lambdas.cover_art.handler._get_bedrock_client", return_value=mock_bedrock):
        cover_art_result: dict[str, Any] = cover_art_handler(cover_art_event, lambda_context)

    assert "s3_key" in cover_art_result, "CoverArt: missing 's3_key'"
    assert "prompt_used" in cover_art_result, "CoverArt: missing 'prompt_used'"

    execution_id: str = str(pipeline_metadata["execution_id"])
    expected_s3_key = f"episodes/{execution_id}/cover.png"
    assert cover_art_result["s3_key"] == expected_s3_key, (
        f"CoverArt s3_key {cover_art_result['s3_key']!r} does not match "
        f"expected {expected_s3_key!r}"
    )

    # Verify the PNG was actually written to the ephemeral S3 bucket
    import boto3

    s3 = boto3.client("s3")
    s3.head_object(Bucket=test_s3_bucket, Key=cover_art_result["s3_key"])
