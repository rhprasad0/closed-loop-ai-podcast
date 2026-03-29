from __future__ import annotations

import base64
import json
import socket
from unittest.mock import MagicMock, patch
from urllib.error import HTTPError

import pytest

from lambdas.research.handler import _parse_research_output

# ---------------------------------------------------------------------------
# Output Parsing Tests
# ---------------------------------------------------------------------------

VALID_OUTPUT = {
    "developer_name": "Test User",
    "developer_github": "testuser",
    "developer_bio": "Builds things for fun.",
    "public_repos_count": 15,
    "notable_repos": [
        {"name": "testrepo", "description": "A test repo", "stars": 7, "language": "Python"},
        {"name": "sideproject", "description": "Another project", "stars": 2, "language": "Rust"},
    ],
    "commit_patterns": "Active on weekends, pushes every few days to the featured repo",
    "technical_profile": "Python and Rust developer, gravitates toward CLI tools",
    "interesting_findings": [
        "Named all repos after Italian cities",
        "Built a custom task runner from scratch instead of using Make",
    ],
    "hiring_signals": [
        "Ships complete projects with documentation, not just proof-of-concept stubs",
        "Chose embedded SQLite over client-server Postgres, showing deployment awareness",
    ],
}


def test_parse_valid_json() -> None:
    result = _parse_research_output(json.dumps(VALID_OUTPUT))
    assert result["developer_name"] == "Test User"
    assert result["public_repos_count"] == 15
    assert len(result["notable_repos"]) == 2


def test_parse_fenced_json() -> None:
    fenced = f"```json\n{json.dumps(VALID_OUTPUT)}\n```"
    result = _parse_research_output(fenced)
    assert result["developer_github"] == "testuser"


def test_parse_fenced_no_language_tag() -> None:
    fenced = f"```\n{json.dumps(VALID_OUTPUT)}\n```"
    result = _parse_research_output(fenced)
    assert result["developer_github"] == "testuser"


def test_parse_coerces_string_public_repos_count() -> None:
    coerced = {**VALID_OUTPUT, "public_repos_count": "15"}
    result = _parse_research_output(json.dumps(coerced))
    assert result["public_repos_count"] == 15
    assert isinstance(result["public_repos_count"], int)


def test_parse_coerces_null_bio_to_empty_string() -> None:
    null_bio = {**VALID_OUTPUT, "developer_bio": None}
    result = _parse_research_output(json.dumps(null_bio))
    assert result["developer_bio"] == ""
    assert isinstance(result["developer_bio"], str)


def test_parse_rejects_missing_field() -> None:
    incomplete = {k: v for k, v in VALID_OUTPUT.items() if k != "developer_github"}
    with pytest.raises(ValueError, match="developer_github"):
        _parse_research_output(json.dumps(incomplete))


def test_parse_rejects_invalid_json() -> None:
    with pytest.raises((ValueError, json.JSONDecodeError)):
        _parse_research_output("this is not json at all")


def test_parse_rejects_notable_repos_missing_required_field() -> None:
    bad_repo = {
        **VALID_OUTPUT,
        "notable_repos": [{"name": "repo"}],
    }  # missing description, stars, language
    with pytest.raises(ValueError, match="notable_repos"):
        _parse_research_output(json.dumps(bad_repo))


def test_parse_accepts_empty_notable_repos() -> None:
    """A developer with zero interesting repos should still pass parsing."""
    empty = {**VALID_OUTPUT, "notable_repos": [], "public_repos_count": 0}
    result = _parse_research_output(json.dumps(empty))
    assert result["notable_repos"] == []


# ---------------------------------------------------------------------------
# GitHub Tool Tests
# ---------------------------------------------------------------------------


def test_get_github_user_returns_curated_fields(mock_research_urlopen: MagicMock) -> None:
    from lambdas.research.handler import _execute_get_github_user

    github_response = {
        "login": "testuser",
        "name": "Test User",
        "bio": "I build things.",
        "public_repos": 15,
        "followers": 3,
        "created_at": "2020-01-01T00:00:00Z",
        "html_url": "https://github.com/testuser",
        "id": 123456,
        "node_id": "U_abc123",
        "avatar_url": "https://...",  # should be filtered
    }
    mock_response = MagicMock()
    mock_response.read.return_value = json.dumps(github_response).encode()
    mock_response.__enter__ = lambda s: s
    mock_response.__exit__ = MagicMock(return_value=False)
    mock_research_urlopen.return_value = mock_response

    result = _execute_get_github_user({"username": "testuser"})
    assert result["login"] == "testuser"
    assert result["name"] == "Test User"
    assert result["public_repos"] == 15
    assert "id" not in result
    assert "avatar_url" not in result


