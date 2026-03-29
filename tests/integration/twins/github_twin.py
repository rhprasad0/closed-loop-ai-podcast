"""GitHub API behavioral twin for integration tests.

Serves fixture data via pytest-httpserver, recording all calls for behavioral assertions.
"""

from __future__ import annotations

import base64
import json
import re
from dataclasses import dataclass, field

from pytest_httpserver import HTTPServer
from werkzeug.wrappers import Request, Response

from tests.integration.twins.fixtures import (
    GITHUB_READMES,
    GITHUB_REPOS,
    GITHUB_USER_REPOS,
    GITHUB_USERS,
)


@dataclass
class GitHubTwinState:
    """Tracks which GitHub API endpoints were called during a test."""

    calls: list[tuple[str, str]] = field(default_factory=list)
    user_lookups: list[str] = field(default_factory=list)
    repo_lookups: list[str] = field(default_factory=list)
    readme_lookups: list[str] = field(default_factory=list)


def setup_github_twin(server: HTTPServer) -> GitHubTwinState:
    """Register GitHub API handlers on the given HTTPServer and return a state tracker."""
    state = GitHubTwinState()

    def _handle(method: str, path: str, request: Request) -> Response:
        """Central dispatcher — route by path pattern, record call, return fixture data."""
        state.calls.append((method, path))

        # GET /users/{username}/repos
        m = re.fullmatch(r"/users/([^/]+)/repos", path)
        if m:
            username = m.group(1)
            repos = GITHUB_USER_REPOS.get(username, [])
            # Honour sort and per_page query params (filter count only — sorting is a no-op
            # in the twin since fixture data is already ordered by recency).
            per_page_str = request.args.get("per_page")
            if per_page_str is not None:
                try:
                    repos = repos[: int(per_page_str)]
                except ValueError:
                    pass
            return Response(json.dumps(repos), status=200, content_type="application/json")

        # GET /users/{username}
        m = re.fullmatch(r"/users/([^/]+)", path)
        if m:
            username = m.group(1)
            state.user_lookups.append(username)
            user = GITHUB_USERS.get(username)
            if user is None:
                return Response(
                    json.dumps({"message": "Not Found"}),
                    status=404,
                    content_type="application/json",
                )
            return Response(json.dumps(user), status=200, content_type="application/json")

        # GET /repos/{owner}/{repo}/readme
        m = re.fullmatch(r"/repos/([^/]+)/([^/]+)/readme", path)
        if m:
            key = f"{m.group(1)}/{m.group(2)}"
            state.readme_lookups.append(key)
            readme = GITHUB_READMES.get(key)
            if readme is None:
                return Response(
                    json.dumps({"message": "Not Found"}),
                    status=404,
                    content_type="application/json",
                )
            encoded = base64.b64encode(readme.encode()).decode()
            payload = {"content": encoded, "encoding": "base64"}
            return Response(json.dumps(payload), status=200, content_type="application/json")

        # GET /repos/{owner}/{repo}
        m = re.fullmatch(r"/repos/([^/]+)/([^/]+)", path)
        if m:
            key = f"{m.group(1)}/{m.group(2)}"
            state.repo_lookups.append(key)
            repo = GITHUB_REPOS.get(key)
            if repo is None:
                return Response(
                    json.dumps({"message": "Not Found"}),
                    status=404,
                    content_type="application/json",
                )
            return Response(json.dumps(repo), status=200, content_type="application/json")

        # GET /search/repositories
        if path == "/search/repositories":
            q = request.args.get("q", "")
            matched = [
                repo
                for key, repo in GITHUB_REPOS.items()
                if q in (repo.get("name") or "")  # type: ignore[operator]
                or q in (repo.get("description") or "")  # type: ignore[operator]
                or q in key
            ]
            per_page_str = request.args.get("per_page")
            if per_page_str is not None:
                try:
                    matched = matched[: int(per_page_str)]
                except ValueError:
                    pass
            payload = {"total_count": len(matched), "items": matched}
            return Response(json.dumps(payload), status=200, content_type="application/json")

        # No route matched
        return Response(
            json.dumps({"message": "Not Found"}), status=404, content_type="application/json"
        )

    def _make_handler(method: str, path: str):  # type: ignore[return]
        """Return a werkzeug-compatible handler function for the given method+path pattern."""

        def handler(request: Request) -> Response:
            return _handle(method, request.path)

        return handler

    # Register a catch-all handler for each path prefix using URI regex patterns.
    # pytest-httpserver supports re.compile() patterns for the uri parameter.
    for uri_pattern in (
        re.compile(r"/users/.*"),
        re.compile(r"/repos/.*"),
        re.compile(r"/search/repositories"),
    ):
        server.expect_request(uri=uri_pattern, method="GET").respond_with_handler(
            # We need access to request.path, so use a closure that captures state + fixtures.
            lambda req, _state=state: _handle("GET", req.path)  # noqa: B023
        )

    return state
