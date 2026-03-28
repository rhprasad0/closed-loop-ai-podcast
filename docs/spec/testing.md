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
│   ├── test_packaging.py
│   ├── test_mcp_pipeline_live.py
│   ├── test_mcp_data_live.py
│   ├── test_mcp_assets_live.py
│   └── test_research_live.py
└── e2e/
    ├── __init__.py
    ├── test_discovery_e2e.py
    ├── test_research_e2e.py
    ├── test_script_e2e.py
    ├── test_producer_e2e.py
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


@pytest.fixture
def mock_script_invoke_model():
    """Patches shared.bedrock.invoke_model for Script handler tests.

    Script handler calls invoke_model (not invoke_with_tools or the raw
    Bedrock client). This fixture patches invoke_model at the handler's
    import site so no Bedrock call is made.

    Usage:
        def test_script(mock_script_invoke_model, ...):
            mock_script_invoke_model.return_value = json.dumps({...})
            result = lambda_handler(event, context)
    """
    with patch("lambdas.script.handler.invoke_model") as mock:
        yield mock


@pytest.fixture
def producer_feedback_for_retry() -> dict:
    """Producer FAIL output used as input to Script handler on retry.

    Placed at $.producer in the pipeline state event when script_attempt > 1.
    """
    return {
        "verdict": "FAIL",
        "score": 4,
        "feedback": (
            "The hiring manager segment is too generic. Reference specific repos "
            "and commit patterns from the research data. Also, character count is "
            "4,950 — cut at least 400 characters."
        ),
        "issues": [
            "Hiring segment uses generic praise instead of specific observations",
            "Character count too close to 5,000 limit (4,950)",
            "Roast's grudging compliment in segment 4 does not reference a specific technical decision",
        ],
    }


@pytest.fixture
def mock_producer_invoke_model():
    """Patches shared.bedrock.invoke_model for Producer handler tests.

    Producer handler calls invoke_model (not invoke_with_tools or the raw
    Bedrock client). This fixture patches invoke_model at the handler's
    import site so no Bedrock call is made.

    Usage:
        def test_producer(mock_producer_invoke_model, ...):
            mock_producer_invoke_model.return_value = json.dumps({...})
            result = lambda_handler(event, context)
    """
    with patch("lambdas.producer.handler.invoke_model") as mock:
        yield mock


@pytest.fixture
def mock_producer_db_query():
    """Patches shared.db.query for Producer handler's benchmark script fetching.

    The Producer handler calls shared.db.query to fetch top-performing episode
    scripts from Postgres. This fixture patches query at the handler's import
    site so no database call is made.

    Usage:
        def test_producer_with_benchmarks(mock_producer_db_query, ...):
            mock_producer_db_query.return_value = [("script text here",)]
            result = lambda_handler(event, context)
    """
    with patch("lambdas.producer.handler.query") as mock:
        mock.return_value = []  # default: no benchmarks
        yield mock


@pytest.fixture
def sample_producer_pass_output() -> dict:
    return {
        "verdict": "PASS",
        "score": 8,
        "notes": "Strong character voices, specific jokes about testrepo. Hiring segment references actual repos.",
    }


@pytest.fixture
def sample_producer_fail_output() -> dict:
    return {
        "verdict": "FAIL",
        "score": 4,
        "feedback": (
            "The hiring manager segment is too generic. Reference specific repos "
            "and commit patterns from the research data. Also, Roast's grudging "
            "compliment in segment 4 says 'it is not terrible' without referencing "
            "a specific technical decision."
        ),
        "issues": [
            "Hiring segment uses generic praise instead of specific observations",
            "Roast's grudging compliment does not reference a specific technical decision",
            "Two generic jokes could apply to any project (lines 3 and 7)",
        ],
    }


@pytest.fixture
def sample_benchmark_scripts() -> list[tuple[str]]:
    """Benchmark scripts as returned by shared.db.query (list of row tuples)."""
    return [
        (
            "**Hype:** Welcome back! Today we found pasta-sorter by noodlefan99!\n"
            "**Roast:** Four stars. My sourdough starter has more followers.\n"
            "**Phil:** But what is a sort, really? Are we not all just unsorted data?",
        ),
    ]
```

@pytest.fixture
def mock_nova_canvas_client():
    """Patches _get_bedrock_client in the Cover Art handler.

    Cover Art creates its own boto3 Bedrock client (not shared.bedrock),
    so we patch the handler's cached client getter. The yielded mock is
    the client object whose invoke_model method can be configured.

    Usage:
        def test_cover_art(mock_nova_canvas_client, ...):
            mock_response = MagicMock()
            mock_response.read.return_value = json.dumps({
                "images": [base64.b64encode(PNG_BYTES).decode()]
            }).encode()
            mock_nova_canvas_client.invoke_model.return_value = {"body": mock_response}
    """
    with patch("lambdas.cover_art.handler._get_bedrock_client") as mock:
        client = MagicMock()
        mock.return_value = client
        yield client


@pytest.fixture
def mock_s3_upload():
    """Patches shared.s3.upload_bytes for Cover Art handler.

    Usage:
        def test_cover_art(mock_s3_upload, ...):
            result = lambda_handler(event, context)
            mock_s3_upload.assert_called_once_with(bucket, key, bytes, "image/png")
    """
    with patch("lambdas.cover_art.handler.upload_bytes") as mock:
        yield mock


@pytest.fixture
def mock_cover_art_prompt_template():
    """Patches _load_prompt_template to return a known template string.

    Uses a short template with all three placeholders for predictable assertions.
    """
    template = (
        "Three robots reacting to {{visual_concept}}. "
        "Colors: {{color_mood}}. Title: {{episode_subtitle}}."
    )
    with patch("lambdas.cover_art.handler._load_prompt_template", return_value=template):
        yield template
```

### Mocking Strategy

| Dependency | Unit test approach | Integration test approach |
|-----------|-------------------|-------------------------|
| Bedrock (invoke_model) | `unittest.mock` — patch `boto3.client("bedrock-runtime")` return values. moto does not support Bedrock. | Real Bedrock calls with dev AWS credentials. |
| Bedrock (invoke_with_tools) | `unittest.mock` — patch `invoke_with_tools` at the handler's import path (e.g., `lambdas.discovery.handler.invoke_with_tools`). | Real Bedrock calls (see E2E tests). |
| Bedrock (Nova Canvas) | `unittest.mock` — patch `_get_bedrock_client` in `lambdas.cover_art.handler`. Mock `invoke_model` to return a response with base64-encoded PNG bytes. | Real Bedrock calls (costs money — skip by default, see integration test). |
| S3 | `moto` `@mock_aws` decorator — creates in-memory S3. | Real S3 bucket in dev account with `test/` key prefix. |
| S3 (Cover Art upload) | `unittest.mock` — patch `upload_bytes` at `lambdas.cover_art.handler.upload_bytes`. | Real S3 bucket (tested transitively via E2E). |
| Postgres (shared/db.py) | `unittest.mock` — patch `psycopg2.connect`, mock cursor `fetchall`/`execute`. | Real dev RDS instance. |
| Postgres (Discovery/psql) | `unittest.mock` — patch `subprocess.run` in `lambdas.discovery.handler`. | Real psql against dev RDS (see Discovery integration tests). |
| Postgres (Producer/shared.db) | `unittest.mock` — patch `shared.db.query` at `lambdas.producer.handler.query`. | Real dev RDS instance (see `test_producer_db_benchmark_query` integration test). |
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

### Script Unit Tests

Tests for the Script handler (`tests/unit/test_script.py`). The Script handler is simpler than Discovery and Research — it uses `invoke_model` (single prompt-response) instead of `invoke_with_tools`, so there are no tool function tests or dispatcher tests. The test structure has three sections: output parsing, user message building, and full handler tests.

#### Output Parsing Tests

