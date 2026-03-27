> Part of the [Implementation Spec](../../IMPLEMENTATION_SPEC.md)

# Testing

Tests use pytest with two tiers: unit tests (mocked dependencies, fast, run in CI) and integration tests (real AWS services, run manually).

### Directory Structure

```
tests/
├── __init__.py
├── conftest.py              # Shared fixtures used by all tests
├── unit/
│   ├── __init__.py
│   ├── test_discovery.py    # One test file per Lambda handler
│   ├── test_research.py
│   ├── test_script.py
│   ├── test_producer.py
│   ├── test_cover_art.py
│   ├── test_tts.py
│   ├── test_post_production.py
│   ├── test_site.py
│   ├── test_shared/         # Tests for shared layer modules
│   │   ├── __init__.py
│   │   ├── test_bedrock.py
│   │   ├── test_db.py
│   │   └── test_s3.py
│   └── test_mcp/            # MCP server tool tests
│       ├── __init__.py
│       ├── conftest.py
│       ├── test_pipeline.py
│       ├── test_agents.py
│       ├── test_observation.py
│       ├── test_data.py
│       ├── test_assets.py
│       ├── test_site.py
│       ├── test_resources.py
│       └── test_handler.py
├── integration/
│   ├── __init__.py
│   ├── test_bedrock_live.py
│   ├── test_s3_live.py
│   ├── test_db_live.py
│   ├── test_mcp_pipeline_live.py
│   ├── test_mcp_data_live.py
│   ├── test_mcp_assets_live.py
│   └── test_research_live.py
└── e2e/
    ├── __init__.py
    ├── test_discovery_e2e.py
    ├── test_research_e2e.py
    └── test_mcp_e2e.py
```

**Naming convention:** `test_{lambda_name}.py` for handler tests, `test_{module}.py` for shared module tests. Test functions: `test_{behavior}_{scenario}` (e.g., `test_discovery_excludes_featured_developers`, `test_script_output_under_character_limit`).

### pytest Configuration

In `pyproject.toml`:

```toml
[tool.pytest.ini_options]
testpaths = ["tests"]
python_files = "test_*.py"
python_functions = "test_*"
markers = [
    "integration: hits real AWS services (deselect with '-m not integration')",
    "e2e: end-to-end tests that cost money (Bedrock, Exa, ElevenLabs). Run manually.",
]
```

Run locally:
```bash
# Unit tests only (default for development and CI)
PYTHONPATH=lambdas/shared/python pytest tests/unit/ -v

# Integration tests (requires AWS credentials)
PYTHONPATH=lambdas/shared/python pytest tests/integration/ -v -m integration

# E2E tests (costs money — run manually)
PYTHONPATH=lambdas/shared/python pytest tests/e2e/ -v -m e2e

# All tests with coverage
PYTHONPATH=lambdas/shared/python pytest -v --cov=lambdas --cov-report=term-missing
```

### Shared Fixtures (`conftest.py`)

```python
import json
import subprocess
from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture
def pipeline_metadata() -> dict:
    return {
        "execution_id": "arn:aws:states:us-east-1:123456789:execution:zerostars-pipeline:test-run",
        "script_attempt": 1,
    }


@pytest.fixture
def lambda_context() -> MagicMock:
    ctx = MagicMock()
    ctx.function_name = "test-function"
    ctx.memory_limit_in_mb = 512
    ctx.invoked_function_arn = "arn:aws:lambda:us-east-1:123456789:function:test"
    ctx.aws_request_id = "test-request-id"
    return ctx


@pytest.fixture
def mock_bedrock_client():
    """Patches the Bedrock Runtime boto3 client used by shared/bedrock.py.

    Used by handler tests that call invoke_model directly (Script, Producer,
    Cover Art). Discovery and Research handlers should mock invoke_with_tools
    instead — see mock_invoke_with_tools fixture.
    """
    with patch("shared.bedrock.boto3.client") as mock:
        client = MagicMock()
        mock.return_value = client
        yield client


@pytest.fixture
def mock_invoke_with_tools():
    """Patches shared.bedrock.invoke_with_tools for Discovery handler tests.

    Discovery and Research handlers call invoke_with_tools (not the raw
    Bedrock client). This fixture patches invoke_with_tools at the handler's
    import site so the handler's tool_executor callback is never called.

    Usage:
        def test_discovery(mock_invoke_with_tools, ...):
            mock_invoke_with_tools.return_value = json.dumps({...})
            result = lambda_handler(event, context)
    """
    with patch("lambdas.discovery.handler.invoke_with_tools") as mock:
        yield mock


@pytest.fixture
def mock_db_connection():
    """Patches psycopg2.connect in shared/db.py.

    Used by handlers that access Postgres via the shared db module
    (Post-Production, Site). NOT used by Discovery — Discovery
    uses psql subprocess, not psycopg2. See mock_subprocess fixture.
    """
    with patch("shared.db.psycopg2.connect") as mock:
        conn = MagicMock()
        cursor = MagicMock()
        conn.cursor.return_value = cursor
        mock.return_value = conn
        yield conn


@pytest.fixture
def mock_ssm():
    """Patches boto3 SSM client for Discovery handler's _get_db_connection_string.

    Returns a mock SSM client whose get_parameter returns a test connection string.
    Also resets the module-level _db_connection_string cache to None.
    """
    with patch("lambdas.discovery.handler.boto3") as mock_boto3:
        ssm_client = MagicMock()
        ssm_client.get_parameter.return_value = {
            "Parameter": {"Value": "postgresql://test:test@localhost:5432/zerostars?sslmode=require"}
        }
        mock_boto3.client.return_value = ssm_client
        with patch("lambdas.discovery.handler._db_connection_string", None):
            yield ssm_client


@pytest.fixture
def mock_secrets_manager():
    """Patches boto3 Secrets Manager client for Discovery handler's _get_exa_api_key.

    Returns a mock whose get_secret_value returns a test Exa API key.
    Also resets the module-level _exa_api_key cache to None.
    """
    with patch("lambdas.discovery.handler.boto3") as mock_boto3:
        sm_client = MagicMock()
        sm_client.get_secret_value.return_value = {"SecretString": "test-exa-api-key-000"}
        mock_boto3.client.return_value = sm_client
        with patch("lambdas.discovery.handler._exa_api_key", None):
            yield sm_client


@pytest.fixture
def mock_subprocess():
    """Patches subprocess.run for Discovery handler's _execute_query_postgres.

    Usage:
        def test_psql_select(mock_subprocess):
            mock_subprocess.return_value = subprocess.CompletedProcess(
                args=[], returncode=0, stdout="row1\nrow2\n", stderr=""
            )
    """
    with patch("lambdas.discovery.handler.subprocess.run") as mock:
        yield mock


@pytest.fixture
def mock_urlopen():
    """Patches urllib.request.urlopen for Exa and GitHub API calls.

    The mock's return value acts as a context manager (matching urlopen's real behavior).

    Usage:
        def test_github(mock_urlopen):
            mock_response = MagicMock()
            mock_response.read.return_value = json.dumps({...}).encode()
            mock_response.__enter__ = lambda s: s
            mock_response.__exit__ = MagicMock(return_value=False)
            mock_urlopen.return_value = mock_response
    """
    with patch("lambdas.discovery.handler.urllib.request.urlopen") as mock:
        yield mock


@pytest.fixture
def sample_discovery_output() -> dict:
    return {
        "repo_url": "https://github.com/testuser/testrepo",
        "repo_name": "testrepo",
        "repo_description": "A test repository",
        "developer_github": "testuser",
        "star_count": 7,
        "language": "Python",
        "discovery_rationale": "Interesting project with clean architecture.",
        "key_files": ["README.md", "src/main.py"],
        "technical_highlights": ["Clean architecture"],
    }


@pytest.fixture
def sample_research_output() -> dict:
    return {
        "developer_name": "Test User",
        "developer_github": "testuser",
        "developer_bio": "Builds things.",
        "public_repos_count": 15,
        "notable_repos": [
            {"name": "testrepo", "description": "A test repo", "stars": 7, "language": "Python"}
        ],
        "commit_patterns": "Active on weekends",
        "technical_profile": "Python, Rust",
        "interesting_findings": ["Built a custom ORM"],
        "hiring_signals": ["Strong fundamentals"],
    }


@pytest.fixture
def sample_script_output() -> dict:
    return {
        "text": (
            "**Hype:** Welcome to 0 Stars, 10 out of 10!\n"
            "**Roast:** Here we go again.\n"
            "**Phil:** But what does it mean to welcome?"
        ),
        "character_count": 107,
        "segments": [
            "intro", "core_debate", "developer_deep_dive",
            "technical_appreciation", "hiring_manager", "outro",
        ],
        "featured_repo": "testrepo",
        "featured_developer": "testuser",
        "cover_art_suggestion": "A terminal with colorful output",
    }


@pytest.fixture
def mock_research_invoke_with_tools():
    """Patches shared.bedrock.invoke_with_tools for Research handler tests.

    Research handler calls invoke_with_tools (not the raw Bedrock client).
    This fixture patches invoke_with_tools at the Research handler's import
    site so the handler's tool_executor callback is never called.

    Usage:
        def test_research(mock_research_invoke_with_tools, ...):
            mock_research_invoke_with_tools.return_value = json.dumps({...})
            result = lambda_handler(event, context)
    """
    with patch("lambdas.research.handler.invoke_with_tools") as mock:
        yield mock


@pytest.fixture
def mock_research_urlopen():
    """Patches urllib.request.urlopen for Research handler's GitHub API calls.

    The mock's return value acts as a context manager (matching urlopen's real behavior).

    Usage:
        def test_github_user(mock_research_urlopen):
            mock_response = MagicMock()
            mock_response.read.return_value = json.dumps({...}).encode()
            mock_response.__enter__ = lambda s: s
            mock_response.__exit__ = MagicMock(return_value=False)
            mock_research_urlopen.return_value = mock_response
    """
    with patch("lambdas.research.handler.urllib.request.urlopen") as mock:
        yield mock


@pytest.fixture
def discovery_output_for_research() -> dict:
    """Discovery output fixture used as input to the Research handler.

    Placed at $.discovery in the pipeline state event.
    """
    return {
        "repo_url": "https://github.com/testuser/testrepo",
        "repo_name": "testrepo",
        "repo_description": "A test repository",
        "developer_github": "testuser",
        "star_count": 7,
        "language": "Python",
        "discovery_rationale": "Interesting project with clean architecture.",
        "key_files": ["README.md", "src/main.py"],
        "technical_highlights": ["Clean architecture"],
    }
```

### Mocking Strategy

| Dependency | Unit test approach | Integration test approach |
|-----------|-------------------|-------------------------|
| Bedrock (invoke_model) | `unittest.mock` — patch `boto3.client("bedrock-runtime")` return values. moto does not support Bedrock. | Real Bedrock calls with dev AWS credentials. |
| Bedrock (invoke_with_tools) | `unittest.mock` — patch `invoke_with_tools` at the handler's import path (e.g., `lambdas.discovery.handler.invoke_with_tools`). | Real Bedrock calls (see E2E tests). |
| S3 | `moto` `@mock_aws` decorator — creates in-memory S3. | Real S3 bucket in dev account with `test/` key prefix. |
| Postgres (shared/db.py) | `unittest.mock` — patch `psycopg2.connect`, mock cursor `fetchall`/`execute`. | Real dev RDS instance. |
| Postgres (Discovery/psql) | `unittest.mock` — patch `subprocess.run` in `lambdas.discovery.handler`. | Real psql against dev RDS (see Discovery integration tests). |
| SSM Parameter Store | `unittest.mock` — patch `boto3` in `lambdas.discovery.handler`, mock `get_parameter` return value. Reset module-level `_db_connection_string` cache. | Real SSM parameter `/zerostars/db-connection-string` in dev account. |
| Secrets Manager (Exa key) | `unittest.mock` — patch `boto3` in `lambdas.discovery.handler`, mock `get_secret_value` return value. Reset module-level `_exa_api_key` cache. | Skip — uses real secret, tested transitively via E2E. |
| Exa API | `unittest.mock` — patch `urllib.request.urlopen`. | Skip — costs money per query. |
| ElevenLabs | `unittest.mock` — patch `urllib.request.urlopen`. | Skip — costs money per call. |
| GitHub API (Discovery) | `unittest.mock` — patch `urllib.request.urlopen` in `lambdas.discovery.handler`. | Real public API (unauthenticated, 60 req/hour). |
| GitHub API (Research) | `unittest.mock` — patch `urllib.request.urlopen` in `lambdas.research.handler`. | Real public API (unauthenticated, 60 req/hour). |

### Unit Test Pattern

Tests for the Discovery handler (`tests/unit/test_discovery.py`). These demonstrate the test patterns for all Discovery-specific behaviors — output parsing, tool functions, the dispatcher, and the full handler. Other handlers follow the same structure with their own fixtures.

#### Output Parsing Tests

