# Implementation Spec: "0 Stars, 10/10" Podcast Pipeline

Single source of truth for implementing the podcast pipeline. Each section is a standalone reference document in [`docs/spec/`](docs/spec/).

**Target runtime:** Python 3.12 on AWS Lambda, Terraform for IaC.

---

## Spec Documents

| Document | Description |
|----------|-------------|
| [File Manifest](docs/spec/file-manifest.md) | Repo structure — every file to create and its purpose |
| [Interface Contracts](docs/spec/interface-contracts.md) | Lambda I/O JSON schemas, state object shape |
| [Step Functions ASL](docs/spec/step-functions-asl.md) | Complete state machine definition |
| [Terraform Resource Map](docs/spec/terraform-resource-map.md) | TF file-by-file resource listing |
| [External API Contracts](docs/spec/external-api-contracts.md) | Bedrock, ElevenLabs, Exa, GitHub API specs |
| [Database Schema](docs/spec/database-schema.md) | DDL for the zerostars database |
| [Prompt Files](docs/spec/prompt-files.md) | Agent prompt specifications |
| [Lambda Packaging & Deployment](docs/spec/packaging-and-deployment.md) | Dependencies, layers, deploy sequence |
| [Instrumentation](docs/spec/instrumentation.md) | Powertools Logger, Tracer, Metrics — structured logging, X-Ray tracing, custom CloudWatch metrics |
| [Observability](docs/spec/observability.md) | CloudWatch Alarms, SNS alerting, dashboard recommendations |
| [Type Checking](docs/spec/type-checking.md) | mypy strict config, TypedDict definitions |
| [Testing](docs/spec/testing.md) | pytest setup, unit/integration/e2e tests for pipeline handlers |
| [MCP Server Testing](docs/spec/testing-mcp.md) | Unit/integration/e2e tests for MCP server tools and resources |
| [CI Pipeline](docs/spec/ci-pipeline.md) | GitHub Actions workflow, ruff config |
| [MCP Server](docs/spec/mcp-server.md) | MCP control plane — tools, resources, Lambda architecture |

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
| MCP Lambda memory | 512 MB |
| MCP Lambda timeout | 300 seconds |
| MCP Function URL auth | `AWS_IAM` |
| MCP Function URL invoke mode | `RESPONSE_STREAM` |
| Bedrock Claude model ID | `us.anthropic.claude-sonnet-4-6` |
| Bedrock Nova Canvas model ID | `amazon.nova-canvas-v1:0` |
| ElevenLabs model | `eleven_v3` |
| ElevenLabs output format | `mp3_44100_128` |
| Discovery star threshold | Under 10 (hard ceiling, verified via GitHub API) |
| DB connection string | `DB_CONNECTION_STRING` env var on all Lambdas that access Postgres (Discovery, Producer, Post-Production, Site, MCP) |
| Script character limit | 5,000 (target 4,000–4,500) |
| Max script retry attempts | 3 |
| Tags | `project = "0-stars-podcast"`, `managed_by = "terraform"` |
| Powertools log level | `INFO` |
| Lambda `logging_config` log format | `JSON` |
| Lambda `logging_config` system log level | `WARN` |
| mypy mode | `strict` |
| pytest markers | `integration`, `e2e` |
| Ruff line length | 100 |
| CI Python version | `3.12` |
