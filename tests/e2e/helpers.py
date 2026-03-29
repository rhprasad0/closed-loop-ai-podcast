"""E2E test helpers — polling, assertions, and MCP invocation utilities."""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from typing import Any

from botocore.exceptions import ClientError

# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class PipelineExecutionResult:
    """Immutable result of a completed (or failed) pipeline execution."""

    execution_arn: str
    status: str  # SUCCEEDED, FAILED, TIMED_OUT, ABORTED
    final_state: dict[str, Any]  # parsed output (SUCCEEDED) or input (other)
    duration_seconds: float


# ---------------------------------------------------------------------------
# Step Functions helpers
# ---------------------------------------------------------------------------


def poll_execution(
    sfn_client: Any,
    execution_arn: str,
    *,
    timeout: int = 900,
    interval: int = 15,
) -> PipelineExecutionResult:
    """Poll describe_execution until the execution reaches a terminal state.

    Returns a PipelineExecutionResult with the final status and parsed state.
    Raises TimeoutError if the execution does not complete within timeout seconds.
    """
    start = time.monotonic()

    while True:
        resp = sfn_client.describe_execution(executionArn=execution_arn)
        status: str = resp["status"]

        if status not in ("RUNNING",):
            elapsed = time.monotonic() - start
            final_state = _parse_execution_state(resp)
            return PipelineExecutionResult(
                execution_arn=execution_arn,
                status=status,
                final_state=final_state,
                duration_seconds=elapsed,
            )

        if time.monotonic() - start > timeout:
            raise TimeoutError(
                f"Execution {execution_arn} still RUNNING after {timeout}s"
            )

        time.sleep(interval)


def _parse_execution_state(describe_resp: dict[str, Any]) -> dict[str, Any]:
    """Extract the pipeline state dict from a describe_execution response.

    For SUCCEEDED executions, the accumulated state is in the 'output' field.
    For all other terminal states, 'output' is null — fall back to 'input'.
    """
    raw: str | None = describe_resp.get("output") or describe_resp.get("input")
    if raw:
        try:
            return json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            return {}
    return {}


def get_final_state(sfn_client: Any, execution_arn: str) -> dict[str, Any]:
    """Fetch and parse the final state of a completed execution."""
    resp = sfn_client.describe_execution(executionArn=execution_arn)
    return _parse_execution_state(resp)


def get_step_history(sfn_client: Any, execution_arn: str) -> list[dict[str, Any]]:
    """Return the ordered list of state transitions for an execution.

    Paginates through get_execution_history and extracts TaskStateEntered /
    TaskStateExited events with timing information.
    """
    events: list[dict[str, Any]] = []
    paginator = sfn_client.get_paginator("get_execution_history")

    for page in paginator.paginate(
        executionArn=execution_arn,
        includeExecutionData=False,
    ):
        for event in page.get("events", []):
            event_type: str = event.get("type", "")

            # Extract state name from the appropriate detail key
            detail_key = None
            if "stateEnteredEventDetails" in event:
                detail_key = "stateEnteredEventDetails"
            elif "stateExitedEventDetails" in event:
                detail_key = "stateExitedEventDetails"

            if detail_key:
                events.append(
                    {
                        "type": event_type,
                        "state_name": event[detail_key].get("name", ""),
                        "timestamp": event.get("timestamp"),
                    }
                )

    return events


# ---------------------------------------------------------------------------
# S3 helpers
# ---------------------------------------------------------------------------


def assert_s3_exists(
    s3_client: Any,
    bucket: str,
    key: str,
) -> dict[str, Any]:
    """Assert that an S3 object exists and return its metadata.

    Raises AssertionError with a clear message if the object does not exist.
    """
    try:
        return s3_client.head_object(Bucket=bucket, Key=key)
    except ClientError as exc:
        code = exc.response.get("Error", {}).get("Code", "")
        raise AssertionError(f"S3 object s3://{bucket}/{key} does not exist ({code})")


# ---------------------------------------------------------------------------
# Database helpers
# ---------------------------------------------------------------------------


def db_query(sql: str, params: tuple[Any, ...] | None = None) -> list[tuple[Any, ...]]:
    """Execute a read-only SQL query via the shared db module.

    Thin wrapper so e2e tests don't import shared.db directly everywhere.
    """
    from shared.db import query

    return query(sql, params)


# ---------------------------------------------------------------------------
# MCP Lambda invocation helpers
# ---------------------------------------------------------------------------


