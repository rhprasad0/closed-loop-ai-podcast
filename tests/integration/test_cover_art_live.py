"""Integration test for the Cover Art Lambda handler.

Nova Canvas has no cheap tier, so Bedrock image generation is mocked.
S3 upload uses a real ephemeral bucket created by the test_s3_bucket session fixture.
"""

from __future__ import annotations

import base64
import struct
import zlib
from typing import Any
from unittest.mock import MagicMock, patch

import boto3
import pytest


def _make_minimal_png() -> bytes:
    """Build a 1x1 white PNG — smallest valid PNG that passes PNG_MAGIC_BYTES check."""
    # PNG signature
    sig = b"\x89PNG\r\n\x1a\n"

    def chunk(tag: bytes, data: bytes) -> bytes:
        length = struct.pack(">I", len(data))
        crc = struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)
        return length + tag + data + crc

    # IHDR: width=1, height=1, bit_depth=8, color_type=2 (RGB), compression=0, filter=0, interlace=0
    ihdr_data = struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0)
    ihdr = chunk(b"IHDR", ihdr_data)

    # IDAT: one scanline, filter byte 0 + RGB bytes for white
    raw_scanline = b"\x00\xff\xff\xff"
    compressed = zlib.compress(raw_scanline)
    idat = chunk(b"IDAT", compressed)

    # IEND
    iend = chunk(b"IEND", b"")

    return sig + ihdr + idat + iend


def _make_nova_canvas_response(image_bytes: bytes) -> MagicMock:
    """Return a mock Bedrock invoke_model response shaped like Nova Canvas output."""
    import json

    encoded = base64.b64encode(image_bytes).decode("utf-8")
    body_json = json.dumps({"images": [encoded]})
    body_stream = MagicMock()
    body_stream.read.return_value = body_json.encode("utf-8")

    response = MagicMock()
    response.__getitem__ = lambda self, key: body_stream if key == "body" else MagicMock()
    return response


@pytest.mark.integration
@pytest.mark.timeout(60)
def test_cover_art_produces_valid_output(
    pipeline_metadata: dict[str, Any],
    lambda_context: MagicMock,
    test_s3_bucket: str,
) -> None:
    """Cover Art handler uploads a PNG to S3 and returns the expected output shape."""
    from lambdas.cover_art.handler import lambda_handler

    png_bytes = _make_minimal_png()
    nova_response = _make_nova_canvas_response(png_bytes)

    mock_bedrock = MagicMock()
    mock_bedrock.invoke_model.return_value = nova_response

    sample_discovery: dict[str, Any] = {
        "repo_url": "https://github.com/iximiuz/ptyme",
        "repo_name": "ptyme",
        "repo_description": "Attaches to a running Linux process via ptrace to sample call stacks.",
        "developer_github": "iximiuz",
        "star_count": 7,
        "language": "Go",
        "discovery_rationale": "Lightweight ptrace profiler with no instrumentation required.",
        "key_files": ["main.go", "README.md"],
        "technical_highlights": [
            "Uses ptrace syscall to attach to running processes",
            "No instrumentation or recompilation required",
        ],
    }

    sample_research: dict[str, Any] = {
        "developer_name": "Ivan Velichko",
        "developer_github": "iximiuz",
        "developer_bio": "Container and Linux internals.",
        "public_repos_count": 19,
        "notable_repos": [],
        "commit_patterns": "Active on weekdays.",
        "technical_profile": "Go, Linux internals, containers.",
        "interesting_findings": ["Built a profiler that needs zero changes to the target binary"],
        "hiring_signals": ["Deep Linux systems knowledge"],
    }

    sample_script: dict[str, Any] = {
        "text": (
            "**Hype:** Welcome back to 0 Stars, 10 out of 10!\n"
            "**Roast:** A Go profiler. Because twelve weren't enough.\n"
            "**Phil:** What is profiling, really?"
        ),
        "character_count": 120,
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

    with patch("lambdas.cover_art.handler._get_bedrock_client", return_value=mock_bedrock):
        result = lambda_handler(event, lambda_context)

    # Structural assertions
    assert "s3_key" in result, "result missing 's3_key'"
    assert "prompt_used" in result, "result missing 'prompt_used'"

    execution_id = pipeline_metadata["execution_id"]
    expected_s3_key = f"episodes/{execution_id}/cover.png"
    assert result["s3_key"] == expected_s3_key, (
        f"s3_key {result['s3_key']!r} does not match expected {expected_s3_key!r}"
    )

    # Verify the object was actually written to S3
    s3 = boto3.client("s3")
    s3.head_object(Bucket=test_s3_bucket, Key=result["s3_key"])