```python
import json
import pytest

from lambdas.script.handler import _parse_script_output

VALID_SCRIPT_TEXT = (
    "**Hype:** Welcome back to 0 Stars, 10 out of 10! Today we found testrepo.\n"
    "**Roast:** Three stars. Impressive. My cat's Instagram has more followers.\n"
    "**Phil:** But what is a star, really? A mass of burning gas, or a mass of burning ambition?\n"
    "**Hype:** This developer built a markdown converter in 200 lines of Rust!\n"
    "**Roast:** Two hundred lines. My error handler is longer.\n"
    "**Phil:** Perhaps brevity is the soul of code, as it is the soul of wit.\n"
    "**Hype:** Let me tell you about this developer. Fifteen repos. Fifteen!\n"
    "**Roast:** Half of them are forks with zero changes.\n"
    "**Phil:** To fork or not to fork. That is the question.\n"
    "**Roast:** Fine. The error handling is actually solid. Happy?\n"
    "**Hype:** He said it! He said something nice!\n"
    "**Phil:** When the cynic finds beauty, the universe notices.\n"
    "**Hype:** Any hiring manager would snap this developer up in a second!\n"
    "**Roast:** They ship finished projects. With READMEs. That alone puts them ahead of 90 percent of candidates.\n"
    "**Phil:** Can we ever truly know a developer through their commits?\n"
    "**Hype:** That is all for today! Remember, zero stars, ten out of ten!\n"
    "**Roast:** Same time next week. Try not to break anything.\n"
    "**Phil:** But what is time, if not a loop we choose to re-enter?"
)

VALID_OUTPUT = {
    "text": VALID_SCRIPT_TEXT,
    "character_count": len(VALID_SCRIPT_TEXT),
    "segments": [
        "intro", "core_debate", "developer_deep_dive",
        "technical_appreciation", "hiring_manager", "outro",
    ],
    "featured_repo": "testrepo",
    "featured_developer": "testuser",
    "cover_art_suggestion": "A terminal window with Rust code scrolling past, three robot silhouettes in a podcast studio",
}


def test_parse_valid_json():
    result = _parse_script_output(json.dumps(VALID_OUTPUT))
    assert result["featured_repo"] == "testrepo"
    assert result["character_count"] == len(VALID_SCRIPT_TEXT)
    assert len(result["segments"]) == 6


def test_parse_fenced_json():
    fenced = f"```json\n{json.dumps(VALID_OUTPUT)}\n```"
    result = _parse_script_output(fenced)
    assert result["featured_repo"] == "testrepo"


def test_parse_fenced_no_language_tag():
    fenced = f"```\n{json.dumps(VALID_OUTPUT)}\n```"
    result = _parse_script_output(fenced)
    assert result["featured_repo"] == "testrepo"


def test_parse_rejects_character_count_gte_5000():
    long_text = "**Hype:** " + "x" * 4991  # total > 5000
    bad = {**VALID_OUTPUT, "text": long_text, "character_count": len(long_text)}
    with pytest.raises(ValueError, match="character_count"):
        _parse_script_output(json.dumps(bad))


def test_parse_coerces_string_character_count():
    coerced = {**VALID_OUTPUT, "character_count": str(len(VALID_SCRIPT_TEXT))}
    result = _parse_script_output(json.dumps(coerced))
    assert isinstance(result["character_count"], int)


def test_parse_corrects_inaccurate_character_count():
    wrong_count = {**VALID_OUTPUT, "character_count": 999}
    result = _parse_script_output(json.dumps(wrong_count))
    assert result["character_count"] == len(VALID_SCRIPT_TEXT)


def test_parse_rejects_missing_field():
    incomplete = {k: v for k, v in VALID_OUTPUT.items() if k != "text"}
    with pytest.raises(ValueError, match="text"):
        _parse_script_output(json.dumps(incomplete))


def test_parse_rejects_missing_segments():
    incomplete = {k: v for k, v in VALID_OUTPUT.items() if k != "segments"}
    with pytest.raises(ValueError, match="segments"):
        _parse_script_output(json.dumps(incomplete))


def test_parse_rejects_invalid_json():
    with pytest.raises((ValueError, json.JSONDecodeError)):
        _parse_script_output("this is not json at all")


def test_parse_rejects_wrong_segments():
    bad = {**VALID_OUTPUT, "segments": ["intro", "outro"]}
    with pytest.raises(ValueError, match="segments"):
        _parse_script_output(json.dumps(bad))


def test_parse_rejects_segments_wrong_order():
    bad = {**VALID_OUTPUT, "segments": [
        "outro", "intro", "core_debate", "developer_deep_dive",
        "technical_appreciation", "hiring_manager",
    ]}
    with pytest.raises(ValueError, match="segments"):
        _parse_script_output(json.dumps(bad))


def test_parse_accepts_text_at_4999_characters():
    # Build a valid script text of exactly 4999 characters
    line = "**Hype:** " + "x" * 70 + "\n"  # 81 chars per line
    num_lines = 4999 // len(line)
    remainder = 4999 - (num_lines * len(line))
    text = line * num_lines + "**Hype:** " + "x" * (remainder - len("**Hype:** "))
    assert len(text) == 4999
    output = {**VALID_OUTPUT, "text": text, "character_count": 4999}
    result = _parse_script_output(json.dumps(output))
    assert result["character_count"] == 4999


def test_parse_rejects_text_at_5000_characters():
    line = "**Hype:** " + "x" * 70 + "\n"
    num_lines = 5000 // len(line)
    remainder = 5000 - (num_lines * len(line))
    text = line * num_lines + "**Hype:** " + "x" * (remainder - len("**Hype:** "))
    assert len(text) == 5000
    bad = {**VALID_OUTPUT, "text": text, "character_count": 5000}
    with pytest.raises(ValueError, match="character_count"):
        _parse_script_output(json.dumps(bad))
```

#### User Message Building Tests

```python
from lambdas.script.handler import _build_user_message


def test_build_user_message_includes_discovery_data(
    pipeline_metadata, sample_discovery_output, sample_research_output,
):
    event = {
        "metadata": pipeline_metadata,
        "discovery": sample_discovery_output,
        "research": sample_research_output,
    }
    msg = _build_user_message(event)
    assert "testrepo" in msg
    assert "Python" in msg
    assert "Clean architecture" in msg


def test_build_user_message_includes_research_data(
    pipeline_metadata, sample_discovery_output, sample_research_output,
):
    event = {
        "metadata": pipeline_metadata,
        "discovery": sample_discovery_output,
        "research": sample_research_output,
    }
    msg = _build_user_message(event)
    assert "Test User" in msg
    assert "Strong fundamentals" in msg
    assert "Built a custom ORM" in msg


def test_build_user_message_includes_attempt_number(
    pipeline_metadata, sample_discovery_output, sample_research_output,
):
    event = {
        "metadata": pipeline_metadata,
        "discovery": sample_discovery_output,
        "research": sample_research_output,
    }
    msg = _build_user_message(event)
    assert "attempt 1" in msg.lower()


def test_build_user_message_omits_feedback_on_first_attempt(
    pipeline_metadata, sample_discovery_output, sample_research_output,
):
    event = {
        "metadata": pipeline_metadata,
        "discovery": sample_discovery_output,
        "research": sample_research_output,
    }
    msg = _build_user_message(event)
    assert "Producer Feedback" not in msg


def test_build_user_message_includes_feedback_on_retry(
    sample_discovery_output, sample_research_output, producer_feedback_for_retry,
):
    event = {
        "metadata": {
            "execution_id": "arn:aws:states:us-east-1:123456789:execution:zerostars-pipeline:test-run",
            "script_attempt": 2,
        },
        "discovery": sample_discovery_output,
        "research": sample_research_output,
        "producer": producer_feedback_for_retry,
    }
    msg = _build_user_message(event)
    assert "Producer Feedback" in msg
    assert "hiring manager segment is too generic" in msg.lower()


def test_build_user_message_includes_all_issues(
    sample_discovery_output, sample_research_output, producer_feedback_for_retry,
):
    event = {
        "metadata": {
            "execution_id": "arn:aws:states:us-east-1:123456789:execution:zerostars-pipeline:test-run",
            "script_attempt": 2,
        },
        "discovery": sample_discovery_output,
        "research": sample_research_output,
        "producer": producer_feedback_for_retry,
    }
    msg = _build_user_message(event)
    for issue in producer_feedback_for_retry["issues"]:
        assert issue in msg
```

#### Full Handler Tests

```python
import json
from unittest.mock import patch

VALID_HANDLER_OUTPUT = json.dumps(VALID_OUTPUT)


def test_handler_returns_valid_output(
    pipeline_metadata, lambda_context, mock_script_invoke_model,
    sample_discovery_output, sample_research_output,
):
    mock_script_invoke_model.return_value = VALID_HANDLER_OUTPUT
    with patch("lambdas.script.handler._load_system_prompt", return_value="sp"):
        from lambdas.script.handler import lambda_handler
        result = lambda_handler(
            {"metadata": pipeline_metadata, "discovery": sample_discovery_output, "research": sample_research_output},
            lambda_context,
        )
    assert result["featured_repo"] == "testrepo"
    assert isinstance(result["character_count"], int)
    assert result["character_count"] < 5000


def test_handler_calls_invoke_model_not_invoke_with_tools(
    pipeline_metadata, lambda_context, mock_script_invoke_model,
    sample_discovery_output, sample_research_output,
):
    mock_script_invoke_model.return_value = VALID_HANDLER_OUTPUT
    with patch("lambdas.script.handler._load_system_prompt", return_value="sp"):
        from lambdas.script.handler import lambda_handler
        lambda_handler(
            {"metadata": pipeline_metadata, "discovery": sample_discovery_output, "research": sample_research_output},
            lambda_context,
        )
    mock_script_invoke_model.assert_called_once()
    call_kwargs = mock_script_invoke_model.call_args
    # invoke_model takes user_message and system_prompt, NOT tools or tool_executor
    assert "tools" not in (call_kwargs.kwargs or {})
    assert "tool_executor" not in (call_kwargs.kwargs or {})


def test_handler_user_message_contains_discovery_data(
    pipeline_metadata, lambda_context, mock_script_invoke_model,
    sample_discovery_output, sample_research_output,
):
    mock_script_invoke_model.return_value = VALID_HANDLER_OUTPUT
    with patch("lambdas.script.handler._load_system_prompt", return_value="sp"):
        from lambdas.script.handler import lambda_handler
        lambda_handler(
            {"metadata": pipeline_metadata, "discovery": sample_discovery_output, "research": sample_research_output},
            lambda_context,
        )
    user_message = mock_script_invoke_model.call_args[1].get(
        "user_message", mock_script_invoke_model.call_args[0][0]
    )
    assert "testrepo" in user_message
    assert "Python" in user_message


def test_handler_user_message_contains_research_data(
    pipeline_metadata, lambda_context, mock_script_invoke_model,
    sample_discovery_output, sample_research_output,
):
    mock_script_invoke_model.return_value = VALID_HANDLER_OUTPUT
    with patch("lambdas.script.handler._load_system_prompt", return_value="sp"):
        from lambdas.script.handler import lambda_handler
        lambda_handler(
            {"metadata": pipeline_metadata, "discovery": sample_discovery_output, "research": sample_research_output},
            lambda_context,
        )
    user_message = mock_script_invoke_model.call_args[1].get(
        "user_message", mock_script_invoke_model.call_args[0][0]
    )
    assert "Test User" in user_message
    assert "Built a custom ORM" in user_message


def test_handler_first_attempt_no_feedback_in_message(
    pipeline_metadata, lambda_context, mock_script_invoke_model,
    sample_discovery_output, sample_research_output,
):
    mock_script_invoke_model.return_value = VALID_HANDLER_OUTPUT
    with patch("lambdas.script.handler._load_system_prompt", return_value="sp"):
        from lambdas.script.handler import lambda_handler
        lambda_handler(
            {"metadata": pipeline_metadata, "discovery": sample_discovery_output, "research": sample_research_output},
            lambda_context,
        )
    user_message = mock_script_invoke_model.call_args[1].get(
        "user_message", mock_script_invoke_model.call_args[0][0]
    )
    assert "Producer Feedback" not in user_message


def test_handler_retry_includes_producer_feedback(
    lambda_context, mock_script_invoke_model,
    sample_discovery_output, sample_research_output, producer_feedback_for_retry,
):
    mock_script_invoke_model.return_value = VALID_HANDLER_OUTPUT
    retry_metadata = {
        "execution_id": "arn:aws:states:us-east-1:123456789:execution:zerostars-pipeline:test-run",
        "script_attempt": 2,
    }
    with patch("lambdas.script.handler._load_system_prompt", return_value="sp"):
        from lambdas.script.handler import lambda_handler
        lambda_handler(
            {
                "metadata": retry_metadata,
                "discovery": sample_discovery_output,
                "research": sample_research_output,
                "producer": producer_feedback_for_retry,
            },
            lambda_context,
        )
    user_message = mock_script_invoke_model.call_args[1].get(
        "user_message", mock_script_invoke_model.call_args[0][0]
    )
    assert "Producer Feedback" in user_message
    assert "hiring manager segment is too generic" in user_message.lower()
    for issue in producer_feedback_for_retry["issues"]:
        assert issue in user_message


def test_handler_handles_fenced_output(
    pipeline_metadata, lambda_context, mock_script_invoke_model,
    sample_discovery_output, sample_research_output,
):
    mock_script_invoke_model.return_value = f"```json\n{VALID_HANDLER_OUTPUT}\n```"
    with patch("lambdas.script.handler._load_system_prompt", return_value="sp"):
        from lambdas.script.handler import lambda_handler
        result = lambda_handler(
            {"metadata": pipeline_metadata, "discovery": sample_discovery_output, "research": sample_research_output},
            lambda_context,
        )
    assert result["featured_repo"] == "testrepo"


def test_handler_raises_on_character_count_exceeded(
    pipeline_metadata, lambda_context, mock_script_invoke_model,
    sample_discovery_output, sample_research_output,
):
    long_text = "**Hype:** " + "x" * 4991  # > 5000 chars
    bad_output = {**VALID_OUTPUT, "text": long_text, "character_count": len(long_text)}
    mock_script_invoke_model.return_value = json.dumps(bad_output)
    with patch("lambdas.script.handler._load_system_prompt", return_value="sp"):
        from lambdas.script.handler import lambda_handler
        with pytest.raises(ValueError, match="character_count"):
            lambda_handler(
                {"metadata": pipeline_metadata, "discovery": sample_discovery_output, "research": sample_research_output},
                lambda_context,
            )


def test_handler_raises_on_invalid_json_from_model(
    pipeline_metadata, lambda_context, mock_script_invoke_model,
    sample_discovery_output, sample_research_output,
):
    mock_script_invoke_model.return_value = "I cannot write a script because the project is too boring."
    with patch("lambdas.script.handler._load_system_prompt", return_value="sp"):
        from lambdas.script.handler import lambda_handler
        with pytest.raises((ValueError, json.JSONDecodeError)):
            lambda_handler(
                {"metadata": pipeline_metadata, "discovery": sample_discovery_output, "research": sample_research_output},
                lambda_context,
            )


def test_handler_raises_on_bedrock_error(
    pipeline_metadata, lambda_context, mock_script_invoke_model,
    sample_discovery_output, sample_research_output,
):
    mock_script_invoke_model.side_effect = RuntimeError("Bedrock throttled")
    with patch("lambdas.script.handler._load_system_prompt", return_value="sp"):
        from lambdas.script.handler import lambda_handler
        with pytest.raises(RuntimeError, match="Bedrock"):
            lambda_handler(
                {"metadata": pipeline_metadata, "discovery": sample_discovery_output, "research": sample_research_output},
                lambda_context,
            )
```

