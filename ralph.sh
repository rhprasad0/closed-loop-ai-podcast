#!/usr/bin/env bash
set -euo pipefail

# ralph.sh — Ralph Wiggum build loop for "0 Stars, 10/10"
#
# Usage:
#   ./ralph.sh              Run build loop (foreground)
#   nohup ./ralph.sh &      Run detached
#   ./ralph.sh status       Print current status
#   ./ralph.sh reset        Reset all tasks to pending

PROJECT_ROOT="$(cd "$(dirname "$0")" && pwd)"
TASKS_FILE="$PROJECT_ROOT/tasks.json"
LOG_FILE="$PROJECT_ROOT/ralph.log"
STATUS_FILE="$PROJECT_ROOT/ralph-status.txt"
PID_FILE="$PROJECT_ROOT/ralph.pid"
ITER_DIR="$PROJECT_ROOT/iterations"
SPEC_DIR="$PROJECT_ROOT/docs/spec"
MODEL="sonnet"
MAX_TASK_RETRIES=3
MAX_CONVERGENCE=30
STALL_THRESHOLD=3
SPEC_INLINE_MAX=51200  # 50KB — inline specs under this size

# ── Subcommands ─────────────────────────────────────────────────
if [[ "${1:-}" == "status" ]]; then
    [[ -f "$STATUS_FILE" ]] && cat "$STATUS_FILE" || echo "Ralph has not started yet."
    exit 0
fi

if [[ "${1:-}" == "reset" ]]; then
    jq '[.[] | .status = "pending" | .attempts = 0]' "$TASKS_FILE" > tmp.$$.json
    mv tmp.$$.json "$TASKS_FILE"
    echo "All tasks reset to pending."
    exit 0
fi

# ── Setup ───────────────────────────────────────────────────────
mkdir -p "$ITER_DIR"
echo $$ > "$PID_FILE"

log() {
    local msg="[$(date -u +%Y-%m-%dT%H:%M:%SZ)] $*"
    echo "$msg" | tee -a "$LOG_FILE"
}

update_status() {
    local phase="$1" task_id="$2" detail="$3"
    local done_count pending_count blocked_count total_count
    done_count=$(jq '[.[] | select(.status == "done")] | length' "$TASKS_FILE")
    blocked_count=$(jq '[.[] | select(.status == "blocked")] | length' "$TASKS_FILE")
    pending_count=$(jq '[.[] | select(.status == "pending" or .status == "in_progress")] | length' "$TASKS_FILE")
    total_count=$(jq 'length' "$TASKS_FILE")

    cat > "$STATUS_FILE" <<EOF
=== RALPH WIGGUM STATUS ===
Updated: $(date -u +%Y-%m-%dT%H:%M:%SZ)
Phase:   $phase
Task:    $task_id
Detail:  $detail

Progress: $done_count / $total_count done  |  $blocked_count blocked  |  $pending_count remaining

Recent log:
$(tail -15 "$LOG_FILE" 2>/dev/null || echo "(no log yet)")
EOF
}

# ── Task helpers ────────────────────────────────────────────────
set_task_status() {
    local id="$1" status="$2"
    jq --arg id "$id" --arg s "$status" \
        '[.[] | if .id == $id then .status = $s else . end]' \
        "$TASKS_FILE" > tmp.$$.json && mv tmp.$$.json "$TASKS_FILE"
}

increment_attempts() {
    local id="$1"
    jq --arg id "$id" \
        '[.[] | if .id == $id then .attempts += 1 else . end]' \
        "$TASKS_FILE" > tmp.$$.json && mv tmp.$$.json "$TASKS_FILE"
}

get_attempts() {
    jq -r --arg id "$1" '.[] | select(.id == $id) | .attempts' "$TASKS_FILE"
}

# Return the next pending task whose dependencies are all done
get_next_task() {
    local task_ids
    task_ids=$(jq -r '.[] | select(.status == "pending") | .id' "$TASKS_FILE")
    for tid in $task_ids; do
        local deps_met=true
        local deps
        deps=$(jq -r --arg id "$tid" '.[] | select(.id == $id) | .depends_on[]?' "$TASKS_FILE")
        for dep in $deps; do
            local dep_status
            dep_status=$(jq -r --arg id "$dep" '.[] | select(.id == $id) | .status' "$TASKS_FILE")
            if [[ "$dep_status" != "done" ]]; then
                deps_met=false
                break
            fi
        done
        if $deps_met; then
            echo "$tid"
            return 0
        fi
    done
    echo ""
}

