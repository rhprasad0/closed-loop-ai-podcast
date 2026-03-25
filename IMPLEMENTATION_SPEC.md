# Implementation Spec: "0 Stars, 10/10" Podcast Pipeline

This is the single source of truth for implementing the podcast pipeline. It contains everything needed to build the system in one pass: every file to create, every interface between components, the exact state machine definition, Terraform resource ownership, external API contracts, and prompt content.

**Target runtime:** Python 3.12 on AWS Lambda, Terraform for IaC.

---

## 1. File Manifest

Every file below must be created. No other files should be created.

```
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
│   │           └── s3.py
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
| `terraform/scheduling.tf` | EventBridge Scheduler rule (weekly, Sunday 9 AM ET), IAM role for scheduler, target pointing to state machine ARN |
| `terraform/s3.tf` | S3 bucket for episode assets (MP3, MP4, cover art PNGs). Bucket policy for CloudFront access. |
| `terraform/site.tf` | Site Lambda function URL, CloudFront distribution (Function URL as origin, ~1 hour TTL), Route53 A record for `podcast.ryans-lab.click` |
| `terraform/secrets.tf` | `aws_secretsmanager_secret` + `aws_secretsmanager_secret_version` for ElevenLabs and Exa API keys |

### Lambda Source Files

| File | Purpose |
|------|---------|
| `lambdas/shared/python/shared/__init__.py` | Package init. Re-exports `bedrock`, `db`, `s3` modules for `from shared import bedrock, db, s3` usage. |
| `lambdas/shared/python/shared/bedrock.py` | Bedrock client wrapper. Functions: `invoke_model(prompt, system_prompt, model_id)`, `invoke_with_tools(prompt, system_prompt, tools, model_id)`. Default model: Claude on Bedrock. Handles retries for throttling. |
| `lambdas/shared/python/shared/db.py` | Postgres connection helper. Uses `psycopg2` with `sslmode=require`. Functions: `get_connection()`, `query(sql, params)` (returns rows), `execute(sql, params)` (returns rowcount). Connection string from `DB_CONNECTION_STRING` env var. |
| `lambdas/shared/python/shared/s3.py` | S3 helper functions: `upload_bytes(bucket, key, data, content_type)`, `upload_file(bucket, key, filepath, content_type)`, `generate_presigned_url(bucket, key, expiry)`. Bucket name from `S3_BUCKET` env var. |
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
- **Retry on transient errors**: Every Lambda task has a `Retry` block for `States.TaskFailed` with exponential backoff (1s, 2s, 4s) and max 3 attempts. This handles Bedrock throttling, API timeouts, etc.
- **Catch**: Each Lambda has a `Catch` block that routes to a `HandleError` state for logging before entering the `PipelineFailed` Fail state.
- **Evaluator loop**: The Producer Lambda returns a verdict. A Choice state checks `$.producer.verdict`. On FAIL, if `$.metadata.script_attempt < 3`, a Pass state increments the counter and execution returns to the Script task. On FAIL with attempts >= 3, execution moves to PipelineFailed.
- **Script retry input**: When looping back to Script, the state object includes `$.producer.feedback` from the failed evaluation. The Script Lambda reads this and incorporates it.

### ASL Definition

```json
TODO: Full ASL JSON to be written. Will include:
- Comment and StartAt
- All Task states with Resource ARNs (referenced via Terraform interpolation)
- ResultPath configuration per state
- Retry and Catch blocks
- Choice state for evaluator verdict
- Pass state for attempt counter increment
- Fail state for max retries exceeded
- Succeed state
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

### `variables.tf`

| Variable | Type | Description |
|----------|------|-------------|
| `elevenlabs_api_key` | `string` (sensitive) | ElevenLabs API key |
| `exa_api_key` | `string` (sensitive) | Exa Search API key |
| `db_connection_string` | `string` (sensitive) | Postgres connection string (`postgresql://user:pass@host:5432/dbname?sslmode=require`) |
| `domain_name` | `string` | Domain for the podcast site (e.g., `podcast.ryans-lab.click`) |
| `project_prefix` | `string` | Resource name prefix, default `zerostars` |

### `lambdas.tf`

| Resource | Type | Notes |
|----------|------|-------|
| Shared Lambda Layer | `aws_lambda_layer_version` | Source: `lambdas/shared/` |
| ffmpeg Lambda Layer | `aws_lambda_layer_version` | Source: `layers/ffmpeg/ffmpeg-layer.zip` (built by `build.sh`) |
| Per-Lambda (×8): | | |
| — Deployment package | `data "archive_file"` | Zips `handler.py` + `prompts/` dir |
| — Function | `aws_lambda_function` | Python 3.12, layers attached, env vars set |
| — IAM role | `aws_iam_role` | Lambda assume-role trust policy |
| — IAM policy | `aws_iam_role_policy` | Least-privilege: CloudWatch Logs + function-specific permissions |
| — Log group | `aws_cloudwatch_log_group` | 14-day retention |

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

### `s3.tf`

| Resource | Type |
|----------|------|
| Episode assets bucket | `aws_s3_bucket` |
| Bucket public access block | `aws_s3_bucket_public_access_block` |
| Bucket policy | `aws_s3_bucket_policy` (CloudFront OAC access) |

### `site.tf`

| Resource | Type |
|----------|------|
| Site Lambda Function URL | `aws_lambda_function_url` |
| CloudFront distribution | `aws_cloudfront_distribution` |
| CloudFront OAC | `aws_cloudfront_origin_access_control` (for S3) |
| Route53 A record | `aws_route53_record` (alias to CloudFront) |
| ACM certificate | `aws_acm_certificate` + validation (for HTTPS) |

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
    modelId="us.anthropic.claude-sonnet-4-20250514-v1:0",
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
    modelId="us.anthropic.claude-sonnet-4-20250514-v1:0",
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

The shared layer at `lambdas/shared/` provides `bedrock.py`, `db.py`, and `s3.py`. It also needs `psycopg2` for Postgres access.

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
| EventBridge schedule | `cron(0 13 ? * SUN *)` (9 AM ET = 1 PM UTC) |
| Bedrock Claude model ID | `us.anthropic.claude-sonnet-4-20250514-v1:0` |
| Bedrock Nova Canvas model ID | `amazon.nova-canvas-v1:0` |
| ElevenLabs model | `eleven_v3` |
| ElevenLabs output format | `mp3_44100_128` |
| Script character limit | 5,000 (target 4,000–4,500) |
| Max script retry attempts | 3 |
| Tags | `project = "0-stars-podcast"`, `managed_by = "terraform"` |
