# Implementation Spec: "0 Stars, 10/10" Podcast Pipeline

This is the single source of truth for implementing the podcast pipeline. It contains everything needed to build the system in one pass: every file to create, every interface between components, the exact state machine definition, Terraform resource ownership, external API contracts, and prompt content.

**Target runtime:** Python 3.12 on AWS Lambda, Terraform for IaC.

---

## 1. File Manifest

Every file below must be created. No other files should be created.

```
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
│   ├── scheduling.tf
│   ├── s3.tf
│   ├── site.tf
│   └── secrets.tf
├── lambdas/
│   ├── shared/
│   │   └── python/
│   │       └── shared/
│   │           ├── __init__.py
│   │           ├── bedrock.py
│   │           ├── db.py
│   │           ├── s3.py
│   │           ├── logging.py
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
│   └── site/
│       ├── handler.py
│       └── templates/
│           ├── base.html
│           └── index.html
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
| `terraform/lambdas.tf` | All 8 Lambda functions (7 pipeline + 1 site), their IAM roles and policies, CloudWatch log groups, `archive_file` data sources for deployment packages, shared Lambda Layer resource, ffmpeg Lambda Layer resource. No modules — every Lambda defined inline. |
| `terraform/step-functions.tf` | Step Functions state machine with inline ASL via `jsonencode()`. IAM execution role for Step Functions (permission to invoke pipeline Lambdas). |
| `terraform/scheduling.tf` | EventBridge Scheduler rule (weekly, Sunday 9 AM Eastern via `schedule_expression_timezone = "America/New_York"`), IAM role for scheduler, target pointing to state machine ARN |
| `terraform/s3.tf` | S3 bucket for episode assets (MP3, MP4, cover art PNGs). Bucket policy for CloudFront access. |
| `terraform/site.tf` | Site Lambda function URL, CloudFront distribution (two origins: Function URL for HTML, S3 via OAC for cover art at `/assets/*`; ~1 hour TTL), Route53 A record for `podcast.ryans-lab.click` |
| `terraform/secrets.tf` | `aws_secretsmanager_secret` + `aws_secretsmanager_secret_version` for ElevenLabs and Exa API keys |

### Lambda Source Files

| File | Purpose |
|------|---------|
| `lambdas/shared/python/shared/__init__.py` | Package init. Re-exports `bedrock`, `db`, `s3`, `logging`, `types` modules for `from shared import bedrock, db, s3` usage. |
| `lambdas/shared/python/shared/bedrock.py` | Bedrock client wrapper. Functions: `invoke_model(prompt, system_prompt, model_id)`, `invoke_with_tools(prompt, system_prompt, tools, model_id)`. Default model: Claude on Bedrock. Handles retries for throttling. |
| `lambdas/shared/python/shared/db.py` | Postgres connection helper. Uses `psycopg2` with `sslmode=require`. Functions: `get_connection()`, `query(sql, params)` (returns rows), `execute(sql, params)` (returns rowcount). Connection string from `DB_CONNECTION_STRING` env var. |
| `lambdas/shared/python/shared/s3.py` | S3 helper functions: `upload_bytes(bucket, key, data, content_type)`, `upload_file(bucket, key, filepath, content_type)`, `generate_presigned_url(bucket, key, expiry)`. Bucket name from `S3_BUCKET` env var. |
| `lambdas/shared/python/shared/logging.py` | Powertools Logger factory. Exports `get_logger(service)` which returns a pre-configured structured JSON logger. See Section 10. |
| `lambdas/shared/python/shared/types.py` | TypedDict definitions for all Lambda input/output contracts. `PipelineState`, `DiscoveryOutput`, `ResearchOutput`, `ScriptOutput`, `ProducerOutput`, `CoverArtOutput`, `TTSOutput`, `PostProductionOutput`. See Section 11. |
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
| `lambdas/site/handler.py` | Website handler. Queries `episodes` table from Postgres. Renders Jinja2 templates. Returns HTML response. Handles Lambda Function URL event format. |
| `lambdas/site/templates/base.html` | Base HTML template. Minimal styling (inline CSS, no external dependencies). Dark theme. Includes `<head>`, nav with podcast title, footer. |
| `lambdas/site/templates/index.html` | Extends base. Lists episodes reverse-chronologically. Each episode shows: title (repo name), developer name, air date, star count at recording, embedded HTML5 audio player (presigned S3 URL for MP3), cover art image. |

### Project Configuration Files

| File | Purpose |
|------|---------|
| `pyproject.toml` | Unified config for mypy (strict mode), pytest (test paths, markers), and ruff (line length, lint rules). See Sections 11–13. |
| `.github/workflows/ci.yml` | GitHub Actions CI pipeline. Runs ruff lint/format, mypy type checking, and pytest unit tests on every PR. See Section 13. |

### Test Files

| File | Purpose |
|------|---------|
| `tests/conftest.py` | Shared pytest fixtures: `pipeline_metadata`, `lambda_context`, `mock_bedrock_client`, `mock_db_connection`, sample output fixtures matching Section 2 contracts. See Section 12. |
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
| `tests/integration/test_bedrock_live.py` | Integration tests hitting real Bedrock. Marked `@pytest.mark.integration`. |
| `tests/integration/test_s3_live.py` | Integration tests hitting real S3. Marked `@pytest.mark.integration`. |
| `tests/integration/test_discovery_live.py` | Integration tests for Discovery external deps (psql, SSM, GitHub API). Marked `@pytest.mark.integration`. |
| `tests/integration/test_discovery_e2e.py` | End-to-end test: invokes Discovery handler with real Bedrock, Exa, psql, GitHub. Marked `@pytest.mark.integration`, skipped by default. |
| `tests/integration/test_db_live.py` | Integration tests hitting real Postgres. Marked `@pytest.mark.integration`. |

### Other Files

| File | Purpose |
|------|---------|
| `layers/ffmpeg/build.sh` | Shell script that downloads a prebuilt Lambda-compatible ffmpeg binary (from `johnvansickle.com/ffmpeg` — the standard source for static ffmpeg builds), creates the Lambda Layer directory structure (`bin/ffmpeg`), and zips it. Output: `layers/ffmpeg/ffmpeg-layer.zip`. Run once manually before `terraform apply`. |
| `README.md` | Project README. Already exists — no changes needed during implementation. |

---

## 2. Interface Contracts

The Step Functions state object is the data bus between Lambdas. Each Lambda receives the full accumulated state and adds its output under a namespaced key. This section defines the exact JSON schema for each Lambda's input and output.

### Convention: Lambda Returns vs. State Object

Each Lambda returns a **flat payload** — just its own output fields, no outer wrapper key. Step Functions places that payload into the state object at the right location using `ResultPath`. For example, the Discovery Lambda returns `{"repo_url": "...", "star_count": 12}`, and Step Functions places it at `$.discovery` via `ResultPath: "$.discovery"`.

The schemas below show **what each Lambda actually returns**. The state object shape section shows **what the accumulated state looks like** after Step Functions applies ResultPath.

### State Object Shape

The state object grows as it passes through the pipeline. Each key is populated by Step Functions placing a Lambda's return value via ResultPath — the Lambdas themselves never see or write these outer keys.

```jsonc
{
  // ResultPath: "$.discovery" — placed by Step Functions from Discovery Lambda return
  "discovery": { ... },

  // ResultPath: "$.research"
  "research": { ... },

  // ResultPath: "$.script"
  "script": { ... },

  // ResultPath: "$.producer"
  "producer": { ... },

  // ResultPath: "$.cover_art"
  "cover_art": { ... },

  // ResultPath: "$.tts"
  "tts": { ... },

  // ResultPath: "$.post_production"
  "post_production": { ... },

  // Pipeline metadata — injected by the InitializeMetadata Pass state at the start
  // of the state machine. execution_id comes from $$.Execution.Id (Step Functions
  // context object), script_attempt starts at 1 and is incremented by the
  // IncrementAttempt Pass state on Script retry.
  "metadata": {
    "execution_id": "arn:aws:states:us-east-1:123456789:execution:zerostars-pipeline:abc-123",
    "script_attempt": 1
  }
}
```

### Discovery Lambda

**Reads from state:**
- `$.metadata.execution_id` — for logging/tracing

**Reads from Postgres (via Bedrock tool use):**
- `featured_developers` — all rows, to exclude previously featured developers from search
- `episodes` — `repo_url` column, to avoid re-featuring the same repository

The Discovery agent queries Postgres directly using a `query_postgres` Bedrock tool backed by the `psql` binary (packaged as a Lambda layer). The handler fetches the DB connection string from SSM Parameter Store (`/zerostars/db-connection-string`) at runtime, not from an environment variable.

> **Deferred:** Querying `episode_metrics` to bias search toward better-performing project types ships as a separate feature. The Discovery agent does not read `episode_metrics` in v1.

**Bedrock tools:** The Discovery agent has three tools available during its agentic loop:
1. `exa_search` — neural search via Exa API to find candidate repos (see §5 Exa Search API)
2. `query_postgres` — read-only SQL against the podcast database via psql subprocess (see §5 Discovery Postgres Tool)
3. `get_github_repo` — GitHub REST API to verify star counts and repo metadata (see §5 Discovery GitHub Tool)

**Returns:** (placed at `$.discovery` by Step Functions)

```json
{
  "repo_url": "https://github.com/user/repo",
  "repo_name": "repo-name",
  "repo_description": "Short description from GitHub",
  "developer_github": "username",
  "star_count": 7,
  "language": "Python",
  "discovery_rationale": "Why this repo was selected — what made it interesting, how it scored against search objectives.",
  "key_files": ["list", "of", "interesting", "files", "or", "dirs"],
  "technical_highlights": ["Notable technical decisions or patterns found in the repo"]
}
```

### Research Lambda

**Reads from state:**
- `$.metadata.execution_id` — for logging/tracing
- `$.discovery.developer_github` — the username to research
- `$.discovery.repo_name` — the featured repo to get details/README for
- `$.discovery.repo_url` — to parse owner/repo for GitHub API calls

**Returns:** (placed at `$.research` by Step Functions)

```json
{
  "developer_name": "Display Name or username",
  "developer_github": "username",
  "developer_bio": "GitHub bio if available",
  "public_repos_count": 15,
  "notable_repos": [
    {
      "name": "repo-name",
      "description": "what it does",
      "stars": 5,
      "language": "Rust"
    }
  ],
  "commit_patterns": "Description of how actively they code, contribution patterns",
  "technical_profile": "Languages, frameworks, areas of interest inferred from repos",
  "interesting_findings": ["Specific observations that would make good podcast material"],
  "hiring_signals": ["What this developer's body of work signals to a hiring manager"]
}
```

### Script Lambda

**Reads from state:**
- `$.metadata.script_attempt` — to know if this is a first attempt or retry
- `$.discovery.*` — full discovery object (repo name, description, language, technical highlights, key files) as source material
- `$.research.*` — full research object (developer profile, notable repos, interesting findings, hiring signals) as source material
- `$.producer.feedback` — (retry only, present when `script_attempt > 1`) structured feedback on what to fix
- `$.producer.issues` — (retry only) list of specific issues from previous evaluation

**Returns:** (placed at `$.script` by Step Functions)

```json
{
  "text": "The full script text with speaker labels (see Script Text Format below)",
  "character_count": 4200,
  "segments": ["intro", "core_debate", "developer_deep_dive", "technical_appreciation", "hiring_manager", "outro"],
  "featured_repo": "repo-name",
  "featured_developer": "username",
  "cover_art_suggestion": "Brief description of a visual concept for the cover art"
}
```

### Producer Lambda

**Reads from state:**
- `$.script.text` — the script to evaluate
- `$.script.character_count` — to enforce the 5,000 character hard limit
- `$.script.segments` — to verify all 6 segments are present
- `$.discovery.repo_name`, `$.discovery.repo_description` — to verify script specificity (jokes reference the actual project)
- `$.research.hiring_signals` — to verify the hiring segment uses real observations

**Reads from Postgres:**
- `episodes` + `episode_metrics` — top-performing episode scripts (by engagement) to use as quality benchmarks

**Returns (PASS):** (placed at `$.producer` by Step Functions)

```json
{
  "verdict": "PASS",
  "score": 8,
  "notes": "Brief evaluation summary"
}
```

**Returns (FAIL):** (placed at `$.producer` by Step Functions)

```json
{
  "verdict": "FAIL",
  "score": 4,
  "feedback": "Structured feedback: what specifically needs to change. This gets appended to the Script Lambda's next input.",
  "issues": ["issue 1", "issue 2"]
}
```

### Cover Art Lambda

**Reads from state:**
- `$.metadata.execution_id` — for S3 key prefix
- `$.script.cover_art_suggestion` — visual concept from the Script agent
- `$.discovery.repo_name` — for episode subtitle text
- `$.discovery.language` — to inform visual theme (e.g., terminal aesthetic for CLI tools)

**Returns:** (placed at `$.cover_art` by Step Functions)

```json
{
  "s3_key": "episodes/{execution_id}/cover.png",
  "prompt_used": "The actual prompt sent to Nova Canvas"
}
```

### TTS Lambda

**Reads from state:**
- `$.metadata.execution_id` — for S3 key prefix
- `$.script.text` — the approved script, parsed into dialogue turns by speaker label

**Returns:** (placed at `$.tts` by Step Functions)

```json
{
  "s3_key": "episodes/{execution_id}/episode.mp3",
  "duration_seconds": 180,
  "character_count": 4200
}
```

### Post-Production Lambda

**Reads from state:**
- `$.metadata.execution_id` — for S3 key prefix (MP4 output)
- `$.discovery.repo_url`, `$.discovery.repo_name`, `$.discovery.developer_github`, `$.discovery.star_count` — for the `episodes` DB row
- `$.research.developer_name` — for the `episodes` DB row
- `$.research` — full object, stored as `research_json` in `episodes`
- `$.script.text` — stored as `script_text` in `episodes`
- `$.metadata.script_attempt` — stored as `producer_attempts` in `episodes`
- `$.cover_art.s3_key` — to download the PNG for ffmpeg input
- `$.cover_art.prompt_used` — stored as `cover_art_prompt` in `episodes`
- `$.tts.s3_key` — to download the MP3 for ffmpeg input

**Returns:** (placed at `$.post_production` by Step Functions)

```json
{
  "s3_mp4_key": "episodes/{execution_id}/episode.mp4",
  "episode_id": 2,
  "air_date": "2025-07-13"
}
```

### Script Text Format

The `script.text` field is the contract between the Script Lambda (writer) and the TTS Lambda (parser). The format must be exact — the TTS Lambda splits on speaker labels to build the ElevenLabs API request.

**Rules:**
- One dialogue turn per line.
- Each line starts with a speaker label: `**Hype:**`, `**Roast:**`, or `**Phil:**` — no other labels permitted.
- Everything after the label on that line is the spoken text for that turn.
- No blank lines, stage directions, segment headers, or parentheticals in the text. Only speakable dialogue.

**Speaker-to-voice mapping (used by TTS Lambda):**

| Label | Voice ID |
|-------|----------|
| `**Hype:**` | `cjVigY5qzO86Huf0OWal` |
| `**Roast:**` | `JBFqnCBsd6RMkjVDRZzb` |
| `**Phil:**` | `cgSgspJ2msm6clMCkdW9` |

**TTS Lambda parsing behavior:** split `script.text` on newlines, match each line against `^\*\*(?:Hype|Roast|Phil):\*\*\s*(.+)$`. Lines that don't match are an error — raise an exception (do not silently skip).

**Example:**
```
**Hype:** Welcome back to 0 Stars, 10 out of 10! Today we found something incredible.
**Roast:** You say that every week. It's never incredible.
**Phil:** But what is incredible, really? Is it the code, or is it the coder?
```

> **TODO:** This exact format specification (the three labels, one turn per line, no stage directions) must be embedded in the Script agent prompt (`lambdas/script/prompts/script.md`) so the model produces compliant output. The Producer agent prompt should also enforce this as a FAIL condition.

---

## 3. Step Functions ASL Definition

The state machine definition as ASL (Amazon States Language). This gets placed inside `jsonencode()` in `terraform/step-functions.tf`.

### State Machine Flow

```
Start
  → InitializeMetadata (Pass — sets execution_id from $$.Execution.Id, script_attempt = 1)
  → Discovery
  → Research
  → Script
  → Producer
  → EvaluateVerdict (Choice)
      ├── FAIL + attempts < 3 → IncrementAttempt → Script (loop back)
      ├── FAIL + attempts >= 3 → PipelineFailed (Fail state)
      └── PASS → CoverArt
  → TTS
  → PostProduction
  → Done (Succeed)
```

### Key Design Decisions

- **ResultPath**: Each Lambda writes to its own key using `ResultPath: "$.lambda_name"` so the full state accumulates without overwriting.
- **Retry on transient errors**: Every Lambda task has a `Retry` block for `States.TaskFailed` with exponential backoff (1s, 2s, 4s) and max 3 attempts. This handles Bedrock throttling, API timeouts, etc. `States.TaskFailed` catches all errors except `States.Timeout` — a Lambda hitting its 300s timeout is non-retriable by design and falls through to Catch.
- **Catch**: Each Lambda has a `Catch` block that routes to a `HandleError` state (Pass) before entering the `PipelineFailed` Fail state. The Catch captures error details at `$.error_info` via `ResultPath` so they're visible in the execution history.
- **Evaluator loop**: The Producer Lambda returns a verdict. A Choice state checks `$.producer.verdict` with three explicit rules evaluated in order: (1) PASS → CoverArt, (2) FAIL with `$.metadata.script_attempt >= 3` → PipelineFailed, (3) FAIL → IncrementAttempt (loop back). The `Default` routes to HandleError, catching unexpected verdict values and surfacing Producer bugs immediately rather than silently retrying.
- **Counter increment**: The `IncrementAttempt` Pass state uses `States.MathAdd($.metadata.script_attempt, 1)` in `Parameters` with `ResultPath: "$.metadata"` to increment the counter while preserving all other state keys.
- **Script retry input**: When looping back to Script, the state object includes `$.producer.feedback` from the failed evaluation. The Script Lambda reads this and incorporates it.

### ASL Definition

Lambda Resource ARNs are shown as `<discovery_lambda_arn>` etc. In Terraform's `jsonencode()`, these become `aws_lambda_function.discovery.arn` references. The mapping is:

| Placeholder | Terraform Reference |
|-------------|-------------------|
| `<discovery_lambda_arn>` | `aws_lambda_function.discovery.arn` |
| `<research_lambda_arn>` | `aws_lambda_function.research.arn` |
| `<script_lambda_arn>` | `aws_lambda_function.script.arn` |
| `<producer_lambda_arn>` | `aws_lambda_function.producer.arn` |
| `<cover_art_lambda_arn>` | `aws_lambda_function.cover_art.arn` |
| `<tts_lambda_arn>` | `aws_lambda_function.tts.arn` |
| `<post_production_lambda_arn>` | `aws_lambda_function.post_production.arn` |

```json
{
  "Comment": "0 Stars, 10/10 — fully autonomous podcast pipeline",
  "StartAt": "InitializeMetadata",
  "States": {
    "InitializeMetadata": {
      "Type": "Pass",
      "Parameters": {
        "metadata": {
          "execution_id.$": "$$.Execution.Id",
          "script_attempt": 1
        }
      },
      "Next": "Discovery"
    },
    "Discovery": {
      "Type": "Task",
      "Resource": "<discovery_lambda_arn>",
      "ResultPath": "$.discovery",
      "Retry": [
        {
          "ErrorEquals": ["States.TaskFailed"],
          "IntervalSeconds": 1,
          "MaxAttempts": 3,
          "BackoffRate": 2.0
        }
      ],
      "Catch": [
        {
          "ErrorEquals": ["States.ALL"],
          "ResultPath": "$.error_info",
          "Next": "HandleError"
        }
      ],
      "Next": "Research"
    },
    "Research": {
      "Type": "Task",
      "Resource": "<research_lambda_arn>",
      "ResultPath": "$.research",
      "Retry": [
        {
          "ErrorEquals": ["States.TaskFailed"],
          "IntervalSeconds": 1,
          "MaxAttempts": 3,
          "BackoffRate": 2.0
        }
      ],
      "Catch": [
        {
          "ErrorEquals": ["States.ALL"],
          "ResultPath": "$.error_info",
          "Next": "HandleError"
        }
      ],
      "Next": "Script"
    },
    "Script": {
      "Type": "Task",
      "Resource": "<script_lambda_arn>",
      "ResultPath": "$.script",
      "Retry": [
        {
          "ErrorEquals": ["States.TaskFailed"],
          "IntervalSeconds": 1,
          "MaxAttempts": 3,
          "BackoffRate": 2.0
        }
      ],
      "Catch": [
        {
          "ErrorEquals": ["States.ALL"],
          "ResultPath": "$.error_info",
          "Next": "HandleError"
        }
      ],
      "Next": "Producer"
    },
    "Producer": {
      "Type": "Task",
      "Resource": "<producer_lambda_arn>",
      "ResultPath": "$.producer",
      "Retry": [
        {
          "ErrorEquals": ["States.TaskFailed"],
          "IntervalSeconds": 1,
          "MaxAttempts": 3,
          "BackoffRate": 2.0
        }
      ],
      "Catch": [
        {
          "ErrorEquals": ["States.ALL"],
          "ResultPath": "$.error_info",
          "Next": "HandleError"
        }
      ],
      "Next": "EvaluateVerdict"
    },
    "EvaluateVerdict": {
      "Type": "Choice",
      "Choices": [
        {
          "Variable": "$.producer.verdict",
          "StringEquals": "PASS",
          "Next": "CoverArt"
        },
        {
          "And": [
            {
              "Variable": "$.producer.verdict",
              "StringEquals": "FAIL"
            },
            {
              "Variable": "$.metadata.script_attempt",
              "NumericGreaterThanEquals": 3
            }
          ],
          "Next": "PipelineFailed"
        },
        {
          "Variable": "$.producer.verdict",
          "StringEquals": "FAIL",
          "Next": "IncrementAttempt"
        }
      ],
      "Default": "HandleError"
    },
    "IncrementAttempt": {
      "Type": "Pass",
      "Parameters": {
        "execution_id.$": "$.metadata.execution_id",
        "script_attempt.$": "States.MathAdd($.metadata.script_attempt, 1)"
      },
      "ResultPath": "$.metadata",
      "Next": "Script"
    },
    "CoverArt": {
      "Type": "Task",
      "Resource": "<cover_art_lambda_arn>",
      "ResultPath": "$.cover_art",
      "Retry": [
        {
          "ErrorEquals": ["States.TaskFailed"],
          "IntervalSeconds": 1,
          "MaxAttempts": 3,
          "BackoffRate": 2.0
        }
      ],
      "Catch": [
        {
          "ErrorEquals": ["States.ALL"],
          "ResultPath": "$.error_info",
          "Next": "HandleError"
        }
      ],
      "Next": "TTS"
    },
    "TTS": {
      "Type": "Task",
      "Resource": "<tts_lambda_arn>",
      "ResultPath": "$.tts",
      "Retry": [
        {
          "ErrorEquals": ["States.TaskFailed"],
          "IntervalSeconds": 1,
          "MaxAttempts": 3,
          "BackoffRate": 2.0
        }
      ],
      "Catch": [
        {
          "ErrorEquals": ["States.ALL"],
          "ResultPath": "$.error_info",
          "Next": "HandleError"
        }
      ],
      "Next": "PostProduction"
    },
    "PostProduction": {
      "Type": "Task",
      "Resource": "<post_production_lambda_arn>",
      "ResultPath": "$.post_production",
      "Retry": [
        {
          "ErrorEquals": ["States.TaskFailed"],
          "IntervalSeconds": 1,
          "MaxAttempts": 3,
          "BackoffRate": 2.0
        }
      ],
      "Catch": [
        {
          "ErrorEquals": ["States.ALL"],
          "ResultPath": "$.error_info",
          "Next": "HandleError"
        }
      ],
      "Next": "Done"
    },
    "HandleError": {
      "Type": "Pass",
      "Next": "PipelineFailed"
    },
    "PipelineFailed": {
      "Type": "Fail",
      "Error": "PipelineError",
      "Cause": "Pipeline execution failed — check execution history for details"
    },
    "Done": {
      "Type": "Succeed"
    }
  }
}
```

---

## 4. Terraform Resource Map

No modules. Every resource defined inline. This section maps each Terraform resource to its file for disambiguation.

### `main.tf`

| Resource | Type |
|----------|------|
| AWS provider | `provider "aws"` |
| Terraform backend | `terraform { backend "local" {} }` |
| Current account ID | `data "aws_caller_identity" "current"` |
| Current region | `data "aws_region" "current"` |
| Default tags | `default_tags` in provider: `project = "0-stars-podcast"`, `managed_by = "terraform"` |

### `variables.tf`

| Variable | Type | Description |
|----------|------|-------------|
| `elevenlabs_api_key` | `string` (sensitive) | ElevenLabs API key |
| `exa_api_key` | `string` (sensitive) | Exa Search API key |
| `db_connection_string` | `string` (sensitive) | Postgres connection string (`postgresql://user:pass@host:5432/dbname?sslmode=require`) |
| `domain_name` | `string` | Domain for the podcast site (e.g., `podcast.ryans-lab.click`) |
| `project_prefix` | `string` | Resource name prefix, default `zerostars` |

### `outputs.tf`

| Output | Source | Description |
|--------|--------|-------------|
| `state_machine_arn` | `aws_sfn_state_machine` | Pipeline state machine ARN |
| `site_url` | `var.domain_name` | Podcast website URL (`https://{domain_name}`) |
| `s3_bucket_name` | `aws_s3_bucket` | Episode assets S3 bucket name |

### `lambdas.tf`

| Resource | Type | Notes |
|----------|------|-------|
| Shared Lambda Layer | `aws_lambda_layer_version` | Source: `lambdas/shared/` |
| ffmpeg Lambda Layer | `aws_lambda_layer_version` | Source: `layers/ffmpeg/ffmpeg-layer.zip` (built by `build.sh`) |
| psql Lambda Layer | `aws_lambda_layer_version` | Source: `layers/psql/psql-layer.zip` (built by `build.sh`). Provides `/opt/bin/psql` and `/opt/lib/libpq.so*`. |
| Per-Lambda (×8): | | |
| — Deployment package | `data "archive_file"` | Zips `handler.py` + `prompts/` dir |
| — Function | `aws_lambda_function` | Python 3.12, layers attached, env vars set, `logging_config` block, `depends_on` log group |
| — IAM role | `aws_iam_role` | Lambda assume-role trust policy |
| — IAM policy | `aws_iam_role_policy` | Least-privilege: CloudWatch Logs + function-specific permissions |
| — Log group | `aws_cloudwatch_log_group` | 14-day retention |

**Per-Lambda `logging_config` block** (native Lambda structured logging — applies to all 8 functions):

```hcl
logging_config {
  log_format            = "JSON"
  application_log_level = "INFO"
  system_log_level      = "WARN"
}
```

**Per-Lambda environment variables** (for Powertools — applies to all 8 functions, in addition to function-specific env vars):

| Variable | Value |
|----------|-------|
| `POWERTOOLS_SERVICE_NAME` | Function-specific: `discovery`, `research`, `script`, `producer`, `cover_art`, `tts`, `post_production`, `site` |
| `POWERTOOLS_LOG_LEVEL` | `INFO` |

**Per-Lambda IAM permissions:**

| Lambda | Extra permissions beyond CloudWatch Logs |
|--------|------------------------------------------|
| Discovery | `bedrock:InvokeModel`, Secrets Manager read (Exa key), SSM `GetParameter` (`/zerostars/db-connection-string`), psql layer attached |
| Research | `bedrock:InvokeModel` |
| Script | `bedrock:InvokeModel` |
| Producer | `bedrock:InvokeModel` |
| Cover Art | `bedrock:InvokeModel` (Nova Canvas) |
| TTS | Secrets Manager read (ElevenLabs key) |
| Post-Production | S3 read/write, ffmpeg layer attached |
| Site | S3 read (for presigned URLs) |

Note: Lambdas that read from Postgres do so over the public internet using the connection string. No VPC or RDS-specific IAM needed.

### `step-functions.tf`

| Resource | Type |
|----------|------|
| State machine | `aws_sfn_state_machine` |
| Execution IAM role | `aws_iam_role` |
| Execution IAM policy | `aws_iam_role_policy` (invoke all 7 pipeline Lambdas) |

### `scheduling.tf`

| Resource | Type |
|----------|------|
| Scheduler rule | `aws_scheduler_schedule` |
| Scheduler IAM role | `aws_iam_role` (permission to start Step Functions execution) |
| Scheduler IAM policy | `aws_iam_role_policy` (`states:StartExecution` on the state machine) |

### `s3.tf`

| Resource | Type |
|----------|------|
| Episode assets bucket | `aws_s3_bucket` |
| Bucket public access block | `aws_s3_bucket_public_access_block` |
| Bucket policy | `aws_s3_bucket_policy` (CloudFront OAC read access to `episodes/*/cover.png` objects) |

### `site.tf`

| Resource | Type |
|----------|------|
| Site Lambda Function URL | `aws_lambda_function_url` |
| CloudFront distribution | `aws_cloudfront_distribution` — two origins: (1) Lambda Function URL for HTML pages (default behavior, ~1 hour TTL), (2) S3 origin via OAC for cover art images at `/assets/*` path pattern. MP3 and MP4 files are accessed via presigned URLs generated by the site Lambda, not through CloudFront. |
| CloudFront OAC | `aws_cloudfront_origin_access_control` (for S3 cover art origin) |
| Route53 hosted zone | `data "aws_route53_zone"` (looks up existing zone for the parent domain) |
| Route53 A record | `aws_route53_record` (alias to CloudFront) |
| ACM certificate | `aws_acm_certificate` (DNS validation, for `var.domain_name`; must be in `us-east-1` for CloudFront) |
| ACM DNS validation record | `aws_route53_record` (CNAME from `domain_validation_options`) |
| ACM validation waiter | `aws_acm_certificate_validation` (blocks until cert is validated) |

### `secrets.tf`

| Resource | Type |
|----------|------|
| ElevenLabs secret | `aws_secretsmanager_secret` + `aws_secretsmanager_secret_version` |
| Exa secret | `aws_secretsmanager_secret` + `aws_secretsmanager_secret_version` |

---

## 5. External API Contracts

Exact endpoints, request/response formats, and credentials for every external service the pipeline calls.

### AWS Bedrock — Claude (Agent Reasoning)

Used by: Discovery, Research, Script, Producer Lambdas.

```python
# Via shared/bedrock.py
import boto3
import json

client = boto3.client("bedrock-runtime")

# Basic invocation (Script, Producer)
response = client.invoke_model(
    modelId="us.anthropic.claude-sonnet-4-6",
    contentType="application/json",
    accept="application/json",
    body=json.dumps({
        "anthropic_version": "bedrock-2023-05-31",
        "max_tokens": 4096,
        "system": system_prompt,
        "messages": [
            {"role": "user", "content": user_prompt}
        ]
    })
)
result = json.loads(response["body"].read())
text = result["content"][0]["text"]

# With tool use (Discovery, Research) — agentic loop via shared/bedrock.py
#
# The invoke_with_tools() function takes a tool_executor callback so each
# Lambda provides its own tool implementations. This keeps bedrock.py generic.
#
# Signature:
#   invoke_with_tools(
#       user_message: str,
#       system_prompt: str,
#       tools: list[dict],
#       tool_executor: Callable[[str, dict], str],  # (tool_name, tool_input) -> JSON string
#       model_id: str = DEFAULT_MODEL_ID,
#       max_turns: int = 25,  # safety valve on loop iterations
#   ) -> str
#
# The function loops internally:
#   1. Invoke Bedrock with tools
#   2. If stop_reason == "tool_use": extract tool_use blocks, call tool_executor
#      for each, append tool_result messages, re-invoke
#   3. If stop_reason == "end_turn": return the text response
#   4. Retry on ThrottlingException with exponential backoff (3 retries, 1s base)
#
# Example handler usage (Discovery):

from shared.bedrock import invoke_with_tools

def _execute_tool(tool_name: str, tool_input: dict) -> str:
    """Dispatch to the right tool function, return JSON string."""
    if tool_name == "exa_search":
        result = _execute_exa_search(tool_input)
    elif tool_name == "query_postgres":
        result = _execute_query_postgres(tool_input)
    elif tool_name == "get_github_repo":
        result = _execute_get_github_repo(tool_input)
    else:
        result = {"error": f"Unknown tool: {tool_name}"}
    return json.dumps(result)

result_text = invoke_with_tools(
    user_message="Find one underrated GitHub repository to feature.",
    system_prompt=system_prompt,
    tools=TOOL_DEFINITIONS,
    tool_executor=_execute_tool,
)

# Tool errors should return {"error": "..."} dicts instead of raising,
# so the agent sees errors and can adapt (retry, pick a different candidate).

# The underlying Bedrock API call is invoke_model with the Anthropic
# Messages API body format — tools array in the body, stop_reason in response:
response = client.invoke_model(
    modelId="us.anthropic.claude-sonnet-4-6",
    contentType="application/json",
    accept="application/json",
    body=json.dumps({
        "anthropic_version": "bedrock-2023-05-31",
        "max_tokens": 4096,
        "system": system_prompt,
        "messages": messages,
        "tools": tool_definitions
    })
)
result = json.loads(response["body"].read())
# result["stop_reason"] is "tool_use" or "end_turn"
# result["content"] contains text blocks and/or tool_use blocks
```

### AWS Bedrock — Nova Canvas (Cover Art)

Used by: Cover Art Lambda.

```python
response = client.invoke_model(
    modelId="amazon.nova-canvas-v1:0",
    contentType="application/json",
    accept="application/json",
    body=json.dumps({
        "taskType": "TEXT_IMAGE",
        "textToImageParams": {
            "text": cover_art_prompt
        },
        "imageGenerationConfig": {
            "numberOfImages": 1,
            "width": 1024,
            "height": 1024,
            "quality": "standard"
        }
    })
)
result = json.loads(response["body"].read())
image_bytes = base64.b64decode(result["images"][0])
```

### ElevenLabs — Text-to-Dialogue (TTS)

Used by: TTS Lambda.

```
POST https://api.elevenlabs.io/v1/text-to-dialogue?output_format=mp3_44100_128
Headers:
  Content-Type: application/json
  xi-api-key: <from Secrets Manager>

Request body:
{
  "inputs": [
    {"text": "First speaker's line", "voice_id": "cjVigY5qzO86Huf0OWal"},
    {"text": "Second speaker's line", "voice_id": "JBFqnCBsd6RMkjVDRZzb"},
    ...
  ],
  "model_id": "eleven_v3"
}

Response: Raw MP3 binary (on 200 OK)
Error: JSON body with "detail" field (on 4xx/5xx)
```

**Voice IDs:**

| Persona | Voice Name | Voice ID |
|---------|------------|----------|
| Hype | Eric | `cjVigY5qzO86Huf0OWal` |
| Roast | George | `JBFqnCBsd6RMkjVDRZzb` |
| Phil | Jessica | `cgSgspJ2msm6clMCkdW9` |

**Hard constraint:** 5,000 character limit across all `text` fields combined.

### Exa Search API

Used by: Discovery Lambda (via Bedrock tool use).

The Discovery agent uses Bedrock's tool-use capability to call Exa. Define Exa search as a tool in the Bedrock request:

```json
{
  "name": "exa_search",
  "description": "Search for GitHub repositories and web content using Exa's neural search.",
  "input_schema": {
    "type": "object",
    "properties": {
      "query": {"type": "string", "description": "Natural language search query"},
      "include_domains": {"type": "array", "items": {"type": "string"}, "description": "Limit results to these domains (e.g. [\"github.com\"])"},
      "num_results": {"type": "integer", "description": "Number of results to return (max 10)"},
      "start_published_date": {"type": "string", "description": "ISO date, filter results after this date"},
      "exclude_text": {"type": "string", "description": "Exclude results containing this text"}
    },
    "required": ["query"]
  }
}
```

When Bedrock returns a `tool_use` block for `exa_search`, the Lambda translates snake_case tool inputs to camelCase and executes the actual Exa API call:

```
POST https://api.exa.ai/search
Headers:
  Content-Type: application/json
  x-api-key: <from Secrets Manager>

Request body:
{
  "query": "...",
  "includeDomains": ["github.com"],
  "numResults": 10,
  "startPublishedDate": "2024-01-01",
  "contents": {
    "text": true
  }
}

Response (200 OK):
{
  "requestId": "...",
  "results": [
    {
      "title": "owner/repo-name",
      "url": "https://github.com/owner/repo-name",
      "id": "...",
      "publishedDate": "2024-06-15T00:00:00.000Z",
      "author": "...",
      "text": "README and repo description text..."
    }
  ]
}
```

### Discovery Postgres Tool (`query_postgres`)

Used by: Discovery Lambda (via Bedrock tool use).

The Discovery agent queries Postgres directly through a `psql` subprocess to check whether candidate projects/developers have already been featured. The `psql` binary is provided by the psql Lambda layer (see §8).

**Tool definition for Bedrock:**

```json
{
  "name": "query_postgres",
  "description": "Run a read-only SQL query against the podcast database. Only SELECT statements are allowed. Returns rows as pipe-delimited text.",
  "input_schema": {
    "type": "object",
    "properties": {
      "sql": {"type": "string", "description": "A SELECT SQL query to execute"}
    },
    "required": ["sql"]
  }
}
```

**Handler implementation:** When Bedrock returns a `tool_use` block for `query_postgres`, the handler:

1. **Enforces read-only:** Checks that the SQL starts with `SELECT` (case-insensitive, after stripping whitespace). Rejects INSERT, UPDATE, DELETE, DROP, etc. with an error.
2. **Fetches connection string:** From SSM Parameter Store at `/zerostars/db-connection-string` with `WithDecryption=True`. Cached in a module-level global across warm invocations.
3. **Runs psql subprocess:**

```python
result = subprocess.run(
    ["/opt/bin/psql", conn_str, "-c", sql, "--no-align", "--tuples-only", "--pset", "null=(null)"],
    capture_output=True, text=True, timeout=15,
)
```

- `--no-align --tuples-only` strips headers and alignment, producing clean pipe-delimited output the model can parse.
- `--pset null=(null)` renders NULL as literal `(null)` instead of empty string.
- Timeout of 15 seconds prevents runaway queries from consuming the Lambda's 300s budget.
- On psql error, returns `{"error": "<stderr truncated to 500 chars>"}`.
- On success, returns `{"rows": "<stdout>"}`.

### Discovery GitHub Tool (`get_github_repo`)

Used by: Discovery Lambda (via Bedrock tool use).

The Discovery agent uses this tool to verify star counts and repo metadata before selecting a candidate. This is critical — Exa search results do not include exact star counts.

**Tool definition for Bedrock:**

```json
{
  "name": "get_github_repo",
  "description": "Get metadata for a GitHub repository including star count, language, description, topics, and activity dates.",
  "input_schema": {
    "type": "object",
    "properties": {
      "owner": {"type": "string", "description": "Repository owner (GitHub username)"},
      "repo": {"type": "string", "description": "Repository name"}
    },
    "required": ["owner", "repo"]
  }
}
```

**Handler implementation:** When Bedrock returns a `tool_use` block for `get_github_repo`, the handler calls the GitHub REST API:

```
GET https://api.github.com/repos/{owner}/{repo}
Headers:
  Accept: application/vnd.github.v3+json
  User-Agent: zerostars-discovery-agent
```

The `User-Agent` header is required — GitHub returns 403 without it. No auth key needed (public API, rate limited to 60 req/hour unauthenticated).

The handler returns a curated subset of the response (the full GitHub response is ~3KB and would inflate the Bedrock conversation):

```python
{
    "name": data["name"],
    "full_name": data["full_name"],
    "description": data["description"],
    "stargazers_count": data["stargazers_count"],
    "forks_count": data["forks_count"],
    "language": data["language"],
    "topics": data["topics"],
    "created_at": data["created_at"],
    "pushed_at": data["pushed_at"],
    "open_issues_count": data["open_issues_count"],
    "license": data["license"]["spdx_id"] if data["license"] else None,
    "owner_type": data["owner"]["type"],  # "User" vs "Organization"
    "html_url": data["html_url"],
    "default_branch": data["default_branch"],
}
```

### GitHub API

Used by: Discovery Lambda (`get_github_repo` tool) and Research Lambda (via Bedrock tool use).

Public API, no auth key needed (rate limited to 60 req/hour for unauthenticated).

Tools defined for Bedrock:

```json
[
  {
    "name": "get_github_user",
    "description": "Get a GitHub user's profile",
    "input_schema": {
      "type": "object",
      "properties": {
        "username": {"type": "string"}
      },
      "required": ["username"]
    }
  },
  {
    "name": "get_user_repos",
    "description": "Get a GitHub user's public repositories",
    "input_schema": {
      "type": "object",
      "properties": {
        "username": {"type": "string"},
        "sort": {"type": "string", "enum": ["updated", "pushed", "created"]},
        "per_page": {"type": "integer"}
      },
      "required": ["username"]
    }
  },
  {
    "name": "get_repo_details",
    "description": "Get details about a specific repository",
    "input_schema": {
      "type": "object",
      "properties": {
        "owner": {"type": "string"},
        "repo": {"type": "string"}
      },
      "required": ["owner", "repo"]
    }
  },
  {
    "name": "get_repo_readme",
    "description": "Get the README content of a repository",
    "input_schema": {
      "type": "object",
      "properties": {
        "owner": {"type": "string"},
        "repo": {"type": "string"}
      },
      "required": ["owner", "repo"]
    }
  },
  {
    "name": "search_repositories",
    "description": "Search GitHub repositories by query. Supports sorting by stars.",
    "input_schema": {
      "type": "object",
      "properties": {
        "query": {"type": "string", "description": "Search query (e.g. 'user:username' or 'topic:ml')"},
        "sort": {"type": "string", "enum": ["stars", "forks", "updated"]},
        "per_page": {"type": "integer"}
      },
      "required": ["query"]
    }
  }
]
```

API endpoints and key response fields:

- `GET https://api.github.com/users/{username}`
  → `login`, `name`, `bio`, `public_repos`, `followers`, `created_at`, `html_url`

- `GET https://api.github.com/users/{username}/repos?sort={sort}&per_page={per_page}`
  → Array of repo objects (see fields below)

- `GET https://api.github.com/repos/{owner}/{repo}`
  → `name`, `full_name`, `description`, `stargazers_count`, `forks_count`, `language`, `topics`, `created_at`, `updated_at`, `html_url`

- `GET https://api.github.com/repos/{owner}/{repo}/readme`
  → `content` (base64-encoded), `encoding` ("base64")

- `GET https://api.github.com/search/repositories?q={query}&sort={sort}&per_page={per_page}`
  → `total_count`, `items` (array of repo objects with same fields as above)

---

## 6. Database Schema

DDL for `sql/schema.sql`. The database and tables below have already been created on the RDS instance — do not re-run this DDL.

```sql
-- 0 Stars, 10/10 — Database Schema
-- Run with: psql <postgres-connection-string> -f sql/schema.sql

CREATE DATABASE zerostars;
\c zerostars

CREATE TABLE IF NOT EXISTS episodes (
    episode_id      SERIAL PRIMARY KEY,
    air_date        DATE NOT NULL,
    repo_url        TEXT NOT NULL,
    repo_name       TEXT NOT NULL,
    developer_github TEXT NOT NULL,
    developer_name  TEXT,
    star_count_at_recording INTEGER,
    script_text     TEXT NOT NULL,
    research_json   JSONB,
    cover_art_prompt TEXT,
    s3_mp3_path     TEXT,
    s3_mp4_path     TEXT,
    s3_cover_art_path TEXT,
    producer_attempts INTEGER DEFAULT 1,
    created_at      TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS episode_metrics (
    metric_id       SERIAL PRIMARY KEY,
    episode_id      INTEGER NOT NULL REFERENCES episodes(episode_id),
    linkedin_post_url TEXT,
    views           INTEGER DEFAULT 0,
    likes           INTEGER DEFAULT 0,
    comments        INTEGER DEFAULT 0,
    shares          INTEGER DEFAULT 0,
    snapshot_date   DATE NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_episode_metrics_episode_id ON episode_metrics(episode_id);

CREATE TABLE IF NOT EXISTS featured_developers (
    developer_github TEXT PRIMARY KEY,
    episode_id      INTEGER NOT NULL REFERENCES episodes(episode_id),
    featured_date   DATE NOT NULL
);
```

---

## 7. Prompt Files

The content for each Lambda's `prompts/` directory. These are bundled into the Lambda deployment package and read at runtime via `LAMBDA_TASK_ROOT`.

### `lambdas/discovery/prompts/discovery.md`

````markdown
# Discovery Agent — "0 Stars, 10/10"

You are the Discovery agent for "0 Stars, 10/10," a comedy podcast where three AI personas (Hype, Roast, and Phil) discuss small, obscure GitHub projects that almost nobody has heard of and hype up the solo developers who built them.

Your job: find ONE GitHub repository to feature on this week's episode.

## What Makes a Good Pick

The ideal repo is a small hobby project built by a solo developer. It should be:

- **Under 10 stars.** This is a hard ceiling. Do not select any repo with 10 or more stars. Verify the exact count with the `get_github_repo` tool before committing to a pick.
- **A solo developer's work.** One person built this, not a team or organization. Look for personal GitHub accounts, not org repos.
- **A hobby or side project.** Something built for fun, curiosity, or to scratch a personal itch. Not a work project, not a startup MVP.
- **Recently active.** The repo should have commits within the last 12 months. Do not pick abandoned projects with no activity since 2023.
- **Technically interesting.** The project should have at least one notable technical decision, unusual approach, or clever solution worth discussing on the podcast. A CRUD app with no distinctive features is not interesting.
- **Has a README.** The README does not need to be long, but it should exist and explain what the project does. A bare repo with no documentation gives the podcast hosts nothing to work with.
- **Has personality.** The best picks are projects where you can sense the developer's personality — a witty README, an unusual project idea, creative naming, or an opinionated design choice.

## What to Avoid

Do NOT select repos that fall into these categories:

- **AI/ML tools, wrappers, or chatbots.** No LLM wrappers, no "ChatGPT but for X," no ML model training scripts, no AI agent frameworks. The podcast covers underrated projects, and AI slop is the opposite of underrated — it is oversaturated.
- **Infrastructure and DevOps tooling.** No Terraform modules, no Kubernetes operators, no CI/CD helpers, no Docker utilities. These are useful but not entertaining podcast material.
- **Awesome lists or curated link collections.** These are not projects.
- **Forks with minimal changes.** The project should be original work.
- **Tutorial output or course homework.** No "my-first-react-app" or "udemy-python-project."
- **Crypto, NFT, or blockchain projects.**
- **Empty or skeleton repos.** The repo must have substantive code.

## Your Tools

You have three tools:

### `exa_search`
Neural search via the Exa API. Use this to discover candidate repos. Tips:
- Always set `include_domains` to `["github.com"]` to limit results to GitHub repos.
- Use specific, descriptive search queries rather than generic ones. "Python CLI tool for converting markdown to slides" is better than "cool Python project."
- Run multiple searches with different queries to build a diverse candidate pool. A single search rarely surfaces the best pick on the first try.
- Use `start_published_date` to filter for recent repos (set to at least "2024-01-01").
- Try varied angles: search by language, by problem domain, by project type. For example, one search for "Rust terminal game," another for "Python automation tool for personal use," another for "Go CLI utility hobbyist project."

### `query_postgres`
Runs a read-only SQL query against the podcast database. Use this to check which developers and repos have already been featured on the show.

The database has these tables:

```sql
-- All previously featured episodes
episodes (
    episode_id              SERIAL PRIMARY KEY,
    air_date                DATE,
    repo_url                TEXT,          -- e.g. "https://github.com/user/repo"
    repo_name               TEXT,          -- e.g. "repo"
    developer_github        TEXT,          -- e.g. "username"
    developer_name          TEXT,
    star_count_at_recording INTEGER
)

-- Dedup list: every developer who has appeared on the show
featured_developers (
    developer_github TEXT PRIMARY KEY,  -- e.g. "username"
    episode_id       INTEGER,
    featured_date    DATE
)
```

**Example queries you should run:**

```sql
-- Get all previously featured developer usernames
SELECT developer_github FROM featured_developers;

-- Get all previously featured repo URLs
SELECT repo_url FROM episodes;

-- Check if a specific developer was already featured
SELECT developer_github FROM featured_developers WHERE developer_github = 'someuser';
```

**IMPORTANT:** Only run SELECT queries. Never run INSERT, UPDATE, DELETE, DROP, or any data-modifying statement.

### `get_github_repo`
Fetches metadata for a specific GitHub repository. Use this to verify star counts, check activity dates, get the description, and confirm the repo is real and public. Provide `owner` and `repo` as inputs.

Returns fields including: `stargazers_count`, `description`, `language`, `topics`, `created_at`, `pushed_at`, `forks_count`, `open_issues_count`, `license`, `default_branch`, and `owner_type` ("User" vs "Organization").

## The Never-Re-Feature Rule

**A developer must never appear on the podcast twice.** Before selecting a repo, you MUST check the `featured_developers` table to confirm the developer has not been featured before. If they have, discard that candidate and find another.

Similarly, never feature the same repository twice. Check the `episodes` table for the repo URL.

## Your Search Strategy

Follow this process:

1. **Query the database first.** Run `SELECT developer_github FROM featured_developers;` and `SELECT repo_url FROM episodes;` to get the exclusion lists. Keep these in mind for all subsequent steps.

2. **Run multiple Exa searches.** Use at least 3 different search queries with varied angles. Try different languages, project types, and problem domains. Cast a wide net.

3. **Build a candidate shortlist.** From the search results, identify 3-5 repos that look promising based on their titles and descriptions.

4. **Verify each candidate.** For each candidate on your shortlist, use `get_github_repo` to check:
   - Star count is under 10 (hard requirement)
   - The repo has been pushed to within the last 12 months
   - There is a description
   - The repo belongs to a personal account, not an organization

5. **Check against the database.** For each verified candidate, confirm the developer is not in `featured_developers` and the repo URL is not in `episodes`.

6. **Select the best one.** From the candidates that passed all checks, pick the one that would make the most entertaining podcast episode. Prioritize personality, technical interest, and storytelling potential.

## Output Format

After completing your search, return your selection as a JSON object with exactly these fields:

```json
{
  "repo_url": "https://github.com/owner/repo",
  "repo_name": "repo",
  "repo_description": "The repo's description from GitHub",
  "developer_github": "owner",
  "star_count": 7,
  "language": "Python",
  "discovery_rationale": "2-3 sentences explaining why this repo was selected. What makes it interesting? What would make good podcast material? Why would the hosts have fun discussing it?",
  "key_files": ["README.md", "src/main.py", "config.yaml"],
  "technical_highlights": [
    "Notable technical decision or pattern #1",
    "Notable technical decision or pattern #2"
  ]
}
```

**Field requirements:**
- `repo_url`: Full GitHub URL. Must start with "https://github.com/".
- `repo_name`: Just the repo name, not the full path.
- `repo_description`: The description from GitHub, not your own summary.
- `developer_github`: The GitHub username (owner). Must NOT be in the featured_developers table.
- `star_count`: Integer from `get_github_repo`. Must be under 10.
- `language`: Primary language from GitHub.
- `discovery_rationale`: Your genuine reasoning. Be specific about what caught your eye. Do not use generic praise.
- `key_files`: 2-5 files or directories in the repo that are worth the Research agent investigating. Identify the interesting parts, not boilerplate.
- `technical_highlights`: 1-3 specific technical observations. "Uses SQLite as an application file format" is good. "Well-structured code" is bad.

Return ONLY the JSON object. No markdown fencing, no preamble, no explanation outside the JSON.
````

### `lambdas/research/prompts/research.md`

```markdown
TODO: Research agent system prompt.

Key content to include:
- Role: You are the Research agent for "0 Stars, 10/10"
- You receive a discovered repo and need to build a developer profile
- Use GitHub tools to research: user profile, all public repos, the featured repo's README and details
- Look for: patterns in their work, languages they use, how active they are, interesting side projects
- Find material for the "developer deep-dive" podcast segment
- Identify "hiring signals" — what does this body of work tell a hiring manager?
- Return structured output matching the research interface contract
```

### `lambdas/script/prompts/script.md`

```markdown
TODO: Script agent system prompt.

Key content to include:
- Role: You are the Script agent for "0 Stars, 10/10"
- Three personas: Hype (relentlessly positive, absurd startup comparisons), Roast (dry British wit, grudgingly respects good work), Phil (over-interprets READMEs, existential questions)
- Episode structure (6 segments): intro & project reveal, core debate, developer deep-dive, technical appreciation (Roast's grudging compliment), hiring manager segment, outro with callbacks
- HARD LIMIT: Script must be under 5,000 characters. Target 4,000-4,500.
- Format: **Speaker:** dialogue text (one line per dialogue turn)
- Comedy must come from the SPECIFIC project — no generic jokes
- Roast's grudging respect should feel earned, not formulaic
- Hiring manager segment must contain real, specific observations
- If producer feedback is provided (retry), incorporate it specifically
- The script must work as spoken dialogue — no stage directions, no parentheticals
```

### `lambdas/producer/prompts/producer.md`

```markdown
TODO: Producer agent system prompt.

Key content to include:
- Role: You are the Producer agent for "0 Stars, 10/10"
- You evaluate scripts for quality before they go to TTS
- You will receive benchmark scripts (top-performing past episodes) for comparison
- Evaluation rubric:
  1. Character count: MUST be under 5,000. FAIL if over.
  2. Segment structure: All 6 segments present and in order
  3. Persona voice: Each persona sounds distinct and consistent with their description
  4. Comedy quality: Jokes are specific to the project, not generic
  5. Hiring manager segment: Contains specific, defensible observations
  6. Roast's turn: The grudging compliment feels earned
  7. Flow: Reads as natural conversation, not a script
- Return PASS with score and brief notes, or FAIL with specific actionable feedback
- On FAIL, feedback must be specific enough that the Script agent can fix the issues
- Do not nitpick — FAIL only for real quality issues
```

### `lambdas/cover_art/prompts/cover_art.md`

```markdown
TODO: Cover art prompt template.

Key content to include:
- This is a template that gets filled in by the Cover Art Lambda based on episode content
- Base elements always present:
  - Three robot characters representing Hype, Roast, and Phil
  - "0 STARS / 10/10" text/title
  - Episode subtitle (repo name or theme)
- Variable elements per episode:
  - Visual reference to the featured project (e.g., if it's a terminal tool, show a terminal)
  - Color scheme or mood matching the project's vibe
- Style: vibrant, fun, podcast cover art aesthetic, bold colors
- Nova Canvas constraints: text rendering is unreliable, keep text simple and large
```

---

## 8. Lambda Dependency Packaging

Each Lambda needs its dependencies available at runtime. This section specifies how.

### Shared Layer

The shared layer at `lambdas/shared/` provides `bedrock.py`, `db.py`, `s3.py`, `logging.py`, and `types.py`. It also needs `psycopg2` for Postgres access and `aws-lambda-powertools` for structured logging.

Use `psycopg2-binary` is not compatible with Lambda's Amazon Linux environment. Use the `aws-psycopg2` package or include a pre-compiled `psycopg2` for Linux x86_64.

**Recommended approach:** Use a Lambda-compatible psycopg2 build. The `build.sh` pattern:

```bash
cd lambdas/shared
pip install aws-lambda-powertools psycopg2-binary -t python/ --platform manylinux2014_x86_64 --only-binary=:all:
# shared Python modules are already in python/shared/
zip -r ../../build/shared-layer.zip python/
```

Note: `psycopg2-binary` wheels for `manylinux2014_x86_64` DO work on Lambda. The old advice about needing a special build is outdated for Python 3.12 + `manylinux2014` wheels.

> **TODO:** Add a `lambdas/shared/build.sh` script to the file manifest that automates this (pip install + zip). Currently not in the manifest — the build steps above are manual.

### Site Lambda

The site Lambda needs `jinja2`. Include it in the deployment package:

```bash
cd lambdas/site
pip install jinja2 -t .
zip -r ../../build/site.zip .
```

### TTS Lambda

The TTS Lambda needs `requests` (or use `urllib3` from botocore to avoid an extra dependency). If using the bundled `urllib3`:

```python
from botocore.vendored import requests  # Don't do this — deprecated
# Instead, use urllib.request from stdlib
import urllib.request
```

**Decision:** Use `urllib.request` from Python stdlib for the ElevenLabs API call. No extra dependencies needed for the TTS Lambda.

### Other Pipeline Lambdas

Research, Script, Producer, Cover Art — these only need `boto3` (pre-installed on Lambda) and the shared layer. No additional dependencies.

Discovery additionally needs the psql Lambda layer (see below) and uses `urllib.request` from stdlib for the Exa and GitHub API calls — no extra pip dependencies.

### psql Layer

Built by `layers/psql/build.sh`. Provides the `psql` binary and `libpq` shared library for Lambda (Amazon Linux 2023, x86_64). Used by the Discovery Lambda's `query_postgres` tool to run SQL queries via subprocess.

Lambda extracts layers to `/opt`. The layer structure places `bin/psql` at `/opt/bin/psql` (in Lambda's default `PATH`) and `lib/libpq.so*` at `/opt/lib/` (in Lambda's default `LD_LIBRARY_PATH`). No additional environment configuration needed.

```bash
#!/usr/bin/env bash
set -euo pipefail

# Build a Lambda layer containing the psql binary for Amazon Linux 2023 (x86_64).
# The binary and libpq are extracted from official PostgreSQL PGDG RPMs for RHEL 9,
# which are binary-compatible with AL2023.
#
# Layer structure:
#   bin/psql      -> /opt/bin/psql on Lambda (in default PATH)
#   lib/libpq.so* -> /opt/lib/ on Lambda (in default LD_LIBRARY_PATH)

OUTPUT_DIR="$(cd "$(dirname "$0")" && pwd)"
BUILD_DIR=$(mktemp -d)
POSTGRES_VERSION="16"
AL2023_REPO="https://download.postgresql.org/pub/repos/yum/${POSTGRES_VERSION}/redhat/rhel-9-x86_64"

echo "Downloading PostgreSQL ${POSTGRES_VERSION} RPMs for RHEL 9 (AL2023-compatible)..."

# Download the psql binary RPM
RPM_URL=$(curl -sL "${AL2023_REPO}/" \
    | grep -oP "postgresql${POSTGRES_VERSION}-${POSTGRES_VERSION}\.[0-9.]+-[0-9]+PGDG\.rhel9\.x86_64\.rpm" \
    | sort -V | tail -1)
if [ -z "$RPM_URL" ]; then
    echo "ERROR: Could not find PostgreSQL RPM in PGDG repo."
    exit 1
fi
echo "  psql RPM: $RPM_URL"
curl -sL "${AL2023_REPO}/${RPM_URL}" -o "$BUILD_DIR/postgresql.rpm"

# Download the libpq shared library RPM
LIBPQ_URL=$(curl -sL "${AL2023_REPO}/" \
    | grep -oP "postgresql${POSTGRES_VERSION}-libs-${POSTGRES_VERSION}\.[0-9.]+-[0-9]+PGDG\.rhel9\.x86_64\.rpm" \
    | sort -V | tail -1)
if [ -z "$LIBPQ_URL" ]; then
    echo "ERROR: Could not find PostgreSQL libs RPM in PGDG repo."
    exit 1
fi
echo "  libpq RPM: $LIBPQ_URL"
curl -sL "${AL2023_REPO}/${LIBPQ_URL}" -o "$BUILD_DIR/postgresql-libs.rpm"

echo "Extracting RPMs..."
cd "$BUILD_DIR"
rpm2cpio postgresql.rpm | cpio -idmv 2>/dev/null
rpm2cpio postgresql-libs.rpm | cpio -idmv 2>/dev/null

echo "Packaging Lambda layer..."
mkdir -p "$BUILD_DIR/layer/bin" "$BUILD_DIR/layer/lib"
cp "$BUILD_DIR/usr/pgsql-${POSTGRES_VERSION}/bin/psql" "$BUILD_DIR/layer/bin/psql"
cp "$BUILD_DIR/usr/pgsql-${POSTGRES_VERSION}/lib/"libpq.so* "$BUILD_DIR/layer/lib/"
chmod +x "$BUILD_DIR/layer/bin/psql"

cd "$BUILD_DIR/layer"
zip -r "$OUTPUT_DIR/psql-layer.zip" .

echo "Done: $OUTPUT_DIR/psql-layer.zip"
echo "Layer size: $(du -h "$OUTPUT_DIR/psql-layer.zip" | cut -f1)"
rm -rf "$BUILD_DIR"
```

### ffmpeg Layer

Built by `layers/ffmpeg/build.sh`:

```bash
#!/usr/bin/env bash
set -euo pipefail

# Download a static ffmpeg build compatible with Lambda (Amazon Linux 2023, x86_64)
FFMPEG_URL="https://johnvansickle.com/ffmpeg/releases/ffmpeg-release-amd64-static.tar.xz"
OUTPUT_DIR="$(dirname "$0")"
BUILD_DIR=$(mktemp -d)

echo "Downloading ffmpeg..."
curl -L "$FFMPEG_URL" -o "$BUILD_DIR/ffmpeg.tar.xz"

echo "Extracting..."
tar -xf "$BUILD_DIR/ffmpeg.tar.xz" -C "$BUILD_DIR"

echo "Packaging Lambda layer..."
mkdir -p "$BUILD_DIR/layer/bin"
cp "$BUILD_DIR"/ffmpeg-*-amd64-static/ffmpeg "$BUILD_DIR/layer/bin/ffmpeg"
chmod +x "$BUILD_DIR/layer/bin/ffmpeg"

cd "$BUILD_DIR/layer"
zip -r "$OUTPUT_DIR/ffmpeg-layer.zip" .

echo "Done: $OUTPUT_DIR/ffmpeg-layer.zip"
rm -rf "$BUILD_DIR"
```

### Dev Dependencies

These packages are needed in the development environment (devcontainer) but are NOT deployed to Lambda:

```bash
pip install pytest pytest-cov moto mypy ruff \
    "boto3-stubs[bedrock-runtime,s3,secretsmanager,ssm]" \
    aws-lambda-powertools
```

The devcontainer Dockerfile installs these automatically. They support type checking (`mypy`, `boto3-stubs`), testing (`pytest`, `pytest-cov`, `moto`), and linting (`ruff`).

---

## 9. Deployment Sequence

Steps to deploy the pipeline from scratch, in order:

1. **Run `layers/ffmpeg/build.sh`** to create `ffmpeg-layer.zip`.
2. **Database already created.** The `zerostars` database and all tables (see §6) have been provisioned on the RDS instance.
3. **Build the shared layer** (install psycopg2, zip).
4. **Run `terraform init` and `terraform apply`** in `terraform/`.
5. **Enable Bedrock model access** for Claude and Nova Canvas in the AWS console (this cannot be done via Terraform).
6. **Verify:** Manually trigger the Step Functions state machine to test an end-to-end run.

---

## 10. Structured Logging

All Lambdas use [AWS Lambda Powertools for Python](https://docs.powertools.aws.dev/lambda/python/latest/) for structured JSON logging with automatic CloudWatch integration.

### Logger Module

`lambdas/shared/python/shared/logging.py` exports a single factory function:

```python
from aws_lambda_powertools import Logger


def get_logger(service: str) -> Logger:
    """Return a pre-configured Powertools Logger for the given service."""
    return Logger(service=service, log_uncaught_exceptions=True)
```

### Handler Pattern

Every Lambda handler follows this pattern:

```python
from aws_lambda_powertools.utilities.typing import LambdaContext
from shared.logging import get_logger
from shared.types import PipelineState, DiscoveryOutput

logger = get_logger("discovery")


@logger.inject_lambda_context(clear_state=True)
def lambda_handler(event: PipelineState, context: LambdaContext) -> DiscoveryOutput:
    logger.set_correlation_id(event["metadata"]["execution_id"])
    logger.append_keys(script_attempt=event["metadata"].get("script_attempt", 1))

    logger.info("Starting discovery agent")
    # ... handler logic ...
    logger.info("Discovery complete", extra={"repo_url": result["repo_url"]})
    return result
```

Key points:
- `@logger.inject_lambda_context(clear_state=True)` — automatically adds Lambda context fields and clears custom keys between warm invocations to prevent state leakage.
- `set_correlation_id()` — sets the Step Functions execution ARN as the correlation ID on every log line. This is the primary field for tracing a full pipeline run across all 7 Lambdas.
- `append_keys()` — adds pipeline-specific context (e.g., `script_attempt`) that persists across all log lines in the invocation.

### Discovery Handler — Additional Patterns

The Discovery handler has patterns beyond the basic template:

**Credential caching:** SSM (`/zerostars/db-connection-string`) and Secrets Manager (`zerostars/exa-api-key`) values are fetched once per cold start and cached in module-level globals. This avoids repeated API calls on warm invocations:

```python
_db_connection_string: str | None = None

def _get_db_connection_string() -> str:
    global _db_connection_string
    if _db_connection_string is None:
        ssm = boto3.client("ssm")
        response = ssm.get_parameter(Name="/zerostars/db-connection-string", WithDecryption=True)
        _db_connection_string = response["Parameter"]["Value"]
    return _db_connection_string
```

**Prompt loading:** The system prompt is read from `prompts/discovery.md` using `LAMBDA_TASK_ROOT` (set automatically by the Lambda runtime, falls back to `__file__` parent for local testing).

**Output parsing:** The handler must parse the agent's final text response as JSON. Because Claude models sometimes wrap JSON in markdown fences (~20% of the time despite prompt instructions), the parser strips `` ``` `` fences before `json.loads()`. It then validates:
- All 9 required fields are present
- `star_count` is an integer under 10
- `repo_url` starts with `https://github.com/`

If validation fails, the handler raises `ValueError`, causing the Lambda to fail. Step Functions retries handle transient agent output issues.

**HTTP calls:** The handler uses `urllib.request` from stdlib for both Exa and GitHub API calls — no extra pip dependencies. Each call has a timeout (30s for Exa, 15s for GitHub) to prevent consuming the Lambda's 300s budget.

### Log Level Conventions

| Level | When to use | Examples |
|-------|-------------|---------|
| INFO | Normal flow milestones | `"Starting discovery agent"`, `"Script passed evaluation"`, `"Episode record written to Postgres"` |
| WARNING | Recoverable issues | `"Exa search returned 0 results, retrying with broader query"`, `"Script at 4,950 chars — close to limit"` |
| ERROR | Failures that will cause the Lambda to raise | `"Bedrock invocation failed after retries"`, `"ElevenLabs returned 422"` |
| DEBUG | Detailed data for troubleshooting | Full Bedrock request/response bodies, raw API payloads. Off by default — set `POWERTOOLS_LOG_LEVEL=DEBUG` to enable. |

### Standard Fields

Every structured log line automatically includes these fields:

| Field | Source | Example |
|-------|--------|---------|
| `service` | Logger constructor arg | `"discovery"` |
| `level` | Log call | `"INFO"` |
| `timestamp` | Powertools | `"2025-07-13T13:00:05.123Z"` |
| `message` | Log call | `"Starting discovery agent"` |
| `location` | Powertools | `"handler.py:lambda_handler:42"` |
| `function_name` | `inject_lambda_context` | `"zerostars-discovery"` |
| `function_arn` | `inject_lambda_context` | `"arn:aws:lambda:us-east-1:..."` |
| `function_request_id` | `inject_lambda_context` | `"a1b2c3d4-..."` |
| `cold_start` | `inject_lambda_context` | `true` / `false` |
| `correlation_id` | `set_correlation_id()` | `"arn:aws:states:us-east-1:...:execution:zerostars-pipeline:abc-123"` |
| `xray_trace_id` | Powertools (automatic) | `"1-abc123-def456"` |

### CloudWatch Logs Insights

Trace a full pipeline execution across all Lambdas:

```
filter correlation_id = "arn:aws:states:us-east-1:123456789:execution:zerostars-pipeline:abc-123"
| sort @timestamp asc
| fields service, level, message
```

Find cold starts across all pipeline functions:

```
filter cold_start = true
| stats count(*) by service
```

### Terraform Configuration

Each Lambda function in `lambdas.tf` includes a native `logging_config` block (separate from Powertools — this controls Lambda platform-level log formatting):

```hcl
resource "aws_lambda_function" "discovery" {
  # ... other config ...

  logging_config {
    log_format            = "JSON"
    application_log_level = "INFO"
    system_log_level      = "WARN"
  }

  tracing_config {
    mode = "Active"
  }

  environment {
    variables = {
      POWERTOOLS_SERVICE_NAME = "discovery"
      POWERTOOLS_LOG_LEVEL    = "INFO"
      # ... function-specific env vars ...
    }
  }

  depends_on = [
    aws_iam_role_policy.discovery,                # inline: CloudWatch Logs + function-specific perms
    aws_iam_role_policy_attachment.discovery_xray, # managed: AWSXrayWriteOnlyAccess
    aws_cloudwatch_log_group.discovery
  ]
}
```

The `logging_config` block ensures Lambda system logs (platform start/end/report events, extension logs) are also JSON-formatted — not just Powertools application logs. Both are needed for fully structured CloudWatch output.

> **Known Terraform issue:** The AWS provider has a bug (hashicorp/terraform-provider-aws#42181) where `log_format = "JSON"` causes perpetual plan drift. If your provider version is affected, add `lifecycle { ignore_changes = [logging_config] }` to each Lambda resource as a workaround.

The `tracing_config { mode = "Active" }` block enables X-Ray active tracing on each Lambda. This populates the `_X_AMZN_TRACE_ID` environment variable that Powertools reads to include `xray_trace_id` in every structured log line. Without this block, the `xray_trace_id` field silently omits from logs. Each Lambda execution role must have `xray:PutTraceSegments` and `xray:PutTelemetryRecords` permissions — attach the `AWSXrayWriteOnlyAccess` managed policy or an equivalent inline policy.

### Error Visibility

Every failure mode is covered by CloudWatch:

| Failure type | What captures it | Where it appears |
|-------------|-----------------|-----------------|
| Application error (your code raises) | Powertools Logger (`log_uncaught_exceptions=True`) | CloudWatch Logs, structured JSON with full stack trace |
| Lambda timeout | Lambda platform | CloudWatch Logs (JSON, via `logging_config`), plus `REPORT` line shows `Status: timeout` |
| Import error / bad deployment package | Lambda platform (before your code runs) | CloudWatch Logs (JSON, via `logging_config.system_log_level = "WARN"`) |
| Bedrock throttling / transient failure | Step Functions Retry block | Step Functions execution history (visible in console), plus the Lambda's error log before retry |
| Producer FAIL verdict (not an error) | Normal application log | CloudWatch Logs (`logger.info("Script failed evaluation", ...)`) + Step Functions Choice state transition |
| Pipeline-level failure (max retries exceeded) | Step Functions `PipelineFailed` Fail state | Step Functions execution history, CloudWatch Events |

The `correlation_id` (Step Functions execution ARN) on every log line lets you trace a full pipeline run across all 7 Lambdas with a single CloudWatch Logs Insights query (see above).

### Site Lambda

The site Lambda is not part of the Step Functions pipeline and has no `execution_id` to use as a correlation ID. Instead, use the Lambda request ID (automatically included by `inject_lambda_context`) for tracing. The handler pattern is the same minus the `set_correlation_id` call.

---

## 11. Type Checking

All Python code uses strict type annotations enforced by mypy. TypedDict definitions in the shared layer provide compile-time validation that Lambda inputs and outputs match the interface contracts from Section 2.

### mypy Configuration

In `pyproject.toml`:

```toml
[tool.mypy]
python_version = "3.12"
strict = true
warn_unused_ignores = true

[[tool.mypy.overrides]]
module = "psycopg2.*"
ignore_missing_imports = true

[[tool.mypy.overrides]]
module = "aws_lambda_powertools.*"
ignore_missing_imports = true
```

`strict = true` enables: `disallow_untyped_defs`, `disallow_any_generics`, `warn_return_any`, `no_implicit_reexport`, `strict_equality`, and all other strict flags. This means every function must have full parameter and return type annotations.

Run locally: `mypy lambdas/` with `PYTHONPATH=lambdas/shared/python`.

### TypedDict Definitions

`lambdas/shared/python/shared/types.py` defines typed interfaces matching Section 2's contracts exactly. Every Lambda imports its input/output types from here.

```python
from __future__ import annotations

from typing import NotRequired, TypedDict


class PipelineMetadata(TypedDict):
    execution_id: str
    script_attempt: int


class DiscoveryOutput(TypedDict):
    repo_url: str
    repo_name: str
    repo_description: str
    developer_github: str
    star_count: int
    language: str
    discovery_rationale: str
    key_files: list[str]
    technical_highlights: list[str]


class NotableRepo(TypedDict):
    name: str
    description: str
    stars: int
    language: str


class ResearchOutput(TypedDict):
    developer_name: str
    developer_github: str
    developer_bio: str
    public_repos_count: int
    notable_repos: list[NotableRepo]
    commit_patterns: str
    technical_profile: str
    interesting_findings: list[str]
    hiring_signals: list[str]


class ScriptOutput(TypedDict):
    text: str
    character_count: int
    segments: list[str]
    featured_repo: str
    featured_developer: str
    cover_art_suggestion: str


class ProducerOutput(TypedDict):
    """Unified producer output. PASS includes `notes`; FAIL includes `feedback` and `issues`."""
    verdict: str
    score: int
    notes: NotRequired[str]
    feedback: NotRequired[str]
    issues: NotRequired[list[str]]


class CoverArtOutput(TypedDict):
    s3_key: str
    prompt_used: str


class TTSOutput(TypedDict):
    s3_key: str
    duration_seconds: int
    character_count: int


class PostProductionOutput(TypedDict):
    s3_mp4_key: str
    episode_id: int
    air_date: str


class PipelineState(TypedDict, total=False):
    """Full accumulated state object passed through Step Functions.

    Each key is populated by ResultPath as the pipeline progresses.
    total=False because early Lambdas see a partial state.
    """
    metadata: PipelineMetadata
    discovery: DiscoveryOutput
    research: ResearchOutput
    script: ScriptOutput
    producer: ProducerOutput
    cover_art: CoverArtOutput
    tts: TTSOutput
    post_production: PostProductionOutput
```

### Handler Type Annotation Pattern

Every Lambda handler is annotated with its specific input/output types:

```python
from aws_lambda_powertools.utilities.typing import LambdaContext
from shared.types import PipelineState, DiscoveryOutput


def lambda_handler(event: PipelineState, context: LambdaContext) -> DiscoveryOutput:
    ...
```

The site Lambda is different — it receives a Lambda Function URL event, not pipeline state:

```python
def lambda_handler(event: dict[str, object], context: LambdaContext) -> dict[str, object]:
    ...
```

### `invoke_with_tools` Strict Type Annotations

The `invoke_with_tools` signature shown in §5 uses `list[dict]` and `Callable[[str, dict], str]` for brevity. Under mypy strict, the actual implementation in `shared/bedrock.py` must use these precise types:

```python
from __future__ import annotations

from collections.abc import Callable
from typing import Any

# The Bedrock Messages API tool definition schema. Each tool is a dict
# with "name", "description", and "input_schema" keys. We use
# dict[str, Any] because the input_schema sub-object has recursive
# JSON Schema structure that cannot be expressed as a TypedDict without
# losing practical usability.
ToolDefinition = dict[str, Any]  # type alias

# The tool_executor callback receives (tool_name, tool_input) and must
# return a JSON-encoded string. tool_input is dict[str, Any] because
# the shape depends on the tool's input_schema.
ToolExecutor = Callable[[str, dict[str, Any]], str]

DEFAULT_MODEL_ID: str = "us.anthropic.claude-sonnet-4-6"


def invoke_model(
    user_message: str,
    system_prompt: str,
    model_id: str = DEFAULT_MODEL_ID,
    max_tokens: int = MAX_TOKENS,
) -> str: ...


def invoke_with_tools(
    user_message: str,
    system_prompt: str,
    tools: list[ToolDefinition],
    tool_executor: ToolExecutor,
    model_id: str = DEFAULT_MODEL_ID,
    max_tokens: int = MAX_TOKENS,
    max_turns: int = 25,
) -> str: ...
```

The `ToolDefinition` and `ToolExecutor` type aliases are module-level exports so handler code can import them for annotation:

```python
from shared.bedrock import invoke_with_tools, ToolDefinition, ToolExecutor
```

### Discovery Handler Internal Function Signatures

The Discovery handler (`lambdas/discovery/handler.py`) contains private helper functions that must all have full type annotations for mypy strict. The exact signatures:

```python
from __future__ import annotations

import json
import os
import subprocess
from typing import Any

import boto3
from aws_lambda_powertools.utilities.typing import LambdaContext

from shared.bedrock import ToolDefinition, ToolExecutor, invoke_with_tools
from shared.logging import get_logger
from shared.types import DiscoveryOutput, PipelineState

logger = get_logger("discovery")

# --- Module-level cached credentials ---
_db_connection_string: str | None = None
_exa_api_key: str | None = None

# --- Tool definitions (module-level constant) ---
TOOL_DEFINITIONS: list[ToolDefinition] = [...]  # populated per §5


def _get_db_connection_string() -> str:
    """Fetch DB connection string from SSM, cached across warm starts."""
    ...


def _get_exa_api_key() -> str:
    """Fetch Exa API key from Secrets Manager, cached across warm starts."""
    ...


def _load_system_prompt() -> str:
    """Read prompts/discovery.md from disk. Uses LAMBDA_TASK_ROOT."""
    ...


def _execute_exa_search(tool_input: dict[str, Any]) -> dict[str, Any]:
    """Call Exa API. Maps snake_case keys to camelCase. Returns parsed JSON."""
    ...


def _execute_query_postgres(tool_input: dict[str, Any]) -> dict[str, str]:
    """Run read-only SQL via psql subprocess. Returns {"rows": ...} or {"error": ...}."""
    ...


def _execute_get_github_repo(tool_input: dict[str, Any]) -> dict[str, Any]:
    """Call GitHub REST API. Returns curated field subset."""
    ...


def _execute_tool(tool_name: str, tool_input: dict[str, Any]) -> str:
    """Dispatch to the correct tool function, return JSON string."""
    ...


def _parse_discovery_output(text: str) -> DiscoveryOutput:
    """Parse agent text response to DiscoveryOutput. Strips markdown fences, validates."""
    ...


@logger.inject_lambda_context(clear_state=True)
def lambda_handler(event: PipelineState, context: LambdaContext) -> DiscoveryOutput:
    ...
```

**Key typing notes:**

- `_execute_exa_search` returns `dict[str, Any]` because the Exa response contains nested lists of result objects with mixed-type values.
- `_execute_query_postgres` returns `dict[str, str]` — always either `{"rows": "<stdout>"}` or `{"error": "<stderr>"}`. The narrower return type (vs `dict[str, Any]`) is intentional and passes strict checks.
- `_execute_get_github_repo` returns `dict[str, Any]` because the curated GitHub response includes `str`, `int`, `list[str]`, and `None` values.
- `_execute_tool` calls `json.dumps()` on the return value of the tool functions, so its return type is `str`.
- `_parse_discovery_output` returns `DiscoveryOutput` (a TypedDict), which provides compile-time field validation at every call site.
- The module-level globals `_db_connection_string` and `_exa_api_key` are typed as `str | None` and narrowed inside their getter functions via the `global` + `if is None` pattern.
- `TOOL_DEFINITIONS` is typed as `list[ToolDefinition]` (alias for `list[dict[str, Any]]`).

### Typing Conventions

- Every function in shared modules (`bedrock.py`, `db.py`, `s3.py`, `logging.py`) must have full type annotations — parameters and return types.
- No bare `Any` without an explicit `# type: ignore[...]` comment explaining why.
- `boto3-stubs` (already in devcontainer) provides typed clients: `mypy_boto3_bedrock_runtime`, `mypy_boto3_s3`, `mypy_boto3_secretsmanager`, `mypy_boto3_ssm`. The `ssm` extra is needed for the Discovery handler's SSM `GetParameter` call.
- Use `from __future__ import annotations` at the top of every file for PEP 604 union syntax (`X | Y`) and forward references.

---

## 12. Testing

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

---

## 13. CI Pipeline

GitHub Actions runs linting, type checking, and unit tests on every push and pull request.

### Workflow File

`.github/workflows/ci.yml`:

```yaml
name: CI

on:
  push:
  pull_request:

jobs:
  lint-and-test:
    runs-on: ubuntu-latest

    steps:
      - uses: actions/checkout@v4

      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"

      - name: Install dependencies
        run: |
          pip install --upgrade pip
          pip install ruff mypy pytest pytest-cov "moto[s3]" boto3 \
            psycopg2-binary jinja2 aws-lambda-powertools \
            "boto3-stubs[bedrock-runtime,s3,secretsmanager,ssm]"

      - uses: hashicorp/setup-terraform@v3

      - name: Terraform validate
        run: |
          cd terraform
          terraform init -backend=false
          terraform validate

      - name: Ruff lint
        run: ruff check .

      - name: Ruff format check
        run: ruff format --check .

      - name: mypy type check
        run: mypy lambdas/
        env:
          PYTHONPATH: lambdas/shared/python

      - name: Unit tests
        run: pytest tests/unit/ -v --tb=short --cov=lambdas --cov-report=term-missing
        env:
          PYTHONPATH: lambdas/shared/python

  integration:
    runs-on: ubuntu-latest
    if: github.event_name == 'workflow_dispatch'

    permissions:
      id-token: write
      contents: read

    steps:
      - uses: actions/checkout@v4

      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"

      - name: Configure AWS credentials
        uses: aws-actions/configure-aws-credentials@v4
        with:
          role-to-assume: ${{ secrets.AWS_ROLE_ARN }}
          aws-region: us-east-1

      - name: Install dependencies
        run: |
          pip install --upgrade pip
          pip install pytest boto3 psycopg2-binary aws-lambda-powertools \
            "boto3-stubs[bedrock-runtime,s3,secretsmanager,ssm]"

      - name: Integration tests
        run: pytest tests/integration/ -v -m integration
        env:
          PYTHONPATH: lambdas/shared/python
          DB_CONNECTION_STRING: ${{ secrets.DEV_DB_CONNECTION_STRING }}
```

### Ruff Configuration

In `pyproject.toml`:

```toml
[tool.ruff]
target-version = "py312"
line-length = 100

[tool.ruff.lint]
select = ["E", "F", "I", "N", "W", "UP"]

[tool.ruff.format]
quote-style = "double"
```

Rule sets: `E` (pycodestyle errors), `F` (pyflakes), `I` (isort import ordering), `N` (pep8-naming), `W` (pycodestyle warnings), `UP` (pyupgrade — modernize syntax for Python 3.12).

---

## Appendix A: Constants

| Constant | Value |
|----------|-------|
| Project prefix | `zerostars` |
| S3 bucket name pattern | `{project_prefix}-episodes-{account_id}` |
| Lambda runtime | `python3.12` |
| Lambda timeout (pipeline) | 300 seconds (5 min) |
| Lambda timeout (site) | 30 seconds |
| Lambda memory (pipeline) | 512 MB |
| Lambda memory (post-production) | 1024 MB (ffmpeg needs more) |
| Lambda memory (site) | 256 MB |
| CloudWatch log retention | 14 days |
| CloudFront TTL | 3600 seconds (1 hour) |
| EventBridge schedule | `cron(0 9 ? * SUN *)` with `schedule_expression_timezone = "America/New_York"` |
| Bedrock Claude model ID | `us.anthropic.claude-sonnet-4-6` |
| Bedrock Nova Canvas model ID | `amazon.nova-canvas-v1:0` |
| ElevenLabs model | `eleven_v3` |
| ElevenLabs output format | `mp3_44100_128` |
| Discovery star threshold | Under 10 (hard ceiling, verified via GitHub API) |
| SSM DB connection string path | `/zerostars/db-connection-string` (SecureString, already provisioned) |
| Script character limit | 5,000 (target 4,000–4,500) |
| Max script retry attempts | 3 |
| Tags | `project = "0-stars-podcast"`, `managed_by = "terraform"` |
| Powertools log level | `INFO` |
| Lambda `logging_config` log format | `JSON` |
| Lambda `logging_config` system log level | `WARN` |
| mypy mode | `strict` |
| pytest markers | `integration` |
| Ruff line length | 100 |
| CI Python version | `3.12` |
