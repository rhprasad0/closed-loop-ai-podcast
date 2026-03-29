from __future__ import annotations

import json
import os
import urllib.error
from collections.abc import Generator
from typing import Any
from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_elevenlabs_api_key() -> Generator[MagicMock, None, None]:
    """Mock Secrets Manager for ElevenLabs API key, reset module-level cache."""
    import lambdas.tts.handler as tts_module

    tts_module._elevenlabs_api_key = None
    with patch("lambdas.tts.handler.boto3") as mock_boto3:
        mock_sm = MagicMock()
        mock_boto3.client.return_value = mock_sm
        mock_sm.get_secret_value.return_value = {"SecretString": "test-elevenlabs-key"}
        yield mock_sm
        tts_module._elevenlabs_api_key = None


@pytest.fixture
def mock_tts_urlopen() -> Generator[tuple[MagicMock, MagicMock], None, None]:
    """Mock urllib.request.urlopen for ElevenLabs API calls."""
    with patch("lambdas.tts.handler.urllib.request.urlopen") as mock:
        response = MagicMock()
        response.__enter__ = lambda s: s
        response.__exit__ = MagicMock(return_value=False)
        response.status = 200
        response.read.return_value = b"\xff\xfb\x90\x00" * 1000  # fake MP3 bytes
        mock.return_value = response
        yield mock, response


@pytest.fixture
def mock_tts_s3_upload() -> Generator[MagicMock, None, None]:
    """Mock S3 upload for TTS MP3 output."""
    with patch("lambdas.tts.handler.upload_bytes") as mock:
        yield mock


# ---------------------------------------------------------------------------
# Dialogue Parsing Tests
# ---------------------------------------------------------------------------


def test_parse_valid_script_returns_turns() -> None:
    from lambdas.tts.handler import _parse_dialogue_turns

    script = (
        "**Hype:** Welcome back everyone!\n"
        "**Roast:** Oh here we go again.\n"
        "**Phil:** But what does it mean to welcome?"
    )
    turns = _parse_dialogue_turns(script)
    assert len(turns) == 3
    assert all("text" in t and "voice_id" in t for t in turns)


def test_parse_maps_hype_to_correct_voice_id() -> None:
    from lambdas.tts.handler import _parse_dialogue_turns

    turns = _parse_dialogue_turns("**Hype:** Hello!")
    assert turns[0]["voice_id"] == "cjVigY5qzO86Huf0OWal"


def test_parse_maps_roast_to_correct_voice_id() -> None:
    from lambdas.tts.handler import _parse_dialogue_turns

    turns = _parse_dialogue_turns("**Roast:** Rubbish.")
    assert turns[0]["voice_id"] == "JBFqnCBsd6RMkjVDRZzb"


def test_parse_maps_phil_to_correct_voice_id() -> None:
    from lambdas.tts.handler import _parse_dialogue_turns

    turns = _parse_dialogue_turns("**Phil:** Interesting thought.")
    assert turns[0]["voice_id"] == "cgSgspJ2msm6clMCkdW9"


def test_parse_strips_speaker_label_from_text() -> None:
    from lambdas.tts.handler import _parse_dialogue_turns

    turns = _parse_dialogue_turns("**Hype:** Welcome back!")
    assert turns[0]["text"] == "Welcome back!"
    assert "Hype" not in turns[0]["text"]


def test_parse_raises_on_malformed_line() -> None:
    from lambdas.tts.handler import _parse_dialogue_turns

    with pytest.raises(ValueError):
        _parse_dialogue_turns("This line has no speaker label")


def test_parse_raises_on_unknown_speaker() -> None:
    from lambdas.tts.handler import _parse_dialogue_turns

    with pytest.raises(ValueError):
        _parse_dialogue_turns("**Unknown:** Who am I?")


def test_parse_raises_on_blank_line() -> None:
    from lambdas.tts.handler import _parse_dialogue_turns

    with pytest.raises(ValueError):
        _parse_dialogue_turns("**Hype:** Hello!\n\n**Roast:** Hi!")


# ---------------------------------------------------------------------------
# ElevenLabs API Call Tests
# ---------------------------------------------------------------------------


