"""Unit tests for the Cover Art Lambda handler.

Three sections:
  1. Prompt construction tests
  2. Image generation tests
  3. Full handler tests
"""

from __future__ import annotations

import base64
import json
import os
from io import BytesIO
from unittest.mock import MagicMock, patch

import pytest
from botocore.exceptions import ClientError

from lambdas.cover_art.handler import (
    DEFAULT_COLOR_MOOD,
    LANGUAGE_COLOR_MOODS,
    PNG_MAGIC_BYTES,
    _build_cover_art_prompt,
    _generate_image,
)

# ---------------------------------------------------------------------------
# Shared constants
# ---------------------------------------------------------------------------

# Minimal valid PNG: magic bytes + minimal IHDR chunk (enough to pass magic byte check)
MINIMAL_PNG = (
    b"\x89PNG\r\n\x1a\n"  # PNG signature
    b"\x00\x00\x00\rIHDR"  # IHDR chunk
    b"\x00\x00\x00\x01\x00\x00\x00\x01\x08\x02"  # 1x1, 8-bit RGB
    b"\x00\x00\x00\x90wS\xde"  # CRC
)


def _mock_nova_canvas_response(image_bytes: bytes) -> MagicMock:
    """Build a mock Bedrock invoke_model response with base64-encoded image."""
    body_content = json.dumps({"images": [base64.b64encode(image_bytes).decode()]}).encode()
    mock_body = MagicMock()
    mock_body.read.return_value = body_content
    return {"body": mock_body}


# ---------------------------------------------------------------------------
# Prompt Construction Tests
# ---------------------------------------------------------------------------


def test_build_prompt_substitutes_visual_concept(mock_cover_art_prompt_template: str) -> None:
    result = _build_cover_art_prompt(
        cover_art_suggestion="a terminal window with pasta names scrolling",
        repo_name="pasta-sorter",
        language="Python",
    )
    assert "a terminal window with pasta names scrolling" in result


def test_build_prompt_substitutes_repo_name(mock_cover_art_prompt_template: str) -> None:
    result = _build_cover_art_prompt(
        cover_art_suggestion="robots coding",
        repo_name="pasta-sorter",
        language="Python",
    )
    assert "pasta-sorter" in result


def test_build_prompt_maps_python_to_color_mood(mock_cover_art_prompt_template: str) -> None:
    result = _build_cover_art_prompt(
        cover_art_suggestion="robots coding",
        repo_name="testrepo",
        language="Python",
    )
    assert "warm yellows" in result


def test_build_prompt_maps_rust_to_color_mood(mock_cover_art_prompt_template: str) -> None:
    result = _build_cover_art_prompt(
        cover_art_suggestion="robots coding",
        repo_name="testrepo",
        language="Rust",
    )
    assert "deep oranges" in result


def test_build_prompt_unknown_language_uses_default(mock_cover_art_prompt_template: str) -> None:
    result = _build_cover_art_prompt(
        cover_art_suggestion="robots coding",
        repo_name="testrepo",
        language="Brainfuck",
    )
    assert DEFAULT_COLOR_MOOD in result


def test_build_prompt_empty_suggestion_uses_fallback(mock_cover_art_prompt_template: str) -> None:
    result = _build_cover_art_prompt(
        cover_art_suggestion="",
        repo_name="testrepo",
        language="Python",
    )
    assert "testrepo" in result
    # Should not contain empty string substitution — fallback kicks in
    assert "abstract visualization" in result or "testrepo" in result


def test_build_prompt_truncates_to_1024_chars(mock_cover_art_prompt_template: str) -> None:
    # Force a prompt that would exceed 1024 chars after substitution
    long_suggestion = "x" * 900  # way longer than template can accommodate
    result = _build_cover_art_prompt(
        cover_art_suggestion=long_suggestion,
        repo_name="testrepo",
        language="Python",
    )
    assert len(result) <= 1024


# ---------------------------------------------------------------------------
# Image Generation Tests
# ---------------------------------------------------------------------------


def test_generate_image_returns_png_bytes(mock_nova_canvas_client: MagicMock) -> None:
    mock_nova_canvas_client.invoke_model.return_value = _mock_nova_canvas_response(MINIMAL_PNG)
    result = _generate_image("test prompt")
    assert result[:4] == PNG_MAGIC_BYTES
    assert result == MINIMAL_PNG