# ── Prompt builder ──────────────────────────────────────────────
build_prompt() {
    local task_id="$1"
    local task_json
    task_json=$(jq --arg id "$task_id" '.[] | select(.id == $id)' "$TASKS_FILE")

    local name description phase validation
    name=$(echo "$task_json" | jq -r '.name')
    description=$(echo "$task_json" | jq -r '.description')
    phase=$(echo "$task_json" | jq -r '.phase')
    validation=$(echo "$task_json" | jq -r '.validation // empty')

    # Build output file list
    local output_files
    output_files=$(echo "$task_json" | jq -r '.output_files[]?')

    # Inline small spec files, list large ones for agent to Read
    local spec_context=""
    local read_instructions=""
    local sf
    while IFS= read -r sf; do
        [[ -z "$sf" ]] && continue
        local full_path="$SPEC_DIR/$sf"
        if [[ -f "$full_path" ]]; then
            local fsize
            fsize=$(stat -c%s "$full_path" 2>/dev/null || stat -f%z "$full_path" 2>/dev/null)
            if [[ "$fsize" -lt "$SPEC_INLINE_MAX" ]]; then
                spec_context+="
=== SPEC: $sf ===
$(cat "$full_path")
=== END SPEC ===
"
            else
                read_instructions+="- $full_path ($((fsize / 1024))KB — use the Read tool to read relevant sections)
"
            fi
        fi
    done < <(echo "$task_json" | jq -r '.spec_files[]?')

    # Inline existing code context files
    local code_context=""
    while IFS= read -r cf; do
        [[ -z "$cf" ]] && continue
        local cf_path="$PROJECT_ROOT/$cf"
        if [[ -f "$cf_path" ]]; then
            code_context+="
=== EXISTING: $cf ===
$(cat "$cf_path")
=== END EXISTING ===
"
        fi
    done < <(echo "$task_json" | jq -r '.context_files[]?')

    # Assemble prompt
    cat <<PROMPT
You are building the "0 Stars, 10/10" podcast pipeline from its implementation spec.

## Task: $task_id — $name (Phase $phase)

$description

## Files to Create
$output_files

## Coding Rules
1. Python 3.12. Use mypy strict-compatible type annotations everywhere.
2. Ruff: line length 100, double quotes, isort import sorting (first-party = "lambdas,shared,tests").
3. Match function signatures, variable names, and types from the spec EXACTLY.
4. Every Lambda handler file must use Powertools Logger, Tracer, and Metrics decorators.
5. Do NOT create files not listed above. Do NOT modify files not listed above.
6. If the spec is ambiguous, make a reasonable choice and add a brief inline comment.

## Validation
${validation:-"No validation command for this task."}

## Spec Documents (inlined below)
$spec_context
${read_instructions:+
## Large Spec Files (use Read tool)
$read_instructions}

## Existing Code (for import/signature reference)
$code_context

## Signal Protocol
- If you complete the task successfully: just finish your work normally.
- If a spec contradiction prevents completion: print BLOCKED: <reason>
- If you have concerns but completed the work: print WARNING: <concern>
PROMPT
}

# ── Auto-commit ─────────────────────────────────────────────────
auto_commit() {
    local task_id="$1" name="$2"
    cd "$PROJECT_ROOT"

    # Stage only the output files for this task
    local output_files
    output_files=$(jq -r --arg id "$task_id" '.[] | select(.id == $id) | .output_files[]?' "$TASKS_FILE")

    local staged=false
    for f in $output_files; do
        if [[ -e "$PROJECT_ROOT/$f" ]]; then
            git add "$f"
            staged=true
        fi
    done

    # Also stage any files the agent may have created in the output directories
    for f in $output_files; do
        local dir
        dir=$(dirname "$f")
        if [[ -d "$PROJECT_ROOT/$dir" ]]; then
            git add "$dir/" 2>/dev/null || true
        fi
    done

    if $staged && ! git diff --cached --quiet 2>/dev/null; then
        git commit -m "$(cat <<EOF
ralph: $task_id — $name

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>
EOF
        )" 2>&1 || log "WARN | commit failed for $task_id"
    else
        log "WARN | no files to commit for $task_id"
    fi
}

