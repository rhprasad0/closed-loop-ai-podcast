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
│   └── test_shared/         # Tests for shared layer modules
│       ├── __init__.py
│       ├── test_bedrock.py
│       ├── test_db.py
│       └── test_s3.py
└── integration/
    ├── __init__.py
    ├── test_bedrock_live.py
    ├── test_s3_live.py
    └── test_db_live.py
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
]
```

Run locally:
```bash
# Unit tests only (default for development and CI)
PYTHONPATH=lambdas/shared/python pytest tests/unit/ -v

# Integration tests (requires AWS credentials)
PYTHONPATH=lambdas/shared/python pytest tests/integration/ -v -m integration

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
| GitHub API | `unittest.mock` — patch `urllib.request.urlopen`. | Real public API (unauthenticated, 60 req/hour). |

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

**Resource isolation:** Integration tests must use unique prefixes for S3 keys and DB test data (e.g., the GitHub Actions run ID or commit SHA) to prevent conflicts when multiple CI runs execute in parallel. Clean up test resources in a `finally` block or pytest `teardown` fixture.

### End-to-End Tests

End-to-end tests invoke a full Lambda handler locally with real external dependencies (real Bedrock, real API keys, real database). They verify that the entire handler path works — from input event through tool use to parsed output. E2E tests are expensive (Bedrock + Exa API calls) and slow (30-90 seconds per run), so they are run manually, not in CI.

E2E tests live in `tests/integration/` alongside other integration tests and use the same `@pytest.mark.integration` marker.

#### Discovery E2E Test (`tests/integration/test_discovery_e2e.py`)

```python
import json
import os

import boto3
import pytest


@pytest.mark.integration
@pytest.mark.skip(reason="E2E: costs money (Bedrock + Exa). Run manually: pytest tests/integration/test_discovery_e2e.py -v -m integration --override-ini='addopts=' -k e2e")
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

### Per-Handler Test Requirements

Each handler's unit test file must verify:

| Handler | Required test cases |
|---------|-------------------|
| Discovery | **Output parsing:** valid JSON; fenced JSON (` ```json ` and ` ``` `); star_count >= 10 rejected; string star_count coerced to int; missing required field rejected; invalid repo_url rejected; invalid JSON rejected. **psql tool:** SELECT allowed; INSERT/DELETE/DROP/UPDATE each rejected; leading whitespace SELECT allowed; psql stderr returns error dict; subprocess timeout returns error dict. **GitHub tool:** curated fields returned (no extra fields); null license handled; HTTP error returns error dict. **Exa tool:** snake_case inputs mapped to camelCase in request body; HTTP error returns error dict. **Tool dispatcher:** routes to correct function for each tool name; unknown tool returns error dict. **Full handler:** returns valid DiscoveryOutput; passes 3 tools and executor to invoke_with_tools; rejects high star_count from agent; handles fenced output from agent. |
| Research | Output matches `ResearchOutput` shape; handles missing GitHub bio; handles user with zero repos |
| Script | Output matches `ScriptOutput` shape; `character_count` under 5,000; all 6 segments in `segments` list; incorporates producer feedback on retry (`script_attempt > 1`) |
| Producer | Returns `verdict: "PASS"` or `"FAIL"` with correct fields; FAIL includes `feedback` and `issues`; character count over 5,000 triggers FAIL |
| Cover Art | Output matches `CoverArtOutput` shape; S3 key follows `episodes/{execution_id}/cover.png` pattern |
| TTS | Output matches `TTSOutput` shape; correctly parses `**Hype:**`, `**Roast:**`, `**Phil:**` labels; raises exception on malformed script lines |
| Post-Production | Output matches `PostProductionOutput` shape; writes to `episodes` table; writes to `featured_developers` table |
| Site | Returns valid HTML with status 200; handles empty episodes table |
| Shared: bedrock | **invoke_model:** returns parsed text from Bedrock response; passes correct body structure (`anthropic_version`, `max_tokens`, `system`, `messages`). **invoke_with_tools:** single turn with no tool use (`end_turn`) returns text; tool use loop (`tool_use` then `end_turn`) calls tool_executor and returns final text; multiple tool_use blocks in one turn calls tool_executor for each; max_turns exceeded raises RuntimeError; appends correct message structure (assistant with tool_use content, then user with tool_result). **Retry:** retries on ThrottlingException with backoff; raises after max retries exhausted. |
| Shared: db | `query` returns rows; `execute` returns rowcount; connection uses `sslmode=require` |
| Shared: s3 | `upload_bytes` calls S3 `put_object`; `generate_presigned_url` returns valid URL |