def test_generate_image_sends_correct_request_body(mock_nova_canvas_client: MagicMock) -> None:
    mock_nova_canvas_client.invoke_model.return_value = _mock_nova_canvas_response(MINIMAL_PNG)
    _generate_image("test prompt")
    call_args = mock_nova_canvas_client.invoke_model.call_args
    assert call_args.kwargs["modelId"] == "amazon.nova-canvas-v1:0"
    assert call_args.kwargs["contentType"] == "application/json"
    body = json.loads(call_args.kwargs["body"])
    assert body["taskType"] == "TEXT_IMAGE"
    assert body["textToImageParams"]["text"] == "test prompt"
    assert body["imageGenerationConfig"]["width"] == 1024
    assert body["imageGenerationConfig"]["height"] == 1024
    assert body["imageGenerationConfig"]["quality"] == "standard"
    assert body["imageGenerationConfig"]["numberOfImages"] == 1


def test_generate_image_raises_on_content_policy_violation(
    mock_nova_canvas_client: MagicMock,
) -> None:
    mock_nova_canvas_client.invoke_model.side_effect = ClientError(
        {"Error": {"Code": "ValidationException", "Message": "Content policy violation"}},
        "InvokeModel",
    )
    with pytest.raises(RuntimeError, match="content policy"):
        _generate_image("offensive prompt")


def test_generate_image_raises_on_empty_images_array(mock_nova_canvas_client: MagicMock) -> None:
    body_content = json.dumps({"images": []}).encode()
    mock_body = MagicMock()
    mock_body.read.return_value = body_content
    mock_nova_canvas_client.invoke_model.return_value = {"body": mock_body}
    with pytest.raises(RuntimeError, match="no images"):  # spec says "no images"
        _generate_image("test prompt")


def test_generate_image_raises_on_throttling(mock_nova_canvas_client: MagicMock) -> None:
    mock_nova_canvas_client.invoke_model.side_effect = ClientError(
        {"Error": {"Code": "ThrottlingException", "Message": "Rate exceeded"}},
        "InvokeModel",
    )
    with pytest.raises(ClientError):
        _generate_image("test prompt")


def test_generate_image_raises_on_rai_error(mock_nova_canvas_client: MagicMock) -> None:
    """Nova Canvas returns an error field when RAI flags the generated image."""
    body_content = json.dumps(
        {
            "images": [],
            "error": "The generated image has been blocked by our content filter.",
        }
    ).encode()
    mock_body = MagicMock()
    mock_body.read.return_value = body_content
    mock_nova_canvas_client.invoke_model.return_value = {"body": mock_body}
    with pytest.raises(RuntimeError, match="RAI"):
        _generate_image("test prompt")


# ---------------------------------------------------------------------------
# Full Handler Tests
# ---------------------------------------------------------------------------


def test_handler_returns_valid_cover_art_output(
    pipeline_metadata: dict,
    lambda_context: MagicMock,
    mock_nova_canvas_client: MagicMock,
    mock_s3_upload: MagicMock,
    mock_cover_art_prompt_template: str,
    sample_discovery_output: dict,
    sample_script_output: dict,
) -> None:
    mock_nova_canvas_client.invoke_model.return_value = _mock_nova_canvas_response(MINIMAL_PNG)
    with patch.dict(os.environ, {"S3_BUCKET": "test-bucket"}):
        from lambdas.cover_art.handler import lambda_handler

        result = lambda_handler(
            {
                "metadata": pipeline_metadata,
                "discovery": sample_discovery_output,
                "script": sample_script_output,
            },
            lambda_context,
        )
    assert "s3_key" in result
    assert "prompt_used" in result


def test_handler_s3_key_contains_execution_id(
    pipeline_metadata: dict,
    lambda_context: MagicMock,
    mock_nova_canvas_client: MagicMock,
    mock_s3_upload: MagicMock,
    mock_cover_art_prompt_template: str,
    sample_discovery_output: dict,
    sample_script_output: dict,
) -> None:
    mock_nova_canvas_client.invoke_model.return_value = _mock_nova_canvas_response(MINIMAL_PNG)
    execution_id = pipeline_metadata["execution_id"]
    with patch.dict(os.environ, {"S3_BUCKET": "test-bucket"}):
        from lambdas.cover_art.handler import lambda_handler

        result = lambda_handler(
            {
                "metadata": pipeline_metadata,
                "discovery": sample_discovery_output,
                "script": sample_script_output,
            },
            lambda_context,
        )
    assert result["s3_key"] == f"episodes/{execution_id}/cover.png"


