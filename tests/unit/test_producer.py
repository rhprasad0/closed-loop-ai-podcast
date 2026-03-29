from __future__ import annotations

import json
from unittest.mock import patch

import pytest

from lambdas.producer.handler import _build_user_message, _parse_producer_output

# ---------------------------------------------------------------------------
# Module-level constants shared across sections
# ---------------------------------------------------------------------------

VALID_PASS_OUTPUT = {
    "verdict": "PASS",
    "score": 8,
    "notes": "Strong character voices, specific jokes. Hiring segment references actual repos.",
}

VALID_FAIL_OUTPUT = {
    "verdict": "FAIL",
    "score": 4,
    "feedback": (
        "The hiring manager segment uses generic praise instead of specific observations. "
        "Rewrite Roast's line in segment 5 to reference a specific repo by name."
    ),
    "issues": [
        "Hiring segment uses generic praise instead of specific observations",
        "Roast's grudging compliment does not reference a specific technical decision",
    ],
}


# Note: The exact SQL of BENCHMARK_QUERY is not asserted in unit tests because
# the query text is an implementation detail. Integration tests (test_db_live.py)
# verify the JOIN works against real Postgres with actual episode_metrics data.

VALID_PASS_HANDLER_OUTPUT = json.dumps(
    {
        "verdict": "PASS",
        "score": 8,
        "notes": "Strong character voices, specific jokes about testrepo.",
    }
)

VALID_FAIL_HANDLER_OUTPUT = json.dumps(
    {
        "verdict": "FAIL",
        "score": 4,
        "feedback": "The hiring segment uses generic praise. Reference specific repos.",
        "issues": [
            "Hiring segment uses generic praise",
            "Roast's compliment is too vague",
        ],
    }
)


# ---------------------------------------------------------------------------
# Output Parsing Tests
# ---------------------------------------------------------------------------


def test_parse_valid_pass_json() -> None:
    result = _parse_producer_output(json.dumps(VALID_PASS_OUTPUT))
    assert result["verdict"] == "PASS"
    assert result["score"] == 8
    assert result["notes"] == VALID_PASS_OUTPUT["notes"]


def test_parse_valid_fail_json() -> None:
    result = _parse_producer_output(json.dumps(VALID_FAIL_OUTPUT))
    assert result["verdict"] == "FAIL"
    assert result["score"] == 4
    assert "hiring" in result["feedback"].lower()
    assert len(result["issues"]) == 2


def test_parse_fenced_json() -> None:
    fenced = f"```json\n{json.dumps(VALID_PASS_OUTPUT)}\n```"
    result = _parse_producer_output(fenced)
    assert result["verdict"] == "PASS"


def test_parse_fenced_no_language_tag() -> None:
    fenced = f"```\n{json.dumps(VALID_PASS_OUTPUT)}\n```"
    result = _parse_producer_output(fenced)
    assert result["verdict"] == "PASS"


def test_parse_rejects_missing_verdict() -> None:
    incomplete = {"score": 8, "notes": "Good script."}
    with pytest.raises(ValueError, match="verdict"):
        _parse_producer_output(json.dumps(incomplete))


def test_parse_rejects_missing_score() -> None:
    incomplete = {"verdict": "PASS", "notes": "Good script."}
    with pytest.raises(ValueError, match="score"):
        _parse_producer_output(json.dumps(incomplete))


def test_parse_rejects_invalid_verdict_value() -> None:
    bad = {**VALID_PASS_OUTPUT, "verdict": "MAYBE"}
    with pytest.raises(ValueError, match="verdict"):
        _parse_producer_output(json.dumps(bad))


def test_parse_rejects_fail_missing_feedback() -> None:
    bad = {"verdict": "FAIL", "score": 4, "issues": ["issue 1"]}
    with pytest.raises(ValueError, match="feedback"):
        _parse_producer_output(json.dumps(bad))


def test_parse_rejects_fail_missing_issues() -> None:
    bad = {"verdict": "FAIL", "score": 4, "feedback": "Fix the hiring segment."}
    with pytest.raises(ValueError, match="issues"):
        _parse_producer_output(json.dumps(bad))


def test_parse_pass_with_notes_accepted() -> None:
    result = _parse_producer_output(json.dumps(VALID_PASS_OUTPUT))
    assert "notes" in result
    assert isinstance(result["notes"], str)


def test_parse_pass_without_notes_accepted() -> None:
    minimal = {"verdict": "PASS", "score": 7}
    result = _parse_producer_output(json.dumps(minimal))
    assert result["verdict"] == "PASS"
    assert result["score"] == 7


