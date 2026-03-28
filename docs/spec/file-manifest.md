> Part of the [Implementation Spec](../../IMPLEMENTATION_SPEC.md)

# File Manifest

Every file below must be created. No other files should be created.

```
├── build-all.sh
├── pyproject.toml
├── .github/
│   └── workflows/
│       └── ci.yml
├── terraform/
│   ├── main.tf
│   ├── variables.tf
│   ├── outputs.tf
│   ├── lambdas.tf
│   ├── step-functions.tf
│   ├── s3.tf
│   ├── site.tf
│   └── secrets.tf
├── lambdas/
│   ├── shared/
│   │   ├── build.sh
│   │   └── python/
│   │       └── shared/
│   │           ├── __init__.py
│   │           ├── bedrock.py
│   │           ├── db.py
│   │           ├── s3.py
│   │           ├── logging.py
│   │           ├── tracing.py
│   │           ├── metrics.py
│   │           └── types.py
│   ├── discovery/
│   │   ├── handler.py
│   │   └── prompts/
│   │       └── discovery.md
│   ├── research/
│   │   ├── handler.py
│   │   └── prompts/
│   │       └── research.md
│   ├── script/
│   │   ├── handler.py
│   │   └── prompts/
│   │       └── script.md
│   ├── producer/
│   │   ├── handler.py
│   │   └── prompts/
│   │       └── producer.md
│   ├── cover_art/
│   │   ├── handler.py
│   │   └── prompts/
│   │       └── cover_art.md
│   ├── tts/
│   │   └── handler.py
│   ├── post_production/
│   │   └── handler.py
│   ├── site/
│   │   ├── handler.py
│   │   ├── build.sh
│   │   └── templates/
│   │       ├── base.html
│   │       └── index.html
│   └── mcp/
│       ├── handler.py
│       └── build.sh
├── layers/
│   ├── ffmpeg/
│   │   └── build.sh
│   └── psql/
│       └── build.sh
├── sql/
│   └── schema.sql
├── tests/
│   ├── __init__.py
│   ├── conftest.py
│   ├── unit/
│   │   ├── __init__.py
│   │   ├── test_discovery.py
│   │   ├── test_research.py
│   │   ├── test_script.py
│   │   ├── test_producer.py
│   │   ├── test_cover_art.py
│   │   ├── test_tts.py
│   │   ├── test_post_production.py
│   │   ├── test_site.py
│   │   └── test_shared/
│   │       ├── __init__.py
│   │       ├── test_bedrock.py
│   │       ├── test_db.py
│   │       └── test_s3.py
│   └── integration/
│       ├── __init__.py
│       ├── test_packaging.py
│       ├── test_bedrock_live.py
│       ├── test_discovery_live.py
│       ├── test_discovery_e2e.py
│       ├── test_s3_live.py
│       └── test_db_live.py
└── README.md
```

### Terraform Files

| File | Contents |
|------|----------|
| `terraform/main.tf` | AWS provider configuration, Terraform backend (local state), common data sources (AWS account ID, region) |
| `terraform/variables.tf` | Input variables: `elevenlabs_api_key`, `exa_api_key`, `db_connection_string`, `domain_name` |
| `terraform/outputs.tf` | Exports: state machine ARN, site URL, S3 bucket name |
| `terraform/lambdas.tf` | All 8 Lambda functions (7 pipeline + 1 site), their IAM roles and policies, CloudWatch log groups, `archive_file` data sources for deployment packages, shared Lambda Layer resource, ffmpeg Lambda Layer resource, psql Lambda Layer resource. No modules — every Lambda defined inline. |
| `terraform/step-functions.tf` | Step Functions state machine with inline ASL via `jsonencode()`. IAM execution role for Step Functions (permission to invoke pipeline Lambdas). |
| `terraform/s3.tf` | S3 bucket for episode assets (MP3, MP4, cover art PNGs). Bucket policy for CloudFront access. |
| `terraform/site.tf` | Site Lambda function URL, CloudFront distribution (two origins: Function URL for HTML, S3 via OAC for cover art at `/assets/*`; ~1 hour TTL), Route53 A record for `podcast.ryans-lab.click` |
| `terraform/secrets.tf` | `aws_secretsmanager_secret` + `aws_secretsmanager_secret_version` for ElevenLabs and Exa API keys |
| `terraform/observability.tf` | CloudWatch Alarms (pipeline-level, per-Lambda, custom metric) and SNS topic for alert notifications. See [Observability](./observability.md). |

### Lambda Source Files