### Producer Unit Tests

Tests for the Producer handler (`tests/unit/test_producer.py`). The Producer handler follows the same pattern as the Script handler — it uses `invoke_model` (single prompt-response) instead of `invoke_with_tools`, so there are no tool function tests or dispatcher tests. The Producer also queries Postgres for benchmark scripts via `shared.db.query`. The test structure has three sections: output parsing, user message building, and full handler tests.

#### Output Parsing Tests

```python
import json
import pytest

from lambdas.producer.handler import _parse_producer_output

VALID_PASS_OUTPUT = {
    "verdict": "PASS",
    "score": 8,
    "notes": "Strong character voices, specific jokes. Hiring segment references actual repos.",
}

VALID_FAIL_OUTPUT = {
    "verdict": "FAIL",
    "score": 4,
    "feedback": (
        "The hiring manager segment uses generic praise instead of specific observations. "
        "Rewrite Roast's line in segment 5 to reference a specific repo by name."
    ),
    "issues": [
        "Hiring segment uses generic praise instead of specific observations",
        "Roast's grudging compliment does not reference a specific technical decision",
    ],
}


def test_parse_valid_pass_json():
    result = _parse_producer_output(json.dumps(VALID_PASS_OUTPUT))
    assert result["verdict"] == "PASS"
    assert result["score"] == 8
    assert result["notes"] == VALID_PASS_OUTPUT["notes"]


def test_parse_valid_fail_json():
    result = _parse_producer_output(json.dumps(VALID_FAIL_OUTPUT))
    assert result["verdict"] == "FAIL"
    assert result["score"] == 4
    assert "hiring" in result["feedback"].lower()
    assert len(result["issues"]) == 2


def test_parse_fenced_json():
    fenced = f"```json\n{json.dumps(VALID_PASS_OUTPUT)}\n```"
    result = _parse_producer_output(fenced)
    assert result["verdict"] == "PASS"


def test_parse_fenced_no_language_tag():
    fenced = f"```\n{json.dumps(VALID_PASS_OUTPUT)}\n```"
    result = _parse_producer_output(fenced)
    assert result["verdict"] == "PASS"


def test_parse_rejects_missing_verdict():
    incomplete = {"score": 8, "notes": "Good script."}
    with pytest.raises(ValueError, match="verdict"):
        _parse_producer_output(json.dumps(incomplete))


def test_parse_rejects_missing_score():
    incomplete = {"verdict": "PASS", "notes": "Good script."}
    with pytest.raises(ValueError, match="score"):
        _parse_producer_output(json.dumps(incomplete))


def test_parse_rejects_invalid_verdict_value():
    bad = {**VALID_PASS_OUTPUT, "verdict": "MAYBE"}
    with pytest.raises(ValueError, match="verdict"):
        _parse_producer_output(json.dumps(bad))


def test_parse_rejects_fail_missing_feedback():
    bad = {"verdict": "FAIL", "score": 4, "issues": ["issue 1"]}
    with pytest.raises(ValueError, match="feedback"):
        _parse_producer_output(json.dumps(bad))


def test_parse_rejects_fail_missing_issues():
    bad = {"verdict": "FAIL", "score": 4, "feedback": "Fix the hiring segment."}
    with pytest.raises(ValueError, match="issues"):
        _parse_producer_output(json.dumps(bad))


def test_parse_pass_with_notes_accepted():
    result = _parse_producer_output(json.dumps(VALID_PASS_OUTPUT))
    assert "notes" in result
    assert isinstance(result["notes"], str)


def test_parse_pass_without_notes_accepted():
    minimal = {"verdict": "PASS", "score": 7}
    result = _parse_producer_output(json.dumps(minimal))
    assert result["verdict"] == "PASS"
    assert result["score"] == 7


def test_parse_coerces_string_score_to_int():
    coerced = {**VALID_PASS_OUTPUT, "score": "8"}
    result = _parse_producer_output(json.dumps(coerced))
    assert result["score"] == 8
    assert isinstance(result["score"], int)


def test_parse_rejects_invalid_json():
    with pytest.raises((ValueError, json.JSONDecodeError)):
        _parse_producer_output("this is not json at all")
```

#### User Message Building Tests

```python
from lambdas.producer.handler import _build_user_message


def test_build_user_message_includes_script_text(
    pipeline_metadata, sample_discovery_output, sample_research_output, sample_script_output,
):
    event = {
        "metadata": pipeline_metadata,
        "discovery": sample_discovery_output,
        "research": sample_research_output,
        "script": sample_script_output,
    }
    msg = _build_user_message(event, benchmarks=[])
    assert "Welcome to 0 Stars" in msg


def test_build_user_message_includes_character_count(
    pipeline_metadata, sample_discovery_output, sample_research_output, sample_script_output,
):
    event = {
        "metadata": pipeline_metadata,
        "discovery": sample_discovery_output,
        "research": sample_research_output,
        "script": sample_script_output,
    }
    msg = _build_user_message(event, benchmarks=[])
    assert str(sample_script_output["character_count"]) in msg


def test_build_user_message_includes_discovery_repo_name(
    pipeline_metadata, sample_discovery_output, sample_research_output, sample_script_output,
):
    event = {
        "metadata": pipeline_metadata,
        "discovery": sample_discovery_output,
        "research": sample_research_output,
        "script": sample_script_output,
    }
    msg = _build_user_message(event, benchmarks=[])
    assert "testrepo" in msg


def test_build_user_message_includes_discovery_repo_description(
    pipeline_metadata, sample_discovery_output, sample_research_output, sample_script_output,
):
    event = {
        "metadata": pipeline_metadata,
        "discovery": sample_discovery_output,
        "research": sample_research_output,
        "script": sample_script_output,
    }
    msg = _build_user_message(event, benchmarks=[])
    assert "A test repository" in msg


def test_build_user_message_includes_research_hiring_signals(
    pipeline_metadata, sample_discovery_output, sample_research_output, sample_script_output,
):
    event = {
        "metadata": pipeline_metadata,
        "discovery": sample_discovery_output,
        "research": sample_research_output,
        "script": sample_script_output,
    }
    msg = _build_user_message(event, benchmarks=[])
    assert "Strong fundamentals" in msg


def test_build_user_message_includes_benchmark_scripts(
    pipeline_metadata, sample_discovery_output, sample_research_output,
    sample_script_output, sample_benchmark_scripts,
):
    benchmarks = [row[0] for row in sample_benchmark_scripts]
    event = {
        "metadata": pipeline_metadata,
        "discovery": sample_discovery_output,
        "research": sample_research_output,
        "script": sample_script_output,
    }
    msg = _build_user_message(event, benchmarks=benchmarks)
    assert "pasta-sorter" in msg
    assert "Benchmark" in msg


def test_build_user_message_handles_no_benchmarks(
    pipeline_metadata, sample_discovery_output, sample_research_output, sample_script_output,
):
    event = {
        "metadata": pipeline_metadata,
        "discovery": sample_discovery_output,
        "research": sample_research_output,
        "script": sample_script_output,
    }
    msg = _build_user_message(event, benchmarks=[])
    assert "Benchmark" not in msg or "no benchmark" in msg.lower()
```

#### Full Handler Tests

