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
│   └── ffmpeg/
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
| `tests/integration/test_db_live.py` | Integration tests hitting real Postgres. Marked `@pytest.mark.integration`. |

### Other Files

| File | Purpose |
|------|---------|
| `layers/ffmpeg/build.sh` | Shell script that downloads a prebuilt Lambda-compatible ffmpeg binary (from `johnvansickle.com/ffmpeg` — the standard source for static ffmpeg builds), creates the Lambda Layer directory structure (`bin/ffmpeg`), and zips it. Output: `layers/ffmpeg/ffmpeg-layer.zip`. Run once manually before `terraform apply`. |
| `sql/schema.sql` | DDL for all three tables: `episodes`, `episode_metrics`, `featured_developers`. Includes column types, constraints, foreign keys, and indices. Run manually against the RDS instance before first pipeline execution. |
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

**Reads from Postgres:**
- `featured_developers` — all rows, to exclude previously featured developers from search
- `episodes` + `episode_metrics` — joined, to identify which project types (language, category) drove higher engagement and bias search accordingly

**Returns:** (placed at `$.discovery` by Step Functions)

```json
{
  "repo_url": "https://github.com/user/repo",
  "repo_name": "repo-name",
  "repo_description": "Short description from GitHub",
  "developer_github": "username",
  "star_count": 12,
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
| Discovery | `bedrock:InvokeModel`, Secrets Manager read (Exa key) |
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

# With tool use (Discovery, Research)
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
# Handle tool_use content blocks, execute tools, send results back in a loop
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
      "category": {"type": "string", "enum": ["github", "general"], "description": "Search category"},
      "num_results": {"type": "integer", "description": "Number of results to return (max 10)"},
      "start_published_date": {"type": "string", "description": "ISO date, filter results after this date"},
      "exclude_text": {"type": "string", "description": "Exclude results containing this text"}
    },
    "required": ["query"]
  }
}
```

When Bedrock returns a `tool_use` block for `exa_search`, the Lambda executes the actual Exa API call:

```
POST https://api.exa.ai/search
Headers:
  Content-Type: application/json
  x-api-key: <from Secrets Manager>

Request body:
{
  "query": "...",
  "category": "github",
  "numResults": 10,
  "startPublishedDate": "2024-01-01",
  "contents": {
    "text": true
  }
}
```

### GitHub API

Used by: Research Lambda (via Bedrock tool use).

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
        "sort": {"type": "string", "enum": ["stars", "updated", "created"]},
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
  }
]
```

API endpoints used when executing tool calls:
- `GET https://api.github.com/users/{username}`
- `GET https://api.github.com/users/{username}/repos?sort={sort}&per_page={per_page}`
- `GET https://api.github.com/repos/{owner}/{repo}`
- `GET https://api.github.com/repos/{owner}/{repo}/readme` (returns base64-encoded content)

---

## 6. Database Schema

DDL for `sql/schema.sql`. Run manually against the RDS Postgres instance before first pipeline execution.

```sql
-- 0 Stars, 10/10 — Database Schema
-- Run against the existing RDS Postgres instance.

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

```markdown
TODO: Discovery agent system prompt.

Key content to include:
- Role: You are the Discovery agent for "0 Stars, 10/10"
- Search criteria: solo developers, hobby projects, under ~50 stars, not AI/ML tools or infrastructure, recent (2024-2025)
- Prioritize: charm, personality, interesting technical choices, good README
- Use the exa_search tool to find candidates
- You will receive episode history (previously featured developers) and episode metrics (what performed well) as context
- Use metrics to bias search: if episodes about CLI tools got more engagement, weight toward CLI tools
- Never re-feature a developer already in the featured_developers list
- Output: select ONE repo and explain why
- Return structured output matching the discovery interface contract
```

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

Discovery, Research, Script, Producer, Cover Art — these only need `boto3` (pre-installed on Lambda) and the shared layer. No additional dependencies.

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
    "boto3-stubs[bedrock-runtime,s3,secretsmanager]" \
    aws-lambda-powertools
```

The devcontainer Dockerfile installs these automatically. They support type checking (`mypy`, `boto3-stubs`), testing (`pytest`, `pytest-cov`, `moto`), and linting (`ruff`).

---

## 9. Deployment Sequence

Steps to deploy the pipeline from scratch, in order:

1. **Run `layers/ffmpeg/build.sh`** to create `ffmpeg-layer.zip`.
2. **Run `sql/schema.sql`** against the RDS Postgres instance.
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

### Typing Conventions

- Every function in shared modules (`bedrock.py`, `db.py`, `s3.py`, `logging.py`) must have full type annotations — parameters and return types.
- No bare `Any` without an explicit `# type: ignore[...]` comment explaining why.
- `boto3-stubs` (already in devcontainer) provides typed clients: `mypy_boto3_bedrock_runtime`, `mypy_boto3_s3`, `mypy_boto3_secretsmanager`.
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
    with patch("shared.bedrock.boto3.client") as mock:
        client = MagicMock()
        mock.return_value = client
        yield client