| File | Purpose |
|------|---------|
| `lambdas/shared/python/shared/__init__.py` | Package init. Re-exports `bedrock`, `db`, `s3`, `logging`, `tracing`, `metrics`, `types` modules for `from shared import bedrock, db, s3` usage. |
| `lambdas/shared/python/shared/bedrock.py` | Bedrock client wrapper. Functions: `invoke_model(prompt, system_prompt, model_id)`, `invoke_with_tools(prompt, system_prompt, tools, model_id)`. Default model: Claude on Bedrock. Handles retries for throttling. |
| `lambdas/shared/python/shared/db.py` | Postgres connection helper. Uses `psycopg2` with `sslmode=require`. Functions: `get_connection()`, `query(sql, params)` (returns rows), `execute(sql, params)` (returns rowcount). Connection string from `DB_CONNECTION_STRING` env var. |
| `lambdas/shared/python/shared/s3.py` | S3 helper functions: `upload_bytes(bucket, key, data, content_type)`, `upload_file(bucket, key, filepath, content_type)`, `generate_presigned_url(bucket, key, expiry)`. Bucket name from `S3_BUCKET` env var. |
| `lambdas/shared/python/shared/logging.py` | Powertools Logger factory. Exports `get_logger(service)` which returns a pre-configured structured JSON logger. See [Instrumentation](./instrumentation.md). |
| `lambdas/shared/python/shared/tracing.py` | Powertools Tracer factory. Exports `get_tracer(service)` which returns a Tracer with auto-patching enabled. See [Instrumentation](./instrumentation.md). |
| `lambdas/shared/python/shared/metrics.py` | Powertools Metrics factory. Exports `get_metrics(service)` which returns a Metrics instance under the `ZeroStars` namespace. See [Instrumentation](./instrumentation.md). |
| `lambdas/shared/python/shared/types.py` | TypedDict definitions for all Lambda input/output contracts. `PipelineState`, `DiscoveryOutput`, `ResearchOutput`, `ScriptOutput`, `ProducerOutput`, `CoverArtOutput`, `TTSOutput`, `PostProductionOutput`. See [Type Checking](./type-checking.md). |
| `lambdas/discovery/handler.py` | Discovery agent. Reads episode history and metrics from Postgres. Calls Bedrock with Exa search as a tool. Returns selected repo and discovery rationale. |
| `lambdas/discovery/prompts/discovery.md` | System prompt for the Discovery agent. Search criteria, what to look for, how to use episode metrics to bias search. |
| `lambdas/research/handler.py` | Research agent. Takes discovered repo from previous step. Calls Bedrock with GitHub API as a tool. Builds developer profile. Returns structured research JSON. |
| `lambdas/research/prompts/research.md` | System prompt for the Research agent. What to research, output structure, how deep to go. |
| `lambdas/script/handler.py` | Script agent. Takes discovery + research output. Calls Bedrock to generate a 3-persona comedy script. Validates character count before returning. If producer feedback is present in input, incorporates it. |
| `lambdas/script/prompts/script.md` | System prompt for the Script agent. Persona definitions, episode structure (6 segments), character limit rules, comedy guidelines. |
| `lambdas/producer/handler.py` | Producer agent. Evaluates script quality. Reads top-performing scripts from Postgres as benchmarks. Returns `{"verdict": "PASS"}` or `{"verdict": "FAIL", "feedback": "..."}`. |
| `lambdas/producer/prompts/producer.md` | System prompt for the Producer agent. Evaluation rubric: character count, segment structure, persona voice distinctness, hiring segment specificity, comedy quality. |
| `lambdas/cover_art/handler.py` | Cover art generator. Invokes Bedrock Nova Canvas (`amazon.nova-canvas-v1:0`) with a prompt derived from the episode content. Uploads resulting PNG to S3. |
| `lambdas/cover_art/prompts/cover_art.md` | Prompt template for Nova Canvas. Three robot personas, visual reference to featured project, "0 STARS / 10/10" title, episode subtitle. |
| `lambdas/tts/handler.py` | TTS handler. Parses the approved script into dialogue turns. Calls ElevenLabs `/v1/text-to-dialogue` API. Uploads MP3 to S3. |
| `lambdas/post_production/handler.py` | Post-production. Downloads cover art PNG and MP3 from S3. Runs ffmpeg to produce MP4. Uploads MP4 to S3. Writes episode record to Postgres `episodes` table. Writes to `featured_developers` table. |
| `lambdas/mcp/handler.py` | MCP server handler. Exposes pipeline control tools (trigger run, check status) via Streamable HTTP transport. See [MCP Server](./mcp-server.md). |
| `lambdas/site/handler.py` | Website handler. Queries `episodes` table from Postgres. Renders Jinja2 templates. Returns HTML response. Handles Lambda Function URL event format. |
| `lambdas/site/templates/base.html` | Base HTML template. Minimal styling (inline CSS, no external dependencies). Dark theme. Includes `<head>`, nav with podcast title, footer. |
| `lambdas/site/templates/index.html` | Extends base. Lists episodes reverse-chronologically. Each episode shows: title (repo name), developer name, air date, star count at recording, embedded HTML5 audio player (presigned S3 URL for MP3), cover art image. |

### Project Configuration Files

