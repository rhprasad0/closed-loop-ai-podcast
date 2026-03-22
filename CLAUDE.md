# CLAUDE.md

Project context and conventions for AI assistants working on this codebase.

## What This Is

"0 Stars, 10/10" is a closed-loop multi-agent podcast pipeline. Four AI agents (Discovery, Research, Script, Producer) run weekly on AWS to find underrated GitHub projects, write comedy podcast scripts about them, produce audio, and publish episodes — fully autonomous, no human in the loop.

The infrastructure is AWS serverless: Step Functions orchestrates Lambda functions, Bedrock provides model access, ElevenLabs handles TTS, and everything is Terraformed.

This repo is a portfolio project demonstrating production agentic AI engineering.

## Repo Layout

```
terraform/          Terraform IaC — all AWS resources
lambdas/            One directory per agent/function, each with handler.py and prompts/
lambdas/shared/     Lambda Layer source — Bedrock client, DB helpers, S3 utils
layers/ffmpeg/      ffmpeg binary packaged as a Lambda Layer
site/               Static podcast website assets
sql/                Database schema definitions
```

## Key Architecture Decisions

**Step Functions (Standard) orchestrates the pipeline.** Standard, not Express — the pipeline takes several minutes end-to-end and we need exactly-once execution, full audit trail, and the evaluator-optimizer retry loop via Choice states.

**One Lambda per agent.** Separate functions keep IAM permissions tight (Discovery needs Exa, TTS needs ElevenLabs, post-production needs the ffmpeg layer) and allow independent iteration. Each Lambda's deployment package includes its prompt files — no external prompt storage.

**Prompts live in Git, deploy with code.** Each Lambda reads its system prompt from its own deployment package at runtime via `LAMBDA_TASK_ROOT`:
```python
import os
prompt_path = os.path.join(os.environ['LAMBDA_TASK_ROOT'], 'prompts', 'discovery.md')
with open(prompt_path) as f:
    system_prompt = f.read()
```
Terraform's `archive_file` data source packages handler + prompts together. Prompt changes trigger redeployment via `source_code_hash`.

**Evaluator-optimizer loop for script quality.** The Producer Lambda evaluates the Script Lambda's output and returns PASS/FAIL with structured feedback. On FAIL, a Step Functions Choice state routes back to the Script Lambda with the feedback appended to its input. Max 3 attempts before the execution errors out. This is implemented in ASL in `terraform/step-functions.tf`.

**Cross-episode learning via RDS.** The Discovery agent queries `episode_metrics` (LinkedIn performance data) and `featured_developers` (dedup) to inform its search objectives. The database is a shared RDS Postgres instance (also used by NanoClaw).

**Static site generated as a pipeline step.** The Site Generator Lambda rebuilds HTML from the `episodes` table and pushes to S3. The entire flow from "find a repo" to "episode live on site" is one Step Functions execution.

## Tech Stack

- **Language:** Python 3.12 (all Lambdas)
- **IaC:** Terraform
- **Models:** Claude via AWS Bedrock (tool use for Discovery and Research agents)
- **TTS:** ElevenLabs `/v1/text-to-dialogue` API, `eleven_v3` model
- **Database:** PostgreSQL (RDS)
- **Media:** ffmpeg Lambda Layer for audio → video conversion

## The Pipeline

```
EventBridge (weekly cron)
  → Discovery Lambda (Bedrock + Exa API, checks episode history + metrics)
  → Research Lambda (Bedrock + GitHub API)
  → Script Lambda (Bedrock, writes 3-persona comedy script)
  → Producer Lambda (Bedrock, evaluates script → PASS/FAIL with feedback)
      └─ FAIL? → back to Script Lambda (max 3 retries)
  → TTS Lambda (ElevenLabs API → MP3 to S3)
  → Post-Production Lambda (ffmpeg → MP4, writes episode to RDS)
  → Site Generator Lambda (rebuilds static site → S3)
```

## Podcast Specifics

