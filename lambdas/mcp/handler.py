from __future__ import annotations

import asyncio
import base64
from typing import Any

from aws_lambda_powertools.utilities.typing import LambdaContext
from mcp.server.fastmcp import FastMCP

from shared.logging import get_logger
from shared.metrics import get_metrics
from shared.tracing import get_tracer

import resources as resources_module
from tools import agents as agents_tools
from tools import assets as assets_tools
from tools import data as data_tools
from tools import observation as observation_tools
from tools import pipeline as pipeline_tools
from tools import site as site_tools

logger = get_logger("mcp")
tracer = get_tracer("mcp")
metrics = get_metrics("mcp")


def create_mcp_server() -> FastMCP:
    """Create and configure the MCP server instance.

    Registers all 26 tools from the 6 tool modules and all 5 resources
    from resources.py. Returns a configured FastMCP instance.

    Tool registration uses FastMCP.add_tool() which introspects type annotations
    to build the MCP tool schema. Resource registration uses @server.resource().

    Note: the spec shows `Server` as the return type, but FastMCP is the correct
    class — it wraps the low-level Server and exposes the @server.tool() decorator
    pattern and list_tools() used by tests.
    """
    server = FastMCP(name="zerostars-mcp")

    # -- Pipeline control tools (5) --
    server.add_tool(pipeline_tools.start_pipeline)
    server.add_tool(pipeline_tools.stop_pipeline)
    server.add_tool(pipeline_tools.get_execution_status)
    server.add_tool(pipeline_tools.list_executions)
    server.add_tool(pipeline_tools.retry_from_step)

    # -- Agent invocation tools (7) --
    server.add_tool(agents_tools.invoke_discovery)
    server.add_tool(agents_tools.invoke_research)
    server.add_tool(agents_tools.invoke_script)
    server.add_tool(agents_tools.invoke_producer)
    server.add_tool(agents_tools.invoke_cover_art)
    server.add_tool(agents_tools.invoke_tts)
    server.add_tool(agents_tools.invoke_post_production)

    # -- Observation tools (3) --
    server.add_tool(observation_tools.get_agent_logs)
    server.add_tool(observation_tools.get_execution_history)
    server.add_tool(observation_tools.get_pipeline_health)

    # -- Data tools (6) --
    server.add_tool(data_tools.query_episodes)
    server.add_tool(data_tools.get_episode_detail)
    server.add_tool(data_tools.query_metrics)
    server.add_tool(data_tools.query_featured_developers)
    server.add_tool(data_tools.run_sql)
    server.add_tool(data_tools.upsert_metrics)

    # -- Asset tools (3) --
    server.add_tool(assets_tools.get_episode_assets)
    server.add_tool(assets_tools.list_s3_assets)
    server.add_tool(assets_tools.get_presigned_url)

    # -- Site tools (2) --
    server.add_tool(site_tools.invalidate_cache)
    server.add_tool(site_tools.get_site_status)

    # -- Resources (5) --
    # Inline wrappers delegate to resources.py handlers. This keeps resource.py
    # thin and ensures mock fixtures only need to patch the tool module paths.

    @server.resource("zerostars://episodes")
    async def episodes_resource() -> str:
        return await resources_module.read_episodes_resource()

    @server.resource("zerostars://episodes/{episode_id}")
    async def episode_detail_resource(episode_id: str) -> str:
        # URI template variables arrive as strings; convert to int for the handler.
        return await resources_module.read_episode_detail_resource(int(episode_id))

    @server.resource("zerostars://metrics")
    async def metrics_resource() -> str:
        return await resources_module.read_metrics_resource()

    @server.resource("zerostars://pipeline/status")
    async def pipeline_status_resource() -> str:
        return await resources_module.read_pipeline_status_resource()

    @server.resource("zerostars://featured-developers")
    async def featured_developers_resource() -> str:
        return await resources_module.read_featured_developers_resource()

    return server


async def _asgi_adapter(event: dict[str, Any], asgi_app: Any) -> dict[str, Any]:
    """Translate a Lambda Function URL event (payload v2) into an ASGI 3.0 call.

    Collects the ASGI response and returns it as a Lambda-compatible dict.
    Used to run the FastMCP Starlette app inside the synchronous lambda_handler.
    """
    raw_headers: dict[str, str] = event.get("headers") or {}
    asgi_headers: list[tuple[bytes, bytes]] = [
        (k.lower().encode(), v.encode()) for k, v in raw_headers.items()
    ]

    raw_body: str | bytes = event.get("body") or ""
    if event.get("isBase64Encoded"):
        body_bytes = base64.b64decode(raw_body)
    else:
        body_bytes = raw_body.encode() if isinstance(raw_body, str) else raw_body

    http_ctx: dict[str, Any] = (event.get("requestContext") or {}).get("http") or {}
    method: str = http_ctx.get("method", "POST").upper()
    path: str = event.get("rawPath") or "/"
    query_string: bytes = (event.get("rawQueryString") or "").encode()

    scope: dict[str, Any] = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": method,
        "path": path,
        "raw_path": path.encode(),
        "query_string": query_string,
        "root_path": "",
        "headers": asgi_headers,
        "client": ("127.0.0.1", 0),
    }

    response_status: list[int] = [200]
    response_headers: list[list[tuple[bytes, bytes]]] = [[]]
    response_chunks: list[bytes] = []

    async def receive() -> dict[str, Any]:
        return {"type": "http.request", "body": body_bytes, "more_body": False}

    async def send(message: dict[str, Any]) -> None:
        if message["type"] == "http.response.start":
            response_status[0] = int(message["status"])
            response_headers[0] = list(message.get("headers") or [])
        elif message["type"] == "http.response.body":
            chunk: bytes = message.get("body") or b""
            if chunk:
                response_chunks.append(chunk)

    await asgi_app(scope, receive, send)

    resp_body = b"".join(response_chunks).decode("utf-8")
    resp_hdrs = {k.decode(): v.decode() for k, v in response_headers[0]}

    return {
        "statusCode": response_status[0],
        "headers": resp_hdrs,
        "body": resp_body,
    }


@logger.inject_lambda_context(clear_state=True)
@tracer.capture_lambda_handler  # type: ignore[misc]
@metrics.log_metrics  # type: ignore[misc]
def lambda_handler(event: dict[str, Any], context: LambdaContext) -> dict[str, Any]:
    """Lambda entry point for the MCP control-plane server.

    Creates the MCP server via create_mcp_server(), wraps it in the
    Streamable HTTP transport (exposed as a Starlette ASGI app by FastMCP),
    then processes the Lambda Function URL event through an ASGI adapter.

    The Function URL is configured with invoke_mode = "RESPONSE_STREAM"
    (see terraform/mcp.tf), which enables SSE streaming for tool calls that
    return incremental events. The handler itself is synchronous — asyncio.run()
    bridges into the async ASGI transport layer.
    """
    logger.info("MCP request received", extra={"path": event.get("rawPath")})

    server = create_mcp_server()

    # streamable_http_app() returns a Starlette ASGI application configured
    # for the MCP Streamable HTTP transport (spec 2025-03-26). Available in
    # mcp[cli] >= 1.3.0. Verify against the installed version if this raises.
    asgi_app = server.streamable_http_app()

    return asyncio.run(_asgi_adapter(event, asgi_app))
