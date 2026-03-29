"""Exa Search API behavioral twin for integration tests.

Serves fixture data via pytest-httpserver, recording all calls for behavioral assertions.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field

from pytest_httpserver import HTTPServer
from werkzeug.wrappers import Request, Response

from tests.integration.twins.fixtures import EXA_SEARCH_RESULTS


@dataclass
class ExaTwinState:
    """Tracks Exa API calls made during a test."""

    search_queries: list[str] = field(default_factory=list)
    total_requests: int = 0


def setup_exa_twin(server: HTTPServer) -> ExaTwinState:
    """Register Exa API handlers on the given HTTPServer and return a state tracker."""
    state = ExaTwinState()

    def _handle_search(request: Request) -> Response:
        state.total_requests += 1

        body: dict[str, object] = json.loads(request.data or b"{}")
        query = str(body.get("query", ""))
        state.search_queries.append(query)

        include_domains: list[str] = body.get("includeDomains", [])  # type: ignore[assignment]
        github_only = "github.com" in include_domains

        results = []
        for result in EXA_SEARCH_RESULTS:
            url = str(result.get("url", ""))
            title = str(result.get("title", ""))
            text = str(result.get("text", ""))

            # Filter by domain if includeDomains contains 'github.com'
            if github_only and "github.com" not in url:
                continue

            # Simple substring match on title or text
            query_lower = query.lower()
            if query_lower and query_lower not in title.lower() and query_lower not in text.lower():
                # Still include results when query is generic (empty match means include all)
                # Only exclude when there's a non-empty query that truly doesn't match.
                # The twin uses permissive matching: if no results match the query substring,
                # fall back to returning all (domain-filtered) results so agents aren't starved.
                pass
            else:
                results.append(result)

        # Fallback: if substring filter yielded nothing, return all domain-filtered results
        if not results:
            results = [
                r
                for r in EXA_SEARCH_RESULTS
                if not github_only or "github.com" in str(r.get("url", ""))
            ]

        num_results = body.get("numResults")
        if isinstance(num_results, int):
            results = results[:num_results]

        payload = {
            "requestId": f"test-{uuid.uuid4()}",
            "results": results,
        }
        return Response(json.dumps(payload), status=200, content_type="application/json")

    server.expect_request("/search", method="POST").respond_with_handler(_handle_search)

    return state