@pytest.fixture
def mock_db_connection():
    with patch("shared.db.psycopg2.connect") as mock:
        conn = MagicMock()
        cursor = MagicMock()
        conn.cursor.return_value = cursor
        mock.return_value = conn
        yield conn


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
| Bedrock | `unittest.mock` — patch `boto3.client("bedrock-runtime")` return values. moto does not support Bedrock. | Real Bedrock calls with dev AWS credentials. |
| S3 | `moto` `@mock_aws` decorator — creates in-memory S3. | Real S3 bucket in dev account with `test/` key prefix. |
| Postgres | `unittest.mock` — patch `psycopg2.connect`, mock cursor `fetchall`/`execute`. | Real dev RDS instance. |
| Exa API | `unittest.mock` — patch `urllib.request.urlopen`. | Skip — costs money per query. |
| ElevenLabs | `unittest.mock` — patch `urllib.request.urlopen`. | Skip — costs money per call. |
| GitHub API | `unittest.mock` — patch `urllib.request.urlopen`. | Real public API (unauthenticated, 60 req/hour). |

### Unit Test Pattern

Example for the Discovery handler:

```python
import json
from unittest.mock import MagicMock, patch


def test_discovery_returns_valid_output(pipeline_metadata, mock_bedrock_client, mock_db_connection, lambda_context):
    """Discovery handler returns output matching DiscoveryOutput TypedDict."""
    # Arrange: no previously featured developers
    mock_db_connection.cursor.return_value.fetchall.return_value = []

    # Arrange: mock Bedrock response with a valid discovery result
    mock_bedrock_client.invoke_model.return_value = {
        "body": MagicMock(read=MagicMock(return_value=json.dumps({
            "content": [{"type": "text", "text": json.dumps({
                "repo_url": "https://github.com/someone/something",
                "repo_name": "something",
                "repo_description": "A cool project",
                "developer_github": "someone",
                "star_count": 3,
                "language": "Go",
                "discovery_rationale": "Interesting CLI tool.",
                "key_files": ["main.go"],
                "technical_highlights": ["Single-binary design"],
            })}],
            "stop_reason": "end_turn",
        }).encode()))
    }

    from lambdas.discovery.handler import lambda_handler

    # Act
    result = lambda_handler({"metadata": pipeline_metadata}, lambda_context)

    # Assert: all required DiscoveryOutput keys present with correct types
    assert isinstance(result["repo_url"], str)
    assert result["repo_url"].startswith("https://github.com/")
    assert isinstance(result["star_count"], int)
    assert isinstance(result["key_files"], list)
    assert isinstance(result["technical_highlights"], list)


def test_discovery_excludes_featured_developers(pipeline_metadata, mock_bedrock_client, mock_db_connection, lambda_context):
    """Discovery handler passes featured developers list to Bedrock for exclusion."""
    mock_db_connection.cursor.return_value.fetchall.return_value = [
        ("previously-featured-dev",),
    ]
    # ... assert the system prompt or tool context includes the exclusion list
```

### Integration Test Pattern

```python
import pytest


@pytest.mark.integration
def test_bedrock_invoke_model():
    """Verify Bedrock Claude invocation works with real credentials."""
    from shared.bedrock import invoke_model

    result = invoke_model(
        prompt="Respond with exactly: PING",
        system_prompt="You are a test helper. Respond with exactly what is asked.",
    )
    assert "PING" in result
```

Integration tests are marked with `@pytest.mark.integration` and excluded from CI by default. They require real AWS credentials (configured via environment or `~/.aws`).

**Resource isolation:** Integration tests must use unique prefixes for S3 keys and DB test data (e.g., the GitHub Actions run ID or commit SHA) to prevent conflicts when multiple CI runs execute in parallel. Clean up test resources in a `finally` block or pytest `teardown` fixture.

### Per-Handler Test Requirements

Each handler's unit test file must verify:

| Handler | Required test cases |
|---------|-------------------|
| Discovery | Output matches `DiscoveryOutput` shape; excludes previously featured developers; handles empty search results |
| Research | Output matches `ResearchOutput` shape; handles missing GitHub bio; handles user with zero repos |
| Script | Output matches `ScriptOutput` shape; `character_count` under 5,000; all 6 segments in `segments` list; incorporates producer feedback on retry (`script_attempt > 1`) |
| Producer | Returns `verdict: "PASS"` or `"FAIL"` with correct fields; FAIL includes `feedback` and `issues`; character count over 5,000 triggers FAIL |
| Cover Art | Output matches `CoverArtOutput` shape; S3 key follows `episodes/{execution_id}/cover.png` pattern |
| TTS | Output matches `TTSOutput` shape; correctly parses `**Hype:**`, `**Roast:**`, `**Phil:**` labels; raises exception on malformed script lines |
| Post-Production | Output matches `PostProductionOutput` shape; writes to `episodes` table; writes to `featured_developers` table |
| Site | Returns valid HTML with status 200; handles empty episodes table |
| Shared: bedrock | `invoke_model` returns parsed text; `invoke_with_tools` handles tool-use loop; retries on throttling |
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
            "boto3-stubs[bedrock-runtime,s3,secretsmanager]"

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
            "boto3-stubs[bedrock-runtime,s3,secretsmanager]"

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
