> Part of the [Implementation Spec](../../IMPLEMENTATION_SPEC.md)

# MCP Server

An MCP (Model Context Protocol) server that provides an interactive control plane for the podcast pipeline. Episodes are triggered, observed, and managed through MCP tools from claude.ai. The server runs as a Lambda behind a Function URL using Streamable HTTP transport.

This spec covers the tool surface, resource definitions, Lambda architecture, and Terraform changes.

## Transport and Hosting

The MCP server is a single Lambda with a Function URL. Each MCP interaction from claude.ai is a stateless HTTP POST — one Lambda invocation per request. No long-lived connections or session state.

| Property | Value |
|----------|-------|
| Runtime | Python 3.12 |
| Handler | `handler.lambda_handler` |
| Memory | 512 MB |
| Timeout | 300 seconds |
| Function URL auth | `AWS_IAM` |
| Function URL invoke mode | `RESPONSE_STREAM` |
| Transport | Streamable HTTP (MCP spec 2025-03-26) |
| Lambda Layer | Shared layer (psycopg2, powertools, shared utils) |

**Why Streamable HTTP, not SSE:** The Streamable HTTP transport works as stateless HTTP POST requests where each request gets a response (optionally streamed). This maps directly to Lambda Function URL invocations — each POST is one Lambda execution, no session state needed. The `mcp` Python SDK supports this via `StreamableHTTPServerTransport`.

**Why `RESPONSE_STREAM`:** Lambda Function URLs with `invoke_mode = "RESPONSE_STREAM"` use the `InvokeWithResponseStream` API, supporting up to 200 MB streamed responses. This is required for SSE event streaming in the Streamable HTTP transport. Without it, Lambda buffers the entire response, breaking SSE for any tool call that returns incremental events.

**Why Lambda over ECS/Fargate:** The MCP server handles maybe 20-50 requests per week. Lambda's pay-per-invocation pricing (effectively free at this scale) beats Fargate's minimum ~$10/month for always-on. Cold start adds 1-2 seconds, acceptable for an interactive control plane.

## Authentication

The Function URL uses `auth_type = "AWS_IAM"`. Claude.ai signs requests with SigV4 using AWS credentials configured in the remote MCP server settings. A resource policy on the Function URL restricts invocation to a specific IAM principal (`var.mcp_allowed_principal`).

No API keys, OAuth, or custom auth. IAM auth provides request signing, integrity protection, and HTTPS-only transport out of the box.

---

## MCP Tools

### Pipeline Control

#### `start_pipeline`

Start a new full pipeline execution.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| — | — | — | No parameters. |

**Returns:**

```json
{
  "execution_arn": "arn:aws:states:us-east-1:123456789:execution:zerostars-pipeline:mcp-20250713T090000Z",
  "start_date": "2025-07-13T09:00:00.000Z"
}
```

**AWS calls:** `states:StartExecution` on the state machine ARN. Execution name is auto-generated as `mcp-{iso-timestamp}` (max 80 chars, alphanumeric plus `-` and `_` only).

---

#### `stop_pipeline`

Stop a running pipeline execution. The execution terminates with ABORTED status.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `execution_arn` | string | yes | ARN of the execution to stop. |
| `cause` | string | no | Why you are stopping it. Recorded in execution history. Max 32,768 chars. |

**Returns:**

```json
{
  "status": "ABORTED",
  "stop_date": "2025-07-13T09:05:00.000Z"
}
```

**AWS calls:** `states:StopExecution` with `executionArn` and optionally `error = "MCP.UserAborted"` and `cause`.

---

#### `get_execution_status`

Get the current status and accumulated state of a pipeline execution.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `execution_arn` | string | yes | The execution to inspect. |

**Returns:**