def test_parse_coerces_string_score_to_int() -> None:
    coerced = {**VALID_PASS_OUTPUT, "score": "8"}
    result = _parse_producer_output(json.dumps(coerced))
    assert result["score"] == 8
    assert isinstance(result["score"], int)


def test_parse_rejects_score_out_of_range() -> None:
    too_low = {**VALID_PASS_OUTPUT, "score": 0}
    with pytest.raises(ValueError, match="score"):
        _parse_producer_output(json.dumps(too_low))
    too_high = {**VALID_PASS_OUTPUT, "score": 11}
    with pytest.raises(ValueError, match="score"):
        _parse_producer_output(json.dumps(too_high))


def test_parse_rejects_invalid_json() -> None:
    with pytest.raises((ValueError, json.JSONDecodeError)):
        _parse_producer_output("this is not json at all")


# ---------------------------------------------------------------------------
# User Message Building Tests
# ---------------------------------------------------------------------------


def test_build_user_message_includes_script_text(
    pipeline_metadata: dict,
    sample_discovery_output: dict,
    sample_research_output: dict,
    sample_script_output: dict,
) -> None:
    event = {
        "metadata": pipeline_metadata,
        "discovery": sample_discovery_output,
        "research": sample_research_output,
        "script": sample_script_output,
    }
    msg = _build_user_message(event, benchmarks=[])
    assert "Welcome to 0 Stars" in msg


def test_build_user_message_includes_character_count(
    pipeline_metadata: dict,
    sample_discovery_output: dict,
    sample_research_output: dict,
    sample_script_output: dict,
) -> None:
    event = {
        "metadata": pipeline_metadata,
        "discovery": sample_discovery_output,
        "research": sample_research_output,
        "script": sample_script_output,
    }
    msg = _build_user_message(event, benchmarks=[])
    assert str(sample_script_output["character_count"]) in msg


def test_build_user_message_includes_discovery_repo_name(
    pipeline_metadata: dict,
    sample_discovery_output: dict,
    sample_research_output: dict,
    sample_script_output: dict,
) -> None:
    event = {
        "metadata": pipeline_metadata,
        "discovery": sample_discovery_output,
        "research": sample_research_output,
        "script": sample_script_output,
    }
    msg = _build_user_message(event, benchmarks=[])
    assert "testrepo" in msg


def test_build_user_message_includes_discovery_repo_description(
    pipeline_metadata: dict,
    sample_discovery_output: dict,
    sample_research_output: dict,
    sample_script_output: dict,
) -> None:
    event = {
        "metadata": pipeline_metadata,
        "discovery": sample_discovery_output,
        "research": sample_research_output,
        "script": sample_script_output,
    }
    msg = _build_user_message(event, benchmarks=[])
    assert "A test repository" in msg


def test_build_user_message_includes_research_hiring_signals(
    pipeline_metadata: dict,
    sample_discovery_output: dict,
    sample_research_output: dict,
    sample_script_output: dict,
) -> None:
    event = {
        "metadata": pipeline_metadata,
        "discovery": sample_discovery_output,
        "research": sample_research_output,
        "script": sample_script_output,
    }
    msg = _build_user_message(event, benchmarks=[])
    assert "Strong fundamentals" in msg


def test_build_user_message_includes_benchmark_scripts(
    pipeline_metadata: dict,
    sample_discovery_output: dict,
    sample_research_output: dict,
    sample_script_output: dict,
    sample_benchmark_scripts: list[tuple[str]],
) -> None:
    benchmarks = [row[0] for row in sample_benchmark_scripts]
    event = {
        "metadata": pipeline_metadata,
        "discovery": sample_discovery_output,
        "research": sample_research_output,
        "script": sample_script_output,
    }
    msg = _build_user_message(event, benchmarks=benchmarks)
    assert "pasta-sorter" in msg
    assert "Benchmark" in msg


def test_build_user_message_handles_no_benchmarks(
    pipeline_metadata: dict,
    sample_discovery_output: dict,
    sample_research_output: dict,
    sample_script_output: dict,
) -> None:
    event = {
        "metadata": pipeline_metadata,
        "discovery": sample_discovery_output,
        "research": sample_research_output,
        "script": sample_script_output,
    }
    msg = _build_user_message(event, benchmarks=[])
    assert "Benchmark" not in msg or "no benchmark" in msg.lower()