```python
import json
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


def test_parse_valid_json():
    result = _parse_discovery_output(json.dumps(VALID_OUTPUT))
    assert result["repo_url"] == "https://github.com/someone/something"
    assert result["star_count"] == 3


def test_parse_fenced_json():
    fenced = f"```json\n{json.dumps(VALID_OUTPUT)}\n```"
    result = _parse_discovery_output(fenced)
    assert result["repo_name"] == "something"


def test_parse_fenced_no_language_tag():
    fenced = f"```\n{json.dumps(VALID_OUTPUT)}\n```"
    result = _parse_discovery_output(fenced)
    assert result["repo_name"] == "something"


def test_parse_rejects_star_count_gte_10():
    bad = {**VALID_OUTPUT, "star_count": 10}
    with pytest.raises(ValueError, match="star_count"):
        _parse_discovery_output(json.dumps(bad))


def test_parse_coerces_string_star_count():
    coerced = {**VALID_OUTPUT, "star_count": "3"}
    result = _parse_discovery_output(json.dumps(coerced))
    assert result["star_count"] == 3
    assert isinstance(result["star_count"], int)


def test_parse_rejects_missing_field():
    incomplete = {k: v for k, v in VALID_OUTPUT.items() if k != "repo_url"}
    with pytest.raises(ValueError, match="repo_url"):
        _parse_discovery_output(json.dumps(incomplete))


def test_parse_rejects_invalid_repo_url():
    bad = {**VALID_OUTPUT, "repo_url": "https://gitlab.com/someone/something"}
    with pytest.raises(ValueError, match="repo_url"):
        _parse_discovery_output(json.dumps(bad))


def test_parse_rejects_invalid_json():
    with pytest.raises((ValueError, json.JSONDecodeError)):
        _parse_discovery_output("this is not json at all")
```

#### psql Tool Tests

```python
import subprocess

def test_psql_select_allowed(mock_subprocess, mock_ssm):
    from lambdas.discovery.handler import _execute_query_postgres
    mock_subprocess.return_value = subprocess.CompletedProcess(
        args=[], returncode=0, stdout="user1\nuser2\n", stderr=""
    )
    result = _execute_query_postgres({"sql": "SELECT developer_github FROM featured_developers;"})
    assert "rows" in result
    assert "user1" in result["rows"]


def test_psql_rejects_insert(mock_ssm):
    from lambdas.discovery.handler import _execute_query_postgres
    result = _execute_query_postgres({"sql": "INSERT INTO episodes VALUES (1, 'x');"})
    assert "error" in result


def test_psql_rejects_delete(mock_ssm):
    from lambdas.discovery.handler import _execute_query_postgres
    result = _execute_query_postgres({"sql": "DELETE FROM episodes;"})
    assert "error" in result


def test_psql_rejects_drop(mock_ssm):
    from lambdas.discovery.handler import _execute_query_postgres
    result = _execute_query_postgres({"sql": "DROP TABLE episodes;"})
    assert "error" in result


def test_psql_rejects_update(mock_ssm):
    from lambdas.discovery.handler import _execute_query_postgres
    result = _execute_query_postgres({"sql": "UPDATE episodes SET repo_name = 'x';"})
    assert "error" in result


def test_psql_leading_whitespace_select(mock_subprocess, mock_ssm):
    from lambdas.discovery.handler import _execute_query_postgres
    mock_subprocess.return_value = subprocess.CompletedProcess(
        args=[], returncode=0, stdout="ok\n", stderr=""
    )
    result = _execute_query_postgres({"sql": "   SELECT 1;"})
    assert "rows" in result


def test_psql_error_returns_stderr(mock_subprocess, mock_ssm):
    from lambdas.discovery.handler import _execute_query_postgres
    mock_subprocess.return_value = subprocess.CompletedProcess(
        args=[], returncode=1, stdout="", stderr="ERROR: relation does not exist"
    )
    result = _execute_query_postgres({"sql": "SELECT * FROM nonexistent;"})
    assert "error" in result
    assert "relation" in result["error"]


def test_psql_timeout_returns_error(mock_subprocess, mock_ssm):
    from lambdas.discovery.handler import _execute_query_postgres
    mock_subprocess.side_effect = subprocess.TimeoutExpired(cmd="psql", timeout=15)
    result = _execute_query_postgres({"sql": "SELECT pg_sleep(999);"})
    assert "error" in result
```

#### GitHub and Exa Tool Tests

```python
import json
from unittest.mock import MagicMock
from urllib.error import HTTPError


def test_github_returns_curated_fields(mock_urlopen):
    from lambdas.discovery.handler import _execute_get_github_repo
    github_response = {
        "name": "testrepo", "full_name": "testuser/testrepo",
        "description": "A test repo", "stargazers_count": 5,
        "forks_count": 1, "language": "Python", "topics": ["cli"],
        "created_at": "2024-01-01T00:00:00Z", "pushed_at": "2024-12-01T00:00:00Z",
        "open_issues_count": 0, "license": {"spdx_id": "MIT"},
        "owner": {"type": "User"}, "html_url": "https://github.com/testuser/testrepo",
        "default_branch": "main",
        "id": 123456, "node_id": "R_abc123", "size": 1024,  # should be filtered out
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


def test_github_null_license(mock_urlopen):
    from lambdas.discovery.handler import _execute_get_github_repo
    github_response = {
        "name": "proj", "full_name": "u/proj", "description": None,
        "stargazers_count": 0, "forks_count": 0, "language": None,
        "topics": [], "created_at": "2024-01-01T00:00:00Z",
        "pushed_at": "2024-01-01T00:00:00Z", "open_issues_count": 0,
        "license": None, "owner": {"type": "User"},
        "html_url": "https://github.com/u/proj", "default_branch": "main",
    }
    mock_response = MagicMock()
    mock_response.read.return_value = json.dumps(github_response).encode()
    mock_response.__enter__ = lambda s: s
    mock_response.__exit__ = MagicMock(return_value=False)
    mock_urlopen.return_value = mock_response

    result = _execute_get_github_repo({"owner": "u", "repo": "proj"})
    assert result["license"] is None


def test_github_http_error(mock_urlopen):
    from lambdas.discovery.handler import _execute_get_github_repo
    mock_urlopen.side_effect = HTTPError(
        url="https://api.github.com/repos/x/y",
        code=404, msg="Not Found", hdrs=None, fp=None,  # type: ignore[arg-type]
    )
    result = _execute_get_github_repo({"owner": "x", "repo": "y"})
    assert "error" in result


def test_exa_snake_to_camel_mapping(mock_urlopen, mock_secrets_manager):
    from lambdas.discovery.handler import _execute_exa_search
    mock_response = MagicMock()
    mock_response.read.return_value = json.dumps({"results": []}).encode()
    mock_response.__enter__ = lambda s: s
    mock_response.__exit__ = MagicMock(return_value=False)
    mock_urlopen.return_value = mock_response

    _execute_exa_search({
        "query": "python cli tool",
        "include_domains": ["github.com"],
        "num_results": 5,
        "start_published_date": "2024-01-01",
    })
    request_obj = mock_urlopen.call_args[0][0]
    sent_body = json.loads(request_obj.data)
    assert "includeDomains" in sent_body
    assert "numResults" in sent_body
    assert "startPublishedDate" in sent_body
    assert "include_domains" not in sent_body


def test_exa_http_error(mock_urlopen, mock_secrets_manager):
    from lambdas.discovery.handler import _execute_exa_search
    mock_urlopen.side_effect = HTTPError(
        url="https://api.exa.ai/search",
        code=429, msg="Too Many Requests", hdrs=None, fp=None,  # type: ignore[arg-type]
    )
    result = _execute_exa_search({"query": "test"})
    assert "error" in result
```

#### Tool Dispatcher Tests

```python
import json
from unittest.mock import patch


def test_tool_dispatcher_routes_exa():
    from lambdas.discovery.handler import _execute_tool
    with patch("lambdas.discovery.handler._execute_exa_search", return_value={"results": []}) as mock:
        result_str = _execute_tool("exa_search", {"query": "test"})
        mock.assert_called_once_with({"query": "test"})
        assert json.loads(result_str) == {"results": []}


def test_tool_dispatcher_routes_postgres():
    from lambdas.discovery.handler import _execute_tool
    with patch("lambdas.discovery.handler._execute_query_postgres", return_value={"rows": "ok"}) as mock:
        result_str = _execute_tool("query_postgres", {"sql": "SELECT 1;"})
        mock.assert_called_once()
        assert json.loads(result_str) == {"rows": "ok"}


def test_tool_dispatcher_routes_github():
    from lambdas.discovery.handler import _execute_tool
    with patch("lambdas.discovery.handler._execute_get_github_repo", return_value={"name": "r"}) as mock:
        result_str = _execute_tool("get_github_repo", {"owner": "u", "repo": "r"})
        mock.assert_called_once()


def test_tool_dispatcher_unknown_tool():
    from lambdas.discovery.handler import _execute_tool
    result = json.loads(_execute_tool("nonexistent_tool", {}))
    assert "error" in result
    assert "nonexistent_tool" in result["error"]
```

#### Full Handler Tests

```python
import json
from unittest.mock import patch

VALID_HANDLER_OUTPUT = json.dumps({
    "repo_url": "https://github.com/someone/something",
    "repo_name": "something",
    "repo_description": "A cool project",
    "developer_github": "someone",
    "star_count": 3,
    "language": "Go",
    "discovery_rationale": "Interesting CLI tool.",
    "key_files": ["main.go"],
    "technical_highlights": ["Single-binary design"],
})


def test_handler_returns_valid_output(pipeline_metadata, lambda_context, mock_invoke_with_tools):
    mock_invoke_with_tools.return_value = VALID_HANDLER_OUTPUT
    with patch("lambdas.discovery.handler._load_system_prompt", return_value="sp"):
        from lambdas.discovery.handler import lambda_handler
        result = lambda_handler({"metadata": pipeline_metadata}, lambda_context)
    assert result["repo_url"] == "https://github.com/someone/something"
    assert isinstance(result["star_count"], int)
    assert result["star_count"] < 10


def test_handler_passes_tools_and_executor(pipeline_metadata, lambda_context, mock_invoke_with_tools):
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


def test_handler_rejects_high_star_count(pipeline_metadata, lambda_context, mock_invoke_with_tools):
    bad = json.loads(VALID_HANDLER_OUTPUT)
    bad["star_count"] = 15
    mock_invoke_with_tools.return_value = json.dumps(bad)
    with patch("lambdas.discovery.handler._load_system_prompt", return_value="sp"):
        from lambdas.discovery.handler import lambda_handler
        import pytest
        with pytest.raises(ValueError, match="star_count"):
            lambda_handler({"metadata": pipeline_metadata}, lambda_context)


def test_handler_handles_fenced_output(pipeline_metadata, lambda_context, mock_invoke_with_tools):
    mock_invoke_with_tools.return_value = f"```json\n{VALID_HANDLER_OUTPUT}\n```"
    with patch("lambdas.discovery.handler._load_system_prompt", return_value="sp"):
        from lambdas.discovery.handler import lambda_handler
        result = lambda_handler({"metadata": pipeline_metadata}, lambda_context)
    assert result["repo_name"] == "something"
```

### Research Unit Tests

Tests for the Research handler (`tests/unit/test_research.py`). These follow the same structure as the Discovery tests above — output parsing, tool functions, dispatcher, and full handler.

#### Output Parsing Tests

```python
import json
import pytest

from lambdas.research.handler import _parse_research_output

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


def test_parse_valid_json():
    result = _parse_research_output(json.dumps(VALID_OUTPUT))
    assert result["developer_name"] == "Test User"
    assert result["public_repos_count"] == 15
    assert len(result["notable_repos"]) == 2


def test_parse_fenced_json():
    fenced = f"```json\n{json.dumps(VALID_OUTPUT)}\n```"
    result = _parse_research_output(fenced)
    assert result["developer_github"] == "testuser"


def test_parse_fenced_no_language_tag():
    fenced = f"```\n{json.dumps(VALID_OUTPUT)}\n```"
    result = _parse_research_output(fenced)
    assert result["developer_github"] == "testuser"


def test_parse_coerces_string_public_repos_count():
    coerced = {**VALID_OUTPUT, "public_repos_count": "15"}
    result = _parse_research_output(json.dumps(coerced))
    assert result["public_repos_count"] == 15
    assert isinstance(result["public_repos_count"], int)


def test_parse_coerces_null_bio_to_empty_string():
    null_bio = {**VALID_OUTPUT, "developer_bio": None}
    result = _parse_research_output(json.dumps(null_bio))
    assert result["developer_bio"] == ""
    assert isinstance(result["developer_bio"], str)


def test_parse_rejects_missing_field():
    incomplete = {k: v for k, v in VALID_OUTPUT.items() if k != "developer_github"}
    with pytest.raises(ValueError, match="developer_github"):
        _parse_research_output(json.dumps(incomplete))


def test_parse_rejects_invalid_json():
    with pytest.raises((ValueError, json.JSONDecodeError)):
        _parse_research_output("this is not json at all")


def test_parse_rejects_notable_repos_missing_required_field():
    bad_repo = {**VALID_OUTPUT, "notable_repos": [{"name": "repo"}]}  # missing description, stars, language
    with pytest.raises(ValueError, match="notable_repos"):
        _parse_research_output(json.dumps(bad_repo))


def test_parse_accepts_empty_notable_repos():
    """A developer with zero interesting repos should still pass parsing."""
    empty = {**VALID_OUTPUT, "notable_repos": [], "public_repos_count": 0}
    result = _parse_research_output(json.dumps(empty))
    assert result["notable_repos"] == []
```

