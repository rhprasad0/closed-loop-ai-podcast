"""Integration test for the TTS Lambda handler.

ElevenLabs is served by the session-scoped behavioral twin (returns silent MP3).
S3 upload uses a real ephemeral bucket created by the test_s3_bucket session fixture.

Behavioral assertions inspect calls intercepted via a monkeypatch wrapper around
_call_elevenlabs so we can verify exactly what was sent to the twin without needing
direct access to the ElevenLabsTwinState created inside the session fixture.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import boto3
import pytest

# ---------------------------------------------------------------------------
# Local fixture: state tracker for ElevenLabs calls within this test
# ---------------------------------------------------------------------------


@pytest.fixture
def elevenlabs_call_tracker(monkeypatch: pytest.MonkeyPatch) -> list[list[dict[str, str]]]:
    """Wrap _call_elevenlabs to capture inputs; delegates to the original (hits the twin).

    Returns a list that accumulates one entry per call, each being the `inputs`
    list of {"text": ..., "voice_id": ...} dicts passed to ElevenLabs.
    """
    import lambdas.tts.handler as tts_handler

    calls: list[list[dict[str, str]]] = []
    _original = tts_handler._call_elevenlabs

    def _wrapper(inputs: list[dict[str, str]]) -> bytes:
        calls.append(inputs)
        return _original(inputs)

    monkeypatch.setattr(tts_handler, "_call_elevenlabs", _wrapper)
    return calls


# ---------------------------------------------------------------------------
# Test
# ---------------------------------------------------------------------------


@pytest.mark.integration
@pytest.mark.timeout(60)
def test_tts_produces_valid_output(
    pipeline_metadata: dict[str, Any],
    lambda_context: MagicMock,
    test_s3_bucket: str,
    elevenlabs_call_tracker: list[list[dict[str, str]]],
) -> None:
    """TTS handler parses the script, calls ElevenLabs, and uploads audio to S3."""
    from lambdas.tts.handler import lambda_handler

    script_text = "**Hype:** Hello!\n**Roast:** Ugh.\n**Phil:** But what is hello?"

    event: dict[str, Any] = {
        "metadata": pipeline_metadata,
        "script": {
            "text": script_text,
            "character_count": len(script_text),
            "segments": [
                "intro",
                "core_debate",
                "developer_deep_dive",
                "technical_appreciation",
                "hiring_manager",
                "outro",
            ],
            "featured_repo": "example-repo",
            "featured_developer": "example-dev",
            "cover_art_suggestion": "Three robots at a terminal.",
        },
    }

    result = lambda_handler(event, lambda_context)

    # --- Structural assertions ---

    assert "s3_key" in result, "result missing 's3_key'"
    assert "duration_seconds" in result, "result missing 'duration_seconds'"

    execution_id = pipeline_metadata["execution_id"]
    expected_s3_key = f"episodes/{execution_id}/episode.mp3"
    assert result["s3_key"] == expected_s3_key, (
        f"s3_key {result['s3_key']!r} does not match expected {expected_s3_key!r}"
    )

    assert result["duration_seconds"] >= 0, (
        f"duration_seconds {result['duration_seconds']} must be non-negative"
    )

    # Verify the object was actually written to S3
    s3 = boto3.client("s3")
    s3.head_object(Bucket=test_s3_bucket, Key=result["s3_key"])

    # --- Behavioral assertions (from twin state) ---

    assert len(elevenlabs_call_tracker) == 1, (
        f"Expected exactly 1 ElevenLabs request, got {len(elevenlabs_call_tracker)}"
    )

    sent_inputs = elevenlabs_call_tracker[0]

    # Verify voice_ids in the request body match the speaker-to-voice mapping
    expected_voice_ids: dict[str, str] = {
        "Hype": "cjVigY5qzO86Huf0OWal",
        "Roast": "JBFqnCBsd6RMkjVDRZzb",
        "Phil": "cgSgspJ2msm6clMCkdW9",
    }
    # The script has 3 lines: Hype, Roast, Phil — in that order
    assert len(sent_inputs) == 3, (
        f"Expected 3 dialogue turns in ElevenLabs request, got {len(sent_inputs)}"
    )

    speakers_in_order = ["Hype", "Roast", "Phil"]
    for i, (turn, speaker) in enumerate(zip(sent_inputs, speakers_in_order)):
        expected_voice_id = expected_voice_ids[speaker]
        assert turn["voice_id"] == expected_voice_id, (
            f"Turn {i} ({speaker}): expected voice_id {expected_voice_id!r}, "
            f"got {turn['voice_id']!r}"
        )