```python
import json
from unittest.mock import patch

import pytest

VALID_PASS_HANDLER_OUTPUT = json.dumps({
    "verdict": "PASS",
    "score": 8,
    "notes": "Strong character voices, specific jokes about testrepo.",
})

VALID_FAIL_HANDLER_OUTPUT = json.dumps({
    "verdict": "FAIL",
    "score": 4,
    "feedback": "The hiring segment uses generic praise. Reference specific repos.",
    "issues": [
        "Hiring segment uses generic praise",
        "Roast's compliment is too vague",
    ],
})


def test_handler_returns_valid_pass_output(
    pipeline_metadata, lambda_context, mock_producer_invoke_model,
    mock_producer_db_query, sample_discovery_output, sample_research_output,
    sample_script_output,
):
    mock_producer_invoke_model.return_value = VALID_PASS_HANDLER_OUTPUT
    with patch("lambdas.producer.handler._load_system_prompt", return_value="sp"):
        from lambdas.producer.handler import lambda_handler
        result = lambda_handler(
            {
                "metadata": pipeline_metadata,
                "discovery": sample_discovery_output,
                "research": sample_research_output,
                "script": sample_script_output,
            },
            lambda_context,
        )
    assert result["verdict"] == "PASS"
    assert isinstance(result["score"], int)
    assert result["score"] == 8


def test_handler_returns_valid_fail_output(
    pipeline_metadata, lambda_context, mock_producer_invoke_model,
    mock_producer_db_query, sample_discovery_output, sample_research_output,
    sample_script_output,
):
    mock_producer_invoke_model.return_value = VALID_FAIL_HANDLER_OUTPUT
    with patch("lambdas.producer.handler._load_system_prompt", return_value="sp"):
        from lambdas.producer.handler import lambda_handler
        result = lambda_handler(
            {
                "metadata": pipeline_metadata,
                "discovery": sample_discovery_output,
                "research": sample_research_output,
                "script": sample_script_output,
            },
            lambda_context,
        )
    assert result["verdict"] == "FAIL"
    assert isinstance(result["score"], int)
    assert "feedback" in result
    assert "issues" in result
    assert isinstance(result["issues"], list)
    assert len(result["issues"]) >= 1


def test_handler_calls_invoke_model_not_invoke_with_tools(
    pipeline_metadata, lambda_context, mock_producer_invoke_model,
    mock_producer_db_query, sample_discovery_output, sample_research_output,
    sample_script_output,
):
    mock_producer_invoke_model.return_value = VALID_PASS_HANDLER_OUTPUT
    with patch("lambdas.producer.handler._load_system_prompt", return_value="sp"):
        from lambdas.producer.handler import lambda_handler
        lambda_handler(
            {
                "metadata": pipeline_metadata,
                "discovery": sample_discovery_output,
                "research": sample_research_output,
                "script": sample_script_output,
            },
            lambda_context,
        )
    mock_producer_invoke_model.assert_called_once()
    call_kwargs = mock_producer_invoke_model.call_args
    # invoke_model takes user_message and system_prompt, NOT tools or tool_executor
    assert "tools" not in (call_kwargs.kwargs or {})
    assert "tool_executor" not in (call_kwargs.kwargs or {})


def test_handler_reads_script_discovery_research_from_event(
    pipeline_metadata, lambda_context, mock_producer_invoke_model,
    mock_producer_db_query, sample_discovery_output, sample_research_output,
    sample_script_output,
):
    mock_producer_invoke_model.return_value = VALID_PASS_HANDLER_OUTPUT
    with patch("lambdas.producer.handler._load_system_prompt", return_value="sp"):
        from lambdas.producer.handler import lambda_handler
        lambda_handler(
            {
                "metadata": pipeline_metadata,
                "discovery": sample_discovery_output,
                "research": sample_research_output,
                "script": sample_script_output,
            },
            lambda_context,
        )
    user_message = mock_producer_invoke_model.call_args[1].get(
        "user_message", mock_producer_invoke_model.call_args[0][0]
    )
    # Script text
    assert "Welcome to 0 Stars" in user_message
    # Discovery data
    assert "testrepo" in user_message
    # Research data
    assert "Strong fundamentals" in user_message


def test_handler_queries_database_for_benchmark_scripts(
    pipeline_metadata, lambda_context, mock_producer_invoke_model,
    mock_producer_db_query, sample_discovery_output, sample_research_output,
    sample_script_output,
):
    mock_producer_invoke_model.return_value = VALID_PASS_HANDLER_OUTPUT
    with patch("lambdas.producer.handler._load_system_prompt", return_value="sp"):
        from lambdas.producer.handler import lambda_handler
        lambda_handler(
            {
                "metadata": pipeline_metadata,
                "discovery": sample_discovery_output,
                "research": sample_research_output,
                "script": sample_script_output,
            },
            lambda_context,
        )
    mock_producer_db_query.assert_called_once()


def test_handler_handles_fenced_output(
    pipeline_metadata, lambda_context, mock_producer_invoke_model,
    mock_producer_db_query, sample_discovery_output, sample_research_output,
    sample_script_output,
):
    mock_producer_invoke_model.return_value = f"```json\n{VALID_PASS_HANDLER_OUTPUT}\n```"
    with patch("lambdas.producer.handler._load_system_prompt", return_value="sp"):
        from lambdas.producer.handler import lambda_handler
        result = lambda_handler(
            {
                "metadata": pipeline_metadata,
                "discovery": sample_discovery_output,
                "research": sample_research_output,
                "script": sample_script_output,
            },
            lambda_context,
        )
    assert result["verdict"] == "PASS"


def test_handler_handles_empty_benchmark_results(
    pipeline_metadata, lambda_context, mock_producer_invoke_model,
    mock_producer_db_query, sample_discovery_output, sample_research_output,
    sample_script_output,
):
    mock_producer_db_query.return_value = []  # no episodes exist yet
    mock_producer_invoke_model.return_value = VALID_PASS_HANDLER_OUTPUT
    with patch("lambdas.producer.handler._load_system_prompt", return_value="sp"):
        from lambdas.producer.handler import lambda_handler
        result = lambda_handler(
            {
                "metadata": pipeline_metadata,
                "discovery": sample_discovery_output,
                "research": sample_research_output,
                "script": sample_script_output,
            },
            lambda_context,
        )
    assert result["verdict"] == "PASS"


def test_handler_propagates_runtime_error_from_invoke_model(
    pipeline_metadata, lambda_context, mock_producer_invoke_model,
    mock_producer_db_query, sample_discovery_output, sample_research_output,
    sample_script_output,
):
    mock_producer_invoke_model.side_effect = RuntimeError("Bedrock throttled")
    with patch("lambdas.producer.handler._load_system_prompt", return_value="sp"):
        from lambdas.producer.handler import lambda_handler
        with pytest.raises(RuntimeError, match="Bedrock"):
            lambda_handler(
                {
                    "metadata": pipeline_metadata,
                    "discovery": sample_discovery_output,
                    "research": sample_research_output,
                    "script": sample_script_output,
                },
                lambda_context,
            )
```

### Cover Art Unit Tests

Tests for the Cover Art handler (`tests/unit/test_cover_art.py`). The Cover Art handler is the simplest pipeline handler — no agent loop, no tool dispatch, no parsing of model-generated JSON. It builds a prompt from a template, calls Nova Canvas for image generation, uploads the PNG to S3, and returns the S3 key. The test structure has three sections: prompt construction, image generation, and full handler tests.

#### Prompt Construction Tests

```python
import json

import pytest

from lambdas.cover_art.handler import (
    _build_cover_art_prompt,
    DEFAULT_COLOR_MOOD,
    LANGUAGE_COLOR_MOODS,
)


def test_build_prompt_substitutes_visual_concept(mock_cover_art_prompt_template):
    result = _build_cover_art_prompt(
        cover_art_suggestion="a terminal window with pasta names scrolling",
        repo_name="pasta-sorter",
        language="Python",
    )
    assert "a terminal window with pasta names scrolling" in result


def test_build_prompt_substitutes_repo_name(mock_cover_art_prompt_template):
    result = _build_cover_art_prompt(
        cover_art_suggestion="robots coding",
        repo_name="pasta-sorter",
        language="Python",
    )
    assert "pasta-sorter" in result


def test_build_prompt_maps_python_to_color_mood(mock_cover_art_prompt_template):
    result = _build_cover_art_prompt(
        cover_art_suggestion="robots coding",
        repo_name="testrepo",
        language="Python",
    )
    assert "warm yellows" in result


def test_build_prompt_maps_rust_to_color_mood(mock_cover_art_prompt_template):
    result = _build_cover_art_prompt(
        cover_art_suggestion="robots coding",
        repo_name="testrepo",
        language="Rust",
    )
    assert "deep oranges" in result


def test_build_prompt_unknown_language_uses_default(mock_cover_art_prompt_template):
    result = _build_cover_art_prompt(
        cover_art_suggestion="robots coding",
        repo_name="testrepo",
        language="Brainfuck",
    )
    assert DEFAULT_COLOR_MOOD in result


def test_build_prompt_empty_suggestion_uses_fallback(mock_cover_art_prompt_template):
    result = _build_cover_art_prompt(
        cover_art_suggestion="",
        repo_name="testrepo",
        language="Python",
    )
    assert "testrepo" in result
    # Should not contain empty string substitution — fallback kicks in
    assert "abstract visualization" in result or "testrepo" in result


def test_build_prompt_truncates_to_1024_chars(mock_cover_art_prompt_template):
    # Force a prompt that would exceed 1024 chars after substitution
    long_suggestion = "x" * 900  # way longer than template can accommodate
    result = _build_cover_art_prompt(
        cover_art_suggestion=long_suggestion,
        repo_name="testrepo",
        language="Python",
    )
    assert len(result) <= 1024
```

#### Image Generation Tests