def test_get_github_user_null_name(mock_research_urlopen: MagicMock) -> None:
    from lambdas.research.handler import _execute_get_github_user

    github_response = {
        "login": "anon",
        "name": None,
        "bio": None,
        "public_repos": 2,
        "followers": 0,
        "created_at": "2024-06-01T00:00:00Z",
        "html_url": "https://github.com/anon",
    }
    mock_response = MagicMock()
    mock_response.read.return_value = json.dumps(github_response).encode()
    mock_response.__enter__ = lambda s: s
    mock_response.__exit__ = MagicMock(return_value=False)
    mock_research_urlopen.return_value = mock_response

    result = _execute_get_github_user({"username": "anon"})
    assert result["name"] is None
    assert result["bio"] is None


def test_get_github_user_http_error(mock_research_urlopen: MagicMock) -> None:
    from lambdas.research.handler import _execute_get_github_user

    mock_research_urlopen.side_effect = HTTPError(
        url="https://api.github.com/users/x",
        code=404,
        msg="Not Found",
        hdrs=None,
        fp=None,  # type: ignore[arg-type]
    )
    result = _execute_get_github_user({"username": "x"})
    assert "error" in result


def test_get_github_user_timeout(mock_research_urlopen: MagicMock) -> None:
    from lambdas.research.handler import _execute_get_github_user

    mock_research_urlopen.side_effect = socket.timeout("timed out")
    result = _execute_get_github_user({"username": "x"})
    assert "error" in result


def test_get_user_repos_returns_curated_array(mock_research_urlopen: MagicMock) -> None:
    from lambdas.research.handler import _execute_get_user_repos

    github_response = [
        {
            "name": "repo1",
            "description": "First repo",
            "stargazers_count": 3,
            "language": "Python",
            "html_url": "https://github.com/u/repo1",
            "pushed_at": "2024-11-01T00:00:00Z",
            "fork": False,
            "id": 111,
            "node_id": "R_111",
            "size": 500,  # should be filtered
        },
    ]
    mock_response = MagicMock()
    mock_response.read.return_value = json.dumps(github_response).encode()
    mock_response.__enter__ = lambda s: s
    mock_response.__exit__ = MagicMock(return_value=False)
    mock_research_urlopen.return_value = mock_response

    result = _execute_get_user_repos({"username": "u", "sort": "pushed", "per_page": 30})
    assert isinstance(result, list)
    assert result[0]["name"] == "repo1"
    assert "id" not in result[0]


def test_get_user_repos_http_error(mock_research_urlopen: MagicMock) -> None:
    from lambdas.research.handler import _execute_get_user_repos

    mock_research_urlopen.side_effect = HTTPError(
        url="https://api.github.com/users/x/repos",
        code=403,
        msg="Forbidden",
        hdrs=None,
        fp=None,  # type: ignore[arg-type]
    )
    result = _execute_get_user_repos({"username": "x"})
    assert "error" in result


def test_get_repo_details_returns_curated_fields(mock_research_urlopen: MagicMock) -> None:
    from lambdas.research.handler import _execute_get_repo_details

    github_response = {
        "name": "testrepo",
        "full_name": "testuser/testrepo",
        "description": "A test repo",
        "stargazers_count": 7,
        "forks_count": 1,
        "language": "Python",
        "topics": ["cli", "tool"],
        "created_at": "2024-01-01T00:00:00Z",
        "updated_at": "2024-12-01T00:00:00Z",
        "html_url": "https://github.com/testuser/testrepo",
        "id": 999,
        "size": 2048,  # should be filtered
    }
    mock_response = MagicMock()
    mock_response.read.return_value = json.dumps(github_response).encode()
    mock_response.__enter__ = lambda s: s
    mock_response.__exit__ = MagicMock(return_value=False)
    mock_research_urlopen.return_value = mock_response

    result = _execute_get_repo_details({"owner": "testuser", "repo": "testrepo"})
    assert result["stargazers_count"] == 7
    assert result["topics"] == ["cli", "tool"]
    assert "id" not in result


