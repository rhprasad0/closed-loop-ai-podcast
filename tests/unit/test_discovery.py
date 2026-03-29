from __future__ import annotations

import json
from unittest.mock import MagicMock, patch
from urllib.error import HTTPError

import pytest

from lambdas.discovery.handler import _parse_discovery_output

VALID_OUTPUT = {
    "repo_url": "https://github.com/someone/something",
    "repo_name": "something",
    "repo_description": "A cool project",
    "developer_github": "someone",
    "star_count": 3,
    "language": "Go",
    "discovery_rationale": "Interesting CLI tool.",
    "key_files": ["main.go"],
    "technical_highlights": ["Single-binary design"],
}


# ---------------------------------------------------------------------------
# Output Parsing Tests
# ---------------------------------------------------------------------------


def test_parse_valid_json() -> None:
    result = _parse_discovery_output(json.dumps(VALID_OUTPUT))
    assert result["repo_url"] == "https://github.com/someone/something"
    assert result["star_count"] == 3


def test_parse_fenced_json() -> None:
    fenced = f"```json\n{json.dumps(VALID_OUTPUT)}\n```"
    result = _parse_discovery_output(fenced)
    assert result["repo_name"] == "something"


def test_parse_fenced_no_language_tag() -> None:
    fenced = f"```\n{json.dumps(VALID_OUTPUT)}\n```"
    result = _parse_discovery_output(fenced)
    assert result["repo_name"] == "something"


def test_parse_rejects_star_count_gte_10() -> None:
    bad = {**VALID_OUTPUT, "star_count": 10}
    with pytest.raises(ValueError, match="star_count"):
        _parse_discovery_output(json.dumps(bad))


def test_parse_coerces_string_star_count() -> None:
    coerced = {**VALID_OUTPUT, "star_count": "3"}
    result = _parse_discovery_output(json.dumps(coerced))
    assert result["star_count"] == 3
    assert isinstance(result["star_count"], int)


def test_parse_rejects_missing_field() -> None:
    incomplete = {k: v for k, v in VALID_OUTPUT.items() if k != "repo_url"}
    with pytest.raises(ValueError, match="repo_url"):
        _parse_discovery_output(json.dumps(incomplete))


def test_parse_rejects_invalid_repo_url() -> None:
    bad = {**VALID_OUTPUT, "repo_url": "https://gitlab.com/someone/something"}
    with pytest.raises(ValueError, match="repo_url"):
        _parse_discovery_output(json.dumps(bad))


def test_parse_rejects_invalid_json() -> None:
    with pytest.raises((ValueError, json.JSONDecodeError)):
        _parse_discovery_output("this is not json at all")


# ---------------------------------------------------------------------------
# Database Query Tool Tests
# ---------------------------------------------------------------------------


def test_execute_query_postgres_returns_rows() -> None:
    from lambdas.discovery.handler import _execute_query_postgres

    with patch("lambdas.discovery.handler.db_query") as mock_query:
        mock_query.return_value = [("user1",), ("user2",)]
        result = _execute_query_postgres(
            {"sql": "SELECT developer_github FROM featured_developers"}
        )

    assert "rows" in result
    assert len(result["rows"]) == 2


def test_execute_query_postgres_rejects_insert() -> None:
    from lambdas.discovery.handler import _execute_query_postgres

    result = _execute_query_postgres({"sql": "INSERT INTO episodes (repo_name) VALUES ('x')"})
    assert "error" in result


def test_execute_query_postgres_rejects_delete() -> None:
    from lambdas.discovery.handler import _execute_query_postgres

    result = _execute_query_postgres({"sql": "DELETE FROM episodes"})
    assert "error" in result


def test_execute_query_postgres_rejects_drop() -> None:
    from lambdas.discovery.handler import _execute_query_postgres

    result = _execute_query_postgres({"sql": "DROP TABLE episodes"})
    assert "error" in result


def test_execute_query_postgres_rejects_update() -> None:
    from lambdas.discovery.handler import _execute_query_postgres

    result = _execute_query_postgres({"sql": "UPDATE episodes SET repo_name = 'x'"})
    assert "error" in result


def test_execute_query_postgres_leading_whitespace_select() -> None:
    from lambdas.discovery.handler import _execute_query_postgres

    with patch("lambdas.discovery.handler.db_query") as mock_query:
        mock_query.return_value = [(1,)]
        result = _execute_query_postgres({"sql": "   SELECT 1"})

    assert "rows" in result


def test_execute_query_postgres_case_insensitive_select() -> None:
    from lambdas.discovery.handler import _execute_query_postgres

    with patch("lambdas.discovery.handler.db_query") as mock_query:
        mock_query.return_value = [(1,)]
        result = _execute_query_postgres(
            {"sql": "select developer_github from featured_developers"}
        )

    assert "rows" in result


def test_execute_query_postgres_error_returns_error_dict() -> None:
    from lambdas.discovery.handler import _execute_query_postgres

    with patch("lambdas.discovery.handler.db_query") as mock_query:
        mock_query.side_effect = Exception("connection refused")
        result = _execute_query_postgres({"sql": "SELECT 1"})

    assert "error" in result
    assert "connection refused" in result["error"]


