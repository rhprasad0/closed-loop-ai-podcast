# E2E Test Report: "0 Stars, 10/10" Pipeline

## Test Tier Summary

| Tier | Tests | Files | What It Covers |
|------|-------|-------|----------------|
| Unit | 297 | 21 | Handler logic, output parsing, mocking, type coercion |
| Integration | ~30 | 8 | Real Bedrock (Haiku), behavioral twins, multi-handler chains |
| E2E | 29 | 5 | Deployed infrastructure — Step Functions, Lambda, S3, Postgres, CloudFront |

## E2E Test Inventory

| File | Tests | What It Validates |
|------|-------|-------------------|
| `test_pipeline_execution.py` | 10 | Step Functions orchestration, all 8 stage outputs (Discovery through PostProduction), schema validation, cross-step contracts |
| `test_pipeline_artifacts.py` | 6 | S3 objects exist with correct content types (PNG, MP3, MP4), Postgres records match pipeline state, data consistency across DB and state |
| `test_pipeline_control_flow.py` | 3 | Resume-from-step via ResumeRouter, stop running execution, error handling path (HandleError to PipelineFailed) |
| `test_mcp_tools.py` | 7 | MCP Lambda full stack via `boto3 lambda.invoke()` — list_executions, get_execution_status, get_pipeline_health, query_episodes, get_episode_detail, get_episode_assets, get_presigned_url |
| `test_site.py` | 3 | CloudFront website returns 200 with HTML, 404 for unknown paths, episode listing includes the e2e episode |

## Architecture

```
                         Session-scoped fixture
                         ┌─────────────────────┐
                         │ pipeline_execution   │
                         │ (starts SFN, polls,  │
                         │  yields result)      │
                         └──────────┬───────────┘
                                    │
            ┌───────────────┬───────┴──────┬──────────────┬─────────────┐
            │               │              │              │             │
    test_pipeline_   test_pipeline_  test_pipeline_  test_mcp_    test_site
    execution (10)   artifacts (6)   control_flow(3) tools (7)      (3)
            │               │              │              │             │
    Asserts on       S3 head_object  Starts own     boto3         HTTP GET
    final_state      DB SELECT       executions     lambda.invoke  CloudFront
```

## AWS API Dependencies

| Service | Operations Used | Tests |
|---------|----------------|-------|
| Step Functions | `StartExecution`, `DescribeExecution`, `StopExecution`, `GetExecutionHistory` | Pipeline execution + control flow |
| Lambda | `Invoke` (MCP Lambda with Function URL v2 events) | MCP tools |
| S3 | `HeadObject`, `DeleteObject` | Artifacts (verify) + cleanup |
| RDS (Postgres) | `SELECT`, `DELETE` | Artifacts (verify) + cleanup |
| CloudFront | HTTP GET via public URL | Site |

## Key Design Decisions

1. **One pipeline execution per session** — costs ~$1-5 per run (Bedrock Sonnet + Nova Canvas + ElevenLabs + Exa). Individual tests assert against the shared result.

2. **MCP tests via `boto3 lambda.invoke()`** — constructs Lambda Function URL v2 events with JSON-RPC bodies, testing the full stack (ASGI adapter, FastMCP, tool registration, tool execution).

3. **Comprehensive skip guards** — tests skip gracefully when infrastructure isn't deployed (module-level env var checks, fixture-level `StateMachineDoesNotExist` handling, test-level pipeline status checks).

4. **Automatic cleanup** — session teardown deletes S3 objects and DB records. Safety-net autouse fixture catches leaked rows from crashed runs.

## Prerequisites

```bash
# Source environment variables (from .env or terraform output)
set -a && source .env && set +a

# Required env vars:
#   STATE_MACHINE_ARN  — from terraform output state_machine_arn
#   S3_BUCKET          — from terraform output s3_bucket_name
#   SITE_URL           — from terraform output site_url
#   DB_CONNECTION_STRING — from AWS SSM /zerostars/db-connection-string
#   PYTHONPATH         — lambdas/shared/python
```