def test_get_repo_details_null_description(mock_research_urlopen: MagicMock) -> None:
    from lambdas.research.handler import _execute_get_repo_details

    github_response = {
        "name": "bare",
        "full_name": "u/bare",
        "description": None,
        "stargazers_count": 0,
        "forks_count": 0,
        "language": None,
        "topics": [],
        "created_at": "2024-01-01T00:00:00Z",
        "updated_at": "2024-01-01T00:00:00Z",
        "html_url": "https://github.com/u/bare",
    }
    mock_response = MagicMock()
    mock_response.read.return_value = json.dumps(github_response).encode()
    mock_response.__enter__ = lambda s: s
    mock_response.__exit__ = MagicMock(return_value=False)
    mock_research_urlopen.return_value = mock_response

    result = _execute_get_repo_details({"owner": "u", "repo": "bare"})
    assert result["description"] is None


def test_get_repo_details_http_error(mock_research_urlopen: MagicMock) -> None:
    from lambdas.research.handler import _execute_get_repo_details

    mock_research_urlopen.side_effect = HTTPError(
        url="https://api.github.com/repos/x/y",
        code=404,
        msg="Not Found",
        hdrs=None,
        fp=None,  # type: ignore[arg-type]
    )
    result = _execute_get_repo_details({"owner": "x", "repo": "y"})
    assert "error" in result


def test_get_repo_readme_returns_decoded_content(mock_research_urlopen: MagicMock) -> None:
    from lambdas.research.handler import _execute_get_repo_readme

    readme_text = "# My Project\n\nThis is a cool project."
    github_response = {
        "content": base64.b64encode(readme_text.encode()).decode(),
        "encoding": "base64",
    }
    mock_response = MagicMock()
    mock_response.read.return_value = json.dumps(github_response).encode()
    mock_response.__enter__ = lambda s: s
    mock_response.__exit__ = MagicMock(return_value=False)
    mock_research_urlopen.return_value = mock_response

    result = _execute_get_repo_readme({"owner": "u", "repo": "proj"})
    assert "My Project" in result["content"]
    assert "cool project" in result["content"]


def test_get_repo_readme_404_returns_error(mock_research_urlopen: MagicMock) -> None:
    from lambdas.research.handler import _execute_get_repo_readme

    mock_research_urlopen.side_effect = HTTPError(
        url="https://api.github.com/repos/x/y/readme",
        code=404,
        msg="Not Found",
        hdrs=None,
        fp=None,  # type: ignore[arg-type]
    )
    result = _execute_get_repo_readme({"owner": "x", "repo": "y"})
    assert "error" in result


def test_search_repositories_returns_curated_results(mock_research_urlopen: MagicMock) -> None:
    from lambdas.research.handler import _execute_search_repositories

    github_response = {
        "total_count": 2,
        "items": [
            {
                "name": "repo1",
                "full_name": "u/repo1",
                "description": "First",
                "stargazers_count": 3,
                "language": "Python",
                "html_url": "https://github.com/u/repo1",
                "id": 111,
                "score": 1.0,  # should be filtered
            },
        ],
    }
    mock_response = MagicMock()
    mock_response.read.return_value = json.dumps(github_response).encode()
    mock_response.__enter__ = lambda s: s
    mock_response.__exit__ = MagicMock(return_value=False)
    mock_research_urlopen.return_value = mock_response

    result = _execute_search_repositories({"query": "user:u", "sort": "stars", "per_page": 10})
    assert result["total_count"] == 2
    assert result["items"][0]["name"] == "repo1"
    assert "id" not in result["items"][0]


def test_search_repositories_http_error(mock_research_urlopen: MagicMock) -> None:
    from lambdas.research.handler import _execute_search_repositories

    mock_research_urlopen.side_effect = HTTPError(
        url="https://api.github.com/search/repositories",
        code=422,
        msg="Validation Failed",
        hdrs=None,
        fp=None,  # type: ignore[arg-type]
    )
    result = _execute_search_repositories({"query": "user:x"})
    assert "error" in result