def test_execute_query_postgres_truncates_long_errors() -> None:
    from lambdas.discovery.handler import _execute_query_postgres

    with patch("lambdas.discovery.handler.db_query") as mock_query:
        mock_query.side_effect = Exception("x" * 1000)
        result = _execute_query_postgres({"sql": "SELECT 1"})

    assert "error" in result
    assert len(result["error"]) <= 500


# ---------------------------------------------------------------------------
# GitHub and Exa Tool Tests
# ---------------------------------------------------------------------------


def test_github_returns_curated_fields(mock_urlopen: MagicMock) -> None:
    from lambdas.discovery.handler import _execute_get_github_repo

    github_response = {
        "name": "testrepo",
        "full_name": "testuser/testrepo",
        "description": "A test repo",
        "stargazers_count": 5,
        "forks_count": 1,
        "language": "Python",
        "topics": ["cli"],
        "created_at": "2024-01-01T00:00:00Z",
        "pushed_at": "2024-12-01T00:00:00Z",
        "open_issues_count": 0,
        "license": {"spdx_id": "MIT"},
        "owner": {"type": "User"},
        "html_url": "https://github.com/testuser/testrepo",
        "default_branch": "main",
        "id": 123456,
        "node_id": "R_abc123",
        "size": 1024,  # should be filtered out
    }
    mock_response = MagicMock()
    mock_response.read.return_value = json.dumps(github_response).encode()
    mock_response.__enter__ = lambda s: s
    mock_response.__exit__ = MagicMock(return_value=False)
    mock_urlopen.return_value = mock_response

    result = _execute_get_github_repo({"owner": "testuser", "repo": "testrepo"})
    assert result["stargazers_count"] == 5
    assert result["license"] == "MIT"
    assert "id" not in result


def test_github_null_license(mock_urlopen: MagicMock) -> None:
    from lambdas.discovery.handler import _execute_get_github_repo

    github_response = {
        "name": "proj",
        "full_name": "u/proj",
        "description": None,
        "stargazers_count": 0,
        "forks_count": 0,
        "language": None,
        "topics": [],
        "created_at": "2024-01-01T00:00:00Z",
        "pushed_at": "2024-01-01T00:00:00Z",
        "open_issues_count": 0,
        "license": None,
        "owner": {"type": "User"},
        "html_url": "https://github.com/u/proj",
        "default_branch": "main",
    }
    mock_response = MagicMock()
    mock_response.read.return_value = json.dumps(github_response).encode()
    mock_response.__enter__ = lambda s: s
    mock_response.__exit__ = MagicMock(return_value=False)
    mock_urlopen.return_value = mock_response

    result = _execute_get_github_repo({"owner": "u", "repo": "proj"})
    assert result["license"] is None


def test_github_http_error(mock_urlopen: MagicMock) -> None:
    from lambdas.discovery.handler import _execute_get_github_repo

    mock_urlopen.side_effect = HTTPError(
        url="https://api.github.com/repos/x/y",
        code=404,
        msg="Not Found",
        hdrs=None,
        fp=None,  # type: ignore[arg-type]
    )
    result = _execute_get_github_repo({"owner": "x", "repo": "y"})
    assert "error" in result


def test_exa_snake_to_camel_mapping(
    mock_urlopen: MagicMock, mock_secrets_manager: MagicMock
) -> None:
    from lambdas.discovery.handler import _execute_exa_search

    mock_response = MagicMock()
    mock_response.read.return_value = json.dumps({"results": []}).encode()
    mock_response.__enter__ = lambda s: s
    mock_response.__exit__ = MagicMock(return_value=False)
    mock_urlopen.return_value = mock_response

    _execute_exa_search(
        {
            "query": "python cli tool",
            "include_domains": ["github.com"],
            "num_results": 5,
            "start_published_date": "2024-01-01",
        }
    )
    request_obj = mock_urlopen.call_args[0][0]
    sent_body = json.loads(request_obj.data)
    assert "includeDomains" in sent_body
    assert "numResults" in sent_body
    assert "startPublishedDate" in sent_body
    assert "include_domains" not in sent_body
    assert sent_body["contents"] == {"text": True}  # always injected by handler


def test_exa_exclude_text_camel_case(
    mock_urlopen: MagicMock, mock_secrets_manager: MagicMock
) -> None:
    from lambdas.discovery.handler import _execute_exa_search

    mock_response = MagicMock()
    mock_response.read.return_value = json.dumps({"results": []}).encode()
    mock_response.__enter__ = lambda s: s
    mock_response.__exit__ = MagicMock(return_value=False)
    mock_urlopen.return_value = mock_response

    _execute_exa_search(
        {
            "query": "python cli tool",
            "exclude_text": "awesome list",
        }
    )
    request_obj = mock_urlopen.call_args[0][0]
    sent_body = json.loads(request_obj.data)
    assert "excludeText" in sent_body
    assert "exclude_text" not in sent_body


