from __future__ import annotations

import json
import os
from typing import Any

from aws_lambda_powertools.utilities.typing import LambdaContext

from shared.bedrock import invoke_model
from shared.db import query
from shared.logging import get_logger
from shared.metrics import get_metrics
from shared.tracing import get_tracer
from shared.types import PipelineState, ProducerOutput

logger = get_logger("producer")
tracer = get_tracer("producer")
metrics = get_metrics("producer")

# --- Module-level constants ---
MAX_SCRIPT_CHARACTERS: int = 5000

BENCHMARK_QUERY: str = """
    SELECT e.script_text
    FROM episodes e
    LEFT JOIN episode_metrics em ON e.episode_id = em.episode_id
    ORDER BY COALESCE(em.views + em.likes * 2 + em.comments * 3 + em.shares * 5, 0) DESC,
             e.created_at DESC
    LIMIT 3
"""


def _load_system_prompt() -> str:
    """Read prompts/producer.md from disk.

    Uses LAMBDA_TASK_ROOT (set by AWS Lambda runtime) to locate the prompt file,
    falling back to the handler's directory for local testing.
    """
    base_dir = os.environ.get("LAMBDA_TASK_ROOT", os.path.dirname(__file__))
    prompt_path = os.path.join(base_dir, "prompts", "producer.md")
    with open(prompt_path) as f:
        return f.read()


def _fetch_benchmark_scripts() -> list[str]:
    """Fetch top-performing episode scripts from Postgres for quality calibration.

    Returns a list of 0-3 script_text strings, ordered by engagement score.
    Returns an empty list if no episodes exist yet or if the DB query fails.
    """
    try:
        rows = query(BENCHMARK_QUERY)
        return [str(row[0]) for row in rows]
    except Exception as exc:
        # Benchmark absence must not crash the evaluation — early pipeline runs have no episodes
        logger.warning("Failed to fetch benchmark scripts", extra={"error": str(exc)})
        return []


def _build_user_message(event: PipelineState, benchmarks: list[str]) -> str:
    """Assemble script + discovery + research + benchmarks into a user message.

    Extracts $.script.text, $.script.character_count, $.script.segments,
    $.discovery.repo_name, $.discovery.repo_description,
    $.research.hiring_signals from the pipeline state. Appends benchmark
    scripts (if any) in a clearly labeled section. Returns a structured
    plain-text message with clear section headers.
    """
    script = event["script"]
    discovery = event["discovery"]
    research = event["research"]

    lines: list[str] = [
        "## Script to Evaluate",
        f"Character Count: {script['character_count']}",
        f"Segments: {', '.join(script['segments'])}",
        "",
        "Script Text:",
        script["text"],
        "",
        "## Discovery Data",
        f"Repo Name: {discovery['repo_name']}",
        f"Repo Description: {discovery['repo_description']}",
        "",
        "## Research Data",
        "Hiring Signals:",
    ]
    for signal in research["hiring_signals"]:
        lines.append(f"  - {signal}")

    if benchmarks:
        lines += ["", "## Benchmark Scripts"]
        for i, benchmark in enumerate(benchmarks, start=1):
            lines += [f"### Benchmark {i}", benchmark, ""]

    lines.append("Evaluate this script and return your verdict as JSON.")

    return "\n".join(lines)


def _parse_producer_output(text: str) -> ProducerOutput:
    """Parse agent text response to ProducerOutput. Strips markdown fences, validates.

    Validates:
    - verdict is exactly "PASS" or "FAIL"
    - score is an integer 1-10 (coerces string to int)
    - FAIL verdicts must include feedback (str) and issues (list[str])
    - PASS verdicts may include notes (str)
    Raises ValueError if validation fails.
    """
    stripped = text.strip()
    if stripped.startswith("```"):
        lines = stripped.splitlines()
        lines = lines[1:]  # remove opening fence (```json or ```)
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        stripped = "\n".join(lines).strip()

    data: Any = json.loads(stripped)

    if "verdict" not in data:
        raise ValueError("Missing required field: verdict")
    if "score" not in data:
        raise ValueError("Missing required field: score")

    verdict: str = str(data["verdict"])
    if verdict not in ("PASS", "FAIL"):
        raise ValueError(f"verdict must be 'PASS' or 'FAIL', got {verdict!r}")

    # Coerce score from string to int if needed
    score: int = int(data["score"])
    if not 1 <= score <= 10:
        raise ValueError(f"score must be 1-10, got {score}")

    output = ProducerOutput(verdict=verdict, score=score)

    if verdict == "FAIL":
        if "feedback" not in data:
            raise ValueError("FAIL verdict must include 'feedback' field")
        if "issues" not in data:
            raise ValueError("FAIL verdict must include 'issues' field")
        output["feedback"] = str(data["feedback"])
        output["issues"] = [str(issue) for issue in data["issues"]]
    else:
        # PASS may optionally include notes
        if "notes" in data:
            output["notes"] = str(data["notes"])

    return output


@logger.inject_lambda_context(clear_state=True)
@tracer.capture_lambda_handler
@metrics.log_metrics
def lambda_handler(event: PipelineState, context: LambdaContext) -> ProducerOutput:
    system_prompt = _load_system_prompt()
    metadata = event.get("metadata", {})
    execution_id: str = metadata.get("execution_id", "unknown")
    logger.info("Starting producer evaluation", extra={"execution_id": execution_id})

    benchmarks = _fetch_benchmark_scripts()
    user_message = _build_user_message(event, benchmarks)
    result_text = invoke_model(
        user_message=user_message,
        system_prompt=system_prompt,
    )

    output = _parse_producer_output(result_text)
    logger.info(
        "Producer evaluation complete",
        extra={"verdict": output["verdict"], "score": output["score"]},
    )
    return output