# ---------------------------------------------------------------------------
# Full Handler Tests
# ---------------------------------------------------------------------------


def test_handler_returns_valid_pass_output(
    pipeline_metadata: dict,
    lambda_context: object,
    mock_producer_invoke_model: object,
    mock_producer_db_query: object,
    sample_discovery_output: dict,
    sample_research_output: dict,
    sample_script_output: dict,
) -> None:
    mock_producer_invoke_model.return_value = VALID_PASS_HANDLER_OUTPUT  # type: ignore[union-attr]
    with patch("lambdas.producer.handler._load_system_prompt", return_value="sp"):
        from lambdas.producer.handler import lambda_handler

        result = lambda_handler(
            {
                "metadata": pipeline_metadata,
                "discovery": sample_discovery_output,
                "research": sample_research_output,
                "script": sample_script_output,
            },
            lambda_context,
        )
    assert result["verdict"] == "PASS"
    assert isinstance(result["score"], int)
    assert result["score"] == 8


def test_handler_returns_valid_fail_output(
    pipeline_metadata: dict,
    lambda_context: object,
    mock_producer_invoke_model: object,
    mock_producer_db_query: object,
    sample_discovery_output: dict,
    sample_research_output: dict,
    sample_script_output: dict,
) -> None:
    mock_producer_invoke_model.return_value = VALID_FAIL_HANDLER_OUTPUT  # type: ignore[union-attr]
    with patch("lambdas.producer.handler._load_system_prompt", return_value="sp"):
        from lambdas.producer.handler import lambda_handler

        result = lambda_handler(
            {
                "metadata": pipeline_metadata,
                "discovery": sample_discovery_output,
                "research": sample_research_output,
                "script": sample_script_output,
            },
            lambda_context,
        )
    assert result["verdict"] == "FAIL"
    assert isinstance(result["score"], int)
    assert "feedback" in result
    assert "issues" in result
    assert isinstance(result["issues"], list)
    assert len(result["issues"]) >= 1


def test_handler_calls_invoke_model_not_invoke_with_tools(
    pipeline_metadata: dict,
    lambda_context: object,
    mock_producer_invoke_model: object,
    mock_producer_db_query: object,
    sample_discovery_output: dict,
    sample_research_output: dict,
    sample_script_output: dict,
) -> None:
    mock_producer_invoke_model.return_value = VALID_PASS_HANDLER_OUTPUT  # type: ignore[union-attr]
    with patch("lambdas.producer.handler._load_system_prompt", return_value="sp"):
        from lambdas.producer.handler import lambda_handler

        lambda_handler(
            {
                "metadata": pipeline_metadata,
                "discovery": sample_discovery_output,
                "research": sample_research_output,
                "script": sample_script_output,
            },
            lambda_context,
        )
    mock_producer_invoke_model.assert_called_once()  # type: ignore[union-attr]
    call_kwargs = mock_producer_invoke_model.call_args  # type: ignore[union-attr]
    # invoke_model takes user_message and system_prompt, NOT tools or tool_executor
    assert "tools" not in (call_kwargs.kwargs or {})
    assert "tool_executor" not in (call_kwargs.kwargs or {})


def test_handler_reads_script_discovery_research_from_event(
    pipeline_metadata: dict,
    lambda_context: object,
    mock_producer_invoke_model: object,
    mock_producer_db_query: object,
    sample_discovery_output: dict,
    sample_research_output: dict,
    sample_script_output: dict,
) -> None:
    mock_producer_invoke_model.return_value = VALID_PASS_HANDLER_OUTPUT  # type: ignore[union-attr]
    with patch("lambdas.producer.handler._load_system_prompt", return_value="sp"):
        from lambdas.producer.handler import lambda_handler

        lambda_handler(
            {
                "metadata": pipeline_metadata,
                "discovery": sample_discovery_output,
                "research": sample_research_output,
                "script": sample_script_output,
            },
            lambda_context,
        )
    user_message = mock_producer_invoke_model.call_args[1].get(  # type: ignore[union-attr]
        "user_message",
        mock_producer_invoke_model.call_args[0][0],  # type: ignore[union-attr]
    )
    # Script text
    assert "Welcome to 0 Stars" in user_message
    # Discovery data
    assert "testrepo" in user_message
    # Research data
    assert "Strong fundamentals" in user_message


