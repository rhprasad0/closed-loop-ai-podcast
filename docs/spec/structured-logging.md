> Part of the [Implementation Spec](../../IMPLEMENTATION_SPEC.md)

# Structured Logging

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