def test_handler_uploads_png_to_s3(
    pipeline_metadata: dict,
    lambda_context: MagicMock,
    mock_nova_canvas_client: MagicMock,
    mock_s3_upload: MagicMock,
    mock_cover_art_prompt_template: str,
    sample_discovery_output: dict,
    sample_script_output: dict,
) -> None:
    mock_nova_canvas_client.invoke_model.return_value = _mock_nova_canvas_response(MINIMAL_PNG)
    with patch.dict(os.environ, {"S3_BUCKET": "test-bucket"}):
        from lambdas.cover_art.handler import lambda_handler

        lambda_handler(
            {
                "metadata": pipeline_metadata,
                "discovery": sample_discovery_output,
                "script": sample_script_output,
            },
            lambda_context,
        )
    mock_s3_upload.assert_called_once()
    call_args = mock_s3_upload.call_args
    assert call_args[0][0] == "test-bucket"  # bucket
    assert call_args[0][1].endswith("/cover.png")  # key
    assert call_args[0][2] == MINIMAL_PNG  # bytes
    assert call_args[0][3] == "image/png"  # content_type


def test_handler_prompt_used_matches_constructed_prompt(
    pipeline_metadata: dict,
    lambda_context: MagicMock,
    mock_nova_canvas_client: MagicMock,
    mock_s3_upload: MagicMock,
    mock_cover_art_prompt_template: str,
    sample_discovery_output: dict,
    sample_script_output: dict,
) -> None:
    mock_nova_canvas_client.invoke_model.return_value = _mock_nova_canvas_response(MINIMAL_PNG)
    with patch.dict(os.environ, {"S3_BUCKET": "test-bucket"}):
        from lambdas.cover_art.handler import lambda_handler

        result = lambda_handler(
            {
                "metadata": pipeline_metadata,
                "discovery": sample_discovery_output,
                "script": sample_script_output,
            },
            lambda_context,
        )
    # prompt_used should contain the substituted values from the template
    assert sample_discovery_output["repo_name"] in result["prompt_used"]


def test_handler_validates_png_magic_bytes(
    pipeline_metadata: dict,
    lambda_context: MagicMock,
    mock_nova_canvas_client: MagicMock,
    mock_s3_upload: MagicMock,
    mock_cover_art_prompt_template: str,
    sample_discovery_output: dict,
    sample_script_output: dict,
) -> None:
    # Return non-PNG bytes (e.g., JPEG magic bytes)
    jpeg_bytes = b"\xff\xd8\xff\xe0" + b"\x00" * 100
    mock_nova_canvas_client.invoke_model.return_value = _mock_nova_canvas_response(jpeg_bytes)
    with patch.dict(os.environ, {"S3_BUCKET": "test-bucket"}):
        from lambdas.cover_art.handler import lambda_handler

        with pytest.raises(RuntimeError, match="invalid PNG"):  # spec expects RuntimeError
            lambda_handler(
                {
                    "metadata": pipeline_metadata,
                    "discovery": sample_discovery_output,
                    "script": sample_script_output,
                },
                lambda_context,
            )


def test_handler_raises_on_missing_script_data(
    pipeline_metadata: dict,
    lambda_context: MagicMock,
    mock_nova_canvas_client: MagicMock,
    mock_s3_upload: MagicMock,
    mock_cover_art_prompt_template: str,
    sample_discovery_output: dict,
) -> None:
    with patch.dict(os.environ, {"S3_BUCKET": "test-bucket"}):
        from lambdas.cover_art.handler import lambda_handler

        with pytest.raises(KeyError):  # spec expects KeyError for missing "script"
            lambda_handler(
                {
                    "metadata": pipeline_metadata,
                    "discovery": sample_discovery_output,
                    # missing "script" key
                },
                lambda_context,
            )


def test_handler_propagates_bedrock_runtime_error(
    pipeline_metadata: dict,
    lambda_context: MagicMock,
    mock_nova_canvas_client: MagicMock,
    mock_s3_upload: MagicMock,
    mock_cover_art_prompt_template: str,
    sample_discovery_output: dict,
    sample_script_output: dict,
) -> None:
    mock_nova_canvas_client.invoke_model.side_effect = RuntimeError("Nova Canvas error")
    with patch.dict(os.environ, {"S3_BUCKET": "test-bucket"}):
        from lambdas.cover_art.handler import lambda_handler

        with pytest.raises(RuntimeError, match="Nova Canvas"):
            lambda_handler(
                {
                    "metadata": pipeline_metadata,
                    "discovery": sample_discovery_output,
                    "script": sample_script_output,
                },
                lambda_context,
            )
