from __future__ import annotations

import json
import os
import time
from collections.abc import Callable
from typing import Any, Literal

import boto3
import botocore.exceptions

# ToolDefinition and ToolExecutor are exported so handler code can annotate callbacks.
# dict[str, Any] is used because input_schema has recursive JSON Schema structure.
ToolDefinition = dict[str, Any]
ToolExecutor = Callable[[str, dict[str, Any]], str]

DEFAULT_MODEL_ID: str = os.environ.get("BEDROCK_MODEL_ID", "us.anthropic.claude-sonnet-4-6")
MAX_TOKENS: int = 16384  # room for adaptive thinking at medium/high effort

# Effort levels for Sonnet 4.6. "high" for agentic multi-turn (Discovery,
# Research); "medium" for single-turn (Script, Producer).
Effort = Literal["low", "medium", "high", "max"]
DEFAULT_EFFORT_AGENTIC: Effort = "high"
DEFAULT_EFFORT_SINGLE_TURN: Effort = "medium"


def _get_bedrock_client() -> Any:
    """Return a boto3 bedrock-runtime client."""
    return boto3.client("bedrock-runtime")


def _invoke_with_retry(body: dict[str, Any], model_id: str) -> dict[str, Any]:
    """Call bedrock invoke_model with exponential backoff on ThrottlingException.

    3 retries, 1s base delay, 2x factor, no jitter. On exhaustion, propagates
    the final ThrottlingException to the caller (Step Functions handles retries
    at the state machine level).
    """
    client = _get_bedrock_client()
    last_exc: botocore.exceptions.ClientError | None = None
    for attempt in range(4):  # 1 initial attempt + 3 retries
        try:
            response = client.invoke_model(
                modelId=model_id,
                contentType="application/json",
                accept="application/json",
                body=json.dumps(body),
            )
            result: dict[str, Any] = json.loads(response["body"].read())
            return result
        except botocore.exceptions.ClientError as exc:
            if exc.response["Error"]["Code"] == "ThrottlingException":
                last_exc = exc
                if attempt < 3:
                    time.sleep(1 * (2**attempt))
                continue
            raise
    # Exhausted retries — propagate the last throttling exception
    assert last_exc is not None
    raise last_exc


def _extract_text(content: list[dict[str, Any]]) -> str:
    """Extract the last text block from a Bedrock response content array.

    With adaptive thinking enabled, the content may include thinking blocks
    before the text block. We take the last text block as the model's response.
    """
    return str(next(b["text"] for b in reversed(content) if b["type"] == "text"))


def invoke_model(
    user_message: str,
    system_prompt: str,
    model_id: str = DEFAULT_MODEL_ID,
    max_tokens: int = MAX_TOKENS,
    effort: Effort = DEFAULT_EFFORT_SINGLE_TURN,
) -> str:
    """Single-turn Bedrock invocation via the Anthropic Messages API.

    Uses adaptive thinking with output_config.effort to control reasoning depth.
    Handles ThrottlingException with exponential backoff (3 retries, 1s base, 2x factor).
    Returns the text content of the model's response.
    """
    body: dict[str, Any] = {
        "anthropic_version": "bedrock-2023-05-31",
        "max_tokens": max_tokens,
        "thinking": {"type": "adaptive"},
        "output_config": {"effort": effort},
        "system": system_prompt,
        "messages": [{"role": "user", "content": user_message}],
    }
    result = _invoke_with_retry(body, model_id)
    return _extract_text(result["content"])


def invoke_with_tools(
    user_message: str,
    system_prompt: str,
    tools: list[ToolDefinition],
    tool_executor: ToolExecutor,
    model_id: str = DEFAULT_MODEL_ID,
    max_tokens: int = MAX_TOKENS,
    max_turns: int = 25,
    effort: Effort = DEFAULT_EFFORT_AGENTIC,
) -> str:
    """Multi-turn agentic loop using the Anthropic Messages API with tool use.

    NOTE: The task spec says "converse API" but Bedrock's converse API does not
    support adaptive thinking or output_config.effort. This uses invoke_model
    with the Messages API body, which matches the external-api-contracts.md spec.

    Loop:
      1. Invoke Bedrock with tools defined in the request body.
      2. If stop_reason == "tool_use": extract all tool_use blocks, call
         tool_executor(name, input) -> JSON string for each, append results,
         re-invoke.
      3. If stop_reason == "end_turn": return the text response.
      4. If max_turns is reached without end_turn, raise RuntimeError.

    ThrottlingException is retried per _invoke_with_retry on each individual call.
    """
    messages: list[dict[str, Any]] = [{"role": "user", "content": user_message}]

    for turn in range(max_turns):
        body: dict[str, Any] = {
            "anthropic_version": "bedrock-2023-05-31",
            "max_tokens": max_tokens,
            "thinking": {"type": "adaptive"},
            "output_config": {"effort": effort},
            "system": system_prompt,
            "messages": messages,
            "tools": tools,
        }
        result = _invoke_with_retry(body, model_id)
        stop_reason: str = result["stop_reason"]
        content: list[dict[str, Any]] = result["content"]

        # Append the assistant's response (may include thinking, text, tool_use blocks)
        messages.append({"role": "assistant", "content": content})

        if stop_reason == "end_turn":
            return _extract_text(content)

        if stop_reason == "tool_use":
            # Collect all tool_use blocks and execute them
            tool_results: list[dict[str, Any]] = []
            for block in content:
                if block["type"] == "tool_use":
                    tool_result = tool_executor(block["name"], block["input"])
                    tool_results.append(
                        {
                            "type": "tool_result",
                            "tool_use_id": block["id"],
                            "content": tool_result,
                        }
                    )
            messages.append({"role": "user", "content": tool_results})
            continue

        # Unexpected stop_reason — treat remaining content as final text if possible
        return _extract_text(content)

    raise RuntimeError(f"invoke_with_tools exceeded max_turns={max_turns}")
