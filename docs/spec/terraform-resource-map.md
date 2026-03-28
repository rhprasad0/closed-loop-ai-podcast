> Part of the [Implementation Spec](../../IMPLEMENTATION_SPEC.md)

# Terraform Resource Map

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
| `alert_email` | `string` | Email for CloudWatch alarm notifications (empty = no subscription) |
| `mcp_allowed_principal` | `string` | IAM principal ARN allowed to invoke the MCP Function URL |
| `pipeline_failure_threshold` | `number` | Pipeline failure count threshold for alarm, default `1` |
| `lambda_error_threshold` | `number` | Per-Lambda error count threshold, default `1` |
| `lambda_timeout_threshold_ms` | `number` | Per-Lambda p99 duration threshold in ms, default `270000` (90% of 300s timeout) |
| `producer_fail_threshold` | `number` | Producer consecutive-fail threshold, default `3` |

### `outputs.tf`

| Output | Source | Description |
|--------|--------|-------------|
| `state_machine_arn` | `aws_sfn_state_machine` | Pipeline state machine ARN |
| `site_url` | `var.domain_name` | Podcast website URL (`https://{domain_name}`) |
| `s3_bucket_name` | `aws_s3_bucket` | Episode assets S3 bucket name |
| `mcp_function_url` | `aws_lambda_function_url.mcp` | MCP server Function URL for claude.ai integration |

### `lambdas.tf`

| Resource | Type | Notes |
|----------|------|-------|
| Shared Lambda Layer | `aws_lambda_layer_version` | Source: `build/shared-layer.zip` (built by `lambdas/shared/build.sh`). `compatible_architectures = ["x86_64"]`. |
| ffmpeg Lambda Layer | `aws_lambda_layer_version` | Source: `layers/ffmpeg/ffmpeg-layer.zip` (built by `build.sh`). `compatible_architectures = ["x86_64"]`. |
| Per-Lambda (×8): | | |
| — Deployment package | `data "archive_file"` | Zips `handler.py` + `prompts/` dir |
| — Function | `aws_lambda_function` | Python 3.12, layers attached, env vars set, `logging_config` block, `depends_on` log group |
| — IAM role | `aws_iam_role` | Lambda assume-role trust policy |
| — IAM policy | `aws_iam_role_policy` | Least-privilege: CloudWatch Logs + function-specific permissions |
| — Log group | `aws_cloudwatch_log_group` | 14-day retention |

**Per-Lambda `tracing_config` block** (X-Ray active tracing — applies to all 8 functions in `lambdas.tf`; MCP in `mcp.tf` uses the same pattern):

```hcl
tracing_config {
  mode = "Active"
}
```

Each Lambda's IAM role also needs the `AWSXrayWriteOnlyAccess` managed policy (`arn:aws:iam::aws:policy/AWSXrayWriteOnlyAccess`).

**Per-Lambda `logging_config` block** (native Lambda structured logging — applies to all 8 functions in `lambdas.tf`; MCP in `mcp.tf` uses the same pattern):

```hcl
logging_config {
  log_format            = "JSON"
  application_log_level = "INFO"
  system_log_level      = "WARN"
}
```

**Per-Lambda environment variables** (for Powertools — applies to all 8 functions in `lambdas.tf`; MCP in `mcp.tf` uses the same pattern, in addition to function-specific env vars):

| Variable | Value |
|----------|-------|
| `POWERTOOLS_SERVICE_NAME` | Function-specific: `discovery`, `research`, `script`, `producer`, `cover_art`, `tts`, `post_production`, `site`, `mcp` |
| `POWERTOOLS_LOG_LEVEL` | `INFO` |
| `POWERTOOLS_METRICS_NAMESPACE` | `ZeroStars` |
| `POWERTOOLS_TRACER_CAPTURE_RESPONSE` | `false` |
| `DB_CONNECTION_STRING` | Discovery, Producer, Post-Production, Site: `var.db_connection_string` |
| `S3_BUCKET` | Cover Art, TTS, Post-Production, Site: `aws_s3_bucket.episodes.id` (the episodes bucket name) |

**Per-Lambda IAM permissions:**