# ---------------------------------------------------------------------------
# Tool Dispatcher Tests
# ---------------------------------------------------------------------------


def test_tool_dispatcher_routes_get_github_user() -> None:
    from lambdas.research.handler import _execute_tool

    with patch(
        "lambdas.research.handler._execute_get_github_user", return_value={"login": "u"}
    ) as mock:
        result_str = _execute_tool("get_github_user", {"username": "u"})
        mock.assert_called_once_with({"username": "u"})
        assert json.loads(result_str) == {"login": "u"}


def test_tool_dispatcher_routes_get_user_repos() -> None:
    from lambdas.research.handler import _execute_tool

    with patch(
        "lambdas.research.handler._execute_get_user_repos", return_value=[{"name": "r"}]
    ) as mock:
        result_str = _execute_tool("get_user_repos", {"username": "u"})
        mock.assert_called_once()
        assert json.loads(result_str) == [{"name": "r"}]


def test_tool_dispatcher_routes_get_repo_details() -> None:
    from lambdas.research.handler import _execute_tool

    with patch(
        "lambdas.research.handler._execute_get_repo_details", return_value={"name": "r"}
    ) as mock:
        result_str = _execute_tool("get_repo_details", {"owner": "u", "repo": "r"})
        mock.assert_called_once()


def test_tool_dispatcher_routes_get_repo_readme() -> None:
    from lambdas.research.handler import _execute_tool

    with patch(
        "lambdas.research.handler._execute_get_repo_readme", return_value={"content": "# README"}
    ) as mock:
        result_str = _execute_tool("get_repo_readme", {"owner": "u", "repo": "r"})
        mock.assert_called_once()


def test_tool_dispatcher_routes_search_repositories() -> None:
    from lambdas.research.handler import _execute_tool

    with patch(
        "lambdas.research.handler._execute_search_repositories",
        return_value={"total_count": 0, "items": []},
    ) as mock:
        result_str = _execute_tool("search_repositories", {"query": "user:u"})
        mock.assert_called_once()


def test_tool_dispatcher_unknown_tool() -> None:
    from lambdas.research.handler import _execute_tool

    result = json.loads(_execute_tool("nonexistent_tool", {}))
    assert "error" in result
    assert "nonexistent_tool" in result["error"]


# ---------------------------------------------------------------------------
# Full Handler Tests
# ---------------------------------------------------------------------------

VALID_HANDLER_OUTPUT = json.dumps(
    {
        "developer_name": "Test User",
        "developer_github": "testuser",
        "developer_bio": "Builds things.",
        "public_repos_count": 15,
        "notable_repos": [
            {"name": "testrepo", "description": "A test repo", "stars": 7, "language": "Python"},
        ],
        "commit_patterns": "Active on weekends",
        "technical_profile": "Python and Rust developer",
        "interesting_findings": ["Built a custom ORM from scratch"],
        "hiring_signals": ["Ships complete projects with documentation"],
    }
)


def test_handler_returns_valid_output(
    pipeline_metadata: dict,
    lambda_context: MagicMock,
    mock_research_invoke_with_tools: MagicMock,
    discovery_output_for_research: dict,
) -> None:
    mock_research_invoke_with_tools.return_value = VALID_HANDLER_OUTPUT
    with patch("lambdas.research.handler._load_system_prompt", return_value="sp"):
        from lambdas.research.handler import lambda_handler

        result = lambda_handler(
            {"metadata": pipeline_metadata, "discovery": discovery_output_for_research},
            lambda_context,
        )
    assert result["developer_name"] == "Test User"
    assert result["developer_github"] == "testuser"
    assert isinstance(result["public_repos_count"], int)
    assert isinstance(result["notable_repos"], list)
    assert isinstance(result["interesting_findings"], list)
    assert isinstance(result["hiring_signals"], list)


