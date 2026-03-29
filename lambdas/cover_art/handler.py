from __future__ import annotations

import base64
import json
import os
from typing import Any

import boto3
from aws_lambda_powertools.utilities.typing import LambdaContext
from botocore.config import Config

from shared.logging import get_logger
from shared.metrics import get_metrics
from shared.s3 import upload_bytes
from shared.tracing import get_tracer
from shared.types import CoverArtOutput, PipelineState

logger = get_logger("cover_art")
tracer = get_tracer("cover_art")
metrics = get_metrics("cover_art")

# --- Module-level constants ---

NOVA_CANVAS_MODEL_ID: str = "amazon.nova-canvas-v1:0"
IMAGE_WIDTH: int = 1024
IMAGE_HEIGHT: int = 1024
IMAGE_QUALITY: str = "standard"
MAX_PROMPT_LENGTH: int = 1024  # Nova Canvas text field hard limit
PNG_MAGIC_BYTES: bytes = b"\x89PNG"
BEDROCK_READ_TIMEOUT: int = 300  # AWS recommends >= 300s for image generation

LANGUAGE_COLOR_MOODS: dict[str, str] = {
    "Python": "warm yellows, blues, and greens inspired by the Python ecosystem",
    "Rust": "deep oranges, warm reds, and metallic copper tones",
    "Go": "cool cyan, teal, and clean white accents",
    "JavaScript": "bright yellows, warm blacks, and neon highlights",
    "TypeScript": "rich blues, white, and subtle purple accents",
    "Ruby": "deep reds, crimson, and gemstone sparkle highlights",
    "C": "steely grays, dark blues, and sharp neon green accents",
    "C++": "similar to C but with warmer blue and subtle gold accents",
    "Java": "warm orange-red, deep brown, and coffee-inspired tones",
    "Shell": "terminal green on dark backgrounds with neon cyan accents",
    "Lua": "deep navy blue, soft purple, and moonlight silver",
    "Zig": "warm amber, bright orange, and golden lightning accents",
    "Haskell": "rich purple, deep violet, and abstract geometric highlights",
    "Elixir": "royal purple, deep magenta, and alchemical gold accents",
    "Swift": "bright orange, gradient warm tones, and clean white",
    "Kotlin": "gradient purple to orange, with modern clean accents",
}
DEFAULT_COLOR_MOOD: str = "vibrant blues, purples, and electric greens"

# --- Module-level cached client ---

_bedrock_client: Any | None = None


def _get_bedrock_client() -> Any:
    """Return a Bedrock Runtime boto3 client, cached across warm starts.

    Configures read_timeout=300s (AWS recommends this for image generation;
    the boto3 default of 60s is too short for Nova Canvas).
    """
    global _bedrock_client
    if _bedrock_client is None:
        _bedrock_client = boto3.client(
            "bedrock-runtime",
            config=Config(read_timeout=BEDROCK_READ_TIMEOUT),
        )
    return _bedrock_client


def _load_prompt_template() -> str:
    """Read prompts/cover_art.md from disk.

    Uses LAMBDA_TASK_ROOT (set by AWS Lambda runtime) to locate the prompt file,
    falling back to the handler's directory for local testing.
    """
    base_dir = os.environ.get("LAMBDA_TASK_ROOT", os.path.dirname(__file__))
    prompt_path = os.path.join(base_dir, "prompts", "cover_art.md")
    with open(prompt_path) as f:
        return f.read()


def _build_cover_art_prompt(
    cover_art_suggestion: str,
    repo_name: str,
    language: str,
) -> str:
    """Substitute {{visual_concept}}, {{episode_subtitle}}, {{color_mood}} into template.

    Falls back to a generic description if cover_art_suggestion is empty.
    Falls back to DEFAULT_COLOR_MOOD if language is not in LANGUAGE_COLOR_MOODS.
    Truncates final prompt to MAX_PROMPT_LENGTH (1024 chars) if needed.
    """
    visual_concept = (
        cover_art_suggestion.strip()
        if cover_art_suggestion.strip()
        else f"an abstract visualization of a software project called {repo_name}"
    )
    color_mood = LANGUAGE_COLOR_MOODS.get(language, DEFAULT_COLOR_MOOD)

    template = _load_prompt_template()
    prompt = (
        template.replace("{{visual_concept}}", visual_concept)
        .replace("{{episode_subtitle}}", repo_name)
        .replace("{{color_mood}}", color_mood)
    )
    return prompt[:MAX_PROMPT_LENGTH]


def _generate_image(prompt: str) -> bytes:
    """Call Nova Canvas TEXT_IMAGE and return decoded PNG bytes.

    Raises RuntimeError on content policy violation (ValidationException),
    empty images array, or RAI-flagged response (error field in response body).
    Lets ThrottlingException propagate for Step Functions retry.
    """
    import botocore.exceptions

    client = _get_bedrock_client()
    body = json.dumps(
        {
            "taskType": "TEXT_IMAGE",
            "textToImageParams": {"text": prompt},
            "imageGenerationConfig": {
                "numberOfImages": 1,
                "width": IMAGE_WIDTH,
                "height": IMAGE_HEIGHT,
                "quality": IMAGE_QUALITY,
                "cfgScale": 8.0,
            },
        }
    )

    try:
        response = client.invoke_model(
            modelId=NOVA_CANVAS_MODEL_ID,
            contentType="application/json",
            accept="application/json",
            body=body,
        )
    except botocore.exceptions.ClientError as exc:
        error_code = exc.response["Error"]["Code"]
        if error_code == "ValidationException":
            raise RuntimeError(f"Nova Canvas content policy violation: {exc}") from exc
        raise

    result: dict[str, Any] = json.loads(response["body"].read())

    if result.get("error"):
        raise RuntimeError(f"Nova Canvas RAI policy: {result['error']}")

    images: list[str] = result.get("images", [])
    if not images:
        raise RuntimeError("Nova Canvas returned no images")

    image_bytes = base64.b64decode(images[0])

    if not image_bytes.startswith(PNG_MAGIC_BYTES):
        raise RuntimeError("invalid PNG: decoded image does not start with PNG magic bytes")

    return image_bytes


@logger.inject_lambda_context(clear_state=True)
@tracer.capture_lambda_handler
@metrics.log_metrics
def lambda_handler(event: PipelineState, context: LambdaContext) -> CoverArtOutput:
    execution_id = event.get("metadata", {}).get("execution_id", "unknown")
    logger.info("Starting cover art generation", extra={"execution_id": execution_id})

    script = event["script"]
    discovery = event.get("discovery", {})

    cover_art_suggestion: str = script.get("cover_art_suggestion", "")
    repo_name: str = discovery.get("repo_name", "unknown")
    language: str = discovery.get("language", "")

    prompt = _build_cover_art_prompt(
        cover_art_suggestion=cover_art_suggestion,
        repo_name=repo_name,
        language=language,
    )
    logger.info("Generating image", extra={"prompt_length": len(prompt)})

    image_bytes = _generate_image(prompt)

    s3_key = f"episodes/{execution_id}/cover.png"
    bucket: str = os.environ["S3_BUCKET"]
    upload_bytes(bucket, s3_key, image_bytes, "image/png")

    logger.info("Cover art uploaded", extra={"s3_key": s3_key})

    return CoverArtOutput(s3_key=s3_key, prompt_used=prompt)
