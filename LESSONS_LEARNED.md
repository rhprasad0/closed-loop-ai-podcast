# Lessons Learned: MCP Lambda Handler Bugs

**Date:** 2026-03-31
**Context:** First live test of the MCP Lambda endpoint from claude.ai. Four bugs shipped despite passing spec review and 297 unit tests.

## What Happened

The MCP Lambda handler (`lambdas/mcp/handler.py`) failed on every request. Four bugs needed fixing before the endpoint worked:

| # | Bug | Symptom | Fix |
|---|-----|---------|-----|
| 1 | ASGI lifespan not driven | `RuntimeError: Task group not initialized` | Drive `lifespan.startup`/`shutdown` via `asyncio.Task` before/after HTTP request |
| 2 | DNS rebinding protection | 403 from Starlette middleware | `FastMCP(host="0.0.0.0")` to disable localhost-only host allowlist |
| 3 | Stateful session mode | 404 on any request after `initialize` | `FastMCP(stateless_http=True)` since Lambda can't persist sessions |
| 4 | SSE streaming + double-wrapped JSON | Hung response / malformed body | `FastMCP(json_response=True)` + `invoke_mode = "BUFFERED"` |

## Why They All Shipped

Every bug has the same root cause: **no test ever called `lambda_handler()`.**

The test suite had 297 passing tests across 21 files. Coverage was thorough for tool logic — every tool function, every edge case, every AWS API parameter. But every test imported tool functions directly and called them with `asyncio.run()`, completely bypassing the Lambda handler, ASGI adapter, and MCP transport layer.

The entire path from "HTTP request arrives at Lambda" to "JSON-RPC response goes back" was untested:

```
Lambda Function URL event
    → lambda_handler()          # NEVER TESTED
        → _asgi_adapter()       # NEVER TESTED
            → ASGI lifespan     # NEVER TESTED
            → Starlette app     # NEVER TESTED
                → FastMCP       # NEVER TESTED
                    → tool fn   # <-- all tests start here
```

## How the Spec Contributed

### 1. The spec described behavior that didn't match the implementation pattern

The spec said `RESPONSE_STREAM` was "required for SSE event streaming" — but the handler collected the full response into a dict and returned it. These are contradictory. The spec described what a persistent server would do, not what a Lambda handler needs to do.

**Lesson:** When specifying Lambda integration with a library (FastMCP/Starlette), spec the *adapter* pattern, not just the library's default behavior. Lambda imposes constraints (stateless, request-response, no persistent server) that change how the library must be configured.

### 2. The spec omitted constructor arguments with Lambda-specific defaults

The spec showed `FastMCP(name="zerostars-mcp")` without specifying `host`, `stateless_http`, or `json_response`. The defaults (`host="127.0.0.1"`, `stateless_http=False`, `json_response=False`) are correct for a normal server but wrong for Lambda. The spec said "stateless HTTP POST, no session state" in prose but didn't translate that into code.

**Lesson:** When a library has config that interacts with the deployment model, spec the config values explicitly with rationale. Prose intentions ("stateless") must be traced to concrete code (`stateless_http=True`).

### 3. The spec described tests that weren't implemented

The spec said:
- `test_handler.py` covers "Transport setup, tool registration, routing" — but the actual test only covered registration.
- E2E tests "invoke the deployed MCP Lambda via `boto3.client('lambda').invoke()`" — but the actual tests imported tools directly.

**Lesson:** Spec'd test descriptions must match actual test implementations. When tests are descoped (e.g., switching from handler invocation to direct tool calls due to import issues), update the spec to reflect the reduced coverage and flag the gap.

## How Tests Could Have Caught This

A single test would have caught all four bugs:

```python
def test_lambda_handler_initialize():
    event = {
        "rawPath": "/mcp",
        "headers": {
            "content-type": "application/json",
            "accept": "application/json, text/event-stream",
            "host": "abc123.lambda-url.us-east-1.on.aws",
        },
        "requestContext": {"http": {"method": "POST", "path": "/mcp"}},
        "body": '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-03-26","capabilities":{},"clientInfo":{"name":"test","version":"1.0"}}}',
        "isBase64Encoded": False,
    }
    response = lambda_handler(event, mock_context)

    assert response["statusCode"] == 200
    body = json.loads(response["body"])
    assert body["result"]["serverInfo"]["name"] == "zerostars-mcp"
```

- **Bug 1:** Test crashes with `RuntimeError: Task group not initialized` (lifespan never started)
- **Bug 2:** `response["statusCode"]` would be 400 (Host header rejected by DNS rebinding protection)
- **Bug 3:** Would surface on a second test calling `tools/list` (session not found)
- **Bug 4:** `json.loads(response["body"])` would fail (body contains SSE event lines, not JSON)

## Takeaways for Future Specs

### Test at the boundary, not just the internals

Tool logic tests are valuable but they test the *implementation*, not the *contract*. The contract is: "HTTP POST to `/mcp` with a JSON-RPC body returns a JSON-RPC response." At least one test must exercise this contract through the actual entry point.

**Rule:** Every Lambda handler must have at least one test that calls the handler function with a realistic event and asserts on the response format. This is the integration seam — the boundary where your code meets the runtime.

### Spec the adapter, not just the library

FastMCP's documentation shows how to run a server with `uvicorn`. Lambda is not `uvicorn`. The adapter between Lambda's event model and the ASGI protocol is the most bug-prone code in the handler — and it's the code the spec said the least about.

**Rule:** When a spec says "use library X," it must also specify how X integrates with the deployment target. If the deployment target (Lambda) imposes constraints that differ from the library's defaults, those constraints need explicit specification.

### Flag coverage gaps when descoping tests

The e2e tests were changed from handler invocation to direct tool calls to work around an import issue. This was a reasonable trade-off, but the coverage gap wasn't flagged. The spec still claimed "full MCP stack" coverage.

**Rule:** When tests are descoped, add a comment documenting what's no longer covered and why. Update the spec. A known gap is manageable; an invisible gap ships bugs.
