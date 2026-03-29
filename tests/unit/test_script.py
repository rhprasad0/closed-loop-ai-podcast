from __future__ import annotations

import json
from unittest.mock import patch

import pytest

from lambdas.script.handler import _build_user_message, _parse_script_output

VALID_SCRIPT_TEXT = (
    "**Hype:** Welcome back to 0 Stars, 10 out of 10! Today we found testrepo.\n"
    "**Roast:** Three stars. Impressive. My cat's Instagram has more followers.\n"
    "**Phil:** But what is a star, really? A mass of burning gas, or a mass of burning ambition?\n"
    "**Hype:** This developer built a markdown converter in 200 lines of Rust!\n"
    "**Roast:** Two hundred lines. My error handler is longer.\n"
    "**Phil:** Perhaps brevity is the soul of code, as it is the soul of wit.\n"
    "**Hype:** Let me tell you about this developer. Fifteen repos. Fifteen!\n"
    "**Roast:** Half of them are forks with zero changes.\n"
    "**Phil:** To fork or not to fork. That is the question.\n"
    "**Roast:** Fine. The error handling is actually solid. Happy?\n"
    "**Hype:** He said it! He said something nice!\n"
    "**Phil:** When the cynic finds beauty, the universe notices.\n"
    "**Hype:** Any hiring manager would snap this developer up in a second!\n"
    "**Roast:** They ship finished projects. With READMEs. That alone puts them ahead of 90 percent of candidates.\n"
    "**Phil:** Can we ever truly know a developer through their commits?\n"
    "**Hype:** That is all for today! Remember, zero stars, ten out of ten!\n"
    "**Roast:** Same time next week. Try not to break anything.\n"
    "**Phil:** But what is time, if not a loop we choose to re-enter?"
)

VALID_OUTPUT = {
    "text": VALID_SCRIPT_TEXT,
    "character_count": len(VALID_SCRIPT_TEXT),
    "segments": [
        "intro",
        "core_debate",
        "developer_deep_dive",
        "technical_appreciation",
        "hiring_manager",
        "outro",
    ],
    "featured_repo": "testrepo",
    "featured_developer": "testuser",
    "cover_art_suggestion": "A terminal window with Rust code scrolling past, three robot silhouettes in a podcast studio",
}


# --- Output Parsing Tests ---


def test_parse_valid_json() -> None:
    result = _parse_script_output(json.dumps(VALID_OUTPUT))
    assert result["featured_repo"] == "testrepo"
    assert result["character_count"] == len(VALID_SCRIPT_TEXT)
    assert len(result["segments"]) == 6


def test_parse_fenced_json() -> None:
    fenced = f"```json\n{json.dumps(VALID_OUTPUT)}\n```"
    result = _parse_script_output(fenced)
    assert result["featured_repo"] == "testrepo"


def test_parse_fenced_no_language_tag() -> None:
    fenced = f"```\n{json.dumps(VALID_OUTPUT)}\n```"
    result = _parse_script_output(fenced)
    assert result["featured_repo"] == "testrepo"


def test_parse_rejects_character_count_gte_5000() -> None:
    long_text = "**Hype:** " + "x" * 4991  # total > 5000
    bad = {**VALID_OUTPUT, "text": long_text, "character_count": len(long_text)}
    with pytest.raises(ValueError, match="character_count"):
        _parse_script_output(json.dumps(bad))


def test_parse_coerces_string_character_count() -> None:
    coerced = {**VALID_OUTPUT, "character_count": str(len(VALID_SCRIPT_TEXT))}
    result = _parse_script_output(json.dumps(coerced))
    assert isinstance(result["character_count"], int)


def test_parse_corrects_inaccurate_character_count() -> None:
    wrong_count = {**VALID_OUTPUT, "character_count": 999}
    result = _parse_script_output(json.dumps(wrong_count))
    assert result["character_count"] == len(VALID_SCRIPT_TEXT)


def test_parse_rejects_missing_field() -> None:
    incomplete = {k: v for k, v in VALID_OUTPUT.items() if k != "text"}
    with pytest.raises(ValueError, match="text"):
        _parse_script_output(json.dumps(incomplete))


def test_parse_rejects_missing_segments() -> None:
    incomplete = {k: v for k, v in VALID_OUTPUT.items() if k != "segments"}
    with pytest.raises(ValueError, match="segments"):
        _parse_script_output(json.dumps(incomplete))


def test_parse_rejects_invalid_json() -> None:
    with pytest.raises((ValueError, json.JSONDecodeError)):
        _parse_script_output("this is not json at all")