# ── Run a single build task ─────────────────────────────────────
run_task() {
    local task_id="$1" iteration="$2"
    local prompt_file="$ITER_DIR/iter-$(printf '%03d' "$iteration")-${task_id}.prompt"
    local output_file="$ITER_DIR/iter-$(printf '%03d' "$iteration")-${task_id}.output"

    local name
    name=$(jq -r --arg id "$task_id" '.[] | select(.id == $id) | .name' "$TASKS_FILE")

    log "ITER $iteration | Task: $task_id ($name) | Building prompt..."
    set_task_status "$task_id" "in_progress"
    update_status "building" "$task_id" "generating prompt"

    build_prompt "$task_id" > "$prompt_file"

    log "ITER $iteration | Task: $task_id | Invoking claude -p --model $MODEL..."
    update_status "running" "$task_id" "claude -p in progress"

    local exit_code=0
    claude -p \
        --model "$MODEL" \
        --dangerously-skip-permissions \
        --no-session-persistence \
        < "$prompt_file" \
        > "$output_file" 2>&1 || exit_code=$?

    log "ITER $iteration | Task: $task_id | claude exit code: $exit_code"

    # Check for BLOCKED signal
    if grep -q "BLOCKED:" "$output_file"; then
        local reason
        reason=$(grep "BLOCKED:" "$output_file" | head -1)
        log "ITER $iteration | Task: $task_id | $reason"
        set_task_status "$task_id" "blocked"
        update_status "blocked" "$task_id" "$reason"
        return 1
    fi

    # Check for WARNING signal
    if grep -q "WARNING:" "$output_file"; then
        local warning
        warning=$(grep "WARNING:" "$output_file" | head -1)
        log "ITER $iteration | Task: $task_id | $warning"
    fi

    # Run validation if specified
    local validation
    validation=$(jq -r --arg id "$task_id" '.[] | select(.id == $id) | .validation // empty' "$TASKS_FILE")
    if [[ -n "$validation" ]]; then
        log "ITER $iteration | Task: $task_id | Validating: $validation"
        local val_exit=0
        eval "$validation" >> "$output_file" 2>&1 || val_exit=$?
        if [[ $val_exit -ne 0 ]]; then
            log "ITER $iteration | Task: $task_id | Validation FAILED (exit $val_exit)"
            increment_attempts "$task_id"
            local attempts
            attempts=$(get_attempts "$task_id")
            if [[ "$attempts" -ge "$MAX_TASK_RETRIES" ]]; then
                log "ITER $iteration | Task: $task_id | Max retries exceeded — BLOCKED"
                set_task_status "$task_id" "blocked"
                update_status "blocked" "$task_id" "validation failed after $MAX_TASK_RETRIES attempts"
                return 1
            fi
            set_task_status "$task_id" "pending"
            update_status "retry" "$task_id" "attempt $attempts/$MAX_TASK_RETRIES"
            return 1
        fi
    fi

    # Success — commit and mark done
    set_task_status "$task_id" "done"
    auto_commit "$task_id" "$name"
    log "ITER $iteration | Task: $task_id | DONE + committed"
    update_status "done" "$task_id" "completed and committed"
    return 0
}

# ── Convergence: Stage 1 — ruff format ──────────────────────────
run_convergence_format() {
    local iteration="$1"
    log "CONV-FMT | Running ruff format..."
    update_status "convergence" "ruff-format" "auto-formatting"

    cd "$PROJECT_ROOT"
    ruff format lambdas/ tests/ 2>&1 | tee "$ITER_DIR/iter-$(printf '%03d' "$iteration")-conv-format.output" || true

    if ! git diff --quiet 2>/dev/null; then
        git add lambdas/ tests/
        git commit -m "$(cat <<EOF
ralph: convergence — ruff format

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>
EOF
        )" 2>&1 || true
        log "CONV-FMT | Formatting changes committed"
    else
        log "CONV-FMT | No formatting changes needed"
    fi
}