```python
import base64
import json
from io import BytesIO
from unittest.mock import MagicMock, patch

import pytest
from botocore.exceptions import ClientError

from lambdas.cover_art.handler import _generate_image, PNG_MAGIC_BYTES

# Minimal valid PNG: magic bytes + minimal IHDR chunk (enough to pass magic byte check)
MINIMAL_PNG = (
    b"\x89PNG\r\n\x1a\n"  # PNG signature
    b"\x00\x00\x00\rIHDR"  # IHDR chunk
    b"\x00\x00\x00\x01\x00\x00\x00\x01\x08\x02"  # 1x1, 8-bit RGB
    b"\x00\x00\x00\x90wS\xde"  # CRC
)


def _mock_nova_canvas_response(image_bytes: bytes) -> MagicMock:
    """Build a mock Bedrock invoke_model response with base64-encoded image."""
    body_content = json.dumps({
        "images": [base64.b64encode(image_bytes).decode()]
    }).encode()
    mock_body = MagicMock()
    mock_body.read.return_value = body_content
    return {"body": mock_body}


def test_generate_image_returns_png_bytes(mock_nova_canvas_client):
    mock_nova_canvas_client.invoke_model.return_value = _mock_nova_canvas_response(MINIMAL_PNG)
    result = _generate_image("test prompt")
    assert result[:4] == PNG_MAGIC_BYTES
    assert result == MINIMAL_PNG


def test_generate_image_sends_correct_request_body(mock_nova_canvas_client):
    mock_nova_canvas_client.invoke_model.return_value = _mock_nova_canvas_response(MINIMAL_PNG)
    _generate_image("test prompt")
    call_args = mock_nova_canvas_client.invoke_model.call_args
    assert call_args.kwargs["modelId"] == "amazon.nova-canvas-v1:0"
    assert call_args.kwargs["contentType"] == "application/json"
    body = json.loads(call_args.kwargs["body"])
    assert body["taskType"] == "TEXT_IMAGE"
    assert body["textToImageParams"]["text"] == "test prompt"
    assert body["imageGenerationConfig"]["width"] == 1024
    assert body["imageGenerationConfig"]["height"] == 1024
    assert body["imageGenerationConfig"]["quality"] == "standard"
    assert body["imageGenerationConfig"]["numberOfImages"] == 1


def test_generate_image_raises_on_content_policy_violation(mock_nova_canvas_client):
    mock_nova_canvas_client.invoke_model.side_effect = ClientError(
        {"Error": {"Code": "ValidationException", "Message": "Content policy violation"}},
        "InvokeModel",
    )
    with pytest.raises(RuntimeError, match="content policy"):
        _generate_image("offensive prompt")


def test_generate_image_raises_on_empty_images_array(mock_nova_canvas_client):
    body_content = json.dumps({"images": []}).encode()
    mock_body = MagicMock()
    mock_body.read.return_value = body_content
    mock_nova_canvas_client.invoke_model.return_value = {"body": mock_body}
    with pytest.raises(RuntimeError, match="no images"):
        _generate_image("test prompt")


def test_generate_image_raises_on_throttling(mock_nova_canvas_client):
    mock_nova_canvas_client.invoke_model.side_effect = ClientError(
        {"Error": {"Code": "ThrottlingException", "Message": "Rate exceeded"}},
        "InvokeModel",
    )
    with pytest.raises(ClientError):
        _generate_image("test prompt")


def test_generate_image_raises_on_rai_error(mock_nova_canvas_client):
    """Nova Canvas returns an error field when RAI flags the generated image."""
    body_content = json.dumps({
        "images": [],
        "error": "The generated image has been blocked by our content filter."
    }).encode()
    mock_body = MagicMock()
    mock_body.read.return_value = body_content
    mock_nova_canvas_client.invoke_model.return_value = {"body": mock_body}
    with pytest.raises(RuntimeError, match="RAI"):
        _generate_image("test prompt")
```

#### Full Handler Tests

```python
import base64
import json
import os
from unittest.mock import MagicMock, patch

import pytest

from lambdas.cover_art.handler import PNG_MAGIC_BYTES

# Reuse MINIMAL_PNG and _mock_nova_canvas_response from Image Generation Tests above.
# In the actual test file, these would be module-level constants.

MINIMAL_PNG = (
    b"\x89PNG\r\n\x1a\n"
    b"\x00\x00\x00\rIHDR"
    b"\x00\x00\x00\x01\x00\x00\x00\x01\x08\x02"
    b"\x00\x00\x00\x90wS\xde"
)


def _mock_nova_canvas_response(image_bytes: bytes) -> MagicMock:
    body_content = json.dumps({
        "images": [base64.b64encode(image_bytes).decode()]
    }).encode()
    mock_body = MagicMock()
    mock_body.read.return_value = body_content
    return {"body": mock_body}


def test_handler_returns_valid_cover_art_output(
    pipeline_metadata, lambda_context, mock_nova_canvas_client,
    mock_s3_upload, mock_cover_art_prompt_template,
    sample_discovery_output, sample_script_output,
):
    mock_nova_canvas_client.invoke_model.return_value = _mock_nova_canvas_response(MINIMAL_PNG)
    with patch.dict(os.environ, {"S3_BUCKET": "test-bucket"}):
        from lambdas.cover_art.handler import lambda_handler
        result = lambda_handler(
            {
                "metadata": pipeline_metadata,
                "discovery": sample_discovery_output,
                "script": sample_script_output,
            },
            lambda_context,
        )
    assert "s3_key" in result
    assert "prompt_used" in result


def test_handler_s3_key_contains_execution_id(
    pipeline_metadata, lambda_context, mock_nova_canvas_client,
    mock_s3_upload, mock_cover_art_prompt_template,
    sample_discovery_output, sample_script_output,
):
    mock_nova_canvas_client.invoke_model.return_value = _mock_nova_canvas_response(MINIMAL_PNG)
    execution_id = pipeline_metadata["execution_id"]
    with patch.dict(os.environ, {"S3_BUCKET": "test-bucket"}):
        from lambdas.cover_art.handler import lambda_handler
        result = lambda_handler(
            {
                "metadata": pipeline_metadata,
                "discovery": sample_discovery_output,
                "script": sample_script_output,
            },
            lambda_context,
        )
    assert result["s3_key"] == f"episodes/{execution_id}/cover.png"


def test_handler_uploads_png_to_s3(
    pipeline_metadata, lambda_context, mock_nova_canvas_client,
    mock_s3_upload, mock_cover_art_prompt_template,
    sample_discovery_output, sample_script_output,
):
    mock_nova_canvas_client.invoke_model.return_value = _mock_nova_canvas_response(MINIMAL_PNG)
    with patch.dict(os.environ, {"S3_BUCKET": "test-bucket"}):
        from lambdas.cover_art.handler import lambda_handler
        lambda_handler(
            {
                "metadata": pipeline_metadata,
                "discovery": sample_discovery_output,
                "script": sample_script_output,
            },
            lambda_context,
        )
    mock_s3_upload.assert_called_once()
    call_args = mock_s3_upload.call_args
    assert call_args[0][0] == "test-bucket"  # bucket
    assert call_args[0][1].endswith("/cover.png")  # key
    assert call_args[0][2] == MINIMAL_PNG  # bytes
    assert call_args[0][3] == "image/png"  # content_type


def test_handler_prompt_used_matches_constructed_prompt(
    pipeline_metadata, lambda_context, mock_nova_canvas_client,
    mock_s3_upload, mock_cover_art_prompt_template,
    sample_discovery_output, sample_script_output,
):
    mock_nova_canvas_client.invoke_model.return_value = _mock_nova_canvas_response(MINIMAL_PNG)
    with patch.dict(os.environ, {"S3_BUCKET": "test-bucket"}):
        from lambdas.cover_art.handler import lambda_handler
        result = lambda_handler(
            {
                "metadata": pipeline_metadata,
                "discovery": sample_discovery_output,
                "script": sample_script_output,
            },
            lambda_context,
        )
    # prompt_used should contain the substituted values from the template
    assert sample_discovery_output["repo_name"] in result["prompt_used"]


def test_handler_validates_png_magic_bytes(
    pipeline_metadata, lambda_context, mock_nova_canvas_client,
    mock_s3_upload, mock_cover_art_prompt_template,
    sample_discovery_output, sample_script_output,
):
    # Return non-PNG bytes (e.g., JPEG magic bytes)
    jpeg_bytes = b"\xff\xd8\xff\xe0" + b"\x00" * 100
    mock_nova_canvas_client.invoke_model.return_value = _mock_nova_canvas_response(jpeg_bytes)
    with patch.dict(os.environ, {"S3_BUCKET": "test-bucket"}):
        from lambdas.cover_art.handler import lambda_handler
        with pytest.raises(RuntimeError, match="invalid PNG"):
            lambda_handler(
                {
                    "metadata": pipeline_metadata,
                    "discovery": sample_discovery_output,
                    "script": sample_script_output,
                },
                lambda_context,
            )


def test_handler_raises_on_missing_script_data(
    pipeline_metadata, lambda_context, mock_nova_canvas_client,
    mock_s3_upload, mock_cover_art_prompt_template,
    sample_discovery_output,
):
    with patch.dict(os.environ, {"S3_BUCKET": "test-bucket"}):
        from lambdas.cover_art.handler import lambda_handler
        with pytest.raises(KeyError):
            lambda_handler(
                {
                    "metadata": pipeline_metadata,
                    "discovery": sample_discovery_output,
                    # missing "script" key
                },
                lambda_context,
            )


def test_handler_propagates_bedrock_runtime_error(
    pipeline_metadata, lambda_context, mock_nova_canvas_client,
    mock_s3_upload, mock_cover_art_prompt_template,
    sample_discovery_output, sample_script_output,
):
    mock_nova_canvas_client.invoke_model.side_effect = RuntimeError("Nova Canvas error")
    with patch.dict(os.environ, {"S3_BUCKET": "test-bucket"}):
        from lambdas.cover_art.handler import lambda_handler
        with pytest.raises(RuntimeError, match="Nova Canvas"):
            lambda_handler(
                {
                    "metadata": pipeline_metadata,
                    "discovery": sample_discovery_output,
                    "script": sample_script_output,
                },
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

#### Producer Integration Test (`tests/integration/test_db_live.py` — add to existing file)

This verifies that the Producer's benchmark query returns the expected data shape from a real Postgres database. The benchmark query joins `episodes` with `episode_metrics` — this test confirms the join works and returns `script_text` values.

```python
@pytest.mark.integration
def test_producer_db_benchmark_query():
    """The Producer benchmark query returns script_text strings from top-performing episodes."""
    from shared.db import query

    rows = query(
        """
        SELECT e.script_text
        FROM episodes e
        JOIN episode_metrics em ON e.episode_id = em.episode_id
        ORDER BY (em.views + em.likes * 2 + em.comments * 3 + em.shares * 5) DESC
        LIMIT 3
        """
    )
    # May be empty if no episodes exist yet — that is valid
    assert isinstance(rows, list)
    for row in rows:
        assert isinstance(row[0], str)
        assert len(row[0]) > 0
```

**Resource isolation:** Integration tests must use unique prefixes for S3 keys and DB test data (e.g., the GitHub Actions run ID or commit SHA) to prevent conflicts when multiple CI runs execute in parallel. Clean up test resources in a `finally` block or pytest `teardown` fixture.

#### Cover Art Integration Test (`tests/integration/test_bedrock_live.py` — add to existing file)

This verifies that Nova Canvas image generation works with real AWS credentials. The test sends a simple prompt and validates the response shape and PNG output. Skipped by default because each invocation costs money (Bedrock image generation pricing).

```python
import base64
import json

import boto3
import pytest


@pytest.mark.integration
@pytest.mark.skip(reason="Costs money (Bedrock Nova Canvas). Run manually.")
def test_nova_canvas_generates_image():
    """Verify Nova Canvas image generation works with real credentials."""
    client = boto3.client("bedrock-runtime")
    response = client.invoke_model(
        modelId="amazon.nova-canvas-v1:0",
        contentType="application/json",
        accept="application/json",
        body=json.dumps({
            "taskType": "TEXT_IMAGE",
            "textToImageParams": {
                "text": "Three colorful robots in a podcast studio, cartoon style, bold outlines",
            },
            "imageGenerationConfig": {
                "numberOfImages": 1,
                "width": 1024,
                "height": 1024,
                "quality": "standard",
            },
        }),
    )
    result = json.loads(response["body"].read())
    assert "images" in result
    assert len(result["images"]) >= 1

    image_bytes = base64.b64decode(result["images"][0])
    assert image_bytes[:4] == b"\x89PNG", "Expected PNG magic bytes"
    assert len(image_bytes) > 10_000, "1024x1024 PNG should be >10KB"