def invoke_mcp_tool(
    lambda_client: Any,
    function_name: str,
    tool_name: str,
    arguments: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Invoke an MCP tool on the deployed MCP Lambda via boto3 lambda.invoke().

    Constructs a Lambda Function URL payload v2 event with an MCP JSON-RPC
    body, invokes the Lambda synchronously, and parses the tool result.

    The MCP Streamable HTTP transport (stateless mode) requires an initialize
    handshake before tool calls. This helper sends initialize → initialized →
    tools/call as separate invocations since each Lambda invocation creates a
    fresh server instance.

    For stateless Streamable HTTP, we attempt the tool call directly first.
    If the server requires initialization, we fall back to a multi-step flow.
    """
    # Build the tools/call JSON-RPC request
    jsonrpc_body = json.dumps(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {
                "name": tool_name,
                "arguments": arguments or {},
            },
        }
    )

    # Try with initialization first (MCP protocol requires it)
    init_result = _invoke_mcp_jsonrpc(
        lambda_client,
        function_name,
        method="initialize",
        params={
            "protocolVersion": "2025-03-26",
            "capabilities": {},
            "clientInfo": {"name": "e2e-test", "version": "1.0.0"},
        },
        rpc_id=0,
    )

    # If initialization succeeded, send the tool call
    # Note: each Lambda invocation creates a fresh server, so we need to send
    # initialize + tool call in the same conceptual session. Since Streamable
    # HTTP is stateless, the server should accept tool calls without prior init.
    # We try the tool call directly.
    result = _invoke_mcp_raw(lambda_client, function_name, jsonrpc_body)
    return result


def _invoke_mcp_jsonrpc(
    lambda_client: Any,
    function_name: str,
    *,
    method: str,
    params: dict[str, Any],
    rpc_id: int,
) -> dict[str, Any]:
    """Send a single MCP JSON-RPC request to the Lambda."""
    body = json.dumps(
        {
            "jsonrpc": "2.0",
            "id": rpc_id,
            "method": method,
            "params": params,
        }
    )
    return _invoke_mcp_raw(lambda_client, function_name, body)


def _invoke_mcp_raw(
    lambda_client: Any,
    function_name: str,
    body: str,
) -> dict[str, Any]:
    """Invoke the MCP Lambda with a raw JSON-RPC body string.

    Constructs a Lambda Function URL v2 event and invokes synchronously.
    Returns the parsed JSON-RPC response body.
    """
    # Lambda Function URL payload format v2
    event = {
        "version": "2.0",
        "rawPath": "/mcp",
        "rawQueryString": "",
        "headers": {
            "content-type": "application/json",
            "accept": "application/json, text/event-stream",
        },
        "requestContext": {
            "http": {
                "method": "POST",
                "path": "/mcp",
            },
        },
        "body": body,
        "isBase64Encoded": False,
    }

    resp = lambda_client.invoke(
        FunctionName=function_name,
        InvocationType="RequestResponse",
        Payload=json.dumps(event),
    )

    # Check for Lambda-level errors
    if resp.get("FunctionError"):
        payload = json.loads(resp["Payload"].read())
        raise RuntimeError(
            f"MCP Lambda error: {payload.get('errorMessage', payload)}"
        )

    # Parse the Lambda response — it returns {statusCode, headers, body}
    lambda_response = json.loads(resp["Payload"].read())
    status_code = lambda_response.get("statusCode", 0)

    if status_code >= 400:
        raise RuntimeError(
            f"MCP Lambda returned {status_code}: {lambda_response.get('body', '')}"
        )

    # Parse the JSON-RPC response from the body
    resp_body: str = lambda_response.get("body", "")
    if not resp_body:
        return {}

    # Handle SSE format (text/event-stream) — extract JSON from data lines
    if resp_body.startswith("event:") or resp_body.startswith("data:"):
        return _parse_sse_response(resp_body)

    try:
        return json.loads(resp_body)
    except json.JSONDecodeError:
        return {"raw": resp_body}


def _parse_sse_response(sse_text: str) -> dict[str, Any]:
    """Parse Server-Sent Events response and extract JSON-RPC result.

    MCP Streamable HTTP may return responses as SSE events:
        event: message
        data: {"jsonrpc": "2.0", "id": 1, "result": {...}}
    """
    result: dict[str, Any] = {}
    for line in sse_text.split("\n"):
        line = line.strip()
        if line.startswith("data:"):
            data_str = line[len("data:"):].strip()
            try:
                parsed = json.loads(data_str)
                # Prefer the last message with a result
                if "result" in parsed:
                    result = parsed["result"]
                elif "error" in parsed:
                    raise RuntimeError(f"MCP tool error: {parsed['error']}")
                else:
                    result = parsed
            except json.JSONDecodeError:
                continue
    return result