# ── Convergence: Stage 2 — ruff check + mypy ────────────────────
run_convergence_lint() {
    local base_iteration="$1"
    local max_lint_iters=10
    local lint_iter=0

    while [[ $lint_iter -lt $max_lint_iters ]]; do
        lint_iter=$((lint_iter + 1))
        local ci=$((base_iteration + lint_iter))
        local output_file="$ITER_DIR/iter-$(printf '%03d' "$ci")-conv-lint.output"

        log "CONV-LINT $lint_iter | Running ruff check + mypy..."
        update_status "convergence" "lint-$lint_iter" "ruff check + mypy"

        cd "$PROJECT_ROOT"

        # Auto-fix what ruff can
        ruff check --fix lambdas/ tests/ 2>&1 > "$output_file" || true

        # Collect remaining lint errors
        local lint_errors=""
        lint_errors=$(ruff check lambdas/ tests/ 2>&1 || true)

        # Collect mypy errors
        local mypy_errors=""
        mypy_errors=$(PYTHONPATH=lambdas/shared/python mypy --strict \
            lambdas/shared/python/shared/ \
            lambdas/discovery/ lambdas/research/ lambdas/script/ \
            lambdas/producer/ lambdas/cover_art/ lambdas/tts/ \
            lambdas/post_production/ lambdas/site/ lambdas/mcp/ \
            2>&1 || true)

        echo "=== RUFF ===" >> "$output_file"
        echo "$lint_errors" >> "$output_file"
        echo "=== MYPY ===" >> "$output_file"
        echo "$mypy_errors" >> "$output_file"

        # Count errors
        local ruff_count mypy_count
        ruff_count=$(echo "$lint_errors" | grep -cE "^[a-zA-Z]" || true)
        mypy_count=$(echo "$mypy_errors" | grep -cE "^[a-zA-Z].*: error:" || true)

        log "CONV-LINT $lint_iter | ruff errors: $ruff_count, mypy errors: $mypy_count"

        if [[ $ruff_count -eq 0 && $mypy_count -eq 0 ]]; then
            # Commit any auto-fixes
            if ! git diff --quiet 2>/dev/null; then
                git add lambdas/ tests/
                git commit -m "$(cat <<EOF
ralph: convergence — lint/type fixes

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>
EOF
                )" 2>&1 || true
            fi
            log "CONV-LINT | All clear"
            return 0
        fi

        # Feed errors to claude for fixing
        local fix_prompt="$ITER_DIR/iter-$(printf '%03d' "$ci")-conv-lint.prompt"
        local fix_output="$ITER_DIR/iter-$(printf '%03d' "$ci")-conv-lint-fix.output"

        cat > "$fix_prompt" <<FIXPROMPT
You are fixing lint and type errors in the "0 Stars, 10/10" podcast pipeline.

## Errors to Fix

### Ruff Lint Errors ($ruff_count)
$lint_errors

### mypy Type Errors ($mypy_count)
$mypy_errors

## Rules
1. Fix the SOURCE code to resolve these errors. Do NOT modify test files.
2. Match the spec's type signatures exactly — read docs/spec/type-checking.md if unsure.
3. For ruff: fix import ordering, unused imports, line length, etc.
4. For mypy: add missing type annotations, fix type mismatches, add type: ignore only as last resort.
5. After fixing, run: cd $PROJECT_ROOT && ruff check lambdas/ tests/ && PYTHONPATH=lambdas/shared/python mypy --strict lambdas/shared/python/shared/
FIXPROMPT

        log "CONV-LINT $lint_iter | Invoking claude to fix $((ruff_count + mypy_count)) errors..."
        update_status "convergence" "lint-fix-$lint_iter" "fixing $((ruff_count + mypy_count)) errors"

        claude -p \
            --model "$MODEL" \
            --dangerously-skip-permissions \
            --no-session-persistence \
            < "$fix_prompt" \
            > "$fix_output" 2>&1 || true

        # Commit fixes
        if ! git diff --quiet 2>/dev/null; then
            git add lambdas/ tests/
            git commit -m "$(cat <<EOF
