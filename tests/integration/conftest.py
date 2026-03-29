"""Integration test conftest — Digital Twin Universe (DTU) orchestration.

Sets up and tears down all integration test infrastructure. Does NOT inherit
or conflict with unit test fixtures in tests/conftest.py.
"""

from __future__ import annotations

import importlib
import os
import urllib.parse
import urllib.request
from collections.abc import Generator
from unittest.mock import MagicMock
from uuid import uuid4

import boto3
import pytest
from pytest_httpserver import HTTPServer

from tests.integration.twins.elevenlabs_twin import setup_elevenlabs_twin
from tests.integration.twins.exa_twin import setup_exa_twin
from tests.integration.twins.fixtures import FEATURED_DEVELOPERS
from tests.integration.twins.github_twin import setup_github_twin

# ---------------------------------------------------------------------------
# Mark all tests in this package as integration tests
# ---------------------------------------------------------------------------

pytestmark = pytest.mark.integration

# ---------------------------------------------------------------------------
# Module-level skip guards — checked once at collection time
# ---------------------------------------------------------------------------

try:
    boto3.client("sts").get_caller_identity()
except Exception:
    pytest.skip("AWS credentials unavailable", allow_module_level=True)

if not os.environ.get("DB_CONNECTION_STRING"):
    pytest.skip("DB_CONNECTION_STRING not set", allow_module_level=True)


# ---------------------------------------------------------------------------
# Session-scoped twin server fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session")
def github_twin() -> Generator[HTTPServer, None, None]:
    """GitHub API behavioral twin — starts on a random port, yields the server."""
    server = HTTPServer()
    server.start()
    setup_github_twin(server)
    yield server
    server.stop()


@pytest.fixture(scope="session")
def exa_twin() -> Generator[HTTPServer, None, None]:
    """Exa Search API behavioral twin — starts on a random port, yields the server."""
    server = HTTPServer()
    server.start()
    setup_exa_twin(server)
    yield server
    server.stop()


@pytest.fixture(scope="session")
def elevenlabs_twin() -> Generator[HTTPServer, None, None]:
    """ElevenLabs text-to-dialogue API behavioral twin — starts on a random port."""
    server = HTTPServer()
    server.start()
    setup_elevenlabs_twin(server)
    yield server
    server.stop()


# ---------------------------------------------------------------------------
# Session-scoped autouse fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session", autouse=True)
def redirect_urls(
    github_twin: HTTPServer,
    exa_twin: HTTPServer,
    elevenlabs_twin: HTTPServer,
) -> Generator[None, None, None]:
    """Monkeypatch urllib.request.urlopen to transparently rewrite API URLs to local twins.

    Intercepts requests to api.github.com, api.exa.ai, and api.elevenlabs.io
    and rewrites the host:port to point at the corresponding local twin server.
    Handler code runs completely unmodified.
    """
    github_host, github_port = github_twin.server_address
    exa_host, exa_port = exa_twin.server_address
    elevenlabs_host, elevenlabs_port = elevenlabs_twin.server_address

    _host_map: dict[str, tuple[str, int]] = {
        "api.github.com": (str(github_host), int(github_port)),
        "api.exa.ai": (str(exa_host), int(exa_port)),
        "api.elevenlabs.io": (str(elevenlabs_host), int(elevenlabs_port)),
    }

    _original_urlopen = urllib.request.urlopen

    def _rewrite_url(raw_url: str) -> str | None:
        """Return a rewritten URL pointing at the local twin, or None if not intercepted."""
        parsed = urllib.parse.urlparse(raw_url)
        if parsed.hostname in _host_map:
            twin_host, twin_port = _host_map[str(parsed.hostname)]
            return urllib.parse.urlunparse(
                parsed._replace(scheme="http", netloc=f"{twin_host}:{twin_port}")
            )
        return None

    def _patched_urlopen(
        url: urllib.request.Request | str, *args: object, **kwargs: object
    ) -> object:
        if isinstance(url, urllib.request.Request):
            rewritten = _rewrite_url(url.full_url)
            if rewritten is not None:
                new_req = urllib.request.Request(
                    rewritten,
                    data=url.data,
                    headers=dict(url.headers),
                    method=url.get_method(),
                )
                return _original_urlopen(new_req, *args, **kwargs)
        elif isinstance(url, str):
            rewritten = _rewrite_url(url)
            if rewritten is not None:
                return _original_urlopen(rewritten, *args, **kwargs)
        return _original_urlopen(url, *args, **kwargs)

    mp = pytest.MonkeyPatch()
    mp.setattr(urllib.request, "urlopen", _patched_urlopen)
    yield
    mp.undo()


@pytest.fixture(scope="session", autouse=True)
def bedrock_model_override() -> Generator[None, None, None]:
    """Override BEDROCK_MODEL_ID to Haiku for faster, cheaper integration tests.

    Reloads shared.bedrock after setting the env var so DEFAULT_MODEL_ID
    picks up the new value. Restores original state on teardown.
    """
    import shared.bedrock as bedrock_module

    original_value = os.environ.get("BEDROCK_MODEL_ID")
    os.environ["BEDROCK_MODEL_ID"] = "us.anthropic.claude-haiku-4-5-20251001-v1:0"
    importlib.reload(bedrock_module)
    yield
    if original_value is None:
        os.environ.pop("BEDROCK_MODEL_ID", None)
    else:
        os.environ["BEDROCK_MODEL_ID"] = original_value
    importlib.reload(bedrock_module)


