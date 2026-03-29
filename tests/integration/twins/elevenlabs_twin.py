"""ElevenLabs text-to-dialogue API behavioral twin for integration tests.

Serves fixture audio data via pytest-httpserver, recording all calls for behavioral assertions.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field

from pytest_httpserver import HTTPServer
from werkzeug.wrappers import Request, Response

from tests.integration.twins.fixtures import SILENT_MP3_BYTES

# Known valid voice IDs from CLAUDE.md / external-api-contracts spec
_KNOWN_VOICE_IDS: frozenset[str] = frozenset(
    {
        "cjVigY5qzO86Huf0OWal",  # Hype / Eric
        "JBFqnCBsd6RMkjVDRZzb",  # Roast / George
        "cgSgspJ2msm6clMCkdW9",  # Phil / Jessica
    }
)

MAX_CHARACTERS: int = 5000


@dataclass
class ElevenLabsTwinState:
    """Tracks ElevenLabs API calls made during a test."""

    requests_received: list[dict[str, object]] = field(default_factory=list)
    total_characters: int = 0


def setup_elevenlabs_twin(server: HTTPServer) -> ElevenLabsTwinState:
    """Register ElevenLabs API handlers on the given HTTPServer and return a state tracker."""
    state = ElevenLabsTwinState()

    def _handle_text_to_dialogue(request: Request) -> Response:
        body: dict[str, object] = json.loads(request.data or b"{}")

        # Validate 'model_id' presence
        if "model_id" not in body:
            return Response(
                json.dumps({"detail": "validation error: missing 'model_id'"}),
                status=400,
                content_type="application/json",
            )

        # Validate 'inputs' is a list
        inputs = body.get("inputs")
        if not isinstance(inputs, list):
            return Response(
                json.dumps({"detail": "validation error: 'inputs' must be a list"}),
                status=400,
                content_type="application/json",
            )

        # Validate each input entry and accumulate character count
        total_chars = 0
        for i, entry in enumerate(inputs):
            if not isinstance(entry, dict):
                return Response(
                    json.dumps({"detail": f"validation error: inputs[{i}] must be a dict"}),
                    status=400,
                    content_type="application/json",
                )
            if "text" not in entry or "voice_id" not in entry:
                return Response(
                    json.dumps(
                        {"detail": (f"validation error: inputs[{i}] missing 'text' or 'voice_id'")}
                    ),
                    status=400,
                    content_type="application/json",
                )
            voice_id = entry["voice_id"]
            if voice_id not in _KNOWN_VOICE_IDS:
                return Response(
                    json.dumps({"detail": f"validation error: unknown voice_id '{voice_id}'"}),
                    status=400,
                    content_type="application/json",
                )
            total_chars += len(str(entry["text"]))

        # Validate character limit
        if total_chars >= MAX_CHARACTERS:
            return Response(
                json.dumps(
                    {
                        "detail": (
                            f"validation error: total character count {total_chars} "
                            f"exceeds limit of {MAX_CHARACTERS}"
                        )
                    }
                ),
                status=400,
                content_type="application/json",
            )

        # Record the request and update state
        state.requests_received.append(body)
        state.total_characters += total_chars

        return Response(SILENT_MP3_BYTES, status=200, content_type="audio/mpeg")

    server.expect_request("/v1/text-to-dialogue", method="POST").respond_with_handler(
        _handle_text_to_dialogue
    )

    return state
