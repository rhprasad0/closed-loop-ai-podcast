"""E2E tests: site Lambda serves episodes correctly.

Tests the site Lambda by invoking it directly via boto3 lambda.invoke()
with Lambda Function URL v2 event payloads. This tests the handler logic
against real Postgres data without depending on CloudFront/Function URL auth.
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from tests.e2e.helpers import PipelineExecutionResult

pytestmark = [pytest.mark.e2e, pytest.mark.timeout(30)]


def _invoke_site(lambda_client: Any, path: str = "/") -> tuple[int, str, dict[str, str]]:
    """Invoke the site Lambda with a GET request and return (status, body, headers)."""
    event = {
        "version": "2.0",
        "rawPath": path,
        "rawQueryString": "",
        "headers": {"accept": "text/html"},
        "requestContext": {"http": {"method": "GET", "path": path}},
        "isBase64Encoded": False,
    }
    resp = lambda_client.invoke(
        FunctionName="zerostars-site",
        InvocationType="RequestResponse",
        Payload=json.dumps(event),
    )
    payload = json.loads(resp["Payload"].read())

    if resp.get("FunctionError"):
        return 500, str(payload.get("errorMessage", "")), {}

    status_code = payload.get("statusCode", 500)
    body = payload.get("body", "")
    headers = payload.get("headers", {})
    return status_code, body, {k.lower(): v for k, v in headers.items()}


# ---------------------------------------------------------------------------
# Site availability
# ---------------------------------------------------------------------------


def test_site_returns_200(lambda_client: Any) -> None:
    """GET / returns 200 with text/html content."""
    status, body, headers = _invoke_site(lambda_client)

    assert status == 200, f"Expected 200, got {status}. Body: {body[:200]}"
    assert "text/html" in headers.get("content-type", ""), (
        f"Expected text/html, got {headers.get('content-type')}"
    )
    assert len(body) > 0, "Response body is empty"


def test_site_returns_404(lambda_client: Any) -> None:
    """GET /nonexistent returns 404."""
    status, _, _ = _invoke_site(lambda_client, "/nonexistent-path-e2e-test")

    assert status == 404, f"Expected 404 for unknown path, got {status}"


# ---------------------------------------------------------------------------
# Episode content
# ---------------------------------------------------------------------------


@pytest.mark.flaky(reruns=2)  # type: ignore[misc]
def test_site_lists_e2e_episode(
    lambda_client: Any,
    pipeline_execution: PipelineExecutionResult,
) -> None:
    """The site HTML includes the repo_name from the e2e pipeline run."""
    if pipeline_execution.status != "SUCCEEDED":
        pytest.skip("Pipeline did not succeed")

    repo_name = pipeline_execution.final_state["discovery"]["repo_name"]

    status, body, _ = _invoke_site(lambda_client)
    assert status == 200

    assert repo_name in body, (
        f"Expected repo_name {repo_name!r} to appear in site HTML."
    )