```

#### Packaging Integration Tests (`tests/integration/test_packaging.py`)

These tests validate that build scripts produce correct Lambda deployment artifacts. They require build artifacts to exist — run all build scripts before running these tests. No AWS credentials needed.

See [Packaging & Deployment](./packaging-and-deployment.md) for the build scripts and expected layer structures.

```python
import os
import zipfile

import pytest


REPO_ROOT = os.path.join(os.path.dirname(__file__), "..", "..")


@pytest.mark.integration
class TestSharedLayerPackaging:
    """Validates the shared layer zip built by lambdas/shared/build.sh."""

    ZIP_PATH = os.path.join(REPO_ROOT, "build", "shared-layer.zip")

    def test_shared_layer_zip_exists(self):
        assert os.path.isfile(self.ZIP_PATH), (
            f"Shared layer zip not found at {self.ZIP_PATH}. "
            "Run lambdas/shared/build.sh first."
        )

    def test_shared_layer_contains_shared_modules(self):
        with zipfile.ZipFile(self.ZIP_PATH) as zf:
            names = zf.namelist()
            for module in [
                "__init__.py", "bedrock.py", "db.py", "s3.py", "logging.py", "types.py",
            ]:
                assert f"python/shared/{module}" in names, f"Missing python/shared/{module}"

    def test_shared_layer_contains_psycopg2(self):
        with zipfile.ZipFile(self.ZIP_PATH) as zf:
            psycopg2_files = [n for n in zf.namelist() if n.startswith("python/psycopg2/")]
            assert len(psycopg2_files) > 0, "psycopg2 package not found in shared layer"

    def test_shared_layer_contains_powertools(self):
        with zipfile.ZipFile(self.ZIP_PATH) as zf:
            powertools_files = [
                n for n in zf.namelist() if n.startswith("python/aws_lambda_powertools/")
            ]
            assert len(powertools_files) > 0, "aws_lambda_powertools not found in shared layer"

    def test_shared_layer_all_entries_under_python_dir(self):
        """All entries must be under python/ — Lambda expects this structure."""
        with zipfile.ZipFile(self.ZIP_PATH) as zf:
            for name in zf.namelist():
                assert name.startswith("python/"), (
                    f"Unexpected path outside python/: {name}"
                )

    def test_shared_layer_no_dist_info_at_wrong_level(self):
        """*.dist-info dirs must be under python/, not nested deeper."""
        with zipfile.ZipFile(self.ZIP_PATH) as zf:
            for name in zf.namelist():
                if ".dist-info" in name:
                    parts = name.split("/")
                    assert parts[0] == "python", (
                        f"dist-info at wrong level: {name}"
                    )

    def test_shared_layer_unzipped_size_under_50mb(self):
        """Shared layer alone should stay well under 50 MB unzipped."""
        with zipfile.ZipFile(self.ZIP_PATH) as zf:
            total = sum(info.file_size for info in zf.infolist())
        max_bytes = 50 * 1024 * 1024
        assert total < max_bytes, (
            f"Shared layer unzipped size {total / 1024 / 1024:.1f} MB exceeds 50 MB"
        )


@pytest.mark.integration
class TestFfmpegLayerPackaging:
    """Validates the ffmpeg layer zip built by layers/ffmpeg/build.sh."""

    ZIP_PATH = os.path.join(REPO_ROOT, "layers", "ffmpeg", "ffmpeg-layer.zip")

    def test_ffmpeg_layer_zip_exists(self):
        assert os.path.isfile(self.ZIP_PATH), (
            f"ffmpeg layer zip not found at {self.ZIP_PATH}. "
            "Run layers/ffmpeg/build.sh first."
        )

    def test_ffmpeg_layer_contains_binary(self):
        with zipfile.ZipFile(self.ZIP_PATH) as zf:
            assert "bin/ffmpeg" in zf.namelist(), "bin/ffmpeg not found in ffmpeg layer"

    def test_ffmpeg_binary_is_executable(self):
        """The ffmpeg binary must have the executable bit set in the zip."""
        with zipfile.ZipFile(self.ZIP_PATH) as zf:
            info = zf.getinfo("bin/ffmpeg")
            # Unix permissions are stored in external_attr >> 16
            unix_mode = info.external_attr >> 16
            assert unix_mode & 0o111, "bin/ffmpeg is not marked executable in zip"

    def test_ffmpeg_binary_is_elf_x86_64(self):
        """The ffmpeg binary must be a Linux x86_64 ELF executable."""
        with zipfile.ZipFile(self.ZIP_PATH) as zf:
            with zf.open("bin/ffmpeg") as f:
                magic = f.read(20)
        # ELF magic: \x7fELF
        assert magic[:4] == b"\x7fELF", "bin/ffmpeg is not an ELF binary"
        # ELF class: 2 = 64-bit
        assert magic[4] == 2, "bin/ffmpeg is not a 64-bit binary"
        # ELF machine: bytes 18-19, little-endian. 0x3E = x86_64
        machine = int.from_bytes(magic[18:20], "little")
        assert machine == 0x3E, f"bin/ffmpeg architecture is {machine:#x}, expected 0x3e (x86_64)"

    def test_ffmpeg_layer_only_contains_bin_dir(self):
        """ffmpeg layer should only contain bin/ directory."""
        with zipfile.ZipFile(self.ZIP_PATH) as zf:
            top_dirs = {n.split("/")[0] for n in zf.namelist() if "/" in n}
            assert top_dirs == {"bin"}, f"Unexpected top-level dirs: {top_dirs}"

    def test_ffmpeg_layer_unzipped_size_under_100mb(self):
        with zipfile.ZipFile(self.ZIP_PATH) as zf:
            total = sum(info.file_size for info in zf.infolist())
        max_bytes = 100 * 1024 * 1024
        assert total < max_bytes, (
            f"ffmpeg layer unzipped size {total / 1024 / 1024:.1f} MB exceeds 100 MB"
        )


@pytest.mark.integration
class TestPsqlLayerPackaging:
    """Validates the psql layer zip built by layers/psql/build.sh."""

    ZIP_PATH = os.path.join(REPO_ROOT, "layers", "psql", "psql-layer.zip")

    def test_psql_layer_zip_exists(self):
        assert os.path.isfile(self.ZIP_PATH), (
            f"psql layer zip not found at {self.ZIP_PATH}. "
            "Run layers/psql/build.sh first."
        )

    def test_psql_layer_contains_binary(self):
        with zipfile.ZipFile(self.ZIP_PATH) as zf:
            assert "bin/psql" in zf.namelist(), "bin/psql not found in psql layer"

    def test_psql_layer_contains_libpq(self):
        with zipfile.ZipFile(self.ZIP_PATH) as zf:
            libpq_files = [n for n in zf.namelist() if n.startswith("lib/libpq.so")]
            assert len(libpq_files) > 0, "lib/libpq.so* not found in psql layer"

    def test_psql_binary_is_executable(self):
        with zipfile.ZipFile(self.ZIP_PATH) as zf:
            info = zf.getinfo("bin/psql")
            unix_mode = info.external_attr >> 16
            assert unix_mode & 0o111, "bin/psql is not marked executable in zip"

    def test_psql_binary_is_elf_x86_64(self):
        """The psql binary must be a Linux x86_64 ELF executable."""
        with zipfile.ZipFile(self.ZIP_PATH) as zf:
            with zf.open("bin/psql") as f:
                magic = f.read(20)
        assert magic[:4] == b"\x7fELF", "bin/psql is not an ELF binary"
        assert magic[4] == 2, "bin/psql is not a 64-bit binary"
        machine = int.from_bytes(magic[18:20], "little")
        assert machine == 0x3E, f"bin/psql architecture is {machine:#x}, expected 0x3e (x86_64)"

    def test_psql_layer_only_contains_bin_and_lib(self):
        """psql layer should only contain bin/ and lib/ directories."""
        with zipfile.ZipFile(self.ZIP_PATH) as zf:
            top_dirs = {n.split("/")[0] for n in zf.namelist() if "/" in n}
            assert top_dirs == {"bin", "lib"}, f"Unexpected top-level dirs: {top_dirs}"

    def test_psql_layer_unzipped_size_under_15mb(self):
        """psql + libpq should be well under 15 MB."""
        with zipfile.ZipFile(self.ZIP_PATH) as zf:
            total = sum(info.file_size for info in zf.infolist())
        max_bytes = 15 * 1024 * 1024
        assert total < max_bytes, (
            f"psql layer unzipped size {total / 1024 / 1024:.1f} MB exceeds 15 MB"
        )


@pytest.mark.integration
class TestCombinedLayerSizes:
    """Validates that layer combinations stay within Lambda's 250 MB unzipped limit.

    Lambda's hard limit: function code + all layers combined must be < 250 MB unzipped.
    Post-Production (shared + ffmpeg) is the tightest combination.
    """

    @staticmethod
    def _unzipped_size(path: str) -> int:
        if not os.path.isfile(path):
            pytest.skip(f"{path} not found — run build scripts first")
        with zipfile.ZipFile(path) as zf:
            return sum(info.file_size for info in zf.infolist())

    def test_post_production_layers_under_250mb(self):
        """Post-Production uses shared + ffmpeg — the tightest combination."""
        shared = self._unzipped_size(os.path.join(REPO_ROOT, "build", "shared-layer.zip"))
        ffmpeg = self._unzipped_size(
            os.path.join(REPO_ROOT, "layers", "ffmpeg", "ffmpeg-layer.zip")
        )
        handler_estimate = 10 * 1024  # handler.py is tiny
        total = shared + ffmpeg + handler_estimate
        limit = 250 * 1024 * 1024
        assert total < limit, (
            f"Post-Production total {total / 1024 / 1024:.1f} MB "
            f"exceeds Lambda's 250 MB limit"
        )

    def test_discovery_layers_under_250mb(self):
        """Discovery uses shared + psql."""
        shared = self._unzipped_size(os.path.join(REPO_ROOT, "build", "shared-layer.zip"))
        psql = self._unzipped_size(
            os.path.join(REPO_ROOT, "layers", "psql", "psql-layer.zip")
        )
        handler_estimate = 50 * 1024  # handler.py + prompts/
        total = shared + psql + handler_estimate
        limit = 250 * 1024 * 1024
        assert total < limit, (
            f"Discovery total {total / 1024 / 1024:.1f} MB "
            f"exceeds Lambda's 250 MB limit"
        )