def test_parse_rejects_wrong_segments() -> None:
    bad = {**VALID_OUTPUT, "segments": ["intro", "outro"]}
    with pytest.raises(ValueError, match="segments"):
        _parse_script_output(json.dumps(bad))


def test_parse_rejects_segments_wrong_order() -> None:
    bad = {
        **VALID_OUTPUT,
        "segments": [
            "outro",
            "intro",
            "core_debate",
            "developer_deep_dive",
            "technical_appreciation",
            "hiring_manager",
        ],
    }
    with pytest.raises(ValueError, match="segments"):
        _parse_script_output(json.dumps(bad))


def test_parse_accepts_text_at_4999_characters() -> None:
    # Build a valid script text of exactly 4999 characters
    line = "**Hype:** " + "x" * 70 + "\n"  # 81 chars per line
    num_lines = 4999 // len(line)
    remainder = 4999 - (num_lines * len(line))
    text = line * num_lines + "**Hype:** " + "x" * (remainder - len("**Hype:** "))
    assert len(text) == 4999
    output = {**VALID_OUTPUT, "text": text, "character_count": 4999}
    result = _parse_script_output(json.dumps(output))
    assert result["character_count"] == 4999


def test_parse_rejects_text_at_5000_characters() -> None:
    line = "**Hype:** " + "x" * 70 + "\n"
    num_lines = 5000 // len(line)
    remainder = 5000 - (num_lines * len(line))
    text = line * num_lines + "**Hype:** " + "x" * (remainder - len("**Hype:** "))
    assert len(text) == 5000
    bad = {**VALID_OUTPUT, "text": text, "character_count": 5000}
    with pytest.raises(ValueError, match="character_count"):
        _parse_script_output(json.dumps(bad))


# --- User Message Building Tests ---


def test_build_user_message_includes_discovery_data(
    pipeline_metadata: dict,
    sample_discovery_output: dict,
    sample_research_output: dict,
) -> None:
    event = {
        "metadata": pipeline_metadata,
        "discovery": sample_discovery_output,
        "research": sample_research_output,
    }
    msg = _build_user_message(event)
    assert "testrepo" in msg
    assert "Python" in msg
    assert "Clean architecture" in msg


def test_build_user_message_includes_research_data(
    pipeline_metadata: dict,
    sample_discovery_output: dict,
    sample_research_output: dict,
) -> None:
    event = {
        "metadata": pipeline_metadata,
        "discovery": sample_discovery_output,
        "research": sample_research_output,
    }
    msg = _build_user_message(event)
    assert "Test User" in msg
    assert "Strong fundamentals" in msg
    assert "Built a custom ORM" in msg


def test_build_user_message_includes_attempt_number(
    pipeline_metadata: dict,
    sample_discovery_output: dict,
    sample_research_output: dict,
) -> None:
    event = {
        "metadata": pipeline_metadata,
        "discovery": sample_discovery_output,
        "research": sample_research_output,
    }
    msg = _build_user_message(event)
    assert "attempt 1" in msg.lower()


def test_build_user_message_omits_feedback_on_first_attempt(
    pipeline_metadata: dict,
    sample_discovery_output: dict,
    sample_research_output: dict,
) -> None:
    event = {
        "metadata": pipeline_metadata,
        "discovery": sample_discovery_output,
        "research": sample_research_output,
    }
    msg = _build_user_message(event)
    assert "Producer Feedback" not in msg


def test_build_user_message_includes_feedback_on_retry(
    sample_discovery_output: dict,
    sample_research_output: dict,
    producer_feedback_for_retry: dict,
) -> None:
    event = {
        "metadata": {
            "execution_id": "arn:aws:states:us-east-1:123456789:execution:zerostars-pipeline:test-run",
            "script_attempt": 2,
        },
        "discovery": sample_discovery_output,
        "research": sample_research_output,
        "producer": producer_feedback_for_retry,
    }
    msg = _build_user_message(event)
    assert "Producer Feedback" in msg
    assert "hiring manager segment is too generic" in msg.lower()


def test_build_user_message_includes_all_issues(
    sample_discovery_output: dict,
    sample_research_output: dict,
    producer_feedback_for_retry: dict,
) -> None:
    event = {
        "metadata": {
            "execution_id": "arn:aws:states:us-east-1:123456789:execution:zerostars-pipeline:test-run",
            "script_attempt": 2,
        },
        "discovery": sample_discovery_output,
        "research": sample_research_output,
        "producer": producer_feedback_for_retry,
    }
    msg = _build_user_message(event)
    for issue in producer_feedback_for_retry["issues"]:
        assert issue in msg