```json
{
  "status": "RUNNING",
  "name": "mcp-20250713T090000Z",
  "current_step": "Script",
  "start_date": "2025-07-13T09:00:00.000Z",
  "stop_date": null,
  "state_object": {
    "metadata": { "execution_id": "...", "script_attempt": 1 },
    "discovery": { "..." : "..." },
    "research": { "..." : "..." }
  },
  "error": null,
  "cause": null
}
```

`state_object` contains the full accumulated pipeline state reflecting how far the execution progressed. For completed executions, this is the `output` field from `DescribeExecution`. For running executions, it is the `input` field (which contains state accumulated so far).

`current_step` is determined by calling `states:GetExecutionHistory` with `reverseOrder=true, maxResults=5` and finding the most recent `TaskStateEntered` event.

**AWS calls:** `states:DescribeExecution`, and for RUNNING executions also `states:GetExecutionHistory`.

---

#### `list_executions`

List recent pipeline executions.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `status_filter` | string | no | One of: `RUNNING`, `SUCCEEDED`, `FAILED`, `ABORTED`, `TIMED_OUT`. Omit for all. |
| `max_results` | integer | no | Default 10, max 50. |

**Returns:**

```json
{
  "executions": [
    {
      "execution_arn": "arn:aws:states:...",
      "name": "mcp-20250713T090000Z",
      "status": "SUCCEEDED",
      "start_date": "2025-07-13T09:00:00.000Z",
      "stop_date": "2025-07-13T09:12:34.000Z"
    }
  ]
}
```

**AWS calls:** `states:ListExecutions` with `stateMachineArn` and optional `statusFilter`. Results are sorted by time, most recent first (API default).

---

#### `retry_from_step`

Retry a failed execution from a specific step. Creates a new execution carrying forward the accumulated state from the failed run up to the retry point.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `failed_execution_arn` | string | yes | ARN of the failed execution. |
| `retry_from` | string | yes | One of: `Discovery`, `Research`, `Script`, `Producer`, `CoverArt`, `TTS`, `PostProduction`. |

**Returns:**

```json
{
  "new_execution_arn": "arn:aws:states:...:mcp-retry-20250713T091500Z",
  "carried_state_keys": ["discovery", "research"],
  "retry_from": "Script"
}
```

**Implementation:** Calls `states:DescribeExecution` on the failed run to extract the state object, then calls `states:StartExecution` with that state plus `metadata.resume_from` set to the retry step name. The state machine's `ResumeRouter` Choice state (see [ASL Modification](#asl-modification-resumerouter)) routes to the correct step.

---

### Agent Invocation

All agent invocation tools use direct synchronous Lambda invoke (`lambda:InvokeFunction` with `InvocationType=RequestResponse`). The MCP Lambda constructs a synthetic `PipelineState` matching the schemas in [Interface Contracts](./interface-contracts.md). Results return directly in the conversation — no polling needed.

**Why direct invoke, not Step Functions:** Step Functions executions are asynchronous. Direct invoke is synchronous and returns within the Lambda timeout, giving an interactive experience. The trade-off is that direct invokes bypass Step Functions retry/catch logic, but that is acceptable for interactive exploration.

#### `invoke_discovery`

Run the Discovery agent to find an underrated GitHub repo.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| — | — | — | No parameters. Queries Postgres internally to exclude previously featured developers. |

