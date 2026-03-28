> Part of the [Implementation Spec](../../IMPLEMENTATION_SPEC.md)

# Instrumentation

All Lambdas use [AWS Lambda Powertools for Python](https://docs.powertools.aws.dev/lambda/python/latest/) for structured JSON logging, distributed tracing, and custom metrics. Powertools provides three core utilities — Logger, Tracer, and Metrics — each with a thin factory wrapper in the shared layer.

---

## Logger

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
from shared.tracing import get_tracer
from shared.metrics import get_metrics
from shared.types import PipelineState, DiscoveryOutput

logger = get_logger("discovery")
tracer = get_tracer("discovery")
metrics = get_metrics("discovery")


@tracer.capture_lambda_handler
@logger.inject_lambda_context(clear_state=True)
@metrics.log_metrics(capture_cold_start_metric=True)
def lambda_handler(event: PipelineState, context: LambdaContext) -> DiscoveryOutput:
    logger.set_correlation_id(event["metadata"]["execution_id"])

    logger.info("Starting discovery agent")
    # ... handler logic ...
    logger.info("Discovery complete", extra={"repo_url": result["repo_url"]})
    return result
```

Key points:
- **Decorator order matters.** Tracer must be outermost (creates the root X-Ray subsegment before anything else runs). Logger is middle. Metrics must be innermost (`log_metrics` flushes metrics on function return and should not interfere with Logger's context injection). This ordering is consistent with every Powertools documentation example.
- `@logger.inject_lambda_context(clear_state=True)` — automatically adds Lambda context fields and clears custom keys between warm invocations to prevent state leakage.
- `set_correlation_id()` — sets the Step Functions execution ARN as the correlation ID on every log line. This is the primary field for tracing a full pipeline run across all 7 Lambdas.

### Conditional Context Keys

Some Lambdas append extra keys that are only meaningful in their context:

| Key | Lambdas | Source |
|-----|---------|--------|
| `script_attempt` | Script, Producer | `event["metadata"]["script_attempt"]` — tracks which iteration within the Script/Producer retry loop |

Example (in the Script handler, after `set_correlation_id`):

```python
logger.append_keys(script_attempt=event["metadata"]["script_attempt"])
```

This is not in the universal template because `script_attempt` is only present in the Script and Producer event payloads. Other Lambdas should not reference it.

> **Discovery-specific handler patterns** (credential caching, prompt loading, output parsing, HTTP timeouts) are documented in their respective specs: [Packaging & Deployment](./packaging-and-deployment.md), [Prompt Files](./prompt-files.md), [Interface Contracts](./interface-contracts.md), and [External API Contracts](./external-api-contracts.md).

### Log Level Conventions

| Level | When to use | Examples |
|-------|-------------|---------|
| INFO | Normal flow milestones | `"Starting discovery agent"`, `"Script passed evaluation"`, `"Episode record written to Postgres"` |
| WARNING | Recoverable issues | `"Exa search returned 0 results, retrying with broader query"`, `"Script at 4,950 chars — close to limit"` |
| ERROR | Failures that will cause the Lambda to raise | `"Bedrock invocation failed after retries"`, `"ElevenLabs returned 422"` |
| DEBUG | Detailed data for troubleshooting | Full Bedrock request/response bodies, raw API payloads. Off by default — set `POWERTOOLS_LOG_LEVEL=DEBUG` to enable. |

### Sensitive Data Policy

Structured logs must never contain secrets or PII:

- **Never log:** API keys, database connection strings, Secrets Manager values, SSM SecureString parameter values, or AWS credentials. If a function fetches a secret, log the parameter name (e.g., `"Fetched Exa API key from Secrets Manager"`) but never the value.
- **Request/response bodies at DEBUG only:** Full Bedrock request/response payloads, raw API responses from Exa and GitHub, and raw ElevenLabs API responses should only be logged at `DEBUG` level (off by default). At `INFO` level, log summaries: repo URL, character count, verdict, duration — not full payloads.
- **Presigned URLs:** Do not log S3 presigned URLs at INFO level. They contain temporary credentials in the query string. Log the S3 key instead.

Powertools provides a [data masking utility](https://docs.powertools.aws.dev/lambda/python/latest/utilities/data_masking/) but it is unnecessary here — the approach is simpler: do not pass sensitive values to log calls in the first place. The module-level credential caching pattern (SSM/Secrets Manager values stored in private globals like `_db_connection_string`) keeps secrets in variables that are never logged.

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

---

## Tracer

### Tracer Module

`lambdas/shared/python/shared/tracing.py` exports a factory function parallel to `shared/logging.py`:

```python
from aws_lambda_powertools import Tracer


def get_tracer(service: str) -> Tracer:
    """Return a pre-configured Powertools Tracer for the given service."""
    return Tracer(service=service)
```

The constructor is deliberately simple. Response auto-capture is disabled globally via the `POWERTOOLS_TRACER_CAPTURE_RESPONSE` environment variable (set to `false` in Terraform) rather than per-decorator, because pipeline responses can approach X-Ray's 64 KB metadata limit and the MCP Lambda streams responses. The env var is cleaner than adding `capture_response=False` to every `@tracer.capture_lambda_handler` and `@tracer.capture_method` call.

`Tracer()` auto-patches boto3 clients by default (`auto_patch=True`), so all Bedrock, S3, SSM, and Secrets Manager calls automatically appear as X-Ray subsegments without additional code. **Do not set `auto_patch=False`** — Powertools documentation explicitly warns against this when reusing Tracer across Lambda Layers or multiple modules, as it prevents patching from propagating.

### Tracing Methods

For key internal operations beyond auto-patched boto3 calls, use `@tracer.capture_method`:

```python
@tracer.capture_method
def _execute_exa_search(tool_input: dict[str, Any]) -> dict[str, Any]:
    ...
```

This creates named X-Ray subsegments for: tool execution functions in Discovery and Research, ElevenLabs HTTP calls in TTS, and the ffmpeg subprocess in Post-Production.

### Tracer Environment Variables

| Variable | Value | Purpose |
|----------|-------|---------|
| `POWERTOOLS_TRACE_DISABLED` | `false` (default) | Set to `true` to disable all tracing (used in test environments) |
| `POWERTOOLS_TRACER_CAPTURE_RESPONSE` | `false` | Disables auto-capture of Lambda/method return values as X-Ray metadata |
| `POWERTOOLS_TRACER_CAPTURE_ERROR` | `true` (default) | Captures exceptions as X-Ray metadata for debugging |

---

## Metrics

### Metrics Module

`lambdas/shared/python/shared/metrics.py` exports a factory function:

```python
from aws_lambda_powertools import Metrics


def get_metrics(service: str) -> Metrics:
    """Return a pre-configured Powertools Metrics instance for the given service."""
    return Metrics(service=service, namespace="ZeroStars")
```

The namespace `ZeroStars` groups all custom metrics under a single CloudWatch custom namespace. The `service` dimension is added automatically by Powertools, matching the Logger and Tracer service names.

`capture_cold_start_metric=True` on the `@metrics.log_metrics` decorator (shown in the handler pattern above) automatically emits a `ColdStart` metric (value 1) on cold invocations with a `function_name` dimension. This provides cold-start rate data without any handler code.

### Per-Lambda Custom Metrics

| Lambda | Metric | Unit | When emitted |
|--------|--------|------|-------------|
| Discovery | `ReposEvaluated` | Count | After agent loop completes. Count of repos the agent called `get_github_repo` on. |
| Discovery | `DuplicatesExcluded` | Count | After agent loop. Count of repos skipped due to `featured_developers` check. |
| Script | `ScriptCharacterCount` | Count | After parsing script output. Value of `output["character_count"]`. |
| Producer | `ProducerVerdict` | Count | After parsing verdict. Dimension `verdict=PASS` or `verdict=FAIL`. Always value 1. |
| Producer | `ProducerScore` | None | After parsing verdict. The numeric score (1-10). |
| Cover Art | `CoverArtSizeBytes` | Bytes | After uploading to S3. `len(image_bytes)`. |
| TTS | `AudioDurationSeconds` | Seconds | After ElevenLabs response. `output["duration_seconds"]`. |
| Post-Production | `EpisodeDurationSeconds` | Seconds | After ffmpeg completes. Duration from the TTS output metadata. |

Example emission in a handler:

```python
from aws_lambda_powertools.metrics import MetricUnit

metrics.add_metric(name="ScriptCharacterCount", unit=MetricUnit.Count, value=output["character_count"])
```

For the Producer verdict (which uses a dimension):

```python
metrics.add_metric(name="ProducerVerdict", unit=MetricUnit.Count, value=1)
metrics.add_dimension(name="verdict", value=output["verdict"])
```

### Metrics Environment Variables

| Variable | Value | Purpose |
|----------|-------|---------|
| `POWERTOOLS_METRICS_NAMESPACE` | `ZeroStars` | CloudWatch custom namespace (also passed explicitly in constructor as fallback) |

---

## Terraform Configuration

### Lambda Resource Pattern

Each Lambda function in `lambdas.tf` includes a `logging_config` block (separate from Powertools — this controls Lambda platform-level log formatting):

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
      POWERTOOLS_SERVICE_NAME              = "discovery"
      POWERTOOLS_LOG_LEVEL                 = "INFO"
      POWERTOOLS_METRICS_NAMESPACE         = "ZeroStars"
      POWERTOOLS_TRACER_CAPTURE_RESPONSE   = "false"
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

The `tracing_config { mode = "Active" }` block enables X-Ray active tracing on each Lambda. This populates the `_X_AMZN_TRACE_ID` environment variable that Powertools reads to include `xray_trace_id` in every structured log line and that Tracer uses to contribute subsegments to the active trace. Without this block, the `xray_trace_id` field silently omits from logs. Each Lambda execution role must have `xray:PutTraceSegments` and `xray:PutTelemetryRecords` permissions — attach the `AWSXrayWriteOnlyAccess` managed policy or an equivalent inline policy.

> **Known Terraform issue:** The AWS provider has a bug (hashicorp/terraform-provider-aws#42181) where `log_format = "JSON"` causes perpetual plan drift. If your provider version is affected, add `lifecycle { ignore_changes = [logging_config] }` to each Lambda resource as a workaround.

### CloudWatch Log Groups

Each Lambda's log group is created explicitly in Terraform (not auto-created by the Lambda service) to control retention and ensure the `depends_on` reference in the Lambda resource resolves:

```hcl
resource "aws_cloudwatch_log_group" "discovery" {
  name              = "/aws/lambda/${var.project_prefix}-discovery"
  retention_in_days = 14
}
```

This pattern repeats for all 9 Lambdas (7 pipeline + site + MCP). The naming convention is `/aws/lambda/{project_prefix}-{service}` where `{service}` matches the `POWERTOOLS_SERVICE_NAME` value.

| Log Group | Terraform Resource |
|-----------|-------------------|
| `/aws/lambda/zerostars-discovery` | `aws_cloudwatch_log_group.discovery` |
| `/aws/lambda/zerostars-research` | `aws_cloudwatch_log_group.research` |
| `/aws/lambda/zerostars-script` | `aws_cloudwatch_log_group.script` |
| `/aws/lambda/zerostars-producer` | `aws_cloudwatch_log_group.producer` |
| `/aws/lambda/zerostars-cover-art` | `aws_cloudwatch_log_group.cover_art` |
| `/aws/lambda/zerostars-tts` | `aws_cloudwatch_log_group.tts` |
| `/aws/lambda/zerostars-post-production` | `aws_cloudwatch_log_group.post_production` |
| `/aws/lambda/zerostars-site` | `aws_cloudwatch_log_group.site` |
| `/aws/lambda/zerostars-mcp` | `aws_cloudwatch_log_group.mcp` |

Retention is 14 days for all groups. Explicit creation also prevents the race condition where the Lambda tries to write logs before the auto-created log group's IAM propagation completes.

---

## Error Visibility

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

---

## Non-Pipeline Lambdas

### Site Lambda

The site Lambda is not part of the Step Functions pipeline and has no `execution_id` to use as a correlation ID. Instead, use the Lambda request ID (automatically included by `inject_lambda_context`) for tracing. The handler pattern is the same minus the `set_correlation_id` call.

### MCP Lambda

The MCP Lambda is not a pipeline Lambda (no Step Functions execution context) and not a site Lambda (not behind CloudFront). It handles streaming MCP requests via a Function URL with `RESPONSE_STREAM` invoke mode.

**Logging pattern:** Same `get_logger("mcp")` factory and `@logger.inject_lambda_context(clear_state=True)` decorator. No `set_correlation_id` call — there is no pipeline execution ARN to correlate against. The Lambda request ID (automatically included by `inject_lambda_context`) is the primary identifier for tracing individual MCP requests.

**Tool-level logging:** Each tool module (`tools/pipeline.py`, `tools/agents.py`, etc.) imports its own logger via `get_logger("mcp")`. The shared `service` name ensures all log lines from the MCP Lambda carry `"service": "mcp"` regardless of which tool module emitted them. Tool-specific context is logged via `extra={}` on individual log calls, not via `append_keys()`, because a single Lambda invocation may serve multiple tool calls in a streaming MCP session.

**CloudWatch Logs Insights for MCP:**

```
filter service = "mcp"
| sort @timestamp desc
| fields level, message, function_request_id
| limit 50
```

---

## Testing

In the test environment, disable Tracer to prevent X-Ray SDK's auto-patching of boto3 from interfering with moto mocks:

```python
# conftest.py
@pytest.fixture(autouse=True)
def _disable_tracing(monkeypatch):
    monkeypatch.setenv("POWERTOOLS_TRACE_DISABLED", "true")
```

Tracer auto-disables when not running in the AWS Lambda environment, but the explicit env var prevents auto-patch side effects during import-time initialization.

For Metrics, set the namespace and service name to prevent `SchemaValidationError`:

```python
@pytest.fixture(autouse=True)
def _metrics_env(monkeypatch):
    monkeypatch.setenv("POWERTOOLS_METRICS_NAMESPACE", "ZeroStars")
    monkeypatch.setenv("POWERTOOLS_SERVICE_NAME", "test")
```

See [Testing](./testing.md) for the full `conftest.py` fixture set.