| Lambda | Extra permissions beyond CloudWatch Logs |
|--------|------------------------------------------|
| Discovery | `bedrock:InvokeModel`, Secrets Manager read (`aws_secretsmanager_secret.exa.arn`) |
| Research | `bedrock:InvokeModel` |
| Script | `bedrock:InvokeModel` |
| Producer | `bedrock:InvokeModel` |
| Cover Art | `bedrock:InvokeModel` (Nova Canvas), S3 write (`s3:PutObject` on episodes bucket) |
| TTS | Secrets Manager read (`aws_secretsmanager_secret.elevenlabs.arn`), S3 write (`s3:PutObject` on episodes bucket) |
| Post-Production | S3 read/write, ffmpeg layer attached |
| Site | S3 read (for presigned URLs) |

Note: Lambdas that read from Postgres do so over the public internet using the connection string. No VPC or RDS-specific IAM needed.

### `step-functions.tf`

| Resource | Type |
|----------|------|
| State machine | `aws_sfn_state_machine` |
| Execution IAM role | `aws_iam_role` |
| Execution IAM policy | `aws_iam_role_policy` (invoke all 7 pipeline Lambdas) |

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

### `observability.tf`

| Resource | Type |
|----------|------|
| SNS alerts topic | `aws_sns_topic` |
| SNS email subscription | `aws_sns_topic_subscription` (conditional on `var.alert_email`) |
| Pipeline failure alarm | `aws_cloudwatch_metric_alarm` (`AWS/States` `ExecutionsFailed`) |
| Pipeline timeout alarm | `aws_cloudwatch_metric_alarm` (`AWS/States` `ExecutionsTimedOut`) |
| Pipeline throttle alarm | `aws_cloudwatch_metric_alarm` (`AWS/States` `ExecutionThrottled`) |
| Per-Lambda error alarms (x9) | `aws_cloudwatch_metric_alarm` (`AWS/Lambda` `Errors`) |
| Per-Lambda timeout alarms (x9) | `aws_cloudwatch_metric_alarm` (`AWS/Lambda` `Duration` p99) |
| Per-Lambda throttle alarms (x9) | `aws_cloudwatch_metric_alarm` (`AWS/Lambda` `Throttles`) |
| Producer fail rate alarm | `aws_cloudwatch_metric_alarm` (`ZeroStars` `ProducerVerdict`) |
| Script length alarm | `aws_cloudwatch_metric_alarm` (`ZeroStars` `ScriptCharacterCount`) |

See [Observability](./observability.md) for alarm thresholds and configuration details.

### `mcp.tf`

See [MCP Server — Terraform](./mcp-server.md#terraform) for full HCL. Summary of resources:

| Resource | Type |
|----------|------|
| MCP Lambda function | `aws_lambda_function` (512 MB, 300s timeout, shared layer, Function URL) |
| MCP deployment package | `data "archive_file"` (zips `lambdas/mcp/`) |
| MCP IAM role | `aws_iam_role` |
| MCP IAM policy | `aws_iam_role_policy` (Step Functions, Lambda invoke, CloudWatch Logs, S3, CloudFront, ACM) |
| MCP log group | `aws_cloudwatch_log_group` (`/aws/lambda/zerostars-mcp`, 14-day retention) |
| MCP Function URL | `aws_lambda_function_url` (`AWS_IAM` auth, `RESPONSE_STREAM` invoke mode) |
| MCP Function URL permission | `aws_lambda_permission` (grants `var.mcp_allowed_principal` invoke access) |

**MCP IAM permissions** (in addition to CloudWatch Logs):

| Permission | Resource |
|-----------|----------|
| `states:StartExecution`, `StopExecution`, `DescribeExecution`, `ListExecutions`, `GetExecutionHistory` | State machine ARN / `*` |
| `lambda:InvokeFunction` | All 7 pipeline Lambda ARNs |
| `logs:FilterLogEvents` | All 9 Lambda log group ARNs |
| `s3:GetObject`, `s3:ListBucket` | Episodes bucket |
| `cloudfront:CreateInvalidation`, `cloudfront:GetDistribution` | Distribution ARN |
| `acm:DescribeCertificate` | Certificate ARN |