def test_handler_passes_tools_and_executor(
    pipeline_metadata: dict,
    lambda_context: MagicMock,
    mock_research_invoke_with_tools: MagicMock,
    discovery_output_for_research: dict,
) -> None:
    mock_research_invoke_with_tools.return_value = VALID_HANDLER_OUTPUT
    with patch("lambdas.research.handler._load_system_prompt", return_value="sp"):
        from lambdas.research.handler import lambda_handler

        lambda_handler(
            {"metadata": pipeline_metadata, "discovery": discovery_output_for_research},
            lambda_context,
        )
    call_kwargs = mock_research_invoke_with_tools.call_args
    tools = call_kwargs.kwargs.get("tools", call_kwargs[1].get("tools"))
    assert len(tools) == 5
    tool_names = {t["name"] for t in tools}
    assert tool_names == {
        "get_github_user",
        "get_user_repos",
        "get_repo_details",
        "get_repo_readme",
        "search_repositories",
    }
    executor = call_kwargs.kwargs.get("tool_executor", call_kwargs[1].get("tool_executor"))
    assert callable(executor)


def test_handler_reads_discovery_fields_from_event(
    pipeline_metadata: dict,
    lambda_context: MagicMock,
    mock_research_invoke_with_tools: MagicMock,
    discovery_output_for_research: dict,
) -> None:
    mock_research_invoke_with_tools.return_value = VALID_HANDLER_OUTPUT
    with patch("lambdas.research.handler._load_system_prompt", return_value="sp"):
        from lambdas.research.handler import lambda_handler

        lambda_handler(
            {"metadata": pipeline_metadata, "discovery": discovery_output_for_research},
            lambda_context,
        )
    call_kwargs = mock_research_invoke_with_tools.call_args
    user_message = call_kwargs.kwargs.get("user_message", call_kwargs[1].get("user_message"))
    assert "testuser" in user_message
    assert "testrepo" in user_message


def test_handler_handles_missing_bio(
    pipeline_metadata: dict,
    lambda_context: MagicMock,
    mock_research_invoke_with_tools: MagicMock,
    discovery_output_for_research: dict,
) -> None:
    output = json.loads(VALID_HANDLER_OUTPUT)
    output["developer_bio"] = None
    mock_research_invoke_with_tools.return_value = json.dumps(output)
    with patch("lambdas.research.handler._load_system_prompt", return_value="sp"):
        from lambdas.research.handler import lambda_handler

        result = lambda_handler(
            {"metadata": pipeline_metadata, "discovery": discovery_output_for_research},
            lambda_context,
        )
    assert result["developer_bio"] == ""


def test_handler_handles_zero_repos(
    pipeline_metadata: dict,
    lambda_context: MagicMock,
    mock_research_invoke_with_tools: MagicMock,
    discovery_output_for_research: dict,
) -> None:
    output = json.loads(VALID_HANDLER_OUTPUT)
    output["public_repos_count"] = 0
    output["notable_repos"] = []
    mock_research_invoke_with_tools.return_value = json.dumps(output)
    with patch("lambdas.research.handler._load_system_prompt", return_value="sp"):
        from lambdas.research.handler import lambda_handler

        result = lambda_handler(
            {"metadata": pipeline_metadata, "discovery": discovery_output_for_research},
            lambda_context,
        )
    assert result["public_repos_count"] == 0
    assert result["notable_repos"] == []


def test_handler_handles_fenced_output(
    pipeline_metadata: dict,
    lambda_context: MagicMock,
    mock_research_invoke_with_tools: MagicMock,
    discovery_output_for_research: dict,
) -> None:
    mock_research_invoke_with_tools.return_value = f"```json\n{VALID_HANDLER_OUTPUT}\n```"
    with patch("lambdas.research.handler._load_system_prompt", return_value="sp"):
        from lambdas.research.handler import lambda_handler

        result = lambda_handler(
            {"metadata": pipeline_metadata, "discovery": discovery_output_for_research},
            lambda_context,
        )
    assert result["developer_name"] == "Test User"


def test_handler_raises_on_agent_error(
    pipeline_metadata: dict,
    lambda_context: MagicMock,
    mock_research_invoke_with_tools: MagicMock,
    discovery_output_for_research: dict,
) -> None:
    mock_research_invoke_with_tools.side_effect = RuntimeError("max_turns exceeded")
    with patch("lambdas.research.handler._load_system_prompt", return_value="sp"):
        from lambdas.research.handler import lambda_handler

        with pytest.raises(RuntimeError, match="max_turns"):
            lambda_handler(
                {"metadata": pipeline_metadata, "discovery": discovery_output_for_research},
                lambda_context,
            )