```

Run these tests after building all layers:

```bash
# Build all artifacts first
lambdas/shared/build.sh
layers/ffmpeg/build.sh
layers/psql/build.sh

# Run packaging validation
pytest tests/integration/test_packaging.py -v -m integration
```

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

#### Script E2E Test (`tests/e2e/test_script_e2e.py`)

```python
import json
import os
import re

import pytest


@pytest.mark.e2e
@pytest.mark.skip(
    reason="E2E: costs money (Bedrock). Run manually: "
    "pytest tests/e2e/test_script_e2e.py -v -m e2e --override-ini='addopts='"
)
def test_script_e2e_produces_valid_output():
    """Invoke Script handler with real Bedrock.

    Verifies:
    1. Output is valid ScriptOutput with all 6 required fields
    2. character_count < 5,000
    3. character_count == len(text)
    4. segments is exactly the 6 required segments in order
    5. Every line in text matches **Hype:**/**Roast:**/**Phil:** pattern
    6. featured_repo matches discovery input
    7. featured_developer matches discovery input
    """
    from unittest.mock import MagicMock

    # Set LAMBDA_TASK_ROOT so the handler can find prompts/script.md
    os.environ.setdefault(
        "LAMBDA_TASK_ROOT",
        os.path.join(os.path.dirname(__file__), "..", "..", "lambdas", "script"),
    )

    from lambdas.script.handler import lambda_handler

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
            "star_count": 0,
            "language": "C",
            "discovery_rationale": "E2E test input",
            "key_files": ["README", "Makefile", "kernel/sched/core.c"],
            "technical_highlights": [
                "Monolithic kernel with loadable module support",
                "Custom build system spanning thousands of Makefiles",
            ],
        },
        "research": {
            "developer_name": "Linus Torvalds",
            "developer_github": "torvalds",
            "developer_bio": "",
            "public_repos_count": 7,
            "notable_repos": [
                {"name": "linux", "description": "Linux kernel source tree", "stars": 0, "language": "C"},
            ],
            "commit_patterns": "Created Git to manage Linux kernel development",
            "technical_profile": "C systems programmer, kernel development, version control",
            "interesting_findings": [
                "Created both Linux and Git",
                "Known for colorful code review feedback",
            ],
            "hiring_signals": [
                "Built and maintained a project used by billions of devices",
                "Created a version control system used by virtually every software team on Earth",
            ],
        },
    }
    context = MagicMock()
    context.function_name = "e2e-test-script"

    result = lambda_handler(event, context)

    # Validate output shape
    required_fields = [
        "text", "character_count", "segments",
        "featured_repo", "featured_developer", "cover_art_suggestion",
    ]
    for field in required_fields:
        assert field in result, f"Missing required field: {field}"

    # Validate types
    assert isinstance(result["text"], str)
    assert isinstance(result["character_count"], int)
    assert isinstance(result["segments"], list)
    assert isinstance(result["featured_repo"], str)
    assert isinstance(result["featured_developer"], str)
    assert isinstance(result["cover_art_suggestion"], str)

    # Validate character count
    assert result["character_count"] < 5000, (
        f"character_count {result['character_count']} >= 5000"
    )
    assert result["character_count"] == len(result["text"]), (
        f"character_count {result['character_count']} != len(text) {len(result['text'])}"
    )

    # Validate segments
    assert result["segments"] == [
        "intro", "core_debate", "developer_deep_dive",
        "technical_appreciation", "hiring_manager", "outro",
    ]

    # Validate text format — every line matches speaker pattern
    speaker_pattern = re.compile(r"^\*\*(?:Hype|Roast|Phil):\*\*\s+.+$")
    lines = result["text"].strip().split("\n")
    assert len(lines) >= 10, f"Script too short: only {len(lines)} lines"
    for i, line in enumerate(lines):
        assert speaker_pattern.match(line), (
            f"Line {i + 1} does not match speaker pattern: {line[:80]}"
        )

    # Validate content references input
    assert result["featured_repo"] == "linux"
    assert result["featured_developer"] == "torvalds"
```

#### Producer E2E Test (`tests/e2e/test_producer_e2e.py`)

```python
import json
import os

import pytest


@pytest.mark.e2e
@pytest.mark.skip(
    reason="E2E: costs money (Bedrock). Run manually: "
    "pytest tests/e2e/test_producer_e2e.py -v -m e2e --override-ini='addopts='"
)
def test_producer_e2e_produces_valid_output():
    """Invoke Producer handler with real Bedrock and real database.

    Verifies:
    1. Output has verdict and score fields
    2. verdict is "PASS" or "FAIL"
    3. score is an integer 1-10
    4. If PASS: notes is present (or absent — both valid)
    5. If FAIL: feedback and issues are present and non-empty
    """
    from unittest.mock import MagicMock

    # Set LAMBDA_TASK_ROOT so the handler can find prompts/producer.md
    os.environ.setdefault(
        "LAMBDA_TASK_ROOT",
        os.path.join(os.path.dirname(__file__), "..", "..", "lambdas", "producer"),
    )

    from lambdas.producer.handler import lambda_handler

    # Use a known script that should pass evaluation
    script_text = (
        "**Hype:** Welcome back to 0 Stars, 10 out of 10! Today we found linux by torvalds!\n"
        "**Roast:** Zero stars on our show, mass adoption everywhere else. Bit of a gap.\n"
        "**Phil:** But what is a kernel, really? The seed from which all computation grows?\n"
        "**Hype:** This developer built an entire operating system! From scratch!\n"
        "**Roast:** With 30 million lines of code. My linter just fainted.\n"
        "**Phil:** To write 30 million lines is not to code. It is to speak a new language into existence.\n"
        "**Hype:** Let me tell you about this developer. Seven repos. Created Git!\n"
        "**Roast:** Created the tool we all use to argue about merge strategies. Thanks for that.\n"
        "**Phil:** To fork or not to fork. The eternal commit.\n"
        "**Roast:** Fine. The module system is genuinely elegant. You can extend the kernel without rebuilding it. That takes real architectural thinking.\n"
        "**Hype:** He said it! He said something nice!\n"
        "**Phil:** When the cynic finds elegance in monolithic design, the paradigm shifts.\n"
        "**Hype:** Any hiring manager would give this developer a corner office immediately!\n"
        "**Roast:** Built and maintained software running on billions of devices. That is not a resume line, that is a geological event.\n"
        "**Phil:** Can a commit history ever truly capture a life's work?\n"
        "**Hype:** That is all for today! Zero stars, ten out of ten! Remember the kernel!\n"
        "**Roast:** Same time next week. Try not to rebase anything.\n"
        "**Phil:** But what is time, if not a branch we never merge?"
    )

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
            "star_count": 0,
            "language": "C",
            "discovery_rationale": "E2E test input",
            "key_files": ["README", "Makefile", "kernel/sched/core.c"],
            "technical_highlights": [
                "Monolithic kernel with loadable module support",
                "Custom build system spanning thousands of Makefiles",
            ],
        },
        "research": {
            "developer_name": "Linus Torvalds",
            "developer_github": "torvalds",
            "developer_bio": "",
            "public_repos_count": 7,
            "notable_repos": [
                {"name": "linux", "description": "Linux kernel source tree", "stars": 0, "language": "C"},
            ],
            "commit_patterns": "Created Git to manage Linux kernel development",
            "technical_profile": "C systems programmer, kernel development, version control",
            "interesting_findings": [
                "Created both Linux and Git",
                "Known for colorful code review feedback",
            ],
            "hiring_signals": [
                "Built and maintained a project used by billions of devices",
                "Created a version control system used by virtually every software team on Earth",
            ],
        },
        "script": {
            "text": script_text,
            "character_count": len(script_text),
            "segments": [
                "intro", "core_debate", "developer_deep_dive",
                "technical_appreciation", "hiring_manager", "outro",
            ],
            "featured_repo": "linux",
            "featured_developer": "torvalds",
            "cover_art_suggestion": "A penguin surrounded by terminal windows, three robot silhouettes in a podcast studio",
        },
    }
    context = MagicMock()
    context.function_name = "e2e-test-producer"

    result = lambda_handler(event, context)

    # Validate output shape
    assert "verdict" in result, "Missing required field: verdict"
    assert "score" in result, "Missing required field: score"

    # Validate verdict
    assert result["verdict"] in ("PASS", "FAIL"), (
        f"verdict must be 'PASS' or 'FAIL', got '{result['verdict']}'"
    )

    # Validate score
    assert isinstance(result["score"], int), f"score must be int, got {type(result['score'])}"
    assert 1 <= result["score"] <= 10, f"score must be 1-10, got {result['score']}"

    # Validate verdict-specific fields
    if result["verdict"] == "PASS":
        # notes is optional on PASS
        if "notes" in result:
            assert isinstance(result["notes"], str)
    else:
        assert "feedback" in result, "FAIL verdict must include feedback"
        assert isinstance(result["feedback"], str)
        assert len(result["feedback"]) > 0, "feedback must be non-empty"

        assert "issues" in result, "FAIL verdict must include issues"
        assert isinstance(result["issues"], list)
        assert len(result["issues"]) >= 1, "issues must have at least one entry"
        for issue in result["issues"]:
            assert isinstance(issue, str)
            assert len(issue) > 0, "each issue must be a non-empty string"
```

#### Cover Art E2E Test (`tests/e2e/test_cover_art_e2e.py`)

```python
import base64
import json
import os

import boto3
import pytest


