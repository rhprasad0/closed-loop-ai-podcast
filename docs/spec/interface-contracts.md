> Part of the [Implementation Spec](../../IMPLEMENTATION_SPEC.md)

# Interface Contracts

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

**Reads from Postgres (via Bedrock tool use):**
- `featured_developers` — all rows, to exclude previously featured developers from search
- `episodes` — `repo_url` column, to avoid re-featuring the same repository

The Discovery agent queries Postgres directly using a `query_postgres` Bedrock tool backed by the `psql` binary (packaged as a Lambda layer). The handler fetches the DB connection string from SSM Parameter Store (`/zerostars/db-connection-string`) at runtime, not from an environment variable.

> **Deferred:** Querying `episode_metrics` to bias search toward better-performing project types ships as a separate feature. The Discovery agent does not read `episode_metrics` in v1.

**Bedrock tools:** The Discovery agent has three tools available during its agentic loop:
1. `exa_search` — neural search via Exa API to find candidate repos (see [Exa Search API](./external-api-contracts.md#exa-search-api))
2. `query_postgres` — read-only SQL against the podcast database via psql subprocess (see [Discovery Postgres Tool](./external-api-contracts.md#discovery-postgres-tool-query_postgres))
3. `get_github_repo` — GitHub REST API to verify star counts and repo metadata (see [Discovery GitHub Tool](./external-api-contracts.md#discovery-github-tool-get_github_repo))

**Returns:** (placed at `$.discovery` by Step Functions)

```json
{
  "repo_url": "https://github.com/user/repo",
  "repo_name": "repo-name",
  "repo_description": "Short description from GitHub",
  "developer_github": "username",
  "star_count": 7,
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
