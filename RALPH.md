# Ralph Wiggum Build System

Autonomous build orchestrator that implements the entire "0 Stars, 10/10" codebase from spec using `claude -p --model sonnet` in a loop.

Named after the [Ralph Wiggum technique](https://mail.risoluto.it/en/news/151/ralph-wiggum-claude-code-bash-loop-coding-agent) — a bash loop that repeatedly invokes Claude Code in pipe mode until a codebase converges.

## Quick Start

```bash
# Run in foreground (watch it work)
./ralph.sh

# Run detached (walk away, check later)
nohup ./ralph.sh > /dev/null 2>&1 &

# Check progress
./ralph.sh status

# Watch live
tail -f ralph.log
```

## How It Works

Ralph reads a structured task backlog (`tasks.json`), picks the next task whose dependencies are satisfied, builds a self-contained prompt with inlined spec context, and invokes `claude -p --model sonnet`. After each successful task, it auto-commits the output. Once all 42 build tasks complete, it enters a 3-stage convergence loop to get lint, types, and unit tests passing.

```
tasks.json ──> ralph.sh ──> claude -p ──> files + git commit
                  │                            │
                  └── next task <── validate <──┘
```

### Build Phase (42 tasks)

Each iteration:

1. Read `tasks.json`, find next pending task with all dependencies met
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
| 3. Unit Tests | `pytest tests/unit/` | Identify worst-failing file, feed to Claude, fix source only (tests are immutable). Stall detection after 3 iterations without improvement. Up to 30 iterations. |

## Task Phases

| Phase | Tasks | What Gets Built |
|-------|-------|-----------------|
| 0 — Scaffolding | 1 | `pyproject.toml`, `.gitignore`, directory structure, `__init__.py` files |
| 1 — Shared Layer | 4 | `shared/types.py`, `logging.py`+`tracing.py`+`metrics.py`, `bedrock.py`, `db.py`+`s3.py`, `__init__.py` |
| 2 — Pipeline Handlers | 7 | Discovery, Research, Script, Producer, Cover Art, TTS, Post-Production (handler + prompt each) |
| 3 — Auxiliary | 7 | Site handler + templates, SQL schema, build scripts, CI workflow, Terraform (3 groups) |
| 4 — MCP Server | 9 | Handler, resources, `__init__.py`, 6 tool modules (pipeline, agents, observation, data, assets, site) |
| 5 — Unit Tests | 14 | conftest, 3 shared tests, 7 handler tests, MCP conftest + 3 MCP test groups |
| **Total** | **42** | **78 files** |

Dependencies are enforced: shared layer before handlers, handlers before tests, Terraform core before app resources, etc.

## Files

| File | Purpose |
|------|---------|
| `ralph.sh` | Main orchestrator script (~350 lines bash) |
| `tasks.json` | Structured backlog — 42 tasks with dependencies, spec refs, validation commands |
| `ralph.log` | Append-only log (machine-parseable timestamps + task IDs) |
| `ralph-status.txt` | Human-readable snapshot (overwritten each iteration) |
| `ralph.pid` | PID file for stopping a detached run |
| `iterations/` | Full prompt + output per iteration (debug audit trail) |

All ralph artifacts are in `.gitignore`.

## Commands

```bash
./ralph.sh              # Run the full build loop
./ralph.sh status       # Print current progress summary
./ralph.sh reset        # Reset all tasks to pending (for re-running)
```

### Stopping and Resuming

```bash
# Stop a detached run
kill $(cat ralph.pid)

# Resume — ralph picks up where it left off (completed tasks stay done)
./ralph.sh

# Full restart from scratch
./ralph.sh reset
./ralph.sh
```

Task state persists in `tasks.json`. Completed tasks stay `"done"` across restarts. Only pending tasks with satisfied dependencies get picked up.

## Monitoring

### Quick check

```bash
./ralph.sh status
```

Output:
```
=== RALPH WIGGUM STATUS ===
Updated: 2026-03-29T02:15:00Z
Phase:   running
Task:    p2-discovery
Detail:  claude -p in progress

Progress: 12 / 42 done  |  0 blocked  |  30 remaining
```

### Live tail

```bash
tail -f ralph.log
```

Log lines:
```
[2026-03-29T02:10:00Z] ITER 5 | Task: p1-bedrock (Shared Bedrock client) | DONE + committed
[2026-03-29T02:12:30Z] ITER 6 | Task: p1-db-s3 (Shared DB and S3 modules + __init__) | claude exit code: 0
[2026-03-29T02:14:00Z] CONV-TEST 3 | 142 passed, 8 failed, 0 errors
```

### Debugging a failed iteration

Every iteration writes its full prompt and Claude's full output:

```bash
# See what Claude was asked
cat iterations/iter-007-p2-research.prompt

# See what Claude produced
cat iterations/iter-007-p2-research.output
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
| `SPEC_INLINE_MAX` | `51200` | Max spec file size (bytes) to inline in prompt; larger files get a Read instruction |

## Editing tasks.json

Each task object:

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
  "validation": "python3 -c 'from lambdas.discovery.handler import lambda_handler'",
  "status": "pending",
  "attempts": 0
}
```

| Field | Use |
|-------|-----|
| `spec_files` | Filenames in `docs/spec/` — inlined into the prompt if under 50KB, otherwise Claude reads them via tool |
| `context_files` | Relative paths to existing code — inlined so Claude sees current signatures |
| `depends_on` | Task IDs that must be `"done"` before this task runs |
| `validation` | Bash command run after Claude finishes; non-zero = retry |
| `status` | `pending` / `in_progress` / `done` / `blocked` |

## Estimated Runtime

| Phase | Tasks | Est. Iterations |
|-------|-------|-----------------|
| 0–1 Scaffold + Shared | 5 | ~6 |
| 2 Pipeline Handlers | 7 | ~10 |
| 3 Auxiliary | 7 | ~8 |
| 4 MCP Server | 9 | ~11 |
| 5 Unit Tests | 14 | ~17 |
| 6 Convergence | — | ~10–25 |
| **Total** | **42** | **~52–77** |

At ~2–3 minutes per iteration, expect **2–4 hours total**.

## Design Decisions

**Single agent, not parallel.** The shared layer is imported by every handler and test. Parallel agents writing to the same files would create constant merge conflicts. Sequential execution is more reliable and simpler to debug.

**Spec inlined in prompt, not read by agent.** For files under 50KB, inlining the spec directly guarantees Claude has the context. Saves 2–4 Read tool calls per iteration. Spec files are read fresh each iteration, so ongoing spec edits are picked up automatically.

**Tests are immutable during convergence.** Tests are transcribed from the spec and represent correct behavior. The convergence loop fixes source code to match tests, never the other way around. If a test is wrong, that requires human intervention.

**Auto-commit per task.** Every completed task gets its own git commit. Enables `git log --oneline` as a progress view and `git revert` for surgical rollback.