def test_call_elevenlabs_sends_correct_body(
    mock_elevenlabs_api_key: MagicMock,
    mock_tts_urlopen: tuple[MagicMock, MagicMock],
) -> None:
    from lambdas.tts.handler import _call_elevenlabs

    mock_urlopen, mock_response = mock_tts_urlopen

    inputs = [{"text": "Hello", "voice_id": "abc123"}]
    _call_elevenlabs(inputs)

    call_args = mock_urlopen.call_args
    req = call_args[0][0]
    body = json.loads(req.data)
    assert body["inputs"] == inputs
    assert body["model_id"] == "eleven_v3"


def test_call_elevenlabs_includes_output_format_in_url(
    mock_elevenlabs_api_key: MagicMock,
    mock_tts_urlopen: tuple[MagicMock, MagicMock],
) -> None:
    from lambdas.tts.handler import _call_elevenlabs

    mock_urlopen, _ = mock_tts_urlopen

    _call_elevenlabs([{"text": "Hi", "voice_id": "abc"}])

    req = mock_urlopen.call_args[0][0]
    assert "output_format=mp3_44100_128" in req.full_url


def test_call_elevenlabs_returns_mp3_bytes(
    mock_elevenlabs_api_key: MagicMock,
    mock_tts_urlopen: tuple[MagicMock, MagicMock],
) -> None:
    from lambdas.tts.handler import _call_elevenlabs

    result = _call_elevenlabs([{"text": "Hi", "voice_id": "abc"}])
    assert isinstance(result, bytes)
    assert len(result) > 0


def test_call_elevenlabs_raises_on_http_error(
    mock_elevenlabs_api_key: MagicMock,
    mock_tts_urlopen: tuple[MagicMock, MagicMock],
) -> None:
    from lambdas.tts.handler import _call_elevenlabs

    mock_urlopen, _ = mock_tts_urlopen
    mock_urlopen.side_effect = urllib.error.HTTPError(
        url="",
        code=422,
        msg="Validation Error",
        hdrs={},  # type: ignore[arg-type]
        fp=None,
    )
    with pytest.raises(RuntimeError):
        _call_elevenlabs([{"text": "Hi", "voice_id": "abc"}])


# ---------------------------------------------------------------------------
# Full TTS Handler Tests
# ---------------------------------------------------------------------------


def test_handler_returns_valid_tts_output(
    pipeline_metadata: dict[str, Any],
    lambda_context: MagicMock,
    mock_elevenlabs_api_key: MagicMock,
    mock_tts_urlopen: tuple[MagicMock, MagicMock],
    mock_tts_s3_upload: MagicMock,
    sample_script_output: dict[str, Any],
) -> None:
    with patch.dict(os.environ, {"S3_BUCKET": "test-bucket"}):
        from lambdas.tts.handler import lambda_handler

        result = lambda_handler(
            {"metadata": pipeline_metadata, "script": sample_script_output},
            lambda_context,
        )
    assert "s3_key" in result
    assert "duration_seconds" in result
    assert "character_count" in result
    assert isinstance(result["duration_seconds"], int)


def test_handler_s3_key_format(
    pipeline_metadata: dict[str, Any],
    lambda_context: MagicMock,
    mock_elevenlabs_api_key: MagicMock,
    mock_tts_urlopen: tuple[MagicMock, MagicMock],
    mock_tts_s3_upload: MagicMock,
    sample_script_output: dict[str, Any],
) -> None:
    with patch.dict(os.environ, {"S3_BUCKET": "test-bucket"}):
        from lambdas.tts.handler import lambda_handler

        result = lambda_handler(
            {"metadata": pipeline_metadata, "script": sample_script_output},
            lambda_context,
        )
    assert result["s3_key"] == f"episodes/{pipeline_metadata['execution_id']}/episode.mp3"


def test_handler_raises_on_malformed_script(
    pipeline_metadata: dict[str, Any],
    lambda_context: MagicMock,
    mock_elevenlabs_api_key: MagicMock,
    mock_tts_urlopen: tuple[MagicMock, MagicMock],
    mock_tts_s3_upload: MagicMock,
) -> None:
    malformed_script = {
        "text": "No speaker labels here",
        "character_count": 22,
        "segments": ["intro"],
        "featured_repo": "r",
        "featured_developer": "d",
        "cover_art_suggestion": "art",
    }
    with patch.dict(os.environ, {"S3_BUCKET": "test-bucket"}):
        from lambdas.tts.handler import lambda_handler

        with pytest.raises(ValueError):
            lambda_handler(
                {"metadata": pipeline_metadata, "script": malformed_script},
                lambda_context,
            )