# --- Full Handler Tests ---

VALID_HANDLER_OUTPUT = json.dumps(VALID_OUTPUT)


def test_handler_returns_valid_output(
    pipeline_metadata: dict,
    lambda_context: object,
    mock_script_invoke_model: object,
    sample_discovery_output: dict,
    sample_research_output: dict,
) -> None:
    mock_script_invoke_model.return_value = VALID_HANDLER_OUTPUT  # type: ignore[union-attr]
    with patch("lambdas.script.handler._load_system_prompt", return_value="sp"):
        from lambdas.script.handler import lambda_handler

        result = lambda_handler(
            {
                "metadata": pipeline_metadata,
                "discovery": sample_discovery_output,
                "research": sample_research_output,
            },
            lambda_context,
        )
    assert result["featured_repo"] == "testrepo"
    assert isinstance(result["character_count"], int)
    assert result["character_count"] < 5000


def test_handler_calls_invoke_model_not_invoke_with_tools(
    pipeline_metadata: dict,
    lambda_context: object,
    mock_script_invoke_model: object,
    sample_discovery_output: dict,
    sample_research_output: dict,
) -> None:
    mock_script_invoke_model.return_value = VALID_HANDLER_OUTPUT  # type: ignore[union-attr]
    with patch("lambdas.script.handler._load_system_prompt", return_value="sp"):
        from lambdas.script.handler import lambda_handler

        lambda_handler(
            {
                "metadata": pipeline_metadata,
                "discovery": sample_discovery_output,
                "research": sample_research_output,
            },
            lambda_context,
        )
    mock_script_invoke_model.assert_called_once()  # type: ignore[union-attr]
    call_kwargs = mock_script_invoke_model.call_args  # type: ignore[union-attr]
    # invoke_model takes user_message and system_prompt, NOT tools or tool_executor
    assert "tools" not in (call_kwargs.kwargs or {})
    assert "tool_executor" not in (call_kwargs.kwargs or {})


def test_handler_user_message_contains_discovery_data(
    pipeline_metadata: dict,
    lambda_context: object,
    mock_script_invoke_model: object,
    sample_discovery_output: dict,
    sample_research_output: dict,
) -> None:
    mock_script_invoke_model.return_value = VALID_HANDLER_OUTPUT  # type: ignore[union-attr]
    with patch("lambdas.script.handler._load_system_prompt", return_value="sp"):
        from lambdas.script.handler import lambda_handler

        lambda_handler(
            {
                "metadata": pipeline_metadata,
                "discovery": sample_discovery_output,
                "research": sample_research_output,
            },
            lambda_context,
        )
    user_message = mock_script_invoke_model.call_args[1].get(  # type: ignore[union-attr]
        "user_message", mock_script_invoke_model.call_args[0][0]  # type: ignore[union-attr]
    )
    assert "testrepo" in user_message
    assert "Python" in user_message


def test_handler_user_message_contains_research_data(
    pipeline_metadata: dict,
    lambda_context: object,
    mock_script_invoke_model: object,
    sample_discovery_output: dict,
    sample_research_output: dict,
) -> None:
    mock_script_invoke_model.return_value = VALID_HANDLER_OUTPUT  # type: ignore[union-attr]
    with patch("lambdas.script.handler._load_system_prompt", return_value="sp"):
        from lambdas.script.handler import lambda_handler

        lambda_handler(
            {
                "metadata": pipeline_metadata,
                "discovery": sample_discovery_output,
                "research": sample_research_output,
            },
            lambda_context,
        )
    user_message = mock_script_invoke_model.call_args[1].get(  # type: ignore[union-attr]
        "user_message", mock_script_invoke_model.call_args[0][0]  # type: ignore[union-attr]
    )
    assert "Test User" in user_message
    assert "Built a custom ORM" in user_message


def test_handler_first_attempt_no_feedback_in_message(
    pipeline_metadata: dict,
    lambda_context: object,
    mock_script_invoke_model: object,
    sample_discovery_output: dict,
    sample_research_output: dict,
) -> None:
    mock_script_invoke_model.return_value = VALID_HANDLER_OUTPUT  # type: ignore[union-attr]
    with patch("lambdas.script.handler._load_system_prompt", return_value="sp"):
        from lambdas.script.handler import lambda_handler

        lambda_handler(
            {
                "metadata": pipeline_metadata,
                "discovery": sample_discovery_output,
                "research": sample_research_output,
            },
            lambda_context,
        )
    user_message = mock_script_invoke_model.call_args[1].get(  # type: ignore[union-attr]
        "user_message", mock_script_invoke_model.call_args[0][0]  # type: ignore[union-attr]
    )
    assert "Producer Feedback" not in user_message