def test_handler_queries_database_for_benchmark_scripts(
    pipeline_metadata: dict,
    lambda_context: object,
    mock_producer_invoke_model: object,
    mock_producer_db_query: object,
    sample_discovery_output: dict,
    sample_research_output: dict,
    sample_script_output: dict,
) -> None:
    mock_producer_invoke_model.return_value = VALID_PASS_HANDLER_OUTPUT  # type: ignore[union-attr]
    with patch("lambdas.producer.handler._load_system_prompt", return_value="sp"):
        from lambdas.producer.handler import lambda_handler

        lambda_handler(
            {
                "metadata": pipeline_metadata,
                "discovery": sample_discovery_output,
                "research": sample_research_output,
                "script": sample_script_output,
            },
            lambda_context,
        )
    mock_producer_db_query.assert_called_once()  # type: ignore[union-attr]
    # Note: _fetch_benchmark_scripts internally does [row[0] for row in rows]
    # to convert the query result tuples to a flat list of script_text strings.


def test_handler_handles_fenced_output(
    pipeline_metadata: dict,
    lambda_context: object,
    mock_producer_invoke_model: object,
    mock_producer_db_query: object,
    sample_discovery_output: dict,
    sample_research_output: dict,
    sample_script_output: dict,
) -> None:
    mock_producer_invoke_model.return_value = f"```json\n{VALID_PASS_HANDLER_OUTPUT}\n```"  # type: ignore[union-attr]
    with patch("lambdas.producer.handler._load_system_prompt", return_value="sp"):
        from lambdas.producer.handler import lambda_handler

        result = lambda_handler(
            {
                "metadata": pipeline_metadata,
                "discovery": sample_discovery_output,
                "research": sample_research_output,
                "script": sample_script_output,
            },
            lambda_context,
        )
    assert result["verdict"] == "PASS"


def test_handler_handles_empty_benchmark_results(
    pipeline_metadata: dict,
    lambda_context: object,
    mock_producer_invoke_model: object,
    mock_producer_db_query: object,
    sample_discovery_output: dict,
    sample_research_output: dict,
    sample_script_output: dict,
) -> None:
    mock_producer_db_query.return_value = []  # type: ignore[union-attr]  # no episodes exist yet
    mock_producer_invoke_model.return_value = VALID_PASS_HANDLER_OUTPUT  # type: ignore[union-attr]
    with patch("lambdas.producer.handler._load_system_prompt", return_value="sp"):
        from lambdas.producer.handler import lambda_handler

        result = lambda_handler(
            {
                "metadata": pipeline_metadata,
                "discovery": sample_discovery_output,
                "research": sample_research_output,
                "script": sample_script_output,
            },
            lambda_context,
        )
    assert result["verdict"] == "PASS"


def test_handler_survives_db_exception_in_benchmark_fetch(
    pipeline_metadata: dict,
    lambda_context: object,
    mock_producer_invoke_model: object,
    mock_producer_db_query: object,
    sample_discovery_output: dict,
    sample_research_output: dict,
    sample_script_output: dict,
) -> None:
    mock_producer_db_query.side_effect = Exception("connection refused")  # type: ignore[union-attr]
    mock_producer_invoke_model.return_value = VALID_PASS_HANDLER_OUTPUT  # type: ignore[union-attr]
    with patch("lambdas.producer.handler._load_system_prompt", return_value="sp"):
        from lambdas.producer.handler import lambda_handler

        result = lambda_handler(
            {
                "metadata": pipeline_metadata,
                "discovery": sample_discovery_output,
                "research": sample_research_output,
                "script": sample_script_output,
            },
            lambda_context,
        )
    # _fetch_benchmark_scripts catches DB exceptions and returns []
    assert result["verdict"] in ("PASS", "FAIL")


def test_handler_propagates_runtime_error_from_invoke_model(
    pipeline_metadata: dict,
    lambda_context: object,
    mock_producer_invoke_model: object,
    mock_producer_db_query: object,
    sample_discovery_output: dict,
    sample_research_output: dict,
    sample_script_output: dict,
) -> None:
    mock_producer_invoke_model.side_effect = RuntimeError("Bedrock throttled")  # type: ignore[union-attr]
    with patch("lambdas.producer.handler._load_system_prompt", return_value="sp"):
        from lambdas.producer.handler import lambda_handler

        with pytest.raises(RuntimeError, match="Bedrock"):
            lambda_handler(
                {
                    "metadata": pipeline_metadata,
                    "discovery": sample_discovery_output,
                    "research": sample_research_output,
                    "script": sample_script_output,
                },
                lambda_context,
            )
