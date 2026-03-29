from collections.abc import Generator
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
def mock_bedrock_client() -> Generator[MagicMock, None, None]:
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
def mock_invoke_with_tools() -> Generator[MagicMock, None, None]:
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
def mock_db_connection() -> Generator[MagicMock, None, None]:
    """Patches psycopg2.connect in shared/db.py.

    Used by handlers that access Postgres via the shared db module
    (Discovery, Post-Production, Site).
    """
    with patch("shared.db.psycopg2.connect") as mock:
        conn = MagicMock()
        cursor = MagicMock()
        conn.cursor.return_value = cursor
        mock.return_value = conn
        yield conn


@pytest.fixture
def mock_secrets_manager() -> Generator[MagicMock, None, None]:
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
def mock_urlopen() -> Generator[MagicMock, None, None]:
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
            "intro",
            "core_debate",
            "developer_deep_dive",
            "technical_appreciation",
            "hiring_manager",
            "outro",
        ],
        "featured_repo": "testrepo",
        "featured_developer": "testuser",
        "cover_art_suggestion": "A terminal with colorful output",
    }


@pytest.fixture
def mock_research_invoke_with_tools() -> Generator[MagicMock, None, None]:
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
def mock_research_urlopen() -> Generator[MagicMock, None, None]:
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
def mock_script_invoke_model() -> Generator[MagicMock, None, None]:
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
def mock_producer_invoke_model() -> Generator[MagicMock, None, None]:
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
def mock_producer_db_query() -> Generator[MagicMock, None, None]:
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


@pytest.fixture
def mock_nova_canvas_client() -> Generator[MagicMock, None, None]:
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
def mock_s3_upload() -> Generator[MagicMock, None, None]:
    """Patches shared.s3.upload_bytes for Cover Art handler.

    Usage:
        def test_cover_art(mock_s3_upload, ...):
            result = lambda_handler(event, context)
            mock_s3_upload.assert_called_once_with(bucket, key, bytes, "image/png")
    """
    with patch("lambdas.cover_art.handler.upload_bytes") as mock:
        yield mock


@pytest.fixture
def mock_cover_art_prompt_template() -> Generator[str, None, None]:
    """Patches _load_prompt_template to return a known template string.

    Uses a short template with all three placeholders for predictable assertions.
    """
    template = (
        "Three robots reacting to {{visual_concept}}. "
        "Colors: {{color_mood}}. Title: {{episode_subtitle}}."
    )
    with patch("lambdas.cover_art.handler._load_prompt_template", return_value=template):
        yield template
