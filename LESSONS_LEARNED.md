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

---

# Lessons Learned: CloudFront Cover Art Path Mismatch

**Date:** 2026-04-01
**Context:** Cover art images generated by Nova Canvas were not displaying on the deployed site at `podcast.ryans-lab.click`. Images existed in S3 but returned 403 errors when loaded by the browser.

## What Happened

The cover art handler writes images to S3 at `episodes/<execution_id>/cover.png`. The site handler builds cover art URLs by prepending `/assets/` to that key, producing `/assets/episodes/<id>/cover.png`. CloudFront routes `/assets/*` requests to the S3 origin — but it forwards the *full* request path, so S3 receives a `GetObject` for key `assets/episodes/<id>/cover.png`. The actual key is `episodes/<id>/cover.png`. The bucket policy only allows `episodes/*/cover.png`, so every request failed with 403.

| Component | What it produced | What was expected |
|-----------|-----------------|-------------------|
| Cover art handler | S3 key: `episodes/<id>/cover.png` | Correct |
| Site handler | URL: `/assets/episodes/<id>/cover.png` | Should have been `/episodes/<id>/cover.png` |
| CloudFront | S3 key: `assets/episodes/<id>/cover.png` | Should have been `episodes/<id>/cover.png` |
| S3 bucket policy | Allows: `episodes/*/cover.png` | Correctly rejects the wrong key |

**Fix:** Changed CloudFront path pattern from `/assets/*` to `/episodes/*` and removed the `/assets/` prefix from URL construction in the site handler. The URL path now matches the S3 key directly.

## How the Spec Contributed

### 1. The spec defined the S3 key scheme and CloudFront routing in isolation

The S3 key structure (`episodes/<id>/cover.png`) was defined as part of the cover art agent's output contract. The CloudFront `/assets/*` path pattern was defined as part of the site infrastructure. Neither section traced the full path from database value to S3 key resolution:

```
DB: s3_cover_art_path = "episodes/<id>/cover.png"
    → Site handler prepends "/assets/"
        → Browser requests "/assets/episodes/<id>/cover.png"
            → CloudFront matches "/assets/*", forwards to S3
                → S3 receives key "assets/episodes/<id>/cover.png"
                    → 403: key doesn't exist, policy doesn't match
```

The mismatch is obvious when you write it out end-to-end, but the spec never required that trace. Each component was correct in isolation. The bug lived in the seam between them.

**Lesson:** When a value flows across component boundaries (DB → Lambda → CDN → object store), the spec should include an explicit end-to-end data flow trace showing the exact value at each hop. This is especially important when URL paths and storage keys are related but not identical.

### 2. The `/assets/*` path was a cosmetic abstraction with no functional purpose

The `/assets/*` prefix was introduced to separate "static assets" from "dynamic pages" at the CDN layer — a convention borrowed from traditional web apps. But in this system, S3 keys already have a meaningful prefix (`episodes/`), and CloudFront forwards the full path to S3. The cosmetic abstraction introduced a translation layer (prepend `/assets/`, then CloudFront must somehow strip it) that was never implemented.

**Lesson:** Don't introduce URL path prefixes that differ from storage key prefixes unless the spec also defines the translation mechanism (e.g., `origin_path`, a CloudFront Function, or path rewriting in the handler). If the CDN serves objects directly from S3, the simplest correct design is: URL path = S3 key.

### 3. No test verified the full asset delivery path

The site handler tests mocked the database and checked HTML rendering, but no test verified that a generated `cover_art_url` would resolve to a real S3 object through CloudFront. This is the same class of gap as the MCP handler bug: tests validated internals but not the contract between components.

A single assertion could have flagged this:

```python
def test_cover_art_url_matches_s3_key():
    """cover_art_url path must match the S3 key so CloudFront can resolve it."""
    s3_key = "episodes/abc-123/cover.png"
    # The URL path (after the domain) should equal the S3 key
    url_path = f"/{s3_key}"  # what the handler should produce
    assert url_path == f"/episodes/abc-123/cover.png"
    assert not url_path.startswith("/assets/")  # no synthetic prefix
```

**Lesson:** When the system has a CDN-to-storage mapping, write at least one test that asserts the URL path produced by the handler matches the S3 key expected by the CDN configuration. This is a cross-component contract test — it doesn't need to hit AWS, just verify the string math.

## Takeaways for Future Specs

### Trace data across component boundaries

A pipeline where data flows through multiple systems (DB → Lambda → CDN → S3) needs an explicit trace in the spec showing the exact value at each stage. Component-level specs that don't show how their outputs connect to the next component's inputs will have bugs at every seam.

**Rule:** For any value that crosses two or more system boundaries, the spec must include a concrete example showing the value at each hop. If the value is transformed at any hop, document the transformation and why it's needed.

### Prefer identity mappings over abstractions

When a CDN serves objects from a storage backend, the simplest correct design maps URL paths directly to storage keys. Introducing a different URL prefix (like `/assets/` for S3 keys under `episodes/`) requires a translation layer. If the spec introduces such a prefix, it must also specify how the translation happens.

**Rule:** Default to URL path = storage key. If the spec introduces a different URL scheme, it must define the translation mechanism and include a test that verifies the round-trip.
