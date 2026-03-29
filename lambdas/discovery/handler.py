from __future__ import annotations

import json
import os
import socket
import urllib.error
import urllib.request
from typing import Any

import boto3
from aws_lambda_powertools.utilities.typing import LambdaContext

from shared.bedrock import ToolDefinition, ToolExecutor, invoke_with_tools
from shared.db import query as db_query
from shared.logging import get_logger
from shared.metrics import get_metrics
from shared.tracing import get_tracer
from shared.types import DiscoveryOutput, PipelineState

logger = get_logger("discovery")
tracer = get_tracer("discovery")
metrics = get_metrics("discovery")

# --- Module-level cached credentials ---
_exa_api_key: str | None = None

# --- Tool definitions (module-level constant) ---
TOOL_DEFINITIONS: list[ToolDefinition] = [
    {
        "name": "exa_search",
        "description": "Search for GitHub repositories and web content using Exa's neural search.",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Natural language search query"},
                "include_domains": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": 'Limit results to these domains (e.g. ["github.com"])',
                },
                "num_results": {
                    "type": "integer",
                    "description": "Number of results to return (max 10)",
                },
                "start_published_date": {
                    "type": "string",
                    "description": "ISO date, filter results after this date",
                },
                "exclude_text": {
                    "type": "string",
                    "description": "Exclude results containing this text",
                },
            },
            "required": ["query"],
        },
    },
    {
        "name": "query_postgres",
        "description": (
            "Run a read-only SQL query against the podcast database. "
            "Only SELECT statements are allowed. Returns rows as JSON."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "sql": {"type": "string", "description": "A SELECT SQL query to execute"}
            },
            "required": ["sql"],
        },
    },
    {
        "name": "get_github_repo",
        "description": (
            "Get metadata for a GitHub repository including star count, language, "
            "description, topics, and activity dates."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "owner": {"type": "string", "description": "Repository owner (GitHub username)"},
                "repo": {"type": "string", "description": "Repository name"},
            },
            "required": ["owner", "repo"],
        },
    },
]


def _get_exa_api_key() -> str:
    """Fetch Exa API key from Secrets Manager (zerostars/exa-api-key), cached across warm starts."""
    global _exa_api_key
    if _exa_api_key is None:
        client = boto3.client("secretsmanager")
        response = client.get_secret_value(SecretId="zerostars/exa-api-key")
        _exa_api_key = response["SecretString"]
    return _exa_api_key


def _load_system_prompt() -> str:
    """Read prompts/discovery.md from disk.

    Uses LAMBDA_TASK_ROOT (set by AWS Lambda runtime) to locate the prompt file,
    falling back to the handler's directory for local testing.
    """
    base_dir = os.environ.get("LAMBDA_TASK_ROOT", os.path.dirname(__file__))
    prompt_path = os.path.join(base_dir, "prompts", "discovery.md")
    with open(prompt_path) as f:
        return f.read()