@pytest.mark.e2e
@pytest.mark.skip(
    reason="E2E: costs money (Bedrock Nova Canvas + S3). Run manually: "
    "pytest tests/e2e/test_cover_art_e2e.py -v -m e2e --override-ini='addopts='"
)
def test_cover_art_e2e_produces_valid_output():
    """Invoke Cover Art handler with real Bedrock Nova Canvas and real S3.

    Verifies:
    1. Output is valid CoverArtOutput with s3_key and prompt_used
    2. s3_key follows episodes/{execution_id}/cover.png pattern
    3. prompt_used is a non-empty string containing the repo name
    4. The PNG was actually uploaded to S3 (download and check magic bytes)
    """
    from unittest.mock import MagicMock

    # Set LAMBDA_TASK_ROOT so the handler can find prompts/cover_art.md
    os.environ.setdefault(
        "LAMBDA_TASK_ROOT",
        os.path.join(os.path.dirname(__file__), "..", "..", "lambdas", "cover_art"),
    )

    from lambdas.cover_art.handler import lambda_handler

    execution_id = "e2e-cover-art-test"
    event = {
        "metadata": {
            "execution_id": execution_id,
            "script_attempt": 1,
        },
        "discovery": {
            "repo_url": "https://github.com/torvalds/linux",
            "repo_name": "linux",
            "repo_description": "Linux kernel source tree",
            "developer_github": "torvalds",
            "star_count": 0,
            "language": "C",
            "discovery_rationale": "E2E test input",
            "key_files": ["README"],
            "technical_highlights": ["Monolithic kernel with loadable module support"],
        },
        "script": {
            "text": "**Hype:** Welcome! **Roast:** Here we go. **Phil:** But what is a kernel?",
            "character_count": 71,
            "segments": [
                "intro", "core_debate", "developer_deep_dive",
                "technical_appreciation", "hiring_manager", "outro",
            ],
            "featured_repo": "linux",
            "featured_developer": "torvalds",
            "cover_art_suggestion": (
                "A penguin mascot surrounded by terminal windows displaying kernel code, "
                "with three robot silhouettes in a podcast studio"
            ),
        },
    }
    context = MagicMock()
    context.function_name = "e2e-test-cover-art"

    s3_client = boto3.client("s3")
    bucket = os.environ["S3_BUCKET"]

    try:
        result = lambda_handler(event, context)

        # Validate output shape
        assert "s3_key" in result, "Missing required field: s3_key"
        assert "prompt_used" in result, "Missing required field: prompt_used"

        # Validate s3_key pattern
        assert result["s3_key"] == f"episodes/{execution_id}/cover.png", (
            f"Unexpected s3_key: {result['s3_key']}"
        )

        # Validate prompt_used contains repo name
        assert isinstance(result["prompt_used"], str)
        assert len(result["prompt_used"]) > 0, "prompt_used must be non-empty"
        assert "linux" in result["prompt_used"], "prompt_used should contain repo name"

        # Verify the PNG was actually uploaded to S3
        s3_response = s3_client.get_object(Bucket=bucket, Key=result["s3_key"])
        image_bytes = s3_response["Body"].read()
        assert image_bytes[:4] == b"\x89PNG", "Uploaded file should be a valid PNG"
        assert len(image_bytes) > 10_000, "1024x1024 PNG should be >10KB"

    finally:
        # Clean up: delete the test S3 object
        try:
            s3_client.delete_object(
                Bucket=bucket,
                Key=f"episodes/{execution_id}/cover.png",
            )
        except Exception:
            pass  # Best-effort cleanup
```

### Per-Handler Test Requirements

Each handler's unit test file must verify:

| Handler | Required test cases |
|---------|-------------------|
| Discovery | **Output parsing:** valid JSON; fenced JSON (` ```json ` and ` ``` `); star_count >= 10 rejected; string star_count coerced to int; missing required field rejected; invalid repo_url rejected; invalid JSON rejected. **psql tool:** SELECT allowed; INSERT/DELETE/DROP/UPDATE each rejected; leading whitespace SELECT allowed; psql stderr returns error dict; subprocess timeout returns error dict. **GitHub tool:** curated fields returned (no extra fields); null license handled; HTTP error returns error dict. **Exa tool:** snake_case inputs mapped to camelCase in request body; HTTP error returns error dict. **Tool dispatcher:** routes to correct function for each tool name; unknown tool returns error dict. **Full handler:** returns valid DiscoveryOutput; passes 3 tools and executor to invoke_with_tools; rejects high star_count from agent; handles fenced output from agent. |
| Research | **Output parsing:** valid JSON; fenced JSON (` ```json ` and ` ``` `); string `public_repos_count` coerced to int; null `developer_bio` coerced to empty string; missing required field rejected; invalid JSON rejected; `notable_repos` entry missing required sub-field rejected; empty `notable_repos` accepted. **`get_github_user` tool:** curated fields returned (login, name, bio, public_repos, followers, created_at, html_url — no extra fields like id, avatar_url); null name handled; null bio handled; HTTP error returns error dict; socket timeout returns error dict. **`get_user_repos` tool:** returns array of curated repo objects (name, description, stargazers_count, language, html_url, pushed_at, fork — no extra fields); HTTP error returns error dict. **`get_repo_details` tool:** curated fields returned (name, full_name, description, stargazers_count, forks_count, language, topics, created_at, updated_at, html_url — no extra fields); null description handled; HTTP error returns error dict. **`get_repo_readme` tool:** returns decoded content string (base64 decoded by tool); 404 (no README) returns error dict; HTTP error returns error dict. **`search_repositories` tool:** returns `total_count` and curated items array; HTTP error returns error dict. **Tool dispatcher:** routes to correct function for each of 5 tool names; unknown tool returns error dict. **Full handler:** returns valid ResearchOutput; passes 5 tools and executor to invoke_with_tools; reads `$.discovery.developer_github`, `$.discovery.repo_name`, and `$.discovery.repo_url` from input event; handles missing developer bio (null → empty string); handles user with zero repos (empty `notable_repos` valid); handles fenced output from agent; propagates RuntimeError from invoke_with_tools. |
| Script | **Output parsing:** valid JSON; fenced JSON (` ```json ` and ` ``` `); `character_count` >= 5,000 rejected; string `character_count` coerced to int; inaccurate `character_count` overwritten with `len(text)`; missing required field rejected; invalid JSON rejected; wrong segments rejected; segments in wrong order rejected; text at 4,999 characters accepted; text at 5,000 characters rejected. **User message building:** includes discovery data (repo_name, language, technical_highlights); includes research data (developer_name, hiring_signals, interesting_findings); includes attempt number; omits producer feedback on first attempt; includes producer feedback and issues on retry (`script_attempt > 1`). **Full handler:** returns valid ScriptOutput; calls `invoke_model` (not `invoke_with_tools`) with no tools or tool_executor; user message contains discovery data; user message contains research data; first attempt has no feedback in message; retry includes producer feedback and all issues; handles fenced output from agent; raises ValueError on character count exceeded; raises ValueError/JSONDecodeError on invalid JSON from model; propagates RuntimeError from invoke_model. |
| Producer | **Output parsing:** valid PASS JSON; valid FAIL JSON; fenced JSON (` ```json ` and ` ``` `); missing `verdict` rejected; missing `score` rejected; invalid `verdict` value (not "PASS" or "FAIL") rejected; FAIL missing `feedback` rejected; FAIL missing `issues` rejected; PASS with `notes` accepted; PASS without `notes` accepted; string `score` coerced to int; invalid JSON rejected. **User message building:** includes script text; includes character count; includes discovery `repo_name`; includes discovery `repo_description`; includes research `hiring_signals`; includes benchmark scripts when available; handles no benchmark scripts gracefully (no crash, no misleading benchmark section). **Full handler:** returns valid PASS ProducerOutput; returns valid FAIL ProducerOutput; calls `invoke_model` (not `invoke_with_tools`) with no tools or tool_executor; reads script, discovery, and research data from event and passes them in user message; queries database for benchmark scripts via `shared.db.query`; handles fenced output from agent; handles empty benchmark results (no episodes in DB); propagates RuntimeError from invoke_model. |
| Cover Art | **Prompt construction:** `visual_concept` substituted from `cover_art_suggestion`; `repo_name` substituted as `episode_subtitle`; known language (Python, Rust, etc.) maps to specific color mood; unknown language uses `DEFAULT_COLOR_MOOD`; empty `cover_art_suggestion` uses fallback description containing repo name; final prompt truncated to 1024 chars (Nova Canvas hard limit). **Image generation:** returns PNG bytes from valid base64 response; sends correct `modelId` (`amazon.nova-canvas-v1:0`), `taskType` (`TEXT_IMAGE`), `width` (1024), `height` (1024), `quality` (`standard`) in request body; raises `RuntimeError` on content policy violation (`ClientError`/`ValidationException`); raises `RuntimeError` on empty `images` array; raises `RuntimeError` on RAI `error` field in response; propagates `ThrottlingException` (not caught — Step Functions handles retry). **Full handler:** returns valid `CoverArtOutput` with `s3_key` and `prompt_used`; `s3_key` is `episodes/{execution_id}/cover.png`; calls `upload_bytes` with correct bucket, key, PNG bytes, `content_type="image/png"`; `prompt_used` matches the prompt sent to Nova Canvas; validates PNG magic bytes (`b"\x89PNG"` — non-PNG raises `RuntimeError`); raises `KeyError` on missing `$.script` in event; propagates `RuntimeError` from `_generate_image`. |
| TTS | Output matches `TTSOutput` shape; correctly parses `**Hype:**`, `**Roast:**`, `**Phil:**` labels; raises exception on malformed script lines |
| Post-Production | Output matches `PostProductionOutput` shape; writes to `episodes` table; writes to `featured_developers` table |
| Site | Returns valid HTML with status 200; handles empty episodes table |
| Shared: bedrock | **invoke_model:** returns parsed text from Bedrock response; passes correct body structure (`anthropic_version`, `max_tokens`, `system`, `messages`). **invoke_with_tools:** single turn with no tool use (`end_turn`) returns text; tool use loop (`tool_use` then `end_turn`) calls tool_executor and returns final text; multiple tool_use blocks in one turn calls tool_executor for each; max_turns exceeded raises RuntimeError; appends correct message structure (assistant with tool_use content, then user with tool_result). **Retry:** retries on ThrottlingException with backoff; raises after max retries exhausted. |
| Shared: db | `query` returns rows; `execute` returns rowcount; connection uses `sslmode=require` |
| Shared: s3 | `upload_bytes` calls S3 `put_object`; `generate_presigned_url` returns valid URL |
| MCP Server | See [MCP Server Testing](./testing-mcp.md) — 26 tools, 5 resources, fixtures, integration, and E2E tests. |
| Packaging | **Shared layer:** zip exists; contains `python/shared/*.py` (6 modules); contains `python/psycopg2/`; contains `python/aws_lambda_powertools/`; all entries under `python/`; unzipped < 50 MB. **ffmpeg layer:** zip exists; `bin/ffmpeg` present; executable bit set; ELF x86_64 binary; only `bin/` dir; unzipped < 100 MB. **psql layer:** zip exists; `bin/psql` present; `lib/libpq.so*` present; executable bit set; ELF x86_64 binary; only `bin/` + `lib/` dirs; unzipped < 15 MB. **Combined sizes:** post-production (shared + ffmpeg) < 250 MB; discovery (shared + psql) < 250 MB. |