#### GitHub Tool Tests

```python
import json
from unittest.mock import MagicMock
from urllib.error import HTTPError


def test_get_github_user_returns_curated_fields(mock_research_urlopen):
    from lambdas.research.handler import _execute_get_github_user
    github_response = {
        "login": "testuser", "name": "Test User", "bio": "I build things.",
        "public_repos": 15, "followers": 3, "created_at": "2020-01-01T00:00:00Z",
        "html_url": "https://github.com/testuser",
        "id": 123456, "node_id": "U_abc123", "avatar_url": "https://...",  # should be filtered
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


def test_get_github_user_null_name(mock_research_urlopen):
    from lambdas.research.handler import _execute_get_github_user
    github_response = {
        "login": "anon", "name": None, "bio": None,
        "public_repos": 2, "followers": 0, "created_at": "2024-06-01T00:00:00Z",
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


def test_get_github_user_http_error(mock_research_urlopen):
    from lambdas.research.handler import _execute_get_github_user
    mock_research_urlopen.side_effect = HTTPError(
        url="https://api.github.com/users/x",
        code=404, msg="Not Found", hdrs=None, fp=None,  # type: ignore[arg-type]
    )
    result = _execute_get_github_user({"username": "x"})
    assert "error" in result


def test_get_github_user_timeout(mock_research_urlopen):
    from lambdas.research.handler import _execute_get_github_user
    import socket
    mock_research_urlopen.side_effect = socket.timeout("timed out")
    result = _execute_get_github_user({"username": "x"})
    assert "error" in result


def test_get_user_repos_returns_curated_array(mock_research_urlopen):
    from lambdas.research.handler import _execute_get_user_repos
    github_response = [
        {
            "name": "repo1", "description": "First repo", "stargazers_count": 3,
            "language": "Python", "html_url": "https://github.com/u/repo1",
            "pushed_at": "2024-11-01T00:00:00Z", "fork": False,
            "id": 111, "node_id": "R_111", "size": 500,  # should be filtered
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


def test_get_user_repos_http_error(mock_research_urlopen):
    from lambdas.research.handler import _execute_get_user_repos
    mock_research_urlopen.side_effect = HTTPError(
        url="https://api.github.com/users/x/repos",
        code=403, msg="Forbidden", hdrs=None, fp=None,  # type: ignore[arg-type]
    )
    result = _execute_get_user_repos({"username": "x"})
    assert "error" in result


def test_get_repo_details_returns_curated_fields(mock_research_urlopen):
    from lambdas.research.handler import _execute_get_repo_details
    github_response = {
        "name": "testrepo", "full_name": "testuser/testrepo",
        "description": "A test repo", "stargazers_count": 7,
        "forks_count": 1, "language": "Python", "topics": ["cli", "tool"],
        "created_at": "2024-01-01T00:00:00Z", "updated_at": "2024-12-01T00:00:00Z",
        "html_url": "https://github.com/testuser/testrepo",
        "id": 999, "size": 2048,  # should be filtered
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


def test_get_repo_details_null_description(mock_research_urlopen):
    from lambdas.research.handler import _execute_get_repo_details
    github_response = {
        "name": "bare", "full_name": "u/bare", "description": None,
        "stargazers_count": 0, "forks_count": 0, "language": None,
        "topics": [], "created_at": "2024-01-01T00:00:00Z",
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


def test_get_repo_details_http_error(mock_research_urlopen):
    from lambdas.research.handler import _execute_get_repo_details
    mock_research_urlopen.side_effect = HTTPError(
        url="https://api.github.com/repos/x/y",
        code=404, msg="Not Found", hdrs=None, fp=None,  # type: ignore[arg-type]
    )
    result = _execute_get_repo_details({"owner": "x", "repo": "y"})
    assert "error" in result


def test_get_repo_readme_returns_decoded_content(mock_research_urlopen):
    from lambdas.research.handler import _execute_get_repo_readme
    import base64
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


def test_get_repo_readme_404_returns_error(mock_research_urlopen):
    from lambdas.research.handler import _execute_get_repo_readme
    mock_research_urlopen.side_effect = HTTPError(
        url="https://api.github.com/repos/x/y/readme",
        code=404, msg="Not Found", hdrs=None, fp=None,  # type: ignore[arg-type]
    )
    result = _execute_get_repo_readme({"owner": "x", "repo": "y"})
    assert "error" in result


def test_search_repositories_returns_curated_results(mock_research_urlopen):
    from lambdas.research.handler import _execute_search_repositories
    github_response = {
        "total_count": 2,
        "items": [
            {
                "name": "repo1", "full_name": "u/repo1", "description": "First",
                "stargazers_count": 3, "language": "Python",
                "html_url": "https://github.com/u/repo1",
                "id": 111, "score": 1.0,  # should be filtered
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


def test_search_repositories_http_error(mock_research_urlopen):
    from lambdas.research.handler import _execute_search_repositories
    mock_research_urlopen.side_effect = HTTPError(
        url="https://api.github.com/search/repositories",
        code=422, msg="Validation Failed", hdrs=None, fp=None,  # type: ignore[arg-type]
    )
    result = _execute_search_repositories({"query": "user:x"})
    assert "error" in result
```

#### Tool Dispatcher Tests

```python
import json
from unittest.mock import patch


def test_tool_dispatcher_routes_get_github_user():
    from lambdas.research.handler import _execute_tool
    with patch("lambdas.research.handler._execute_get_github_user",
               return_value={"login": "u"}) as mock:
        result_str = _execute_tool("get_github_user", {"username": "u"})
        mock.assert_called_once_with({"username": "u"})
        assert json.loads(result_str) == {"login": "u"}


def test_tool_dispatcher_routes_get_user_repos():
    from lambdas.research.handler import _execute_tool
    with patch("lambdas.research.handler._execute_get_user_repos",
               return_value=[{"name": "r"}]) as mock:
        result_str = _execute_tool("get_user_repos", {"username": "u"})
        mock.assert_called_once()
        assert json.loads(result_str) == [{"name": "r"}]


def test_tool_dispatcher_routes_get_repo_details():
    from lambdas.research.handler import _execute_tool
    with patch("lambdas.research.handler._execute_get_repo_details",
               return_value={"name": "r"}) as mock:
        result_str = _execute_tool("get_repo_details", {"owner": "u", "repo": "r"})
        mock.assert_called_once()


def test_tool_dispatcher_routes_get_repo_readme():
    from lambdas.research.handler import _execute_tool
    with patch("lambdas.research.handler._execute_get_repo_readme",
               return_value={"content": "# README"}) as mock:
        result_str = _execute_tool("get_repo_readme", {"owner": "u", "repo": "r"})
        mock.assert_called_once()


def test_tool_dispatcher_routes_search_repositories():
    from lambdas.research.handler import _execute_tool
    with patch("lambdas.research.handler._execute_search_repositories",
               return_value={"total_count": 0, "items": []}) as mock:
        result_str = _execute_tool("search_repositories", {"query": "user:u"})
        mock.assert_called_once()


def test_tool_dispatcher_unknown_tool():
    from lambdas.research.handler import _execute_tool
    result = json.loads(_execute_tool("nonexistent_tool", {}))
    assert "error" in result
    assert "nonexistent_tool" in result["error"]
```

#### Full Handler Tests

```python
import json
from unittest.mock import patch

import pytest

VALID_HANDLER_OUTPUT = json.dumps({
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
})


def test_handler_returns_valid_output(
    pipeline_metadata, lambda_context, mock_research_invoke_with_tools, discovery_output_for_research,
):
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
    pipeline_metadata, lambda_context, mock_research_invoke_with_tools, discovery_output_for_research,
):
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
        "get_github_user", "get_user_repos", "get_repo_details",
        "get_repo_readme", "search_repositories",
    }
    executor = call_kwargs.kwargs.get("tool_executor", call_kwargs[1].get("tool_executor"))
    assert callable(executor)


def test_handler_reads_discovery_fields_from_event(
    pipeline_metadata, lambda_context, mock_research_invoke_with_tools, discovery_output_for_research,
):
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
    pipeline_metadata, lambda_context, mock_research_invoke_with_tools, discovery_output_for_research,
):
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
    pipeline_metadata, lambda_context, mock_research_invoke_with_tools, discovery_output_for_research,
):
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
    pipeline_metadata, lambda_context, mock_research_invoke_with_tools, discovery_output_for_research,
):
    mock_research_invoke_with_tools.return_value = f"```json\n{VALID_HANDLER_OUTPUT}\n```"
    with patch("lambdas.research.handler._load_system_prompt", return_value="sp"):
        from lambdas.research.handler import lambda_handler
        result = lambda_handler(
            {"metadata": pipeline_metadata, "discovery": discovery_output_for_research},
            lambda_context,
        )
    assert result["developer_name"] == "Test User"


def test_handler_raises_on_agent_error(
    pipeline_metadata, lambda_context, mock_research_invoke_with_tools, discovery_output_for_research,
):
    mock_research_invoke_with_tools.side_effect = RuntimeError("max_turns exceeded")
    with patch("lambdas.research.handler._load_system_prompt", return_value="sp"):
        from lambdas.research.handler import lambda_handler
        with pytest.raises(RuntimeError, match="max_turns"):
            lambda_handler(
                {"metadata": pipeline_metadata, "discovery": discovery_output_for_research},
                lambda_context,
            )
```

### Integration Test Pattern

Integration tests hit real AWS services and external APIs. They are marked with `@pytest.mark.integration` and excluded from CI by default. They require real AWS credentials (configured via environment or `~/.aws`).

#### Generic Bedrock Integration Test (`tests/integration/test_bedrock_live.py`)

```python
import pytest


@pytest.mark.integration
def test_bedrock_invoke_model():
    """Verify Bedrock Claude invocation works with real credentials."""
    from shared.bedrock import invoke_model

    result = invoke_model(
        user_message="Respond with exactly: PING",
        system_prompt="You are a test helper. Respond with exactly what is asked.",
    )
    assert "PING" in result
```

#### Discovery Integration Tests (`tests/integration/test_discovery_live.py`)

These verify that Discovery's external dependencies are reachable and return expected data shapes.

```python
import json
import subprocess

import boto3
import pytest


@pytest.mark.integration
def test_psql_connects_to_zerostars_db():
    """psql can connect to the real zerostars database and query featured_developers."""
    ssm = boto3.client("ssm")
    response = ssm.get_parameter(Name="/zerostars/db-connection-string", WithDecryption=True)
    conn_str = response["Parameter"]["Value"]

    result = subprocess.run(
        ["psql", conn_str, "-c", "SELECT developer_github FROM featured_developers LIMIT 5;",
         "--no-align", "--tuples-only"],
        capture_output=True, text=True, timeout=15,
    )
    assert result.returncode == 0
    assert "ERROR" not in result.stderr


@pytest.mark.integration
def test_ssm_parameter_exists():
    """SSM parameter /zerostars/db-connection-string exists and is a SecureString."""
    ssm = boto3.client("ssm")
    response = ssm.get_parameter(Name="/zerostars/db-connection-string", WithDecryption=True)
    value = response["Parameter"]["Value"]
    assert value.startswith("postgresql://")


@pytest.mark.integration
def test_github_api_returns_expected_fields():
    """GitHub public API returns expected repo metadata fields for a known repo."""
    import urllib.request

    req = urllib.request.Request(
        "https://api.github.com/repos/python/cpython",
        headers={
            "Accept": "application/vnd.github.v3+json",
            "User-Agent": "zerostars-integration-test",
        },
    )
    with urllib.request.urlopen(req, timeout=15) as resp:
        data = json.loads(resp.read())

    for field in ["name", "full_name", "description", "stargazers_count",
                  "forks_count", "language", "topics", "created_at",
                  "pushed_at", "open_issues_count", "license", "owner",
                  "html_url", "default_branch"]:
        assert field in data, f"Expected field '{field}' missing from GitHub API response"


@pytest.mark.integration
@pytest.mark.skip(reason="Exa API costs money per query. Run manually when needed.")
def test_exa_search_returns_results():
    """Exa search API returns results for a GitHub-scoped query."""
    sm = boto3.client("secretsmanager")
    secret = sm.get_secret_value(SecretId="zerostars/exa-api-key")
    api_key = secret["SecretString"]

    import urllib.request

    body = json.dumps({
        "query": "python cli tool hobbyist project",
        "includeDomains": ["github.com"],
        "numResults": 3,
        "contents": {"text": True},
    }).encode()
    req = urllib.request.Request(
        "https://api.exa.ai/search",
        data=body,
        headers={"Content-Type": "application/json", "x-api-key": api_key},
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        data = json.loads(resp.read())
    assert "results" in data
    assert len(data["results"]) > 0
```