**Returns:** Full Discovery output per [Interface Contracts](./interface-contracts.md#discovery-lambda):

```json
{
  "repo_url": "https://github.com/user/repo",
  "repo_name": "repo-name",
  "repo_description": "Short description from GitHub",
  "developer_github": "username",
  "star_count": 7,
  "language": "Python",
  "discovery_rationale": "Why this repo was selected",
  "key_files": ["src/main.py", "README.md"],
  "technical_highlights": ["Notable technical decisions"]
}
```

**Synthetic state:** `{"metadata": {"execution_id": "mcp-standalone-{timestamp}", "script_attempt": 1}}`

---

#### `invoke_research`

Build a developer profile from GitHub.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `repo_url` | string | yes | GitHub repo URL, e.g. `https://github.com/user/repo` |
| `repo_name` | string | yes | The repo name. |
| `developer_github` | string | yes | GitHub username. |

**Returns:** Full Research output per [Interface Contracts](./interface-contracts.md#research-lambda):

```json
{
  "developer_name": "Display Name",
  "developer_github": "username",
  "developer_bio": "GitHub bio",
  "public_repos_count": 15,
  "notable_repos": [{"name": "...", "description": "...", "stars": 5, "language": "Rust"}],
  "commit_patterns": "Description of contribution patterns",
  "technical_profile": "Languages, frameworks, interests",
  "interesting_findings": ["Observations for podcast material"],
  "hiring_signals": ["What their work signals to a hiring manager"]
}
```

**Synthetic state:** Places parameters under `$.discovery` in a pipeline state object.

---

#### `invoke_script`

Write a 3-persona comedy podcast script.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `discovery` | object | yes | Full Discovery output. |
| `research` | object | yes | Full Research output. |
| `producer_feedback` | string | no | Feedback from a previous Producer evaluation. |
| `producer_issues` | array[string] | no | Specific issues from a previous evaluation. |

If `producer_feedback` is provided, sets `$.producer.feedback` and `$.metadata.script_attempt = 2` in the synthetic state.

**Returns:** Full Script output per [Interface Contracts](./interface-contracts.md#script-lambda):

```json
{
  "text": "**Hype:** Welcome back...\n**Roast:** You say that every week...",
  "character_count": 4200,
  "segments": ["intro", "core_debate", "developer_deep_dive", "technical_appreciation", "hiring_manager", "outro"],
  "featured_repo": "repo-name",
  "featured_developer": "username",
  "cover_art_suggestion": "Visual concept for cover art"
}
```

---

#### `invoke_producer`

Evaluate a script's quality. Returns PASS/FAIL with score and feedback.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `script_text` | string | yes | Full script text with speaker labels. |
| `discovery` | object | yes | Discovery output (to verify script specificity). |
| `research` | object | yes | Research output (to verify hiring segment). |

**Returns:** Producer output per [Interface Contracts](./interface-contracts.md#producer-lambda):

```json
{
  "verdict": "PASS",
  "score": 8,
  "notes": "Brief evaluation summary"
}
```

Or on failure:

```json
{
  "verdict": "FAIL",
  "score": 4,
  "feedback": "What needs to change",
  "issues": ["issue 1", "issue 2"]
}
```

---

#### `invoke_cover_art`

Generate episode cover art via Bedrock Nova Canvas.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `cover_art_suggestion` | string | yes | Visual concept description. |
| `repo_name` | string | yes | For the episode subtitle overlay. |
| `language` | string | no | Primary language, informs visual theme. |
| `execution_id` | string | no | S3 key prefix. Auto-generated if omitted. |

**Returns:**

```json
{
  "s3_key": "episodes/{execution_id}/cover.png",
  "prompt_used": "The actual prompt sent to Nova Canvas"
}
```

---

#### `invoke_tts`

Generate podcast audio from a script via ElevenLabs text-to-dialogue.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `script_text` | string | yes | Approved script with `**Hype:**`, `**Roast:**`, `**Phil:**` labels. |
| `execution_id` | string | no | S3 key prefix. Auto-generated if omitted. |

**Returns:**

```json
{
  "s3_key": "episodes/{execution_id}/episode.mp3",
  "duration_seconds": 180,
  "character_count": 4200
}
```

---

#### `invoke_post_production`

Combine MP3 + PNG into MP4, write episode record to Postgres.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `discovery` | object | yes | Full Discovery output. |
| `research` | object | yes | Full Research output. |
| `script` | object | yes | Full Script output. |
| `cover_art` | object | yes | Full Cover Art output. |
| `tts` | object | yes | Full TTS output. |
| `execution_id` | string | no | Auto-generated if omitted. |

**Returns:**

```json
{
  "s3_mp4_key": "episodes/{execution_id}/episode.mp4",
  "episode_id": 2,
  "air_date": "2025-07-13"
}
```

---

### Observation

#### `get_agent_logs`

Retrieve CloudWatch logs for a specific pipeline agent.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `agent` | string | yes | One of: `discovery`, `research`, `script`, `producer`, `cover_art`, `tts`, `post_production`, `site`. |
| `execution_id` | string | no | Filter by `correlation_id` field. Omit for all recent logs. |
| `since_minutes` | integer | no | How far back to look. Default 60. |
| `log_level` | string | no | Minimum level: `DEBUG`, `INFO`, `WARNING`, `ERROR`. |
| `limit` | integer | no | Max log lines. Default 50, max 200. |

**Returns:**

```json
{
  "logs": [
    {
      "timestamp": "2025-07-13T09:01:23.456Z",
      "level": "INFO",
      "message": "Discovery agent found repo: user/repo",
      "service": "discovery",
      "correlation_id": "arn:aws:states:...",
      "extra": {}
    }
  ]
}
```

**AWS calls:** `logs:FilterLogEvents` on log group `/aws/lambda/zerostars-{agent}` with `startTime` computed from `since_minutes` (epoch milliseconds), and `filterPattern` set to the `execution_id` when provided. Log level filtering is done client-side after retrieval.

---

#### `get_execution_history`

Get the full event history for a pipeline execution — every state transition, input/output, and timing.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `execution_arn` | string | yes | The execution to inspect. |
| `include_input_output` | boolean | no | Include full I/O JSON at each step. Default true. |

**Returns:**

```json
{
  "events": [
    {
      "timestamp": "2025-07-13T09:00:01.000Z",
      "type": "TaskStateEntered",
      "state_name": "Discovery",
      "input": {"metadata": {"...": "..."}},
      "output": null,
      "duration_ms": null
    },
    {
      "timestamp": "2025-07-13T09:01:30.000Z",
      "type": "TaskSucceeded",
      "state_name": "Discovery",
      "input": null,
      "output": {"repo_url": "...", "star_count": 7},
      "duration_ms": 89000
    }
  ]
}
```

**AWS calls:** `states:GetExecutionHistory` with `includeExecutionData` matching the `include_input_output` parameter. Paginated — the tool fetches all pages and returns the consolidated list.

---

#### `get_pipeline_health`

Health check across the pipeline: success/failure rates, running executions, recent failures.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `days` | integer | no | Look-back period. Default 30. |

**Returns:**

```json
{
  "total_executions": 12,
  "succeeded": 10,
  "failed": 1,
  "aborted": 1,
  "success_rate": "83%",
  "avg_duration_seconds": 720,
  "currently_running": [],
  "recent_failures": [
    {
      "execution_arn": "...",
      "name": "mcp-20250706T090000Z",
      "error": "States.TaskFailed",
      "cause": "TTS Lambda timeout"
    }
  ],
  "last_successful_episode": {
    "episode_id": 11,
    "repo_name": "cool-project",
    "air_date": "2025-07-06"
  }
}
```

**AWS calls:** Multiple `states:ListExecutions` calls with different `statusFilter` values, `states:DescribeExecution` for running/failed executions, Postgres query for last successful episode.

---

### Data

All data tools connect to Postgres using `psycopg2` from the shared Lambda Layer. Connection string from SSM Parameter Store `/zerostars/db-connection-string`, fetched at cold start and cached. Same pattern as existing pipeline Lambdas — public internet connection, no VPC. See [Database Schema](./database-schema.md) for DDL.

#### `query_episodes`

Query the episodes table with filtering and pagination.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `episode_id` | integer | no | Get a specific episode. |
| `developer_github` | string | no | Filter by developer. |
| `language` | string | no | Filter by primary language (from `research_json`). |
| `limit` | integer | no | Default 10, max 50. |
| `offset` | integer | no | Pagination offset. Default 0. |
| `order_by` | string | no | One of: `created_at`, `air_date`, `episode_id`, `star_count_at_recording`. Default `created_at`. |
| `order` | string | no | `asc` or `desc`. Default `desc`. |

**Returns:**

```json
{
  "episodes": [
    {
      "episode_id": 11,
      "air_date": "2025-07-06",
      "repo_url": "https://github.com/user/repo",
      "repo_name": "cool-project",
      "developer_github": "username",
      "developer_name": "Display Name",
      "star_count_at_recording": 7,
      "producer_attempts": 1,
      "s3_mp3_path": "episodes/.../episode.mp3",
      "s3_mp4_path": "episodes/.../episode.mp4",
      "s3_cover_art_path": "episodes/.../cover.png",
      "created_at": "2025-07-06T09:12:34.000Z"
    }
  ],
  "total_count": 11
}
```

Excludes `script_text`, `research_json`, and `cover_art_prompt` to keep response size manageable. Use `get_episode_detail` for full text.

---

#### `get_episode_detail`

Full details for a single episode including script text and research JSON.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `episode_id` | integer | yes | The episode ID. |

**Returns:** Full episode row including `script_text`, `research_json`, `cover_art_prompt`, and all other columns from the `episodes` table.

---

#### `query_metrics`

Query engagement metrics for episodes.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `episode_id` | integer | no | Filter to specific episode. |
| `order_by` | string | no | One of: `views`, `likes`, `comments`, `shares`, `snapshot_date`. Default `views`. |
| `limit` | integer | no | Default 10. |

**Returns:**

```json
{
  "metrics": [
    {
      "episode_id": 11,
      "repo_name": "cool-project",
      "developer_github": "username",
      "linkedin_post_url": "https://linkedin.com/...",
      "views": 1200,
      "likes": 45,
      "comments": 12,
      "shares": 8,
      "snapshot_date": "2025-07-10"
    }
  ]
}
```

**SQL:** Joins `episode_metrics` with `episodes` for the `repo_name`/`developer_github` context.

---

#### `query_featured_developers`

List all previously featured developers.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `limit` | integer | no | Default 100. |

**Returns:**

```json
{
  "developers": [
    {
      "developer_github": "username",
      "episode_id": 11,
      "featured_date": "2025-07-06",
      "repo_name": "cool-project"
    }
  ]
}
```

**SQL:** Joins `featured_developers` with `episodes` for `repo_name`.

---

#### `run_sql`

Execute a read-only SQL query. Only `SELECT` statements allowed.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `sql` | string | yes | A SELECT query. |

**Returns:**

```json
{
  "columns": ["episode_id", "repo_name"],
  "rows": [[11, "cool-project"], [10, "other-project"]],
  "row_count": 2
}
```

**Safety:** Rejects any statement not starting with `SELECT` (case-insensitive, whitespace-trimmed). Uses a 15-second `statement_timeout` on the Postgres session.

---

#### `upsert_metrics`

Insert or update engagement metrics for an episode.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `episode_id` | integer | yes | The episode to record metrics for. |
| `linkedin_post_url` | string | no | URL of the LinkedIn post. |
| `views` | integer | no | Default 0. |
| `likes` | integer | no | Default 0. |
| `comments` | integer | no | Default 0. |
| `shares` | integer | no | Default 0. |

**Returns:**

```json
{
  "metric_id": 5,
  "action": "inserted"
}
```

**SQL:** `INSERT INTO episode_metrics (...) VALUES (...) ON CONFLICT (episode_id, snapshot_date) DO UPDATE SET ...`. Snapshot date is set to current date.

> **Note:** The `episode_metrics` table does not currently have a unique constraint on `(episode_id, snapshot_date)`. This constraint should be added when implementing the MCP server:
> ```sql
> CREATE UNIQUE INDEX idx_episode_metrics_unique ON episode_metrics(episode_id, snapshot_date);
> ```

---

### Assets

#### `get_episode_assets`

Get presigned download URLs for an episode's S3 assets. URLs expire after 1 hour.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `episode_id` | integer | yes | The episode whose assets to retrieve. |

**Returns:**

```json
{
  "cover_art_url": "https://zerostars-episodes-123456789.s3.amazonaws.com/...",
  "mp3_url": "https://...",
  "mp4_url": "https://...",
  "s3_keys": {
    "cover": "episodes/.../cover.png",
    "mp3": "episodes/.../episode.mp3",
    "mp4": "episodes/.../episode.mp4"
  }
}
```

Null for any asset that doesn't exist. Gets S3 paths from the `episodes` table, then generates presigned URLs with `s3:GetObject`.

---

#### `list_s3_assets`

List objects in the episode assets bucket.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `prefix` | string | no | S3 key prefix, e.g. `episodes/` or `episodes/mcp-20250713/`. |
| `limit` | integer | no | Default 50. |

**Returns:**

```json
{
  "objects": [
    {
      "key": "episodes/mcp-20250713/cover.png",
      "size_bytes": 524288,
      "last_modified": "2025-07-13T09:05:00.000Z"
    }
  ]
}
```

**AWS calls:** `s3:ListObjectsV2` on the `zerostars-episodes-{account_id}` bucket.

---

#### `get_presigned_url`

Generate a presigned URL for a specific S3 object.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `s3_key` | string | yes | Full S3 key, e.g. `episodes/mcp-20250713/cover.png`. |
| `expires_in` | integer | no | URL expiry in seconds. Default 3600, max 43200 (12 hours). |

**Returns:**

```json
{
  "url": "https://...",
  "expires_at": "2025-07-13T10:05:00.000Z"
}
```

---

### Site

#### `invalidate_cache`

Invalidate the CloudFront cache for the podcast website.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `paths` | array[string] | no | CloudFront paths to invalidate. Default `["/*"]`. |

**Returns:**

```json
{
  "invalidation_id": "I1JLWSDAP8FU89",
  "status": "InProgress",
  "paths": ["/*"]
}
```

**AWS calls:** `cloudfront:CreateInvalidation` with `distributionId` and a `Paths` batch. `CallerReference` is auto-generated as a timestamp.

---

#### `get_site_status`

Health check for the podcast website.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| — | — | — | No parameters. |

**Returns:**

```json
{
  "distribution_status": "Deployed",
  "domain": "podcast.ryans-lab.click",
  "ssl_status": "ISSUED",
  "episode_count": 11,
  "latest_episode": {
    "episode_id": 11,
    "repo_name": "cool-project",
    "air_date": "2025-07-06"
  },
  "cloudfront_id": "E1234567890"
}
```

**AWS calls:** `cloudfront:GetDistribution`, `acm:DescribeCertificate`, Postgres query for episode count and latest episode.

---

## MCP Resources

Read-only data that Claude can browse without invoking a tool.

| URI | Description | Data Source |
|-----|-------------|-------------|
| `zerostars://episodes` | All episodes (id, air_date, repo_name, developer_github, star_count, producer_attempts) | Postgres `episodes` table |
| `zerostars://episodes/{episode_id}` | Full episode detail including script and research | Postgres `episodes` table |
| `zerostars://metrics` | Latest engagement metrics per episode, ordered by views | Postgres `episode_metrics` joined with `episodes` |
| `zerostars://pipeline/status` | Currently running executions and last 5 completed | `states:ListExecutions` |
| `zerostars://featured-developers` | All featured developers with episode ID and date | Postgres `featured_developers` joined with `episodes` |

---

## Lambda File Structure

```
lambdas/mcp/
    handler.py              # Lambda entry point, Streamable HTTP transport setup
    tools/
        __init__.py
        pipeline.py         # start_pipeline, stop_pipeline, get_execution_status, list_executions, retry_from_step
        agents.py           # invoke_discovery, invoke_research, invoke_script, invoke_producer, invoke_cover_art, invoke_tts, invoke_post_production
        observation.py      # get_agent_logs, get_execution_history, get_pipeline_health
        data.py             # query_episodes, get_episode_detail, query_metrics, query_featured_developers, run_sql, upsert_metrics
        assets.py           # get_episode_assets, list_s3_assets, get_presigned_url
        site.py             # invalidate_cache, get_site_status
    resources.py            # MCP resource handlers
```

`handler.py` creates the MCP server instance, registers all tools and resources, and wires up the Streamable HTTP transport for the Lambda Function URL. Each tool module imports boto3 clients and the shared DB connection helper at module level (cached across warm invocations).

### Dependencies

The `mcp` Python SDK (`mcp[cli]`) is bundled into the Lambda deployment package alongside the handler:

```bash
cd lambdas/mcp
pip install "mcp[cli]" -t . --platform manylinux2014_x86_64 --only-binary=:all:
```

The shared Lambda Layer provides `psycopg2`, `aws-lambda-powertools`, and the shared utility modules (`bedrock.py`, `db.py`, `s3.py`, `logging.py`, `types.py`).

---

## Terraform Changes

### New file: `terraform/mcp.tf`

| Resource | Type | Notes |
|----------|------|-------|
| MCP Lambda function | `aws_lambda_function` | `zerostars-mcp`, Python 3.12, 512 MB, 300s, shared layer |
| Deployment package | `data "archive_file"` | Zips `lambdas/mcp/` |
| IAM role | `aws_iam_role` | Lambda assume-role trust policy |
| IAM policy | `aws_iam_role_policy` | Inline policy (see IAM section below) |
| CloudWatch log group | `aws_cloudwatch_log_group` | `/aws/lambda/zerostars-mcp`, 14-day retention |
| Function URL | `aws_lambda_function_url` | `auth_type = "AWS_IAM"`, `invoke_mode = "RESPONSE_STREAM"` |
| Function URL permission | `aws_lambda_permission` | Grants `var.mcp_allowed_principal` invoke access |

**Lambda configuration:**

```hcl
resource "aws_lambda_function" "mcp" {
  function_name = "${var.project_prefix}-mcp"
  runtime       = "python3.12"
  handler       = "handler.lambda_handler"
  timeout       = 300
  memory_size   = 512

  filename         = data.archive_file.mcp.output_path
  source_code_hash = data.archive_file.mcp.output_base64sha256
  role             = aws_iam_role.mcp.arn

  layers = [aws_lambda_layer_version.shared.arn]

  logging_config {
    log_format            = "JSON"
    application_log_level = "INFO"
    system_log_level      = "WARN"
  }

  environment {
    variables = {
      POWERTOOLS_SERVICE_NAME    = "mcp"
      POWERTOOLS_LOG_LEVEL       = "INFO"
      STATE_MACHINE_ARN          = aws_sfn_state_machine.pipeline.arn
      S3_BUCKET                  = aws_s3_bucket.episodes.id
      CLOUDFRONT_DISTRIBUTION_ID = aws_cloudfront_distribution.site.id
      ACM_CERTIFICATE_ARN        = aws_acm_certificate.site.arn
      SITE_DOMAIN                = var.domain_name
    }
  }
}

resource "aws_lambda_function_url" "mcp" {
  function_name      = aws_lambda_function.mcp.function_name
  authorization_type = "AWS_IAM"
  invoke_mode        = "RESPONSE_STREAM"
}
```

### New variable in `terraform/variables.tf`

```hcl
variable "mcp_allowed_principal" {
  type        = string
  description = "IAM principal ARN allowed to invoke the MCP Function URL"
  default     = ""
}
```

### New output in `terraform/outputs.tf`

```hcl
output "mcp_function_url" {
  value       = aws_lambda_function_url.mcp.function_url
  description = "MCP server Function URL for claude.ai integration"
}
```

### IAM Permissions

| Permission | Resource | Tools |
|-----------|----------|-------|
| `states:StartExecution` | State machine ARN | `start_pipeline`, `retry_from_step` |
| `states:StopExecution` | `*` | `stop_pipeline` |
| `states:DescribeExecution` | `*` | `get_execution_status`, `retry_from_step` |
| `states:ListExecutions` | State machine ARN | `list_executions`, `get_pipeline_health` |
| `states:GetExecutionHistory` | `*` | `get_execution_status`, `get_execution_history` |
| `lambda:InvokeFunction` | All 7 pipeline Lambda ARNs | `invoke_*` tools |
| `logs:FilterLogEvents` | All 8 Lambda log group ARNs | `get_agent_logs` |
| `s3:GetObject` | `arn:aws:s3:::zerostars-episodes-*/*` | `get_episode_assets`, `get_presigned_url` |
| `s3:ListBucket` | `arn:aws:s3:::zerostars-episodes-*` | `list_s3_assets` |
| `ssm:GetParameter` | `/zerostars/db-connection-string` | All data tools |
| `cloudfront:CreateInvalidation` | Distribution ARN | `invalidate_cache` |
| `cloudfront:GetDistribution` | Distribution ARN | `get_site_status` |
| `acm:DescribeCertificate` | Certificate ARN | `get_site_status` |
| `logs:CreateLogGroup`, `logs:CreateLogStream`, `logs:PutLogEvents` | MCP log group ARN | Own logging |

### ASL Modification: ResumeRouter

To support `retry_from_step`, the state machine ASL in `terraform/step-functions.tf` gets a new `ResumeRouter` Choice state inserted after `InitializeMetadata`. This is backward-compatible — normal executions (without `resume_from`) route to `Discovery` via the `Default` case.

```json
"ResumeRouter": {
  "Type": "Choice",
  "Choices": [
    { "Variable": "$.metadata.resume_from", "StringEquals": "Research", "Next": "Research" },
    { "Variable": "$.metadata.resume_from", "StringEquals": "Script", "Next": "Script" },
    { "Variable": "$.metadata.resume_from", "StringEquals": "Producer", "Next": "Producer" },
    { "Variable": "$.metadata.resume_from", "StringEquals": "CoverArt", "Next": "CoverArt" },
    { "Variable": "$.metadata.resume_from", "StringEquals": "TTS", "Next": "TTS" },
    { "Variable": "$.metadata.resume_from", "StringEquals": "PostProduction", "Next": "PostProduction" }
  ],
  "Default": "Discovery"
}
```

`InitializeMetadata.Next` changes from `"Discovery"` to `"ResumeRouter"`.

---

## Design Decisions

### Database Access: Direct Connection, No VPC

The MCP Lambda connects to Postgres over the public internet using the connection string from SSM, same as all existing pipeline Lambdas. No VPC, no RDS Proxy.

**Why:** The pipeline already works this way. MCP has very low concurrency (1-2 connections at most from a single user). RDS Proxy ($15+/month) solves a connection pooling problem that doesn't exist here. Adding VPC would increase cold start from ~1-2s to ~5-10s and be inconsistent with the rest of the architecture.

### `run_sql` Safety

`run_sql` only allows `SELECT` statements. It checks that the trimmed, case-folded query starts with `select`. It also sets `statement_timeout = '15s'` on the connection to prevent long-running queries from blocking the Lambda.

This is not a full SQL injection defense — it's a guardrail for an authenticated, single-user control plane. The IAM auth on the Function URL is the primary access control.

### Execution Naming

MCP-triggered executions use the name pattern `mcp-{iso-timestamp}` (e.g., `mcp-20250713T090000Z`). Retry executions use `mcp-retry-{iso-timestamp}`. Names are max 80 characters, restricted to `[0-9A-Za-z-_]` per the Step Functions API.

---


## Testing

See [Testing — MCP Server Tests](./testing.md#mcp-server-tests) for unit, integration, and end-to-end test specifications.