@pytest.fixture(scope="session")
def test_s3_bucket() -> Generator[str, None, None]:
    """Create an ephemeral S3 bucket and set S3_BUCKET env var for the session.

    Deletes all objects and the bucket on teardown.
    """
    bucket_name = f"zerostars-integration-test-{uuid4().hex[:12]}"
    s3 = boto3.client("s3")

    region = boto3.session.Session().region_name or "us-east-1"
    if region == "us-east-1":
        s3.create_bucket(Bucket=bucket_name)
    else:
        s3.create_bucket(
            Bucket=bucket_name,
            CreateBucketConfiguration={"LocationConstraint": region},
        )

    os.environ["S3_BUCKET"] = bucket_name
    yield bucket_name

    paginator = s3.get_paginator("list_objects_v2")
    for page in paginator.paginate(Bucket=bucket_name):
        objects = page.get("Contents", [])
        if objects:
            s3.delete_objects(
                Bucket=bucket_name,
                Delete={"Objects": [{"Key": obj["Key"]} for obj in objects]},
            )
    s3.delete_bucket(Bucket=bucket_name)


@pytest.fixture(scope="session")
def test_secrets() -> Generator[None, None, None]:
    """Create test secrets in Secrets Manager; force-delete without recovery on teardown."""
    sm = boto3.client("secretsmanager")
    _secrets: list[tuple[str, str]] = [
        ("integration-test/exa-api-key", "test-exa-key"),
        ("integration-test/elevenlabs-api-key", "test-elevenlabs-key"),
    ]
    for secret_id, secret_value in _secrets:
        sm.create_secret(Name=secret_id, SecretString=secret_value)

    yield

    for secret_id, _ in _secrets:
        sm.delete_secret(SecretId=secret_id, ForceDeleteWithoutRecovery=True)


@pytest.fixture(scope="session", autouse=True)
def inject_api_keys() -> Generator[None, None, None]:
    """Inject test API keys into handler module-level caches.

    Bypasses Secrets Manager calls entirely — handlers return the cached value
    without making a boto3 call.
    """
    import lambdas.discovery.handler as discovery_handler
    import lambdas.tts.handler as tts_handler

    discovery_handler._exa_api_key = "test-exa-key"
    tts_handler._elevenlabs_api_key = "test-elevenlabs-key"
    yield
    discovery_handler._exa_api_key = None
    tts_handler._elevenlabs_api_key = None


# ---------------------------------------------------------------------------
# Function-scoped fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def test_execution_id() -> str:
    """Unique execution ID scoped to a single test."""
    return f"integration-test-{uuid4().hex[:12]}"


@pytest.fixture
def pipeline_metadata(test_execution_id: str) -> dict[str, object]:
    """Minimal pipeline state metadata for integration test events."""
    return {"execution_id": test_execution_id, "script_attempt": 1}


@pytest.fixture
def lambda_context() -> MagicMock:
    """Mock LambdaContext populated with integration-test values."""
    ctx = MagicMock()
    ctx.function_name = "integration-test-function"
    ctx.memory_limit_in_mb = 512
    ctx.invoked_function_arn = "arn:aws:lambda:us-east-1:123456789:function:integration-test"
    ctx.aws_request_id = f"integration-test-{uuid4().hex[:8]}"
    return ctx


@pytest.fixture(autouse=True)
def cleanup_test_data() -> Generator[None, None, None]:
    """Delete integration test rows from episodes and featured_developers after each test.

    Runs silently if the DB is unavailable (so collection-time skips still work).
    """
    yield
    try:
        from shared.db import execute

        execute("DELETE FROM episodes WHERE execution_id LIKE 'integration-test-%'")
        execute("DELETE FROM featured_developers WHERE developer_github LIKE 'integration-test-%'")
    except Exception:
        pass  # DB may be unavailable; don't fail the test on teardown


@pytest.fixture
def seed_featured_developers(cleanup_test_data: None) -> Generator[None, None, None]:
    """Seed FEATURED_DEVELOPERS into the featured_developers table.

    Inserts a throwaway episode row to satisfy the FK constraint, then inserts
    each developer from fixtures.FEATURED_DEVELOPERS. Cleans up both in teardown.
    Depends on cleanup_test_data to ensure prior-test rows are removed first.
    """
    from shared.db import execute
    from shared.db import query as db_query

    seed_execution_id = f"integration-test-seed-{uuid4().hex[:12]}"

    # Insert a minimal episode to satisfy the NOT NULL FK on featured_developers.episode_id
    rows = db_query(
        """
        INSERT INTO episodes (
            air_date, repo_url, repo_name, developer_github, script_text, execution_id
        ) VALUES (
            CURRENT_DATE,
            'https://github.com/integration-test/seed',
            'seed',
            'integration-test-seed',
            'integration test seed script',
            %s
        ) RETURNING episode_id
        """,
        (seed_execution_id,),
    )
    episode_id: int = int(rows[0][0])

    for developer_github in FEATURED_DEVELOPERS:
        execute(
            "INSERT INTO featured_developers (developer_github, episode_id, featured_date) "
            "VALUES (%s, %s, CURRENT_DATE) ON CONFLICT DO NOTHING",
            (developer_github, episode_id),
        )

    yield

    # Teardown: delete in FK order
    execute("DELETE FROM featured_developers WHERE episode_id = %s", (episode_id,))
    execute("DELETE FROM episodes WHERE episode_id = %s", (episode_id,))