#### Research Integration Tests (`tests/integration/test_research_live.py`)

These verify that the GitHub API endpoints used by the Research handler return expected data shapes. All use the public (unauthenticated) API.

```python
import json

import pytest


@pytest.mark.integration
def test_github_user_api_returns_expected_fields():
    """GitHub public API returns expected user profile fields for a known user."""
    import urllib.request

    req = urllib.request.Request(
        "https://api.github.com/users/torvalds",
        headers={
            "Accept": "application/vnd.github.v3+json",
            "User-Agent": "zerostars-integration-test",
        },
    )
    with urllib.request.urlopen(req, timeout=15) as resp:
        data = json.loads(resp.read())

    for field in ["login", "name", "bio", "public_repos", "followers",
                  "created_at", "html_url"]:
        assert field in data, f"Expected field '{field}' missing from GitHub user API response"


@pytest.mark.integration
def test_github_user_repos_api_returns_array():
    """GitHub public API returns an array of repo objects for a known user."""
    import urllib.request

    req = urllib.request.Request(
        "https://api.github.com/users/torvalds/repos?sort=pushed&per_page=5",
        headers={
            "Accept": "application/vnd.github.v3+json",
            "User-Agent": "zerostars-integration-test",
        },
    )
    with urllib.request.urlopen(req, timeout=15) as resp:
        data = json.loads(resp.read())

    assert isinstance(data, list)
    assert len(data) > 0
    for field in ["name", "description", "stargazers_count", "language",
                  "html_url", "pushed_at", "fork"]:
        assert field in data[0], f"Expected field '{field}' missing from repo object"


@pytest.mark.integration
def test_github_repo_details_api_returns_expected_fields():
    """GitHub public API returns expected repo detail fields for a known repo."""
    import urllib.request

    req = urllib.request.Request(
        "https://api.github.com/repos/python/cpython",
        headers={
            "Accept": "application/vnd.github.v3+json",
            "User-Agent": "zerostars-integration-test",
        },
    )
    with urllib.request.urlopen(req, timeout=15) as resp:
        data = json.loads(resp.read())

    for field in ["name", "full_name", "description", "stargazers_count",
                  "forks_count", "language", "topics", "created_at",
                  "updated_at", "html_url"]:
        assert field in data, f"Expected field '{field}' missing from GitHub repo API response"


@pytest.mark.integration
def test_github_readme_api_returns_base64_content():
    """GitHub public API returns base64-encoded README content for a known repo."""
    import urllib.request

    req = urllib.request.Request(
        "https://api.github.com/repos/python/cpython/readme",
        headers={
            "Accept": "application/vnd.github.v3+json",
            "User-Agent": "zerostars-integration-test",
        },
    )
    with urllib.request.urlopen(req, timeout=15) as resp:
        data = json.loads(resp.read())

    assert "content" in data
    assert data.get("encoding") == "base64"

    import base64
    decoded = base64.b64decode(data["content"]).decode()
    assert len(decoded) > 0


@pytest.mark.integration
def test_github_search_api_returns_expected_structure():
    """GitHub search API returns total_count and items array."""
    import urllib.request

    req = urllib.request.Request(
        "https://api.github.com/search/repositories?q=user:torvalds&per_page=3",
        headers={
            "Accept": "application/vnd.github.v3+json",
            "User-Agent": "zerostars-integration-test",
        },
    )
    with urllib.request.urlopen(req, timeout=15) as resp:
        data = json.loads(resp.read())

    assert "total_count" in data
    assert "items" in data
    assert isinstance(data["items"], list)
```

**Resource isolation:** Integration tests must use unique prefixes for S3 keys and DB test data (e.g., the GitHub Actions run ID or commit SHA) to prevent conflicts when multiple CI runs execute in parallel. Clean up test resources in a `finally` block or pytest `teardown` fixture.

### End-to-End Tests

End-to-end tests invoke a full Lambda handler locally with real external dependencies (real Bedrock, real API keys, real database). They verify that the entire handler path works — from input event through tool use to parsed output. E2E tests are expensive (Bedrock + Exa API calls) and slow (30-90 seconds per run), so they are run manually, not in CI.

E2E tests live in `tests/e2e/` and use the `@pytest.mark.e2e` marker.

#### Discovery E2E Test (`tests/e2e/test_discovery_e2e.py`)

```python
import json
import os

import boto3
import pytest


@pytest.mark.e2e
@pytest.mark.skip(reason="E2E: costs money (Bedrock + Exa). Run manually: pytest tests/e2e/test_discovery_e2e.py -v -m e2e --override-ini='addopts='")
def test_discovery_e2e_produces_valid_output():
    """Invoke Discovery handler with real Bedrock, psql, Exa, and GitHub API.

    Verifies:
    1. Output is valid DiscoveryOutput with all 9 required fields
    2. star_count < 10
    3. repo_url starts with https://github.com/
    4. Selected developer is not in featured_developers table
    """
    import subprocess
    from unittest.mock import MagicMock

    # Set LAMBDA_TASK_ROOT so the handler can find prompts/discovery.md
    os.environ.setdefault(
        "LAMBDA_TASK_ROOT",
        os.path.join(os.path.dirname(__file__), "..", "..", "lambdas", "discovery"),
    )

    from lambdas.discovery.handler import lambda_handler

    event = {
        "metadata": {
            "execution_id": "arn:aws:states:us-east-1:123456789:execution:zerostars-pipeline:e2e-test",
            "script_attempt": 1,
        }
    }
    context = MagicMock()
    context.function_name = "e2e-test-discovery"

    result = lambda_handler(event, context)

    # Validate output shape
    required_fields = [
        "repo_url", "repo_name", "repo_description", "developer_github",
        "star_count", "language", "discovery_rationale", "key_files",
        "technical_highlights",
    ]
    for field in required_fields:
        assert field in result, f"Missing required field: {field}"

    # Validate constraints
    assert isinstance(result["star_count"], int)
    assert result["star_count"] < 10, f"star_count {result['star_count']} >= 10"
    assert result["repo_url"].startswith("https://github.com/")

    # Verify developer is not already featured
    ssm = boto3.client("ssm")
    conn_str = ssm.get_parameter(
        Name="/zerostars/db-connection-string", WithDecryption=True
    )["Parameter"]["Value"]
    check = subprocess.run(
        ["psql", conn_str, "-c",
         f"SELECT developer_github FROM featured_developers WHERE developer_github = '{result['developer_github']}';",
         "--no-align", "--tuples-only"],
        capture_output=True, text=True, timeout=15,
    )
    assert check.stdout.strip() == "", (
        f"Developer {result['developer_github']} is already in featured_developers"
    )
```

#### Research E2E Test (`tests/e2e/test_research_e2e.py`)

```python
import json
import os

import pytest


@pytest.mark.e2e
@pytest.mark.skip(reason="E2E: costs money (Bedrock + GitHub API). Run manually: pytest tests/e2e/test_research_e2e.py -v -m e2e --override-ini='addopts='")
def test_research_e2e_produces_valid_output():
    """Invoke Research handler with real Bedrock and real GitHub API.

    Verifies:
    1. Output is valid ResearchOutput with all 9 required fields
    2. developer_github matches input
    3. notable_repos is a list with correct sub-fields
    4. interesting_findings and hiring_signals are non-empty lists of strings
    """
    from unittest.mock import MagicMock

    # Set LAMBDA_TASK_ROOT so the handler can find prompts/research.md
    os.environ.setdefault(
        "LAMBDA_TASK_ROOT",
        os.path.join(os.path.dirname(__file__), "..", "..", "lambdas", "research"),
    )

    from lambdas.research.handler import lambda_handler

    # Use a well-known, stable GitHub user for repeatable E2E testing
    event = {
        "metadata": {
            "execution_id": "arn:aws:states:us-east-1:123456789:execution:zerostars-pipeline:e2e-test",
            "script_attempt": 1,
        },
        "discovery": {
            "repo_url": "https://github.com/torvalds/linux",
            "repo_name": "linux",
            "repo_description": "Linux kernel source tree",
            "developer_github": "torvalds",
            "star_count": 0,  # not relevant for research
            "language": "C",
            "discovery_rationale": "E2E test input",
            "key_files": ["README"],
            "technical_highlights": ["E2E test"],
        },
    }
    context = MagicMock()
    context.function_name = "e2e-test-research"

    result = lambda_handler(event, context)

    # Validate output shape
    required_fields = [
        "developer_name", "developer_github", "developer_bio",
        "public_repos_count", "notable_repos", "commit_patterns",
        "technical_profile", "interesting_findings", "hiring_signals",
    ]
    for field in required_fields:
        assert field in result, f"Missing required field: {field}"

    # Validate types
    assert isinstance(result["public_repos_count"], int)
    assert isinstance(result["notable_repos"], list)
    assert isinstance(result["interesting_findings"], list)
    assert isinstance(result["hiring_signals"], list)
    assert isinstance(result["developer_bio"], str)

    # Validate content
    assert result["developer_github"] == "torvalds"
    assert len(result["interesting_findings"]) >= 1
    assert len(result["hiring_signals"]) >= 1
```

### Per-Handler Test Requirements

Each handler's unit test file must verify:

