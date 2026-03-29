"""E2E tests: website serves episodes via CloudFront."""

from __future__ import annotations

import urllib.error
import urllib.request

import pytest

from tests.e2e.helpers import PipelineExecutionResult

pytestmark = [pytest.mark.e2e, pytest.mark.timeout(30)]


def _get(url: str) -> tuple[int, str, dict[str, str]]:
    """HTTP GET returning (status_code, body, headers). Handles 404 without raising."""
    req = urllib.request.Request(url, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            body = resp.read().decode("utf-8", errors="replace")
            headers = {k.lower(): v for k, v in resp.headers.items()}
            return resp.status, body, headers
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace") if exc.fp else ""
        headers = {k.lower(): v for k, v in exc.headers.items()} if exc.headers else {}
        return exc.code, body, headers


@pytest.fixture(scope="module")
def site_url(deployed_resources: dict[str, str]) -> str:
    """Get the site URL, skipping all tests if not configured."""
    url = deployed_resources.get("site_url", "")
    if not url:
        pytest.skip("SITE_URL not set")
    return url


# ---------------------------------------------------------------------------
# Site availability
# ---------------------------------------------------------------------------


def test_site_returns_200(site_url: str) -> None:
    """GET / returns 200 with text/html content."""
    status, body, headers = _get(site_url)

    assert status == 200, f"Expected 200, got {status}"
    assert "text/html" in headers.get("content-type", ""), (
        f"Expected text/html, got {headers.get('content-type')}"
    )
    assert len(body) > 0, "Response body is empty"


def test_site_returns_404(site_url: str) -> None:
    """GET /nonexistent returns 404."""
    url = site_url.rstrip("/") + "/nonexistent-path-e2e-test"
    status, _, _ = _get(url)

    assert status == 404, f"Expected 404 for unknown path, got {status}"


# ---------------------------------------------------------------------------
# Episode content
# ---------------------------------------------------------------------------


@pytest.mark.flaky(reruns=2)  # type: ignore[misc]
def test_site_lists_e2e_episode(
    site_url: str,
    pipeline_execution: PipelineExecutionResult,
) -> None:
    """The site HTML includes the repo_name from the e2e pipeline run."""
    if pipeline_execution.status != "SUCCEEDED":
        pytest.skip("Pipeline did not succeed")

    repo_name = pipeline_execution.final_state["discovery"]["repo_name"]

    status, body, _ = _get(site_url)
    assert status == 200

    assert repo_name in body, (
        f"Expected repo_name {repo_name!r} to appear in site HTML. "
        f"The episode may not be visible yet (CloudFront cache)."
    )