def test_handler_retry_includes_producer_feedback(
    lambda_context: object,
    mock_script_invoke_model: object,
    sample_discovery_output: dict,
    sample_research_output: dict,
    producer_feedback_for_retry: dict,
) -> None:
    mock_script_invoke_model.return_value = VALID_HANDLER_OUTPUT  # type: ignore[union-attr]
    retry_metadata = {
        "execution_id": "arn:aws:states:us-east-1:123456789:execution:zerostars-pipeline:test-run",
        "script_attempt": 2,
    }
    with patch("lambdas.script.handler._load_system_prompt", return_value="sp"):
        from lambdas.script.handler import lambda_handler

        lambda_handler(
            {
                "metadata": retry_metadata,
                "discovery": sample_discovery_output,
                "research": sample_research_output,
                "producer": producer_feedback_for_retry,
            },
            lambda_context,
        )
    user_message = mock_script_invoke_model.call_args[1].get(  # type: ignore[union-attr]
        "user_message", mock_script_invoke_model.call_args[0][0]  # type: ignore[union-attr]
    )
    assert "Producer Feedback" in user_message
    assert "hiring manager segment is too generic" in user_message.lower()
    for issue in producer_feedback_for_retry["issues"]:
        assert issue in user_message


def test_handler_handles_fenced_output(
    pipeline_metadata: dict,
    lambda_context: object,
    mock_script_invoke_model: object,
    sample_discovery_output: dict,
    sample_research_output: dict,
) -> None:
    mock_script_invoke_model.return_value = f"```json\n{VALID_HANDLER_OUTPUT}\n```"  # type: ignore[union-attr]
    with patch("lambdas.script.handler._load_system_prompt", return_value="sp"):
        from lambdas.script.handler import lambda_handler

        result = lambda_handler(
            {
                "metadata": pipeline_metadata,
                "discovery": sample_discovery_output,
                "research": sample_research_output,
            },
            lambda_context,
        )
    assert result["featured_repo"] == "testrepo"


def test_handler_raises_on_character_count_exceeded(
    pipeline_metadata: dict,
    lambda_context: object,
    mock_script_invoke_model: object,
    sample_discovery_output: dict,
    sample_research_output: dict,
) -> None:
    long_text = "**Hype:** " + "x" * 4991  # > 5000 chars
    bad_output = {**VALID_OUTPUT, "text": long_text, "character_count": len(long_text)}
    mock_script_invoke_model.return_value = json.dumps(bad_output)  # type: ignore[union-attr]
    with patch("lambdas.script.handler._load_system_prompt", return_value="sp"):
        from lambdas.script.handler import lambda_handler

        with pytest.raises(ValueError, match="character_count"):
            lambda_handler(
                {
                    "metadata": pipeline_metadata,
                    "discovery": sample_discovery_output,
                    "research": sample_research_output,
                },
                lambda_context,
            )


def test_handler_raises_on_invalid_json_from_model(
    pipeline_metadata: dict,
    lambda_context: object,
    mock_script_invoke_model: object,
    sample_discovery_output: dict,
    sample_research_output: dict,
) -> None:
    mock_script_invoke_model.return_value = (  # type: ignore[union-attr]
        "I cannot write a script because the project is too boring."
    )
    with patch("lambdas.script.handler._load_system_prompt", return_value="sp"):
        from lambdas.script.handler import lambda_handler

        with pytest.raises((ValueError, json.JSONDecodeError)):
            lambda_handler(
                {
                    "metadata": pipeline_metadata,
                    "discovery": sample_discovery_output,
                    "research": sample_research_output,
                },
                lambda_context,
            )


def test_handler_raises_on_bedrock_error(
    pipeline_metadata: dict,
    lambda_context: object,
    mock_script_invoke_model: object,
    sample_discovery_output: dict,
    sample_research_output: dict,
) -> None:
    mock_script_invoke_model.side_effect = RuntimeError("Bedrock throttled")  # type: ignore[union-attr]
    with patch("lambdas.script.handler._load_system_prompt", return_value="sp"):
        from lambdas.script.handler import lambda_handler

        with pytest.raises(RuntimeError, match="Bedrock"):
            lambda_handler(
                {
                    "metadata": pipeline_metadata,
                    "discovery": sample_discovery_output,
                    "research": sample_research_output,
                },
                lambda_context,
            )
