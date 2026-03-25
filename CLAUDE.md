# CLAUDE.md

Project context and conventions for AI assistants working on this codebase.

## What This Is

"0 Stars, 10/10" is a closed-loop multi-agent podcast pipeline. AI agents run weekly on AWS to find underrated GitHub projects, write comedy podcast scripts, generate cover art, produce audio, and publish episodes — fully autonomous, no human in the loop. AWS serverless (Step Functions, Lambda, Bedrock, RDS), Terraformed. Portfolio project demonstrating production agentic AI engineering.

**Full build blueprint:** See `IMPLEMENTATION_SPEC.md` for architecture decisions, database schema, Terraform conventions, Lambda patterns, API contracts, and the Step Functions ASL definition.

## Repo Layout

```
terraform/          Terraform IaC — all AWS resources
lambdas/            One directory per agent/function, each with handler.py and prompts/
lambdas/shared/     Lambda Layer source — Bedrock client, DB helpers, S3 utils
lambdas/site/       Dynamic website Lambda (Function URL + CloudFront)
layers/ffmpeg/      ffmpeg binary packaged as a Lambda Layer
sql/                Database schema definitions
tests/              Unit and integration tests
```

## Hard Constraints

- **Script length:** ElevenLabs text-to-dialogue API has a 5,000 character limit. Scripts must target 4,000-4,500 characters. The Producer agent enforces this.
- **Three personas:** Hype (optimist), Roast (British cynic), Phil (philosopher).

### ElevenLabs Voice IDs

| Persona | Voice | ID |
|---------|-------|----|
| Hype | Eric | `cjVigY5qzO86Huf0OWal` |
| Roast | George | `JBFqnCBsd6RMkjVDRZzb` |
| Phil | Jessica | `cgSgspJ2msm6clMCkdW9` |

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

# Test the site Lambda locally
sam local start-api --template terraform/site-template.yaml
```

## External Dependencies

- **ElevenLabs API** — TTS generation. Key in Secrets Manager.
- **Exa API** — Discovery agent search. Key in Secrets Manager.
- **GitHub API** — Research agent developer profiling. Public API, rate-limited.
- **AWS Bedrock (Claude)** — Agent reasoning. IAM-authenticated, no external key.
- **AWS Bedrock (Nova Canvas)** — Cover art generation. IAM-authenticated, no external key.