ralph: convergence — lint/type fix iter $lint_iter

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>
EOF
            )" 2>&1 || true
        fi
    done

    log "CONV-LINT | Max lint iterations ($max_lint_iters) reached"
    return 1
}

# ── Convergence: Stage 3 — pytest ────────────────────────────────
run_convergence_pytest() {
    local base_iteration="$1"
    local conv_iter=0
    local prev_fail_count=9999
    local stall_count=0

    while [[ $conv_iter -lt $MAX_CONVERGENCE ]]; do
        conv_iter=$((conv_iter + 1))
        local ci=$((base_iteration + conv_iter))
        local test_output="$ITER_DIR/iter-$(printf '%03d' "$ci")-conv-pytest.output"

        log "CONV-TEST $conv_iter | Running pytest..."
        update_status "convergence" "pytest-$conv_iter" "running unit tests"

        cd "$PROJECT_ROOT"
        local test_exit=0
        PYTHONPATH=lambdas/shared/python pytest tests/unit/ -v --tb=short \
            > "$test_output" 2>&1 || test_exit=$?

        # Parse results
        local pass_count fail_count error_count
        pass_count=$(grep -cE " PASSED" "$test_output" || true)
        fail_count=$(grep -cE " FAILED" "$test_output" || true)
        error_count=$(grep -cE " ERROR" "$test_output" || true)
        local total_fail=$((fail_count + error_count))

        log "CONV-TEST $conv_iter | $pass_count passed, $fail_count failed, $error_count errors"

        if [[ $total_fail -eq 0 ]]; then
            log "CONV-TEST | ALL TESTS PASS"
            update_status "COMPLETE" "all" "$pass_count tests passing"
            echo "RALPH_DONE" >> "$LOG_FILE"
            return 0
        fi

        # Stall detection
        if [[ $total_fail -ge $prev_fail_count ]]; then
            stall_count=$((stall_count + 1))
        else
            stall_count=0
        fi
        prev_fail_count=$total_fail

        if [[ $stall_count -ge $STALL_THRESHOLD ]]; then
            log "CONV-TEST | STALLED for $stall_count iterations ($total_fail failures remain)"
            update_status "BLOCKED" "convergence" "stalled at $total_fail failures for $stall_count iterations"
            return 1
        fi

        # Find worst-failing test file
        local worst_test
        worst_test=$(grep -E "FAILED|ERROR" "$test_output" \
            | sed -E 's#^(tests/unit/[^ :]+).*#\1#' \
            | sort | uniq -c | sort -rn | head -1 \
            | awk '{print $2}' || true)

        if [[ -z "$worst_test" ]]; then
            worst_test=$(grep -E "FAILED|ERROR" "$test_output" | head -1 || true)
            log "CONV-TEST $conv_iter | Could not identify worst test file"
            continue
        fi

        log "CONV-TEST $conv_iter | Targeting: $worst_test"

        # Map test file to source file
        local source_file=""
        local basename_noext
        basename_noext=$(basename "$worst_test" .py | sed 's/^test_//')

        if [[ "$worst_test" == *"test_shared/"* ]]; then
            source_file="lambdas/shared/python/shared/${basename_noext}.py"
        elif [[ "$worst_test" == *"test_mcp/"* ]]; then
            case "$basename_noext" in
                handler)   source_file="lambdas/mcp/handler.py" ;;
                resources) source_file="lambdas/mcp/resources.py" ;;
                *)         source_file="lambdas/mcp/tools/${basename_noext}.py" ;;
            esac
        else
            source_file="lambdas/${basename_noext}/handler.py"
        fi

        # Build fix prompt
        local fix_prompt="$ITER_DIR/iter-$(printf '%03d' "$ci")-conv-pytest.prompt"
        local fix_output="$ITER_DIR/iter-$(printf '%03d' "$ci")-conv-pytest-fix.output"

        local source_content=""
        if [[ -f "$PROJECT_ROOT/$source_file" ]]; then
            source_content="