def test_exa_http_error(mock_urlopen: MagicMock, mock_secrets_manager: MagicMock) -> None:
    from lambdas.discovery.handler import _execute_exa_search

    mock_urlopen.side_effect = HTTPError(
        url="https://api.exa.ai/search",
        code=429,
        msg="Too Many Requests",
        hdrs=None,
        fp=None,  # type: ignore[arg-type]
    )
    result = _execute_exa_search({"query": "test"})
    assert "error" in result


# ---------------------------------------------------------------------------
# Tool Dispatcher Tests
# ---------------------------------------------------------------------------


def test_tool_dispatcher_routes_exa() -> None:
    from lambdas.discovery.handler import _execute_tool

    with patch(
        "lambdas.discovery.handler._execute_exa_search", return_value={"results": []}
    ) as mock:
        result_str = _execute_tool("exa_search", {"query": "test"})
        mock.assert_called_once_with({"query": "test"})
        assert json.loads(result_str) == {"results": []}


def test_tool_dispatcher_routes_postgres() -> None:
    from lambdas.discovery.handler import _execute_tool

    with patch(
        "lambdas.discovery.handler._execute_query_postgres", return_value={"rows": "ok"}
    ) as mock:
        result_str = _execute_tool("query_postgres", {"sql": "SELECT 1;"})
        mock.assert_called_once()
        assert json.loads(result_str) == {"rows": "ok"}


def test_tool_dispatcher_routes_github() -> None:
    from lambdas.discovery.handler import _execute_tool

    with patch(
        "lambdas.discovery.handler._execute_get_github_repo", return_value={"name": "r"}
    ) as mock:
        result_str = _execute_tool("get_github_repo", {"owner": "u", "repo": "r"})
        mock.assert_called_once()


def test_tool_dispatcher_unknown_tool() -> None:
    from lambdas.discovery.handler import _execute_tool

    result = json.loads(_execute_tool("nonexistent_tool", {}))
    assert "error" in result
    assert "nonexistent_tool" in result["error"]


# ---------------------------------------------------------------------------
# Full Handler Tests
# ---------------------------------------------------------------------------


VALID_HANDLER_OUTPUT = json.dumps(
    {
        "repo_url": "https://github.com/someone/something",
        "repo_name": "something",
        "repo_description": "A cool project",
        "developer_github": "someone",
        "star_count": 3,
        "language": "Go",
        "discovery_rationale": "Interesting CLI tool.",
        "key_files": ["main.go"],
        "technical_highlights": ["Single-binary design"],
    }
)


def test_handler_returns_valid_output(
    pipeline_metadata: dict,
    lambda_context: MagicMock,
    mock_invoke_with_tools: MagicMock,
) -> None:
    mock_invoke_with_tools.return_value = VALID_HANDLER_OUTPUT
    with patch("lambdas.discovery.handler._load_system_prompt", return_value="sp"):
        from lambdas.discovery.handler import lambda_handler

        result = lambda_handler({"metadata": pipeline_metadata}, lambda_context)
    assert result["repo_url"] == "https://github.com/someone/something"
    assert isinstance(result["star_count"], int)
    assert result["star_count"] < 10


def test_handler_passes_tools_and_executor(
    pipeline_metadata: dict,
    lambda_context: MagicMock,
    mock_invoke_with_tools: MagicMock,
) -> None:
    mock_invoke_with_tools.return_value = VALID_HANDLER_OUTPUT
    with patch("lambdas.discovery.handler._load_system_prompt", return_value="sp"):
        from lambdas.discovery.handler import lambda_handler

        lambda_handler({"metadata": pipeline_metadata}, lambda_context)
    call_kwargs = mock_invoke_with_tools.call_args
    tools = call_kwargs.kwargs.get("tools", call_kwargs[1].get("tools"))
    assert len(tools) == 3
    tool_names = {t["name"] for t in tools}
    assert tool_names == {"exa_search", "query_postgres", "get_github_repo"}
    executor = call_kwargs.kwargs.get("tool_executor", call_kwargs[1].get("tool_executor"))
    assert callable(executor)


def test_handler_rejects_high_star_count(
    pipeline_metadata: dict,
    lambda_context: MagicMock,
    mock_invoke_with_tools: MagicMock,
) -> None:
    bad = json.loads(VALID_HANDLER_OUTPUT)
    bad["star_count"] = 15
    mock_invoke_with_tools.return_value = json.dumps(bad)
    with patch("lambdas.discovery.handler._load_system_prompt", return_value="sp"):
        from lambdas.discovery.handler import lambda_handler

        with pytest.raises(ValueError, match="star_count"):
            lambda_handler({"metadata": pipeline_metadata}, lambda_context)


def test_handler_handles_fenced_output(
    pipeline_metadata: dict,
    lambda_context: MagicMock,
    mock_invoke_with_tools: MagicMock,
) -> None:
    mock_invoke_with_tools.return_value = f"```json\n{VALID_HANDLER_OUTPUT}\n```"
    with patch("lambdas.discovery.handler._load_system_prompt", return_value="sp"):
        from lambdas.discovery.handler import lambda_handler

        result = lambda_handler({"metadata": pipeline_metadata}, lambda_context)
    assert result["repo_name"] == "something"