Three AI personas: **Hype** (optimist), **Roast** (British cynic), **Phil** (philosopher). Each episode follows a six-segment arc: intro, core debate, developer deep-dive, technical appreciation, hiring manager segment, outro with callbacks.

**Hard constraint:** ElevenLabs text-to-dialogue API has a 5,000 character limit. Scripts must target 4,000–4,500 characters. The Producer agent enforces this.

### ElevenLabs Voice IDs

| Persona | Voice | ID |
|---------|-------|----|
| Hype | Eric | `cjVigY5qzO86Huf0OWal` |
| Roast | George | `JBFqnCBsd6RMkjVDRZzb` |
| Phil | Jessica | `cgSgspJ2msm6clMCkdW9` |

## Database Tables

- **`episodes`** — Episode catalog. Columns: episode_id, air_date, repo_url, repo_name, developer_github, developer_name, star_count_at_recording, script_text, research_json (jsonb), s3_mp3_path, s3_mp4_path, cover_art_prompt, producer_attempts, created_at.
- **`episode_metrics`** — LinkedIn performance snapshots. Columns: metric_id, episode_id (FK), linkedin_post_url, views, likes, comments, shares, snapshot_date.
- **`featured_developers`** — Dedup list. Columns: developer_github (PK), episode_id (FK), featured_date.

## Terraform Conventions

- All resources are in `terraform/`. No modules outside of `terraform/modules/`.
- The reusable `modules/lambda/` module handles: `archive_file` packaging, IAM role creation, CloudWatch log group, and attaching layers.
- Secrets (API keys) are in Secrets Manager, referenced by Lambda environment variables.
- The Step Functions state machine ASL definition lives in `terraform/step-functions.tf` as a `jsonencode()` block, not a separate JSON file.
- Tags: `project = "0-stars-podcast"`, `managed_by = "terraform"` on all resources.

## Lambda Conventions

- Python 3.12 runtime, all functions.
- Handler pattern: `handler.lambda_handler(event, context)`.
- Shared utilities (Bedrock client, DB connection, S3 helpers) are in the `shared/` Lambda Layer, imported as `from shared import bedrock, db, s3`.
- Each function's `prompts/` directory contains markdown prompt files bundled into the deployment ZIP.
- State is passed between Lambdas via the Step Functions state object (JSON). Each Lambda receives the accumulated output of all previous steps and adds its own output.
- Error handling: Lambdas raise specific exception classes. Step Functions Retry/Catch blocks handle transient errors (Bedrock throttling, API timeouts) with exponential backoff. Business logic failures (Producer FAIL verdict) are returned as normal output and handled by Choice states.

## Writing and Content Conventions

When working on prompts, scripts, or any text content for this project:

- **No AI slop vocabulary.** No "delve," "landscape," "leverage," "at its core," "it's not just X — it's Y," "game-changer," "groundbreaking." If it sounds like ChatGPT wrote it, rewrite it.
- **No promotional language.** No "thrilled to share," "excited to announce," "proud to present."
- **Specific over general.** Always prefer a concrete technical detail over a vague claim.
- **The podcast is an "agent system" or "multi-agent workflow."** Not "an AI podcast." This is a portfolio piece.

## Useful Commands

```bash
# Deploy infrastructure
cd terraform && terraform plan && terraform apply

# Package a single Lambda for testing
cd lambdas/discovery && zip -r ../../build/discovery.zip . 

# Run a Lambda locally (requires SAM CLI)
sam local invoke DiscoveryAgent --event test/discovery_event.json

# Check Step Functions execution history
aws stepfunctions list-executions --state-machine-arn <arn> --max-results 5
```

## External Dependencies

- **ElevenLabs API** — TTS generation. Key in Secrets Manager.
- **Exa API** — Discovery agent search. Key in Secrets Manager.
- **GitHub API** — Research agent developer profiling. Public API, rate-limited.
- **AWS Bedrock** — Claude model access. IAM-authenticated, no external key.