=== SOURCE: $source_file ===
$(cat "$PROJECT_ROOT/$source_file")
=== END SOURCE ===
"
        fi

        local test_content=""
        if [[ -f "$PROJECT_ROOT/$worst_test" ]]; then
            test_content="
=== TEST: $worst_test ===
$(cat "$PROJECT_ROOT/$worst_test")
=== END TEST ===
"
        fi

        cat > "$fix_prompt" <<FIXPROMPT
You are fixing unit test failures in the "0 Stars, 10/10" podcast pipeline.

## Full Test Output
$(cat "$test_output")

## Focus File: $worst_test ($total_fail total failures across all files)

## Rules
1. Fix the SOURCE code to make the tests pass. The tests are the spec — do NOT modify test files.
2. If a test imports a function that doesn't exist, create it in the source file with the expected signature.
3. If a test asserts a specific return value, ensure the source returns exactly that.
4. Read any spec files you need for context (docs/spec/type-checking.md, docs/spec/interface-contracts.md).
5. After fixing, run: cd $PROJECT_ROOT && PYTHONPATH=lambdas/shared/python pytest $worst_test -v --tb=short

$source_content
$test_content
FIXPROMPT

        log "CONV-TEST $conv_iter | Invoking claude to fix $worst_test..."
        update_status "convergence" "fix-$conv_iter" "fixing $worst_test ($total_fail failures)"

        claude -p \
            --model "$MODEL" \
            --dangerously-skip-permissions \
            --no-session-persistence \
            < "$fix_prompt" \
            > "$fix_output" 2>&1 || true

        # Check for BLOCKED
        if grep -q "BLOCKED:" "$fix_output"; then
            local reason
            reason=$(grep "BLOCKED:" "$fix_output" | head -1)
            log "CONV-TEST $conv_iter | $reason"
        fi

        # Commit fixes
        if ! git diff --quiet 2>/dev/null; then
            git add lambdas/ tests/ 2>/dev/null || true
            git commit -m "$(cat <<EOF
ralph: convergence — pytest fix iter $conv_iter ($worst_test)

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>
EOF
            )" 2>&1 || true
        fi
    done

    log "CONV-TEST | Max iterations ($MAX_CONVERGENCE) reached with $prev_fail_count failures"
    update_status "BLOCKED" "convergence" "max pytest iterations reached ($prev_fail_count failures remain)"
    return 1
}

# ── Main ────────────────────────────────────────────────────────
main() {
    log "=========================================="
    log "RALPH WIGGUM STARTING"
    log "Project: $PROJECT_ROOT"
    log "Model:   $MODEL"
    log "=========================================="

    local iteration=0

    # Phase 0–5: Create all files
    while true; do
        local next_task
        next_task=$(get_next_task)

        if [[ -z "$next_task" ]]; then
            local pending blocked
            pending=$(jq '[.[] | select(.status == "pending")] | length' "$TASKS_FILE")
            blocked=$(jq '[.[] | select(.status == "blocked")] | length' "$TASKS_FILE")

            if [[ "$pending" -gt 0 ]]; then
                log "STUCK | $pending tasks pending with unmet deps, $blocked blocked"
                update_status "STUCK" "none" "$pending tasks have unmet deps ($blocked blocked)"
                break
            fi
            log "All build tasks complete. Starting convergence."
            break
        fi

        iteration=$((iteration + 1))
        run_task "$next_task" "$iteration" || true

        sleep 2  # Brief pause between iterations
    done

    # Convergence Stage 1: ruff format
    iteration=$((iteration + 1))
    run_convergence_format "$iteration"

    # Convergence Stage 2: ruff check + mypy
    run_convergence_lint "$iteration" || true

    # Convergence Stage 3: pytest
    iteration=$((iteration + 20))  # Reserve space for lint iterations in numbering
    run_convergence_pytest "$iteration" || true

    log "=========================================="
    log "RALPH WIGGUM FINISHED"
    log "=========================================="

    # Final status
    local done_count total_count
    done_count=$(jq '[.[] | select(.status == "done")] | length' "$TASKS_FILE")
    total_count=$(jq 'length' "$TASKS_FILE")
    update_status "FINISHED" "summary" "$done_count/$total_count tasks done"
}

main "$@"
