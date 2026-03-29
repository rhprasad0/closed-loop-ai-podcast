# Ralph Wiggum Build System

Autonomous build orchestrator that implements the "0 Stars, 10/10" codebase from spec using `claude -p --model sonnet` in a loop. Supports multiple campaigns — each campaign is a task backlog with its own convergence strategy.

Named after the [Ralph Wiggum technique](https://mail.risoluto.it/en/news/151/ralph-wiggum-claude-code-bash-loop-coding-agent) — a bash loop that repeatedly invokes Claude Code in pipe mode until a codebase converges.

## Quick Start

```bash
# Run the unit campaign (production code + unit tests)
./ralph.sh

# Run the integration campaign (DTU twin servers + integration tests)
./ralph.sh --tasks tasks-integration.json

# Run detached
nohup ./ralph.sh --tasks tasks-integration.json > /dev/null 2>&1 &

# Check progress
./ralph.sh status
./ralph.sh --tasks tasks-integration.json status

# Watch live
tail -f ralph-unit.log
tail -f ralph-integration.log
```

## How It Works

Ralph reads a structured task backlog (a JSON file with campaign metadata and tasks), picks the next task whose dependencies are satisfied, builds a self-contained prompt with inlined spec context, and invokes `claude -p --model sonnet`. After each successful task, it auto-commits the output. Once all build tasks complete, it enters a convergence loop to get lint, types, and tests passing.

```
tasks file ──> ralph.sh ──> claude -p ──> files + git commit
                  │                            │
                  └── next task <── validate <──┘
```

### Build Phase

Each iteration:

1. Read the tasks file, find next pending task with all dependencies met
2. Build a prompt: task description + inlined spec files (< 50KB each) + existing code context
3. Run `claude -p --model sonnet --dangerously-skip-permissions`
4. Check output for `BLOCKED:` or `WARNING:` signals
5. Run task-specific validation (e.g., `python3 -c "from module import function"`)
6. On success: mark done, `git commit`. On failure: retry up to 3 times, then mark blocked.

### Convergence Phase (3 stages)

After all build tasks complete:

| Stage | Tool | Strategy |
|-------|------|----------|
| 1. Format | `ruff format` | Deterministic auto-fix, single pass |
| 2. Lint + Types | `ruff check` + `mypy --strict` | Feed errors to Claude for fixes, up to 10 iterations |
| 3. Tests | `pytest` (campaign-specific) | Identify worst-failing file, feed to Claude, fix source only (tests are immutable). Stall detection after 3 iterations without improvement. Up to 30 iterations. |

The test command and lint/mypy paths are read from the campaign's `convergence` config in the tasks file.

## Campaigns

A campaign is a complete task backlog with metadata. Each tasks file has this structure:

```json
{
  "campaign": "unit",
  "description": "Build production code + unit tests from spec",
  "convergence": {
    "test_cmd": "PYTHONPATH=lambdas/shared/python pytest tests/unit/ -v --tb=short",
    "lint_paths": ["lambdas/", "tests/"],
    "mypy_paths": ["lambdas/shared/python/shared/", "lambdas/discovery/", ...]
  },
  "tasks": [...]
}
```

### Unit Campaign (`tasks.json`)

Builds all production code and unit tests from the implementation spec.

| Phase | Tasks | What Gets Built |
|-------|-------|-----------------|
| 0 — Scaffolding | 1 | `pyproject.toml`, `.gitignore`, directory structure, `__init__.py` files |
| 1 — Shared Layer | 4 | `shared/types.py`, `logging.py`+`tracing.py`+`metrics.py`, `bedrock.py`, `db.py`+`s3.py`, `__init__.py` |
| 2 — Pipeline Handlers | 7 | Discovery, Research, Script, Producer, Cover Art, TTS, Post-Production (handler + prompt each) |
| 3 — Auxiliary | 7 | Site handler + templates, SQL schema, build scripts, CI workflow, Terraform (3 groups) |
| 4 — MCP Server | 9 | Handler, resources, `__init__.py`, 6 tool modules (pipeline, agents, observation, data, assets, site) |
| 5 — Unit Tests | 14 | conftest, 3 shared tests, 7 handler tests, MCP conftest + 3 MCP test groups |
| **Total** | **42** | **78 files** |

**Convergence:** `pytest tests/unit/` — tests are immutable, source code is fixed to match.

**Status:** Complete. 42/42 tasks done, 297 unit tests passing.

### Integration Campaign (`tasks-integration.json`)

Builds a Digital Twin Universe (DTU) for integration testing. The DTU provides behavioral clones of external HTTP APIs (Exa, GitHub, ElevenLabs) while using real AWS services (Bedrock Haiku, S3, Secrets Manager, RDS) for everything else.

| Phase | Tasks | What Gets Built |
|-------|-------|-----------------|
| 0 — Infrastructure | 1 | Dockerfile test dependencies |
| 1 — Shared Changes | 1 | `bedrock.py` configurable model ID |
| 2 — Twin Fixtures | 1 | Shared fixture data for twin servers |
| 3 — Twin Servers | 3 | GitHub API twin, Exa API twin, ElevenLabs API twin |
| 4 — Conftest | 1 | Integration test orchestration (DTU setup, URL redirect, cleanup) |
| 5 — Handler Tests | 7 | One integration test per handler |
| 6 — Chain Tests | 2 | Multi-handler pipeline flow tests |
| **Total** | **~16** | |

**Convergence:** `pytest tests/integration/ -m integration --timeout=120` — gated on AWS credentials. Skipped if `aws sts get-caller-identity` fails.

**Service boundary strategy:**

| Service | Strategy |
|---------|----------|
| Bedrock Claude | Real Haiku (`us.anthropic.claude-haiku-4-5-20251001-v1:0`) — cheap, real LLM reasoning |
| Exa API | HTTP twin (pytest-httpserver) — controlled search results |
| GitHub API | HTTP twin (pytest-httpserver) — fixture repos and users |
| ElevenLabs API | HTTP twin (pytest-httpserver) — returns silent MP3 |
| Postgres/RDS | Real production RDS — test data isolated by execution_id prefix |
| S3 | Real S3 — ephemeral test bucket per session |
| Secrets Manager | Real Secrets Manager — ephemeral test secrets per session |
| Nova Canvas | Mocked (no cheap tier) |

**Cost per run:** ~$0.03 (9 Bedrock Haiku calls). S3/Secrets Manager negligible.

## Task Conventions

Both campaigns follow the same task structure:

```json
{
  "id": "p2-discovery",
  "phase": 2,
  "name": "Discovery handler + prompt",
  "description": "Detailed instructions for Claude...",
  "output_files": ["lambdas/discovery/handler.py", "lambdas/discovery/prompts/discovery.md"],
  "spec_files": ["type-checking.md", "interface-contracts.md"],
  "context_files": ["lambdas/shared/python/shared/types.py"],
  "depends_on": ["p1-bedrock", "p1-db-s3"],
  "validation": "cd /workspaces/closed-loop-ai-podcast && python3 -c '...'",
  "status": "pending",
  "attempts": 0
}
```

| Field | Use |
|-------|-----|
| `id` | Unique task ID. Unit: `p{phase}-{name}`. Integration: `i{phase}-{name}`. |
| `phase` | Build order group (0 = first) |
| `spec_files` | Filenames in `docs/spec/` — inlined into the prompt if under 50KB |
| `context_files` | Relative paths to existing code — inlined so Claude sees current signatures |
| `depends_on` | Task IDs that must be `"done"` before this task runs |
| `validation` | Bash command run after Claude finishes; non-zero = retry |
| `status` | `pending` / `in_progress` / `done` / `blocked` |

## Files

| File | Purpose |
|------|---------|
| `ralph.sh` | Main orchestrator script |
| `tasks.json` | Unit campaign — 42 tasks |
| `tasks-integration.json` | Integration campaign — ~16 tasks |
| `ralph-{campaign}.log` | Append-only log (machine-parseable timestamps + task IDs) |
| `ralph-{campaign}-status.txt` | Human-readable snapshot (overwritten each iteration) |
| `ralph-{campaign}.pid` | PID file for stopping a detached run |
| `iterations/{campaign}/` | Full prompt + output per iteration (debug audit trail) |

All ralph artifacts are in `.gitignore`.

## Commands

```bash
./ralph.sh                                       # Run unit campaign
./ralph.sh --tasks tasks-integration.json        # Run integration campaign
./ralph.sh status                                # Unit campaign status
./ralph.sh --tasks tasks-integration.json status # Integration campaign status
./ralph.sh reset                                 # Reset unit campaign tasks
./ralph.sh --tasks tasks-integration.json reset  # Reset integration campaign tasks
```

### Stopping and Resuming

```bash
# Stop a detached run
kill $(cat ralph-unit.pid)
kill $(cat ralph-integration.pid)

# Resume — ralph picks up where it left off (completed tasks stay done)
./ralph.sh --tasks tasks-integration.json

# Full restart from scratch
./ralph.sh --tasks tasks-integration.json reset
./ralph.sh --tasks tasks-integration.json
```

Task state persists in the tasks file. Completed tasks stay `"done"` across restarts. Only pending tasks with satisfied dependencies get picked up.

## Monitoring

### Quick check

```bash
./ralph.sh --tasks tasks-integration.json status
```

Output:
```
=== RALPH WIGGUM STATUS ===
Campaign: integration
Updated:  2026-03-29T15:30:00Z
Phase:    running
Task:     i3-github-twin
Detail:   claude -p in progress

Progress: 5 / 16 done  |  0 blocked  |  11 remaining
```

### Live tail

```bash
tail -f ralph-integration.log
```

Log lines:
```
[2026-03-29T15:25:00Z] [integration] ITER 3 | Task: i2-fixtures (Twin fixture data) | DONE + committed
[2026-03-29T15:27:30Z] [integration] ITER 4 | Task: i3-github-twin (GitHub API twin) | claude exit code: 0
[2026-03-29T15:30:00Z] [integration] CONV-TEST 1 | 7 passed, 2 failed, 0 errors
```

### Debugging a failed iteration

Every iteration writes its full prompt and Claude's full output:

```bash
cat iterations/integration/iter-004-i3-github-twin.prompt
cat iterations/integration/iter-004-i3-github-twin.output
```

## Signals

Claude outputs these keywords to communicate status back to the bash loop:

| Signal | Meaning | Ralph's Response |
|--------|---------|------------------|
| _(none)_ | Task completed normally | Mark done, commit, move on |
| `BLOCKED: <reason>` | Spec contradiction prevents completion | Mark task blocked, log reason, skip to next |
| `WARNING: <concern>` | Completed but with concerns | Log warning, still mark done |

## Configuration

Edit these variables at the top of `ralph.sh`:

| Variable | Default | Purpose |
|----------|---------|---------|
| `MODEL` | `sonnet` | Claude model for all invocations |
| `MAX_TASK_RETRIES` | `3` | Retries per task before marking blocked |
| `MAX_CONVERGENCE` | `30` | Max pytest convergence iterations |
| `STALL_THRESHOLD` | `3` | Consecutive non-improving iterations before giving up |
| `SPEC_INLINE_MAX` | `51200` | Max spec file size (bytes) to inline in prompt |

Campaign-specific settings (convergence test command, lint paths, mypy paths) are defined in the tasks file's `convergence` object.

## Estimated Runtime

### Unit Campaign
| Phase | Tasks | Est. Iterations |
|-------|-------|-----------------|
| 0-1 Scaffold + Shared | 5 | ~6 |
| 2 Pipeline Handlers | 7 | ~10 |
| 3 Auxiliary | 7 | ~8 |
| 4 MCP Server | 9 | ~11 |
| 5 Unit Tests | 14 | ~17 |
| Convergence | — | ~10-25 |
| **Total** | **42** | **~52-77** |

At ~2-3 minutes per iteration, expect **2-4 hours total**.

### Integration Campaign
| Phase | Tasks | Est. Iterations |
|-------|-------|-----------------|
| 0-1 Infrastructure + Shared | 2 | ~3 |
| 2-3 Twin Fixtures + Servers | 4 | ~6 |
| 4 Conftest | 1 | ~2 |
| 5 Handler Tests | 7 | ~10 |
| 6 Chain Tests | 2 | ~4 |
| Convergence | — | ~5-15 |
| **Total** | **~16** | **~30-40** |

At ~2-3 minutes per iteration, expect **1-2 hours total**.

## Design Decisions

**Single agent, not parallel.** The shared layer is imported by every handler and test. Parallel agents writing to the same files would create constant merge conflicts. Sequential execution is more reliable and simpler to debug.

**Spec inlined in prompt, not read by agent.** For files under 50KB, inlining the spec directly guarantees Claude has the context. Saves 2-4 Read tool calls per iteration. Spec files are read fresh each iteration, so ongoing spec edits are picked up automatically.

**Tests are immutable during convergence.** Tests are transcribed from the spec and represent correct behavior. The convergence loop fixes source code to match tests, never the other way around. If a test is wrong, that requires human intervention.

**Auto-commit per task.** Every completed task gets its own git commit. Enables `git log --oneline` as a progress view and `git revert` for surgical rollback. Commits include the campaign name: `ralph[unit]: p2-discovery — Discovery handler + prompt`.

**Campaign isolation.** Each campaign gets its own log file, status file, PID file, and iterations directory. Running the unit and integration campaigns concurrently is not recommended (they share source files) but their state tracking is fully independent.

**Integration convergence is credential-gated.** Integration tests require AWS credentials for Bedrock, S3, Secrets Manager, and RDS. If `aws sts get-caller-identity` fails, convergence is skipped with a log message rather than failing the entire run. This means ralph can build the integration test code without credentials — actual test execution happens when credentials are available.