| Handler | Required test cases |
|---------|-------------------|
| Discovery | **Output parsing:** valid JSON; fenced JSON (` ```json ` and ` ``` `); star_count >= 10 rejected; string star_count coerced to int; missing required field rejected; invalid repo_url rejected; invalid JSON rejected. **psql tool:** SELECT allowed; INSERT/DELETE/DROP/UPDATE each rejected; leading whitespace SELECT allowed; psql stderr returns error dict; subprocess timeout returns error dict. **GitHub tool:** curated fields returned (no extra fields); null license handled; HTTP error returns error dict. **Exa tool:** snake_case inputs mapped to camelCase in request body; HTTP error returns error dict. **Tool dispatcher:** routes to correct function for each tool name; unknown tool returns error dict. **Full handler:** returns valid DiscoveryOutput; passes 3 tools and executor to invoke_with_tools; rejects high star_count from agent; handles fenced output from agent. |
| Research | **Output parsing:** valid JSON; fenced JSON (` ```json ` and ` ``` `); string `public_repos_count` coerced to int; null `developer_bio` coerced to empty string; missing required field rejected; invalid JSON rejected; `notable_repos` entry missing required sub-field rejected; empty `notable_repos` accepted. **`get_github_user` tool:** curated fields returned (login, name, bio, public_repos, followers, created_at, html_url — no extra fields like id, avatar_url); null name handled; null bio handled; HTTP error returns error dict; socket timeout returns error dict. **`get_user_repos` tool:** returns array of curated repo objects (name, description, stargazers_count, language, html_url, pushed_at, fork — no extra fields); HTTP error returns error dict. **`get_repo_details` tool:** curated fields returned (name, full_name, description, stargazers_count, forks_count, language, topics, created_at, updated_at, html_url — no extra fields); null description handled; HTTP error returns error dict. **`get_repo_readme` tool:** returns decoded content string (base64 decoded by tool); 404 (no README) returns error dict; HTTP error returns error dict. **`search_repositories` tool:** returns `total_count` and curated items array; HTTP error returns error dict. **Tool dispatcher:** routes to correct function for each of 5 tool names; unknown tool returns error dict. **Full handler:** returns valid ResearchOutput; passes 5 tools and executor to invoke_with_tools; reads `$.discovery.developer_github`, `$.discovery.repo_name`, and `$.discovery.repo_url` from input event; handles missing developer bio (null → empty string); handles user with zero repos (empty `notable_repos` valid); handles fenced output from agent; propagates RuntimeError from invoke_with_tools. |
| Script | Output matches `ScriptOutput` shape; `character_count` under 5,000; all 6 segments in `segments` list; incorporates producer feedback on retry (`script_attempt > 1`) |
| Producer | Returns `verdict: "PASS"` or `"FAIL"` with correct fields; FAIL includes `feedback` and `issues`; character count over 5,000 triggers FAIL |
| Cover Art | Output matches `CoverArtOutput` shape; S3 key follows `episodes/{execution_id}/cover.png` pattern |
| TTS | Output matches `TTSOutput` shape; correctly parses `**Hype:**`, `**Roast:**`, `**Phil:**` labels; raises exception on malformed script lines |
| Post-Production | Output matches `PostProductionOutput` shape; writes to `episodes` table; writes to `featured_developers` table |
| Site | Returns valid HTML with status 200; handles empty episodes table |
| Shared: bedrock | **invoke_model:** returns parsed text from Bedrock response; passes correct body structure (`anthropic_version`, `max_tokens`, `system`, `messages`). **invoke_with_tools:** single turn with no tool use (`end_turn`) returns text; tool use loop (`tool_use` then `end_turn`) calls tool_executor and returns final text; multiple tool_use blocks in one turn calls tool_executor for each; max_turns exceeded raises RuntimeError; appends correct message structure (assistant with tool_use content, then user with tool_result). **Retry:** retries on ThrottlingException with backoff; raises after max retries exhausted. |
| Shared: db | `query` returns rows; `execute` returns rowcount; connection uses `sslmode=require` |
| Shared: s3 | `upload_bytes` calls S3 `put_object`; `generate_presigned_url` returns valid URL |
| MCP Server | See [MCP Server Tests](#mcp-server-tests) section below — 26 tools, 5 resources, fixtures, integration, and E2E tests. |

---

## MCP Server Tests

Tests for the [MCP Server](./mcp-server.md) — 26 tools, 5 resources, Lambda handler. Same conventions as above: `unittest.mock` for AWS services, `moto` for S3, `@pytest.mark.integration` for real services.

### Directory Structure

```
tests/
├── unit/
│   └── test_mcp/
│       ├── __init__.py
│       ├── conftest.py             # MCP-specific fixtures
│       ├── test_pipeline.py        # start_pipeline, stop_pipeline, get_execution_status, list_executions, retry_from_step
│       ├── test_agents.py          # invoke_discovery through invoke_post_production
│       ├── test_observation.py     # get_agent_logs, get_execution_history, get_pipeline_health
│       ├── test_data.py            # query_episodes, get_episode_detail, query_metrics, query_featured_developers, run_sql, upsert_metrics
│       ├── test_assets.py          # get_episode_assets, list_s3_assets, get_presigned_url
│       ├── test_site.py            # invalidate_cache, get_site_status
│       ├── test_resources.py       # MCP resource handlers
│       └── test_handler.py         # Transport setup, tool registration, routing
├── integration/
│   ├── test_mcp_pipeline_live.py   # Real Step Functions API (read-only)
│   ├── test_mcp_data_live.py       # Real Postgres queries
│   └── test_mcp_assets_live.py     # Real S3 operations
└── e2e/
    └── test_mcp_e2e.py             # Full tool chain: start → observe → stop
```

### MCP Fixtures (`tests/unit/test_mcp/conftest.py`)

```python
import json
from unittest.mock import MagicMock, patch

import pytest


STATE_MACHINE_ARN = "arn:aws:states:us-east-1:123456789:stateMachine:zerostars-pipeline"
EXECUTION_ARN = "arn:aws:states:us-east-1:123456789:execution:zerostars-pipeline:mcp-20250713T090000Z"
S3_BUCKET = "zerostars-episodes-123456789"
CLOUDFRONT_DIST_ID = "E1234567890"
ACM_CERT_ARN = "arn:aws:acm:us-east-1:123456789:certificate/abc-123"
SITE_DOMAIN = "podcast.ryans-lab.click"


@pytest.fixture(autouse=True)
def mcp_env(monkeypatch):
    """Set environment variables that the MCP Lambda reads at import time."""
    monkeypatch.setenv("STATE_MACHINE_ARN", STATE_MACHINE_ARN)
    monkeypatch.setenv("S3_BUCKET", S3_BUCKET)
    monkeypatch.setenv("CLOUDFRONT_DISTRIBUTION_ID", CLOUDFRONT_DIST_ID)
    monkeypatch.setenv("ACM_CERTIFICATE_ARN", ACM_CERT_ARN)
    monkeypatch.setenv("SITE_DOMAIN", SITE_DOMAIN)
    monkeypatch.setenv("POWERTOOLS_SERVICE_NAME", "mcp")
    monkeypatch.setenv("POWERTOOLS_LOG_LEVEL", "INFO")


@pytest.fixture
def mock_sfn_client():
    """Mock Step Functions boto3 client."""
    with patch("lambdas.mcp.tools.pipeline.boto3.client") as mock:
        client = MagicMock()
        mock.return_value = client
        yield client


@pytest.fixture
def mock_lambda_client():
    """Mock Lambda boto3 client for agent invocations."""
    with patch("lambdas.mcp.tools.agents.boto3.client") as mock:
        client = MagicMock()
        mock.return_value = client
        yield client


@pytest.fixture
def mock_logs_client():
    """Mock CloudWatch Logs boto3 client."""
    with patch("lambdas.mcp.tools.observation.boto3.client") as mock:
        client = MagicMock()
        mock.return_value = client
        yield client


@pytest.fixture
def mock_s3_client():
    """Mock S3 boto3 client for asset tools."""
    with patch("lambdas.mcp.tools.assets.boto3.client") as mock:
        client = MagicMock()
        mock.return_value = client
        yield client


@pytest.fixture
def mock_cloudfront_client():
    """Mock CloudFront boto3 client for site tools."""
    with patch("lambdas.mcp.tools.site.boto3.client") as mock:
        client = MagicMock()
        mock.return_value = client
        yield client


@pytest.fixture
def mock_acm_client():
    """Mock ACM boto3 client for get_site_status."""
    with patch("lambdas.mcp.tools.site.boto3.client") as mock:
        client = MagicMock()
        mock.return_value = client
        yield client


@pytest.fixture
def mock_mcp_db(mock_db_connection):
    """Patches psycopg2 at the MCP data module's import path.

    Reuses the shared mock_db_connection fixture from the top-level conftest,
    but patches it at the MCP module path.
    """
    with patch("lambdas.mcp.tools.data.get_connection") as mock:
        conn = MagicMock()
        cursor = MagicMock()
        conn.cursor.return_value = cursor
        cursor.__enter__ = lambda s: s
        cursor.__exit__ = MagicMock(return_value=False)
        conn.__enter__ = lambda s: s
        conn.__exit__ = MagicMock(return_value=False)
        mock.return_value = conn
        yield conn, cursor


@pytest.fixture
def sample_execution_running():
    """DescribeExecution response for a RUNNING execution."""
    return {
        "executionArn": EXECUTION_ARN,
        "stateMachineArn": STATE_MACHINE_ARN,
        "name": "mcp-20250713T090000Z",
        "status": "RUNNING",
        "startDate": "2025-07-13T09:00:00.000Z",
        "input": json.dumps({
            "metadata": {"execution_id": EXECUTION_ARN, "script_attempt": 1},
            "discovery": {"repo_url": "https://github.com/user/repo", "star_count": 7},
        }),
        "inputDetails": {"included": True},
    }


@pytest.fixture
def sample_execution_succeeded():
    """DescribeExecution response for a SUCCEEDED execution."""
    return {
        "executionArn": EXECUTION_ARN,
        "stateMachineArn": STATE_MACHINE_ARN,
        "name": "mcp-20250713T090000Z",
        "status": "SUCCEEDED",
        "startDate": "2025-07-13T09:00:00.000Z",
        "stopDate": "2025-07-13T09:12:34.000Z",
        "input": json.dumps({"metadata": {"execution_id": EXECUTION_ARN, "script_attempt": 1}}),
        "output": json.dumps({
            "metadata": {"execution_id": EXECUTION_ARN, "script_attempt": 1},
            "discovery": {"repo_url": "https://github.com/user/repo"},
            "research": {"developer_name": "Test User"},
            "script": {"text": "**Hype:** Hello!", "character_count": 15},
            "producer": {"verdict": "PASS", "score": 8},
            "cover_art": {"s3_key": "episodes/test/cover.png"},
            "tts": {"s3_key": "episodes/test/episode.mp3", "duration_seconds": 180},
            "post_production": {"s3_mp4_key": "episodes/test/episode.mp4", "episode_id": 1},
        }),
        "outputDetails": {"included": True},
    }


@pytest.fixture
def sample_execution_failed():
    """DescribeExecution response for a FAILED execution."""
    return {
        "executionArn": EXECUTION_ARN,
        "stateMachineArn": STATE_MACHINE_ARN,
        "name": "mcp-20250713T090000Z",
        "status": "FAILED",
        "startDate": "2025-07-13T09:00:00.000Z",
        "stopDate": "2025-07-13T09:05:00.000Z",
        "input": json.dumps({
            "metadata": {"execution_id": EXECUTION_ARN, "script_attempt": 1},
            "discovery": {"repo_url": "https://github.com/user/repo", "star_count": 7},
            "research": {"developer_name": "Test User"},
        }),
        "error": "States.TaskFailed",
        "cause": "TTS Lambda timed out after 300 seconds",
    }


@pytest.fixture
def sample_execution_history_events():
    """GetExecutionHistory response events for a completed Discovery step."""
    return {
        "events": [
            {
                "timestamp": "2025-07-13T09:00:01.000Z",
                "type": "TaskStateEntered",
                "id": 1,
                "stateEnteredEventDetails": {
                    "name": "Discovery",
                    "input": '{"metadata": {}}',
                },
            },
            {
                "timestamp": "2025-07-13T09:01:30.000Z",
                "type": "TaskSucceeded",
                "id": 2,
                "taskSucceededEventDetails": {
                    "output": '{"repo_url": "https://github.com/user/repo"}',
                },
            },
            {
                "timestamp": "2025-07-13T09:01:31.000Z",
                "type": "TaskStateEntered",
                "id": 3,
                "stateEnteredEventDetails": {
                    "name": "Research",
                    "input": '{"metadata": {}, "discovery": {}}',
                },
            },
        ],
    }
```

### Unit Tests: Pipeline Control (`test_pipeline.py`)

```python
import json
from unittest.mock import ANY

from tests.unit.test_mcp.conftest import STATE_MACHINE_ARN, EXECUTION_ARN


def test_start_pipeline_calls_start_execution(mock_sfn_client):
    from lambdas.mcp.tools.pipeline import start_pipeline
    mock_sfn_client.start_execution.return_value = {
        "executionArn": EXECUTION_ARN,
        "startDate": "2025-07-13T09:00:00.000Z",
    }

    result = start_pipeline()

    mock_sfn_client.start_execution.assert_called_once()
    call_kwargs = mock_sfn_client.start_execution.call_args.kwargs
    assert call_kwargs["stateMachineArn"] == STATE_MACHINE_ARN
    assert call_kwargs["name"].startswith("mcp-")
    assert result["execution_arn"] == EXECUTION_ARN


def test_start_pipeline_name_format(mock_sfn_client):
    mock_sfn_client.start_execution.return_value = {
        "executionArn": EXECUTION_ARN, "startDate": "2025-07-13T09:00:00.000Z",
    }
    start_pipeline()
    name = mock_sfn_client.start_execution.call_args.kwargs["name"]
    assert len(name) <= 80
    assert all(c in "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz-_T" for c in name)


def test_stop_pipeline_passes_cause(mock_sfn_client):
    from lambdas.mcp.tools.pipeline import stop_pipeline
    mock_sfn_client.stop_execution.return_value = {"stopDate": "2025-07-13T09:05:00.000Z"}

    result = stop_pipeline(execution_arn=EXECUTION_ARN, cause="Bad repo pick")

    mock_sfn_client.stop_execution.assert_called_once_with(
        executionArn=EXECUTION_ARN,
        error="MCP.UserAborted",
        cause="Bad repo pick",
    )
    assert result["status"] == "ABORTED"


def test_stop_pipeline_without_cause(mock_sfn_client):
    from lambdas.mcp.tools.pipeline import stop_pipeline
    mock_sfn_client.stop_execution.return_value = {"stopDate": "2025-07-13T09:05:00.000Z"}

    stop_pipeline(execution_arn=EXECUTION_ARN)

    call_kwargs = mock_sfn_client.stop_execution.call_args.kwargs
    assert "cause" not in call_kwargs or call_kwargs["cause"] is None


def test_get_execution_status_running_includes_current_step(
    mock_sfn_client, sample_execution_running, sample_execution_history_events,
):
    from lambdas.mcp.tools.pipeline import get_execution_status
    mock_sfn_client.describe_execution.return_value = sample_execution_running
    mock_sfn_client.get_execution_history.return_value = sample_execution_history_events

    result = get_execution_status(execution_arn=EXECUTION_ARN)

    assert result["status"] == "RUNNING"
    assert result["current_step"] == "Research"
    assert "discovery" in result["state_object"]
    mock_sfn_client.get_execution_history.assert_called_once()


def test_get_execution_status_succeeded_uses_output(mock_sfn_client, sample_execution_succeeded):
    from lambdas.mcp.tools.pipeline import get_execution_status
    mock_sfn_client.describe_execution.return_value = sample_execution_succeeded

    result = get_execution_status(execution_arn=EXECUTION_ARN)

    assert result["status"] == "SUCCEEDED"
    assert result["current_step"] is None
    assert "post_production" in result["state_object"]
    mock_sfn_client.get_execution_history.assert_not_called()


def test_get_execution_status_failed_includes_error(mock_sfn_client, sample_execution_failed):
    from lambdas.mcp.tools.pipeline import get_execution_status
    mock_sfn_client.describe_execution.return_value = sample_execution_failed

    result = get_execution_status(execution_arn=EXECUTION_ARN)

    assert result["status"] == "FAILED"
    assert result["error"] == "States.TaskFailed"
    assert "TTS" in result["cause"]


def test_list_executions_with_status_filter(mock_sfn_client):
    from lambdas.mcp.tools.pipeline import list_executions
    mock_sfn_client.list_executions.return_value = {"executions": []}

    list_executions(status_filter="FAILED", max_results=5)

    mock_sfn_client.list_executions.assert_called_once_with(
        stateMachineArn=STATE_MACHINE_ARN,
        statusFilter="FAILED",
        maxResults=5,
    )


def test_list_executions_without_filter(mock_sfn_client):
    from lambdas.mcp.tools.pipeline import list_executions
    mock_sfn_client.list_executions.return_value = {"executions": []}

    list_executions()

    call_kwargs = mock_sfn_client.list_executions.call_args.kwargs
    assert "statusFilter" not in call_kwargs


def test_retry_from_step_carries_state(mock_sfn_client, sample_execution_failed):
    from lambdas.mcp.tools.pipeline import retry_from_step
    mock_sfn_client.describe_execution.return_value = sample_execution_failed
    mock_sfn_client.start_execution.return_value = {
        "executionArn": "arn:aws:states:us-east-1:123456789:execution:zerostars-pipeline:mcp-retry-20250713T091500Z",
        "startDate": "2025-07-13T09:15:00.000Z",
    }

    result = retry_from_step(failed_execution_arn=EXECUTION_ARN, retry_from="Script")

    # Verify the new execution input carries discovery + research but adds resume_from
    call_kwargs = mock_sfn_client.start_execution.call_args.kwargs
    new_input = json.loads(call_kwargs["input"])
    assert new_input["metadata"]["resume_from"] == "Script"
    assert "discovery" in new_input
    assert "research" in new_input
    assert "script" not in new_input  # Script and later steps should not be carried
    assert result["carried_state_keys"] == ["discovery", "research"]
    assert result["retry_from"] == "Script"


def test_retry_from_step_name_format(mock_sfn_client, sample_execution_failed):
    from lambdas.mcp.tools.pipeline import retry_from_step
    mock_sfn_client.describe_execution.return_value = sample_execution_failed
    mock_sfn_client.start_execution.return_value = {
        "executionArn": EXECUTION_ARN, "startDate": "2025-07-13T09:15:00.000Z",
    }

    retry_from_step(failed_execution_arn=EXECUTION_ARN, retry_from="TTS")

    name = mock_sfn_client.start_execution.call_args.kwargs["name"]
    assert name.startswith("mcp-retry-")
```

### Unit Tests: Agent Invocation (`test_agents.py`)

```python
import json

from tests.unit.test_mcp.conftest import EXECUTION_ARN


def test_invoke_discovery_builds_synthetic_state(mock_lambda_client):
    from lambdas.mcp.tools.agents import invoke_discovery
    mock_lambda_client.invoke.return_value = {
        "StatusCode": 200,
        "Payload": MagicMock(read=lambda: json.dumps({
            "repo_url": "https://github.com/user/repo",
            "star_count": 5,
        }).encode()),
    }

    result = invoke_discovery()

    call_kwargs = mock_lambda_client.invoke.call_args.kwargs
    assert call_kwargs["FunctionName"] == "zerostars-discovery"
    assert call_kwargs["InvocationType"] == "RequestResponse"
    payload = json.loads(call_kwargs["Payload"])
    assert "metadata" in payload
    assert payload["metadata"]["execution_id"].startswith("mcp-standalone-")
    assert result["repo_url"] == "https://github.com/user/repo"


def test_invoke_research_places_params_in_discovery_key(mock_lambda_client):
    from lambdas.mcp.tools.agents import invoke_research
    mock_lambda_client.invoke.return_value = {
        "StatusCode": 200,
        "Payload": MagicMock(read=lambda: json.dumps({
            "developer_name": "Test User",
        }).encode()),
    }

    invoke_research(
        repo_url="https://github.com/user/repo",
        repo_name="repo",
        developer_github="user",
    )

    payload = json.loads(mock_lambda_client.invoke.call_args.kwargs["Payload"])
    assert payload["discovery"]["repo_url"] == "https://github.com/user/repo"
    assert payload["discovery"]["developer_github"] == "user"


def test_invoke_script_without_feedback(mock_lambda_client, sample_discovery_output, sample_research_output):
    from lambdas.mcp.tools.agents import invoke_script
    mock_lambda_client.invoke.return_value = {
        "StatusCode": 200,
        "Payload": MagicMock(read=lambda: json.dumps({
            "text": "**Hype:** Hello!", "character_count": 15,
        }).encode()),
    }

    invoke_script(discovery=sample_discovery_output, research=sample_research_output)

    payload = json.loads(mock_lambda_client.invoke.call_args.kwargs["Payload"])
    assert payload["metadata"]["script_attempt"] == 1
    assert "producer" not in payload


def test_invoke_script_with_feedback_sets_attempt_2(
    mock_lambda_client, sample_discovery_output, sample_research_output,
):
    from lambdas.mcp.tools.agents import invoke_script
    mock_lambda_client.invoke.return_value = {
        "StatusCode": 200,
        "Payload": MagicMock(read=lambda: json.dumps({
            "text": "**Hype:** Improved!", "character_count": 18,
        }).encode()),
    }

    invoke_script(
        discovery=sample_discovery_output,
        research=sample_research_output,
        producer_feedback="More jokes",
        producer_issues=["Not funny enough"],
    )

    payload = json.loads(mock_lambda_client.invoke.call_args.kwargs["Payload"])
    assert payload["metadata"]["script_attempt"] == 2
    assert payload["producer"]["feedback"] == "More jokes"
    assert payload["producer"]["issues"] == ["Not funny enough"]


def test_invoke_producer_places_script_text(
    mock_lambda_client, sample_discovery_output, sample_research_output,
):
    from lambdas.mcp.tools.agents import invoke_producer
    mock_lambda_client.invoke.return_value = {
        "StatusCode": 200,
        "Payload": MagicMock(read=lambda: json.dumps({
            "verdict": "PASS", "score": 8,
        }).encode()),
    }

    invoke_producer(
        script_text="**Hype:** Hello!",
        discovery=sample_discovery_output,
        research=sample_research_output,
    )

    payload = json.loads(mock_lambda_client.invoke.call_args.kwargs["Payload"])
    assert payload["script"]["text"] == "**Hype:** Hello!"


def test_invoke_cover_art_auto_generates_execution_id(mock_lambda_client):
    from lambdas.mcp.tools.agents import invoke_cover_art
    mock_lambda_client.invoke.return_value = {
        "StatusCode": 200,
        "Payload": MagicMock(read=lambda: json.dumps({
            "s3_key": "episodes/test/cover.png",
        }).encode()),
    }

    invoke_cover_art(cover_art_suggestion="Robots coding", repo_name="testrepo")

    payload = json.loads(mock_lambda_client.invoke.call_args.kwargs["Payload"])
    assert payload["metadata"]["execution_id"].startswith("mcp-standalone-")


def test_invoke_cover_art_uses_provided_execution_id(mock_lambda_client):
    from lambdas.mcp.tools.agents import invoke_cover_art
    mock_lambda_client.invoke.return_value = {
        "StatusCode": 200,
        "Payload": MagicMock(read=lambda: json.dumps({
            "s3_key": "episodes/custom-id/cover.png",
        }).encode()),
    }

    invoke_cover_art(
        cover_art_suggestion="Robots coding", repo_name="testrepo", execution_id="custom-id",
    )

    payload = json.loads(mock_lambda_client.invoke.call_args.kwargs["Payload"])
    assert payload["metadata"]["execution_id"] == "custom-id"


def test_invoke_agent_lambda_error_raises(mock_lambda_client):
    from lambdas.mcp.tools.agents import invoke_discovery
    mock_lambda_client.invoke.return_value = {
        "StatusCode": 200,
        "FunctionError": "Unhandled",
        "Payload": MagicMock(read=lambda: json.dumps({
            "errorMessage": "KeyError: 'metadata'",
        }).encode()),
    }

    with pytest.raises(RuntimeError, match="Lambda invocation failed"):
        invoke_discovery()
```

### Unit Tests: Observation (`test_observation.py`)

```python
import time


def test_get_agent_logs_correct_log_group(mock_logs_client):
    from lambdas.mcp.tools.observation import get_agent_logs
    mock_logs_client.filter_log_events.return_value = {"events": []}

    get_agent_logs(agent="discovery")

    call_kwargs = mock_logs_client.filter_log_events.call_args.kwargs
    assert call_kwargs["logGroupName"] == "/aws/lambda/zerostars-discovery"


def test_get_agent_logs_start_time_from_since_minutes(mock_logs_client):
    from lambdas.mcp.tools.observation import get_agent_logs
    mock_logs_client.filter_log_events.return_value = {"events": []}
    before = int(time.time() * 1000) - (30 * 60 * 1000)

    get_agent_logs(agent="script", since_minutes=30)

    start_time = mock_logs_client.filter_log_events.call_args.kwargs["startTime"]
    assert abs(start_time - before) < 5000  # within 5 seconds tolerance


def test_get_agent_logs_filters_by_execution_id(mock_logs_client):
    from lambdas.mcp.tools.observation import get_agent_logs
    mock_logs_client.filter_log_events.return_value = {"events": []}

    get_agent_logs(agent="tts", execution_id="arn:aws:states:test")

    call_kwargs = mock_logs_client.filter_log_events.call_args.kwargs
    assert "arn:aws:states:test" in call_kwargs["filterPattern"]


def test_get_agent_logs_respects_limit(mock_logs_client):
    from lambdas.mcp.tools.observation import get_agent_logs
    events = [{"timestamp": i, "message": f'{{"level": "INFO"}}'} for i in range(100)]
    mock_logs_client.filter_log_events.return_value = {"events": events}

    result = get_agent_logs(agent="discovery", limit=20)

    assert len(result["logs"]) <= 20


def test_get_agent_logs_filters_by_log_level(mock_logs_client):
    from lambdas.mcp.tools.observation import get_agent_logs
    events = [
        {"timestamp": 1, "message": '{"level": "INFO", "message": "ok"}'},
        {"timestamp": 2, "message": '{"level": "ERROR", "message": "fail"}'},
        {"timestamp": 3, "message": '{"level": "DEBUG", "message": "trace"}'},
    ]
    mock_logs_client.filter_log_events.return_value = {"events": events}

    result = get_agent_logs(agent="discovery", log_level="ERROR")

    levels = [log["level"] for log in result["logs"]]
    assert "DEBUG" not in levels
    assert "INFO" not in levels
    assert "ERROR" in levels


def test_get_execution_history_passes_include_flag(mock_sfn_client):
    from lambdas.mcp.tools.observation import get_execution_history
    mock_sfn_client.get_execution_history.return_value = {"events": []}

    get_execution_history(execution_arn=EXECUTION_ARN, include_input_output=False)

    call_kwargs = mock_sfn_client.get_execution_history.call_args.kwargs
    assert call_kwargs["includeExecutionData"] is False


def test_get_execution_history_paginates(mock_sfn_client):
    from lambdas.mcp.tools.observation import get_execution_history
    mock_sfn_client.get_execution_history.side_effect = [
        {"events": [{"type": "TaskStateEntered", "id": 1}], "nextToken": "page2"},
        {"events": [{"type": "TaskSucceeded", "id": 2}]},
    ]

    result = get_execution_history(execution_arn=EXECUTION_ARN)

    assert len(result["events"]) == 2
    assert mock_sfn_client.get_execution_history.call_count == 2


def test_get_pipeline_health_calculates_success_rate(mock_sfn_client, mock_mcp_db):
    from lambdas.mcp.tools.observation import get_pipeline_health
    conn, cursor = mock_mcp_db
    cursor.fetchone.return_value = (1, "cool-project", "2025-07-06")

    mock_sfn_client.list_executions.side_effect = [
        {"executions": [{"status": "SUCCEEDED"}] * 8},  # SUCCEEDED
        {"executions": [{"status": "FAILED"}] * 2},      # FAILED
        {"executions": []},                               # ABORTED
        {"executions": []},                               # RUNNING
    ]

    result = get_pipeline_health(days=30)

    assert result["succeeded"] == 8
    assert result["failed"] == 2
    assert result["success_rate"] == "80%"
    assert result["total_executions"] == 10
```

### Unit Tests: Data (`test_data.py`)

```python
import pytest


def test_query_episodes_excludes_large_fields(mock_mcp_db):
    from lambdas.mcp.tools.data import query_episodes
    conn, cursor = mock_mcp_db
    cursor.description = [("episode_id",), ("repo_name",), ("air_date",)]
    cursor.fetchall.return_value = [(1, "repo", "2025-07-06")]
    cursor.fetchone.return_value = (1,)  # total count

    result = query_episodes()

    sql = cursor.execute.call_args_list[0][0][0]
    assert "script_text" not in sql
    assert "research_json" not in sql
    assert "cover_art_prompt" not in sql


def test_query_episodes_applies_filters(mock_mcp_db):
    from lambdas.mcp.tools.data import query_episodes
    conn, cursor = mock_mcp_db
    cursor.description = [("episode_id",)]
    cursor.fetchall.return_value = []
    cursor.fetchone.return_value = (0,)

    query_episodes(developer_github="testuser", limit=5, offset=10, order_by="air_date", order="asc")

    sql = cursor.execute.call_args_list[0][0][0]
    assert "testuser" in str(cursor.execute.call_args_list[0])
    assert "ORDER BY air_date ASC" in sql or "order by air_date asc" in sql.lower()
    assert "LIMIT" in sql
    assert "OFFSET" in sql


def test_query_episodes_rejects_invalid_order_by(mock_mcp_db):
    from lambdas.mcp.tools.data import query_episodes
    with pytest.raises(ValueError, match="order_by"):
        query_episodes(order_by="DROP TABLE episodes; --")


def test_get_episode_detail_returns_full_row(mock_mcp_db):
    from lambdas.mcp.tools.data import get_episode_detail
    conn, cursor = mock_mcp_db
    cursor.description = [
        ("episode_id",), ("script_text",), ("research_json",), ("cover_art_prompt",),
    ]
    cursor.fetchone.return_value = (1, "**Hype:** Hello!", '{"key": "val"}', "art prompt")

    result = get_episode_detail(episode_id=1)

    assert result["script_text"] == "**Hype:** Hello!"
    assert result["research_json"] == '{"key": "val"}'


def test_run_sql_allows_select(mock_mcp_db):
    from lambdas.mcp.tools.data import run_sql
    conn, cursor = mock_mcp_db
    cursor.description = [("count",)]
    cursor.fetchall.return_value = [(11,)]

    result = run_sql(sql="SELECT count(*) FROM episodes")

    assert result["columns"] == ["count"]
    assert result["rows"] == [[11]]
    assert result["row_count"] == 1


def test_run_sql_rejects_insert(mock_mcp_db):
    from lambdas.mcp.tools.data import run_sql
    with pytest.raises(ValueError, match="SELECT"):
        run_sql(sql="INSERT INTO episodes (repo_name) VALUES ('x')")


def test_run_sql_rejects_delete(mock_mcp_db):
    from lambdas.mcp.tools.data import run_sql
    with pytest.raises(ValueError, match="SELECT"):
        run_sql(sql="DELETE FROM episodes")


def test_run_sql_rejects_drop(mock_mcp_db):
    from lambdas.mcp.tools.data import run_sql
    with pytest.raises(ValueError, match="SELECT"):
        run_sql(sql="DROP TABLE episodes")


def test_run_sql_rejects_update(mock_mcp_db):
    from lambdas.mcp.tools.data import run_sql
    with pytest.raises(ValueError, match="SELECT"):
        run_sql(sql="UPDATE episodes SET repo_name = 'x'")


def test_run_sql_leading_whitespace_select(mock_mcp_db):
    from lambdas.mcp.tools.data import run_sql
    conn, cursor = mock_mcp_db
    cursor.description = [("x",)]
    cursor.fetchall.return_value = [(1,)]

    result = run_sql(sql="   SELECT 1")

    assert result["row_count"] == 1


def test_run_sql_case_insensitive(mock_mcp_db):
    from lambdas.mcp.tools.data import run_sql
    conn, cursor = mock_mcp_db
    cursor.description = [("x",)]
    cursor.fetchall.return_value = [(1,)]

    result = run_sql(sql="select 1")

    assert result["row_count"] == 1


def test_run_sql_sets_statement_timeout(mock_mcp_db):
    from lambdas.mcp.tools.data import run_sql
    conn, cursor = mock_mcp_db
    cursor.description = [("x",)]
    cursor.fetchall.return_value = [(1,)]

    run_sql(sql="SELECT 1")

    # Verify statement_timeout was set before the query
    execute_calls = [str(c) for c in cursor.execute.call_args_list]
    assert any("statement_timeout" in c for c in execute_calls)


def test_upsert_metrics_inserts(mock_mcp_db):
    from lambdas.mcp.tools.data import upsert_metrics
    conn, cursor = mock_mcp_db
    cursor.fetchone.return_value = (5,)

    result = upsert_metrics(episode_id=1, views=100, likes=10)

    sql = cursor.execute.call_args_list[-1][0][0]
    assert "INSERT" in sql
    assert "ON CONFLICT" in sql
    assert result["metric_id"] == 5


def test_query_featured_developers_joins_episodes(mock_mcp_db):
    from lambdas.mcp.tools.data import query_featured_developers
    conn, cursor = mock_mcp_db
    cursor.description = [("developer_github",), ("episode_id",), ("featured_date",), ("repo_name",)]
    cursor.fetchall.return_value = [("user", 1, "2025-07-06", "repo")]

    result = query_featured_developers()

    sql = cursor.execute.call_args[0][0]
    assert "JOIN" in sql or "join" in sql.lower()
    assert result["developers"][0]["repo_name"] == "repo"
```

### Unit Tests: Assets (`test_assets.py`)

```python
from unittest.mock import MagicMock

from moto import mock_aws
import boto3


def test_get_episode_assets_returns_presigned_urls(mock_s3_client, mock_mcp_db):
    from lambdas.mcp.tools.assets import get_episode_assets
    conn, cursor = mock_mcp_db
    cursor.fetchone.return_value = (
        "episodes/test/cover.png",
        "episodes/test/episode.mp3",
        "episodes/test/episode.mp4",
    )
    mock_s3_client.generate_presigned_url.return_value = "https://presigned-url"

    result = get_episode_assets(episode_id=1)

    assert result["cover_art_url"] == "https://presigned-url"
    assert result["mp3_url"] == "https://presigned-url"
    assert result["mp4_url"] == "https://presigned-url"
    assert mock_s3_client.generate_presigned_url.call_count == 3


def test_get_episode_assets_null_for_missing(mock_s3_client, mock_mcp_db):
    from lambdas.mcp.tools.assets import get_episode_assets
    conn, cursor = mock_mcp_db
    cursor.fetchone.return_value = ("episodes/test/cover.png", None, None)
    mock_s3_client.generate_presigned_url.return_value = "https://presigned-url"

    result = get_episode_assets(episode_id=1)

    assert result["cover_art_url"] == "https://presigned-url"
    assert result["mp3_url"] is None
    assert result["mp4_url"] is None


def test_list_s3_assets_passes_prefix(mock_s3_client):
    from lambdas.mcp.tools.assets import list_s3_assets
    mock_s3_client.list_objects_v2.return_value = {
        "Contents": [
            {"Key": "episodes/test/cover.png", "Size": 1024, "LastModified": "2025-07-13T09:00:00Z"},
        ],
    }

    result = list_s3_assets(prefix="episodes/test/")

    mock_s3_client.list_objects_v2.assert_called_once()
    call_kwargs = mock_s3_client.list_objects_v2.call_args.kwargs
    assert call_kwargs["Prefix"] == "episodes/test/"
    assert len(result["objects"]) == 1


def test_list_s3_assets_empty_bucket(mock_s3_client):
    from lambdas.mcp.tools.assets import list_s3_assets
    mock_s3_client.list_objects_v2.return_value = {}  # No Contents key

    result = list_s3_assets()

    assert result["objects"] == []


def test_get_presigned_url_default_expiry(mock_s3_client):
    from lambdas.mcp.tools.assets import get_presigned_url
    mock_s3_client.generate_presigned_url.return_value = "https://presigned-url"

    get_presigned_url(s3_key="episodes/test/cover.png")

    call_kwargs = mock_s3_client.generate_presigned_url.call_args.kwargs
    assert call_kwargs["ExpiresIn"] == 3600


def test_get_presigned_url_custom_expiry(mock_s3_client):
    from lambdas.mcp.tools.assets import get_presigned_url
    mock_s3_client.generate_presigned_url.return_value = "https://presigned-url"

    get_presigned_url(s3_key="episodes/test/cover.png", expires_in=7200)

    call_kwargs = mock_s3_client.generate_presigned_url.call_args.kwargs
    assert call_kwargs["ExpiresIn"] == 7200


def test_get_presigned_url_caps_at_max(mock_s3_client):
    from lambdas.mcp.tools.assets import get_presigned_url
    mock_s3_client.generate_presigned_url.return_value = "https://presigned-url"

    get_presigned_url(s3_key="episodes/test/cover.png", expires_in=999999)

    call_kwargs = mock_s3_client.generate_presigned_url.call_args.kwargs
    assert call_kwargs["ExpiresIn"] <= 43200
```

### Unit Tests: Site (`test_site.py`)

```python
def test_invalidate_cache_default_paths(mock_cloudfront_client):
    from lambdas.mcp.tools.site import invalidate_cache
    mock_cloudfront_client.create_invalidation.return_value = {
        "Invalidation": {"Id": "I123", "Status": "InProgress"},
    }

    result = invalidate_cache()

    call_kwargs = mock_cloudfront_client.create_invalidation.call_args.kwargs
    paths = call_kwargs["InvalidationBatch"]["Paths"]["Items"]
    assert paths == ["/*"]
    assert result["invalidation_id"] == "I123"


def test_invalidate_cache_custom_paths(mock_cloudfront_client):
    from lambdas.mcp.tools.site import invalidate_cache
    mock_cloudfront_client.create_invalidation.return_value = {
        "Invalidation": {"Id": "I456", "Status": "InProgress"},
    }

    result = invalidate_cache(paths=["/", "/episodes/1"])

    paths = mock_cloudfront_client.create_invalidation.call_args.kwargs[
        "InvalidationBatch"
    ]["Paths"]["Items"]
    assert paths == ["/", "/episodes/1"]


def test_get_site_status_aggregates_sources(mock_cloudfront_client, mock_acm_client, mock_mcp_db):
    from lambdas.mcp.tools.site import get_site_status
    conn, cursor = mock_mcp_db
    cursor.fetchone.side_effect = [(11,), (11, "cool-project", "2025-07-06")]

    mock_cloudfront_client.get_distribution.return_value = {
        "Distribution": {"Id": "E123", "Status": "Deployed"},
    }
    mock_acm_client.describe_certificate.return_value = {
        "Certificate": {"Status": "ISSUED"},
    }

    result = get_site_status()

    assert result["distribution_status"] == "Deployed"
    assert result["ssl_status"] == "ISSUED"
    assert result["episode_count"] == 11
    assert result["cloudfront_id"] == "E123"
```

### Unit Tests: Resources (`test_resources.py`)

```python
def test_episodes_resource_returns_list(mock_mcp_db):
    from lambdas.mcp.resources import read_episodes_resource
    conn, cursor = mock_mcp_db
    cursor.description = [("episode_id",), ("air_date",), ("repo_name",)]
    cursor.fetchall.return_value = [(1, "2025-07-06", "repo")]

    result = read_episodes_resource()

    assert len(result) == 1
    assert result[0]["episode_id"] == 1


def test_pipeline_status_resource(mock_sfn_client):
    from lambdas.mcp.resources import read_pipeline_status_resource
    mock_sfn_client.list_executions.side_effect = [
        {"executions": []},  # RUNNING
        {"executions": [
            {"executionArn": "arn:...", "name": "test", "status": "SUCCEEDED",
             "startDate": "2025-07-13T09:00:00Z", "stopDate": "2025-07-13T09:12:00Z"},
        ]},  # recent completed
    ]

    result = read_pipeline_status_resource()

    assert result["currently_running"] == []
    assert len(result["recent"]) == 1


def test_featured_developers_resource(mock_mcp_db):
    from lambdas.mcp.resources import read_featured_developers_resource
    conn, cursor = mock_mcp_db
    cursor.description = [("developer_github",), ("episode_id",), ("featured_date",)]
    cursor.fetchall.return_value = [("user1", 1, "2025-07-06")]

    result = read_featured_developers_resource()

    assert result[0]["developer_github"] == "user1"
```

### Unit Tests: Handler (`test_handler.py`)

```python
def test_handler_registers_all_tools():
    """Verify the MCP server registers all 26 tools."""
    from lambdas.mcp.handler import create_mcp_server
    server = create_mcp_server()
    tool_names = {t.name for t in server.list_tools()}

    expected = {
        "start_pipeline", "stop_pipeline", "get_execution_status", "list_executions", "retry_from_step",
        "invoke_discovery", "invoke_research", "invoke_script", "invoke_producer",
        "invoke_cover_art", "invoke_tts", "invoke_post_production",
        "get_agent_logs", "get_execution_history", "get_pipeline_health",
        "query_episodes", "get_episode_detail", "query_metrics",
        "query_featured_developers", "run_sql", "upsert_metrics",
        "get_episode_assets", "list_s3_assets", "get_presigned_url",
        "invalidate_cache", "get_site_status",
    }
    assert tool_names == expected


def test_handler_registers_all_resources():
    """Verify the MCP server registers all 5 resources."""
    from lambdas.mcp.handler import create_mcp_server
    server = create_mcp_server()
    resource_uris = {r.uri for r in server.list_resources()}

    expected = {
        "zerostars://episodes",
        "zerostars://episodes/{episode_id}",
        "zerostars://metrics",
        "zerostars://pipeline/status",
        "zerostars://featured-developers",
    }
    assert resource_uris == expected
```

### Integration Tests

Integration tests hit real AWS services. They require AWS credentials and are excluded from CI by default. They perform read-only operations to avoid side effects.

#### Step Functions (`tests/integration/test_mcp_pipeline_live.py`)

```python
import os

import boto3
import pytest


@pytest.mark.integration
def test_list_executions_returns_valid_shape():
    """ListExecutions against the real state machine returns expected fields."""
    sfn = boto3.client("stepfunctions")
    arn = os.environ.get("STATE_MACHINE_ARN")
    assert arn, "STATE_MACHINE_ARN env var required"

    response = sfn.list_executions(stateMachineArn=arn, maxResults=5)

    assert "executions" in response
    for exc in response["executions"]:
        assert "executionArn" in exc
        assert "status" in exc
        assert exc["status"] in {"RUNNING", "SUCCEEDED", "FAILED", "ABORTED", "TIMED_OUT", "PENDING_REDRIVE"}


@pytest.mark.integration
def test_describe_execution_if_any_exist():
    """DescribeExecution on the most recent execution returns expected fields."""
    sfn = boto3.client("stepfunctions")
    arn = os.environ.get("STATE_MACHINE_ARN")
    assert arn, "STATE_MACHINE_ARN env var required"

    executions = sfn.list_executions(stateMachineArn=arn, maxResults=1)
    if not executions["executions"]:
        pytest.skip("No executions to describe")

    exc_arn = executions["executions"][0]["executionArn"]
    detail = sfn.describe_execution(executionArn=exc_arn)

    assert detail["status"] in {"RUNNING", "SUCCEEDED", "FAILED", "ABORTED", "TIMED_OUT", "PENDING_REDRIVE"}
    assert "startDate" in detail
    if detail["status"] == "SUCCEEDED":
        assert detail["output"] is not None
```

#### Postgres (`tests/integration/test_mcp_data_live.py`)

```python
import boto3
import psycopg2
import pytest


@pytest.mark.integration
def test_query_episodes_table():
    """SELECT from episodes table succeeds and returns expected columns."""
    ssm = boto3.client("ssm")
    conn_str = ssm.get_parameter(
        Name="/zerostars/db-connection-string", WithDecryption=True,
    )["Parameter"]["Value"]

    conn = psycopg2.connect(conn_str)
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT episode_id, repo_name, air_date, star_count_at_recording "
                "FROM episodes ORDER BY episode_id DESC LIMIT 5"
            )
            columns = [desc[0] for desc in cur.description]
            assert "episode_id" in columns
            assert "repo_name" in columns
    finally:
        conn.close()


@pytest.mark.integration
def test_query_featured_developers_table():
    """SELECT from featured_developers succeeds."""
    ssm = boto3.client("ssm")
    conn_str = ssm.get_parameter(
        Name="/zerostars/db-connection-string", WithDecryption=True,
    )["Parameter"]["Value"]

    conn = psycopg2.connect(conn_str)
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT developer_github, episode_id FROM featured_developers LIMIT 5")
            columns = [desc[0] for desc in cur.description]
            assert "developer_github" in columns
    finally:
        conn.close()


@pytest.mark.integration
def test_statement_timeout_works():
    """Verify statement_timeout prevents long queries."""
    ssm = boto3.client("ssm")
    conn_str = ssm.get_parameter(
        Name="/zerostars/db-connection-string", WithDecryption=True,
    )["Parameter"]["Value"]

    conn = psycopg2.connect(conn_str)
    try:
        with conn.cursor() as cur:
            cur.execute("SET statement_timeout = '1s'")
            with pytest.raises(psycopg2.errors.QueryCanceled):
                cur.execute("SELECT pg_sleep(10)")
    finally:
        conn.close()
```

#### S3 (`tests/integration/test_mcp_assets_live.py`)

```python
import os

import boto3
import pytest


@pytest.mark.integration
def test_list_objects_in_episodes_bucket():
    """ListObjectsV2 on the real bucket returns valid response."""
    s3 = boto3.client("s3")
    bucket = os.environ.get("S3_BUCKET")
    assert bucket, "S3_BUCKET env var required"

    response = s3.list_objects_v2(Bucket=bucket, Prefix="episodes/", MaxKeys=5)

    assert response["ResponseMetadata"]["HTTPStatusCode"] == 200
    if "Contents" in response:
        for obj in response["Contents"]:
            assert "Key" in obj
            assert "Size" in obj


@pytest.mark.integration
def test_generate_presigned_url():
    """Presigned URL generation succeeds for an existing object."""
    s3 = boto3.client("s3")
    bucket = os.environ.get("S3_BUCKET")
    assert bucket, "S3_BUCKET env var required"

    response = s3.list_objects_v2(Bucket=bucket, Prefix="episodes/", MaxKeys=1)
    if "Contents" not in response:
        pytest.skip("No objects in bucket to generate presigned URL for")

    key = response["Contents"][0]["Key"]
    url = s3.generate_presigned_url(
        "get_object", Params={"Bucket": bucket, "Key": key}, ExpiresIn=60,
    )
    assert url.startswith("https://")
```

### End-to-End Tests (`tests/e2e/test_mcp_e2e.py`)

E2E tests exercise the full MCP tool chain against real AWS. They start a pipeline execution, observe it, and stop it before it consumes expensive resources (Bedrock, ElevenLabs). The Discovery agent is the first step and takes 30-60 seconds, so stopping during Discovery avoids most cost.

```python
import json
import os
import time

import boto3
import pytest


STATE_MACHINE_ARN = os.environ.get("STATE_MACHINE_ARN", "")


@pytest.mark.e2e
@pytest.mark.skip(reason="E2E: starts a real execution (costs Bedrock $). Run manually.")
class TestMCPEndToEnd:
    """Full tool chain: start → status → logs → stop.

    Run with:
        STATE_MACHINE_ARN=arn:... S3_BUCKET=... \
        PYTHONPATH=lambdas/shared/python \
        pytest tests/e2e/test_mcp_e2e.py -v -m e2e \
        --override-ini='addopts='
    """

    def test_start_observe_stop_cycle(self):
        """Start a pipeline, observe it running, then abort it."""
        from lambdas.mcp.tools.pipeline import start_pipeline, get_execution_status, stop_pipeline, list_executions
        from lambdas.mcp.tools.observation import get_agent_logs

        # 1. Start
        start_result = start_pipeline()
        execution_arn = start_result["execution_arn"]
        assert execution_arn.startswith("arn:aws:states:")

        try:
            # 2. Wait for it to enter RUNNING
            time.sleep(3)

            # 3. Get status — should be RUNNING in Discovery
            status = get_execution_status(execution_arn=execution_arn)
            assert status["status"] == "RUNNING"
            assert status["current_step"] in ("Discovery", "InitializeMetadata", "ResumeRouter")

            # 4. List executions — our execution should appear
            executions = list_executions(status_filter="RUNNING")
            running_arns = [e["execution_arn"] for e in executions["executions"]]
            assert execution_arn in running_arns

            # 5. Get logs (may be empty if Discovery hasn't logged yet)
            logs = get_agent_logs(agent="discovery", since_minutes=5)
            assert "logs" in logs  # shape is valid even if empty

        finally:
            # 6. Stop — always stop to avoid wasting Bedrock/Exa credits
            stop_result = stop_pipeline(execution_arn=execution_arn, cause="E2E test cleanup")
            assert stop_result["status"] == "ABORTED"

        # 7. Verify stopped
        final_status = get_execution_status(execution_arn=execution_arn)
        assert final_status["status"] == "ABORTED"

    def test_list_and_describe_historical_execution(self):
        """List past executions and describe one — no new execution started."""
        from lambdas.mcp.tools.pipeline import list_executions, get_execution_status
        from lambdas.mcp.tools.observation import get_execution_history

        executions = list_executions(max_results=3)
        if not executions["executions"]:
            pytest.skip("No historical executions to describe")

        exc = executions["executions"][0]
        status = get_execution_status(execution_arn=exc["execution_arn"])
        assert status["name"] == exc["name"]

        if exc["status"] != "RUNNING":
            history = get_execution_history(
                execution_arn=exc["execution_arn"], include_input_output=False,
            )
            assert len(history["events"]) > 0

    def test_query_episodes_and_assets(self):
        """Query episodes from Postgres and get presigned URLs for the latest."""
        from lambdas.mcp.tools.data import query_episodes
        from lambdas.mcp.tools.assets import get_episode_assets

        episodes = query_episodes(limit=1)
        if episodes["total_count"] == 0:
            pytest.skip("No episodes in database")

        episode = episodes["episodes"][0]
        assert "episode_id" in episode
        assert "repo_name" in episode

        assets = get_episode_assets(episode_id=episode["episode_id"])
        assert "s3_keys" in assets
        # At least one asset should exist for a real episode
        has_asset = any([assets["cover_art_url"], assets["mp3_url"], assets["mp4_url"]])
        assert has_asset, "Expected at least one S3 asset for the episode"

    def test_site_status(self):
        """Get site status — verifies CloudFront and ACM integration."""
        from lambdas.mcp.tools.site import get_site_status

        status = get_site_status()

        assert status["distribution_status"] in ("Deployed", "InProgress")
        assert status["ssl_status"] == "ISSUED"
        assert status["domain"] == os.environ.get("SITE_DOMAIN", "podcast.ryans-lab.click")
```

### Per-Tool Test Requirements

| Tool | Required unit test cases |
|------|------------------------|
| `start_pipeline` | Calls `StartExecution` with correct ARN; name matches `mcp-{timestamp}` format; name <= 80 chars and valid characters; returns `execution_arn` + `start_date`. |
| `stop_pipeline` | Passes `executionArn`, `error`, `cause`; works without `cause`; returns `ABORTED` status. |
| `get_execution_status` | RUNNING: calls `GetExecutionHistory` to find `current_step`; SUCCEEDED: uses `output` for state, no history call; FAILED: includes `error` + `cause`; state_object parsed from JSON. |
| `list_executions` | Passes `statusFilter` when provided; omits `statusFilter` when not; respects `maxResults`. |
| `retry_from_step` | Extracts state from failed execution; carries only keys before retry point; sets `metadata.resume_from`; name starts with `mcp-retry-`; does not carry keys at or after retry point. |
| `invoke_discovery` | Calls `zerostars-discovery` with `RequestResponse`; builds synthetic state with `metadata`; returns parsed payload. |
| `invoke_research` | Places `repo_url`, `repo_name`, `developer_github` under `$.discovery`. |
| `invoke_script` | Without feedback: `script_attempt=1`, no `producer` key; with feedback: `script_attempt=2`, `producer.feedback` + `producer.issues` set. |
| `invoke_producer` | Places `script_text` at `$.script.text`, discovery and research in correct keys. |
| `invoke_cover_art` | Auto-generates `execution_id` when omitted; uses provided `execution_id` when given. |
| `invoke_tts` | Passes `script_text` at `$.script.text`; auto-generates `execution_id`. |
| `invoke_post_production` | Passes all 5 agent outputs in correct state keys. |
| All `invoke_*` | Returns error when Lambda returns `FunctionError`. |
| `get_agent_logs` | Correct log group name per agent; `startTime` from `since_minutes`; `filterPattern` from `execution_id`; respects `limit`; filters by `log_level` client-side. |
| `get_execution_history` | Passes `includeExecutionData`; paginates through `nextToken`. |
| `get_pipeline_health` | Aggregates counts from multiple `ListExecutions` calls; calculates success rate; includes last successful episode from Postgres. |
| `query_episodes` | Excludes `script_text`, `research_json`, `cover_art_prompt`; applies filter params; validates `order_by` against allowlist; rejects SQL injection in `order_by`. |
| `get_episode_detail` | Returns full row including `script_text` and `research_json`. |
| `query_metrics` | Joins with `episodes` for context fields. |
| `query_featured_developers` | Joins with `episodes` for `repo_name`. |
| `run_sql` | Allows SELECT; rejects INSERT, DELETE, DROP, UPDATE; handles leading whitespace; case-insensitive check; sets `statement_timeout`; returns `columns`, `rows`, `row_count`. |
| `upsert_metrics` | Generates `INSERT ... ON CONFLICT` SQL; returns `metric_id` and action. |
| `get_episode_assets` | Queries DB for S3 paths; generates presigned URLs; returns null for missing assets. |
| `list_s3_assets` | Passes prefix; handles empty bucket (no `Contents` key); respects limit. |
| `get_presigned_url` | Default expiry 3600s; accepts custom expiry; caps at 43200s. |
| `invalidate_cache` | Default paths `["/*"]`; accepts custom paths; auto-generates `CallerReference`. |
| `get_site_status` | Aggregates CloudFront status + ACM status + episode count from Postgres. |

### Running MCP Tests

```bash
# Unit tests only
PYTHONPATH=lambdas/shared/python pytest tests/unit/test_mcp/ -v

# Integration tests (requires AWS credentials + env vars)
STATE_MACHINE_ARN=arn:... S3_BUCKET=zerostars-episodes-... \
PYTHONPATH=lambdas/shared/python pytest tests/integration/test_mcp_*_live.py -v -m integration

# E2E (costs money — run manually)
STATE_MACHINE_ARN=arn:... S3_BUCKET=zerostars-episodes-... SITE_DOMAIN=podcast.ryans-lab.click \
PYTHONPATH=lambdas/shared/python pytest tests/e2e/test_mcp_e2e.py -v -m e2e \
--override-ini='addopts='
```