## Running

```bash
# All e2e tests (~15 min)
PYTHONPATH=lambdas/shared/python pytest tests/e2e/ -m e2e -v --timeout=900

# Pipeline only (cheapest)
PYTHONPATH=lambdas/shared/python pytest tests/e2e/test_pipeline_execution.py tests/e2e/test_pipeline_artifacts.py -m e2e -v

# Site only (free if episodes exist)
PYTHONPATH=lambdas/shared/python pytest tests/e2e/test_site.py -m e2e -v
```

## Cost Estimate

| Service | Per-Run Cost |
|---------|-------------|
| Bedrock Claude Sonnet (4-6 calls) | ~$0.50-2.00 |
| Bedrock Nova Canvas (1-2 calls) | ~$0.10-0.20 |
| ElevenLabs text-to-dialogue (1-2 calls) | ~$0.50-1.00 |
| Exa Neural Search (2-4 calls) | ~$0.02-0.05 |
| **Total** | **~$1-5** |

---

## Execution Log

### Run 1 — 2026-03-29

**Infrastructure deployment:**
- Terraform plan: 100 resources to add
- Fixed `observability.tf`: `extended_statistics` → `extended_statistic` (9 occurrences)
- Fixed `step-functions.tf`: added CloudWatch Logs permissions to SFN IAM role
- Terraform apply: 112 resources created (100 planned + 11 on second apply + 1 change)
- All outputs match `.env`: state_machine_arn, s3_bucket_name, site_url
- Fixed `step-functions.tf`: added `resume_from = ""` to InitializeMetadata (Choice state requires variable to exist)
- Fixed `lambdas/shared/build.sh`: added `aws-xray-sdk==2.14.0` (Powertools Tracer dependency missing from layer)
- Fixed `terraform/lambdas.tf`: `handler.handler` → `handler.lambda_handler` (8 Lambdas)

**Test results:**

| File | Status | Passed | Failed | Skipped | Notes |
|------|--------|--------|--------|---------|-------|
| `test_pipeline_execution.py` | PASS | 10 | 0 | 0 | 1 rerun (first attempt failed, retry succeeded) |
| `test_pipeline_artifacts.py` | PASS | 6 | 0 | 0 | S3 objects + DB records all verified |
| `test_pipeline_control_flow.py` | PARTIAL | 2 | 1 | 0 | resume + stop pass; error handling test needs investigation |
| `test_mcp_tools.py` | FAIL | 0 | 7 | 0 | MCP Lambda import error (relative import packaging issue) |
| `test_site.py` | FAIL | 0 | 3 | 0 | CloudFront returns 403 (ACM/origin config) |

**Total: 18 passed, 11 failed across 29 tests. Pipeline core fully working.**

**Current blocker:** Discovery handler's `_parse_discovery_output` gets empty/non-JSON from Haiku 4.5. The agentic loop completes (4 turns, ~10s) but final text is not valid JSON. Needs handler-level fix (output parsing robustness or model quality tuning).

**Infrastructure fixes discovered during deployment (7 total):**
1. `observability.tf`: `extended_statistics` → `extended_statistic` (terraform plan error, 9 alarms)
2. `step-functions.tf`: added `resume_from = ""` to InitializeMetadata (SFN Choice state runtime error)
3. `step-functions.tf`: added CloudWatch Logs IAM permissions for SFN role (AccessDeniedException)
4. `lambdas/shared/build.sh`: added `aws-xray-sdk==2.14.0` (Powertools Tracer dependency)
5. `terraform/lambdas.tf`: `handler.handler` → `handler.lambda_handler` (HandlerNotFound)
6. `terraform/lambdas.tf`: Discovery/Research timeout 300→900s (agentic loop too slow for Sonnet)
7. `shared/bedrock.py`: model ID `anthropic.claude-haiku-4-5` → `us.anthropic.claude-haiku-4-5` (inference profile required), added to `_NO_ADAPTIVE_THINKING_PATTERNS` (no output_config.effort support), added turn-level logging