| File | Purpose |
|------|---------|
| `pyproject.toml` | Unified config for mypy (strict mode), pytest (test paths, markers), and ruff (line length, lint rules). See [Type Checking](./type-checking.md), [Testing](./testing.md), and [CI Pipeline](./ci-pipeline.md). |
| `.github/workflows/ci.yml` | GitHub Actions CI pipeline. Runs ruff lint/format, mypy type checking, and pytest unit tests on every PR. See [CI Pipeline](./ci-pipeline.md). |

### Test Files

| File | Purpose |
|------|---------|
| `tests/conftest.py` | Shared pytest fixtures: `pipeline_metadata`, `lambda_context`, `mock_bedrock_client`, `mock_db_connection`, sample output fixtures matching [Interface Contracts](./interface-contracts.md). See [Testing](./testing.md). |
| `tests/unit/test_discovery.py` | Unit tests for Discovery Lambda handler. |
| `tests/unit/test_research.py` | Unit tests for Research Lambda handler. |
| `tests/unit/test_script.py` | Unit tests for Script Lambda handler. |
| `tests/unit/test_producer.py` | Unit tests for Producer Lambda handler. |
| `tests/unit/test_cover_art.py` | Unit tests for Cover Art Lambda handler. |
| `tests/unit/test_tts.py` | Unit tests for TTS Lambda handler. |
| `tests/unit/test_post_production.py` | Unit tests for Post-Production Lambda handler. |
| `tests/unit/test_site.py` | Unit tests for Site Lambda handler. |
| `tests/unit/test_shared/test_bedrock.py` | Unit tests for shared Bedrock client wrapper. |
| `tests/unit/test_shared/test_db.py` | Unit tests for shared Postgres helper. |
| `tests/unit/test_shared/test_s3.py` | Unit tests for shared S3 helper. |
| `tests/integration/test_packaging.py` | Integration tests validating build artifacts: shared layer zip structure and contents, ffmpeg layer binary, psql layer binary + libpq, combined layer sizes within Lambda's 250 MB limit. Requires build scripts to be run first. See [Packaging & Deployment](./packaging-and-deployment.md). |
| `tests/integration/test_bedrock_live.py` | Integration tests hitting real Bedrock. Marked `@pytest.mark.integration`. |
| `tests/integration/test_s3_live.py` | Integration tests hitting real S3. Marked `@pytest.mark.integration`. |
| `tests/integration/test_discovery_live.py` | Integration tests for Discovery external deps (psql, SSM, GitHub API). Marked `@pytest.mark.integration`. |
| `tests/integration/test_discovery_e2e.py` | End-to-end test: invokes Discovery handler with real Bedrock, Exa, psql, GitHub. Marked `@pytest.mark.integration`, skipped by default. |
| `tests/e2e/test_cover_art_e2e.py` | End-to-end test: invokes Cover Art handler with real Bedrock Nova Canvas and S3. Marked `@pytest.mark.e2e`, skipped by default. |
| `tests/integration/test_db_live.py` | Integration tests hitting real Postgres. Marked `@pytest.mark.integration`. |

### Other Files

| File | Purpose |
|------|---------|
| `lambdas/shared/build.sh` | Shell script that pip-installs `psycopg2-binary` and `aws-lambda-powertools` (with pinned versions, targeting `manylinux2014_x86_64`) into the `python/` directory alongside the shared source modules, then zips everything into `build/shared-layer.zip`. Run before `terraform plan`. See [Packaging & Deployment](./packaging-and-deployment.md). |
| `layers/ffmpeg/build.sh` | Shell script that downloads a prebuilt Lambda-compatible ffmpeg binary (from `johnvansickle.com/ffmpeg` — the standard source for static ffmpeg builds), creates the Lambda Layer directory structure (`bin/ffmpeg`), and zips it. Output: `layers/ffmpeg/ffmpeg-layer.zip`. Run once manually before `terraform apply`. |
| `lambdas/site/build.sh` | Shell script that pip-installs `jinja2` (pinned version) into the site Lambda directory. Run before `terraform plan` (or via `build-all.sh`). See [Packaging & Deployment](./packaging-and-deployment.md). |
| `lambdas/mcp/build.sh` | Shell script that pip-installs `mcp[cli]` (pinned version, targeting `manylinux2014_x86_64`) into the MCP Lambda directory. Run before `terraform plan` (or via `build-all.sh`). See [Packaging & Deployment](./packaging-and-deployment.md). |
| `build-all.sh` | Top-level build orchestration script. Runs all layer builds and Lambda pip installs in parallel. Run before `terraform plan`. See [Packaging & Deployment](./packaging-and-deployment.md). |
| `layers/psql/build.sh` | Shell script that downloads PostgreSQL 16 RPMs for RHEL 9 (AL2023-compatible), extracts the `psql` binary and `libpq` shared library, and packages them as a Lambda Layer. Output: `layers/psql/psql-layer.zip`. Run once manually before `terraform apply`. See [Packaging & Deployment](./packaging-and-deployment.md). |
| `README.md` | Project README. Already exists — no changes needed during implementation. |
