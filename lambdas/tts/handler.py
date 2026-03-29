from __future__ import annotations

import json
import os
import re
import urllib.request

import boto3
from aws_lambda_powertools.utilities.typing import LambdaContext

from shared.logging import get_logger
from shared.metrics import get_metrics
from shared.s3 import upload_bytes
from shared.tracing import get_tracer
from shared.types import PipelineState, TTSOutput

logger = get_logger("tts")
tracer = get_tracer("tts")
metrics = get_metrics("tts")

# --- Module-level constants ---

ELEVENLABS_ENDPOINT: str = "https://api.elevenlabs.io/v1/text-to-dialogue"
ELEVENLABS_MODEL_ID: str = "eleven_v3"
ELEVENLABS_OUTPUT_FORMAT: str = "mp3_44100_128"

SPEAKER_VOICE_MAP: dict[str, str] = {
    "Hype": "cjVigY5qzO86Huf0OWal",
    "Roast": "JBFqnCBsd6RMkjVDRZzb",
    "Phil": "cgSgspJ2msm6clMCkdW9",
}

SPEAKER_PATTERN: re.Pattern[str] = re.compile(
    r"^\*\*(?P<speaker>Hype|Roast|Phil):\*\*\s*(?P<text>.+)$"
)

MAX_CHARACTER_COUNT: int = 5000

# --- Module-level cached credentials ---
_elevenlabs_api_key: str | None = None


def _get_elevenlabs_api_key() -> str:
    """Fetch ElevenLabs API key from Secrets Manager, cached across warm starts.

    Secret name: zerostars/elevenlabs-api-key.
    """
    global _elevenlabs_api_key
    if _elevenlabs_api_key is None:
        client = boto3.client("secretsmanager")
        response = client.get_secret_value(SecretId="zerostars/elevenlabs-api-key")
        _elevenlabs_api_key = response["SecretString"]
    return _elevenlabs_api_key


def _parse_dialogue_turns(script_text: str) -> list[dict[str, str]]:
    """Parse script text into ElevenLabs dialogue turn format.

    Splits on newlines, matches each line against SPEAKER_PATTERN.
    Maps speaker names to voice IDs via SPEAKER_VOICE_MAP.
    Returns list of {"text": "...", "voice_id": "..."} dicts.

    Raises ValueError on:
    - Lines that do not match SPEAKER_PATTERN (malformed or unknown speaker)
    - Blank lines (the script format does not allow blank lines)
    """
    turns: list[dict[str, str]] = []
    for line in script_text.splitlines():
        if not line:
            raise ValueError(
                "Blank line found in script — script format does not allow blank lines"
            )
        match = SPEAKER_PATTERN.match(line)
        if not match:
            raise ValueError(f"Line does not match speaker pattern: {line!r}")
        speaker = match.group("speaker")
        text = match.group("text")
        voice_id = SPEAKER_VOICE_MAP[speaker]  # speaker is already validated by the regex
        turns.append({"text": text, "voice_id": voice_id})
    return turns


def _call_elevenlabs(inputs: list[dict[str, str]]) -> bytes:
    """POST to ElevenLabs text-to-dialogue API and return raw MP3 bytes.

    Sends request body: {"inputs": inputs, "model_id": ELEVENLABS_MODEL_ID}
    with output_format query parameter.

    Raises RuntimeError on non-200 responses (422 validation error, 5xx server error).
    """
    api_key = _get_elevenlabs_api_key()
    url = f"{ELEVENLABS_ENDPOINT}?output_format={ELEVENLABS_OUTPUT_FORMAT}"
    body = json.dumps({"inputs": inputs, "model_id": ELEVENLABS_MODEL_ID}).encode()

    req = urllib.request.Request(
        url,
        data=body,
        headers={
            "Content-Type": "application/json",
            "xi-api-key": api_key,
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(req) as response:
            mp3_bytes: bytes = response.read()
    except urllib.error.HTTPError as exc:
        error_body = exc.read().decode(errors="replace")
        raise RuntimeError(f"ElevenLabs API error {exc.code}: {error_body[:500]}") from exc

    return mp3_bytes


@logger.inject_lambda_context(clear_state=True)
@tracer.capture_lambda_handler
@metrics.log_metrics
def lambda_handler(event: PipelineState, context: LambdaContext) -> TTSOutput:
    execution_id = event.get("metadata", {}).get("execution_id", "unknown")
    logger.info("Starting TTS generation", extra={"execution_id": execution_id})

    script = event.get("script", {})
    script_text: str = script.get("text", "")
    character_count: int = len(script_text)

    logger.info("Parsing dialogue turns", extra={"character_count": character_count})
    turns = _parse_dialogue_turns(script_text)
    logger.info("Calling ElevenLabs", extra={"turn_count": len(turns)})

    mp3_bytes = _call_elevenlabs(turns)

    # Estimate duration: 128kbps = 128000 bits/s = 16000 bytes/s
    duration_seconds: int = int(len(mp3_bytes) / (128000 / 8))

    s3_key = f"episodes/{execution_id}/episode.mp3"
    bucket: str = os.environ["S3_BUCKET"]
    upload_bytes(bucket, s3_key, mp3_bytes, "audio/mpeg")

    logger.info(
        "TTS audio uploaded",
        extra={"s3_key": s3_key, "duration_seconds": duration_seconds},
    )

    return TTSOutput(
        s3_key=s3_key,
        duration_seconds=duration_seconds,
        character_count=character_count,
    )