def _execute_exa_search(tool_input: dict[str, Any]) -> dict[str, Any]:
    """Call Exa API. Maps snake_case keys to camelCase. Returns parsed JSON."""
    api_key = _get_exa_api_key()

    # Generic snake_case -> camelCase translation for all tool input keys
    def to_camel(key: str) -> str:
        parts = key.split("_")
        return parts[0] + "".join(p.capitalize() for p in parts[1:])

    body: dict[str, Any] = {to_camel(k): v for k, v in tool_input.items()}
    # Always request text content regardless of agent input
    body["contents"] = {"text": True}

    req = urllib.request.Request(
        "https://api.exa.ai/search",
        data=json.dumps(body).encode(),
        headers={
            "Content-Type": "application/json",
            "x-api-key": api_key,
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        result: dict[str, Any] = json.loads(resp.read())
    return result


def _execute_query_postgres(tool_input: dict[str, Any]) -> dict[str, Any]:
    """Run read-only SQL via shared/db.py. Returns {"rows": ...} or {"error": ...}."""
    sql: str = tool_input.get("sql", "")
    # Enforce read-only: only SELECT statements allowed
    if not sql.lstrip().upper().startswith("SELECT"):
        return {"error": "Only SELECT statements are allowed."}
    try:
        rows = db_query(sql)
        # Convert tuple rows to dicts — we don't have cursor.description here, so
        # return as lists of values (the agent will interpret positional values).
        # For exclusion queries the agent issues (e.g. SELECT col FROM table),
        # single-column results as flat lists are the most usable form.
        serializable_rows = [list(row) for row in rows]
        return {"rows": serializable_rows}
    except Exception as exc:
        return {"error": str(exc)[:500]}


def _execute_get_github_repo(tool_input: dict[str, Any]) -> dict[str, Any]:
    """Call GitHub REST API. Returns curated field subset."""
    owner: str = tool_input["owner"]
    repo: str = tool_input["repo"]
    url = f"https://api.github.com/repos/{owner}/{repo}"
    req = urllib.request.Request(
        url,
        headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": "zerostars-discovery-agent",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            data: dict[str, Any] = json.loads(resp.read())
        return {
            "name": data["name"],
            "full_name": data["full_name"],
            "description": data["description"],
            "stargazers_count": data["stargazers_count"],
            "forks_count": data["forks_count"],
            "language": data["language"],
            "topics": data["topics"],
            "created_at": data["created_at"],
            "pushed_at": data["pushed_at"],
            "open_issues_count": data["open_issues_count"],
            "license": data["license"]["spdx_id"] if data["license"] else None,
            "owner_type": data["owner"]["type"],
            "html_url": data["html_url"],
            "default_branch": data["default_branch"],
        }
    except (urllib.error.HTTPError, socket.timeout) as exc:
        return {"error": str(exc)}


def _execute_tool(tool_name: str, tool_input: dict[str, Any]) -> str:
    """Dispatch to the correct tool function, return JSON string."""
    result: dict[str, Any]
    if tool_name == "exa_search":
        result = _execute_exa_search(tool_input)
    elif tool_name == "query_postgres":
        result = _execute_query_postgres(tool_input)
    elif tool_name == "get_github_repo":
        result = _execute_get_github_repo(tool_input)
    else:
        result = {"error": f"Unknown tool: {tool_name}"}
    return json.dumps(result)


def _parse_discovery_output(text: str) -> DiscoveryOutput:
    """Parse agent text response to DiscoveryOutput. Strips markdown fences, validates."""
    # Strip markdown code fences if present
    stripped = text.strip()
    if stripped.startswith("```"):
        lines = stripped.splitlines()
        # Remove opening fence (```json or ```)
        lines = lines[1:]
        # Remove closing fence
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        stripped = "\n".join(lines).strip()

    data: Any = json.loads(stripped)

    required_fields = [
        "repo_url",
        "repo_name",
        "repo_description",
        "developer_github",
        "star_count",
        "language",
        "discovery_rationale",
        "key_files",
        "technical_highlights",
    ]
    for field in required_fields:
        if field not in data:
            raise ValueError(f"Missing required field: {field}")

    # Coerce star_count to int if returned as string
    star_count = int(data["star_count"])
    if star_count >= 10:
        raise ValueError(f"star_count must be under 10, got {star_count}")

    repo_url: str = data["repo_url"]
    if not repo_url.startswith("https://github.com/"):
        raise ValueError(f"repo_url must start with https://github.com/, got {repo_url!r}")

    return DiscoveryOutput(
        repo_url=repo_url,
        repo_name=str(data["repo_name"]),
        repo_description=str(data["repo_description"]),
        developer_github=str(data["developer_github"]),
        star_count=star_count,
        language=str(data["language"]),
        discovery_rationale=str(data["discovery_rationale"]),
        key_files=list(data["key_files"]),
        technical_highlights=list(data["technical_highlights"]),
    )


@logger.inject_lambda_context(clear_state=True)
@tracer.capture_lambda_handler  # type: ignore[misc]
@metrics.log_metrics  # type: ignore[misc]
def lambda_handler(event: PipelineState, context: LambdaContext) -> DiscoveryOutput:
    system_prompt = _load_system_prompt()
    execution_id = event.get("metadata", {}).get("execution_id", "unknown")
    logger.info("Starting discovery", extra={"execution_id": execution_id})

    tool_executor: ToolExecutor = _execute_tool
    result_text = invoke_with_tools(
        user_message="Find one underrated GitHub repository to feature on this week's episode.",
        system_prompt=system_prompt,
        tools=TOOL_DEFINITIONS,
        tool_executor=tool_executor,
    )

    output = _parse_discovery_output(result_text)
    logger.info(
        "Discovery complete",
        extra={"repo_url": output["repo_url"], "star_count": output["star_count"]},
    )
    return output
