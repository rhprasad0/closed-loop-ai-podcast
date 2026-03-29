from __future__ import annotations

import json
import os
import re
from typing import Any

from aws_lambda_powertools.utilities.typing import LambdaContext

from shared.bedrock import invoke_model
from shared.logging import get_logger
from shared.metrics import get_metrics
from shared.tracing import get_tracer
from shared.types import PipelineState, ScriptOutput

logger = get_logger("script")
tracer = get_tracer("script")
metrics = get_metrics("script")

# --- Module-level constants ---
MAX_SCRIPT_CHARACTERS: int = 5000

REQUIRED_SEGMENTS: list[str] = [
    "intro",
    "core_debate",
    "developer_deep_dive",
    "technical_appreciation",
    "hiring_manager",
    "outro",
]

SPEAKER_PATTERN: re.Pattern[str] = re.compile(r"^\*\*(?:Hype|Roast|Phil):\*\*\s+.+$")


def _load_system_prompt() -> str:
    """Read prompts/script.md from disk.

    Uses LAMBDA_TASK_ROOT (set by AWS Lambda runtime) to locate the prompt file,
    falling back to the handler's directory for local testing.
    """
    base_dir = os.environ.get("LAMBDA_TASK_ROOT", os.path.dirname(__file__))
    prompt_path = os.path.join(base_dir, "prompts", "script.md")
    with open(prompt_path) as f:
        return f.read()


def _build_user_message(event: PipelineState) -> str:
    """Assemble discovery + research + optional producer feedback into a user message.

    Extracts $.discovery.*, $.research.*, and (on retry) $.producer.feedback
    and $.producer.issues from the pipeline state. Returns a structured plain-text
    message with clear section headers.
    """
    discovery = event["discovery"]
    research = event["research"]
    metadata = event.get("metadata", {})
    script_attempt: int = metadata.get("script_attempt", 1)

    lines: list[str] = [
        f"Attempt {script_attempt}",
        "",
        "## Discovery Data",
        f"Repo URL: {discovery['repo_url']}",
        f"Repo Name: {discovery['repo_name']}",
        f"Description: {discovery['repo_description']}",
        f"Developer GitHub: {discovery['developer_github']}",
        f"Star Count: {discovery['star_count']}",
        f"Language: {discovery['language']}",
        f"Discovery Rationale: {discovery['discovery_rationale']}",
        f"Key Files: {', '.join(discovery['key_files'])}",
        "Technical Highlights:",
    ]
    for highlight in discovery["technical_highlights"]:
        lines.append(f"  - {highlight}")

    lines += [
        "",
        "## Research Data",
        f"Developer Name: {research['developer_name']}",
        f"Developer GitHub: {research['developer_github']}",
        f"Developer Bio: {research['developer_bio']}",
        f"Public Repos Count: {research['public_repos_count']}",
        f"Commit Patterns: {research['commit_patterns']}",
        f"Technical Profile: {research['technical_profile']}",
        "Notable Repos:",
    ]
    for repo in research["notable_repos"]:
        lines.append(
            f"  - {repo['name']} ({repo['language']}, {repo['stars']} stars): {repo['description']}"
        )

    lines.append("Interesting Findings:")
    for finding in research["interesting_findings"]:
        lines.append(f"  - {finding}")

    lines.append("Hiring Signals:")
    for signal in research["hiring_signals"]:
        lines.append(f"  - {signal}")

    # Include producer feedback on retries
    if script_attempt > 1 and "producer" in event:
        producer = event["producer"]
        lines += [
            "",
            "## Producer Feedback",
            f"Previous script was rejected. Feedback: {producer.get('feedback', '')}",
            "Issues to fix:",
        ]
        for issue in producer.get("issues", []):
            lines.append(f"  - {issue}")

    lines.append("")
    lines.append("Write the podcast script for this episode.")

    return "\n".join(lines)


def _parse_script_output(text: str) -> ScriptOutput:
    """Parse agent text response to ScriptOutput. Strips markdown fences, validates.

    Overwrites character_count with actual len(text) if the model miscounted.
    Raises ValueError if character_count >= 5000 or required fields/segments are wrong.
    """
    stripped = text.strip()
    if stripped.startswith("```"):
        lines = stripped.splitlines()
        lines = lines[1:]  # remove opening fence (```json or ```)
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        stripped = "\n".join(lines).strip()

    data: Any = json.loads(stripped)

    required_fields = [
        "text",
        "character_count",
        "segments",
        "featured_repo",
        "featured_developer",
        "cover_art_suggestion",
    ]
    for field in required_fields:
        if field not in data:
            raise ValueError(f"Missing required field: {field}")

    script_text: str = str(data["text"])

    # Overwrite character_count with actual length — LLMs frequently miscount
    actual_count = len(script_text)
    if actual_count >= MAX_SCRIPT_CHARACTERS:
        raise ValueError(
            f"character_count {actual_count} >= hard limit {MAX_SCRIPT_CHARACTERS}"
        )

    # Validate segments (exact match, order matters)
    segments: list[str] = list(data["segments"])
    if segments != REQUIRED_SEGMENTS:
        raise ValueError(f"segments must be exactly {REQUIRED_SEGMENTS}, got {segments}")

    # Warn (but do not raise) on lines that don't match the speaker pattern
    for i, line in enumerate(script_text.splitlines()):
        if line and not SPEAKER_PATTERN.match(line):
            logger.warning(
                "Script line does not match speaker pattern",
                extra={"line_number": i + 1, "line": line[:100]},
            )

    return ScriptOutput(
        text=script_text,
        character_count=actual_count,
        segments=segments,
        featured_repo=str(data["featured_repo"]),
        featured_developer=str(data["featured_developer"]),
        cover_art_suggestion=str(data["cover_art_suggestion"]),
    )


@logger.inject_lambda_context(clear_state=True)
@tracer.capture_lambda_handler
@metrics.log_metrics
def lambda_handler(event: PipelineState, context: LambdaContext) -> ScriptOutput:
    system_prompt = _load_system_prompt()
    metadata = event.get("metadata", {})
    execution_id: str = metadata.get("execution_id", "unknown")
    script_attempt: int = metadata.get("script_attempt", 1)
    logger.info(
        "Starting script generation",
        extra={"execution_id": execution_id, "script_attempt": script_attempt},
    )

    user_message = _build_user_message(event)
    result_text = invoke_model(user_message, system_prompt=system_prompt)

    output = _parse_script_output(result_text)
    logger.info(
        "Script generation complete",
        extra={
            "featured_repo": output["featured_repo"],
            "character_count": output["character_count"],
        },
    )
    return output
