from __future__ import annotations

import base64
import json
import os
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

from aws_lambda_powertools.utilities.typing import LambdaContext

from shared.bedrock import ToolDefinition, ToolExecutor, invoke_with_tools
from shared.logging import get_logger
from shared.metrics import get_metrics
from shared.tracing import get_tracer
from shared.types import NotableRepo, PipelineState, ResearchOutput

logger = get_logger("research")
tracer = get_tracer("research")
metrics = get_metrics("research")

# --- Tool definitions (module-level constant) ---
TOOL_DEFINITIONS: list[ToolDefinition] = [
    {
        "name": "get_github_user",
        "description": "Get a GitHub user's profile",
        "input_schema": {
            "type": "object",
            "properties": {
                "username": {"type": "string"},
            },
            "required": ["username"],
        },
    },
    {
        "name": "get_user_repos",
        "description": "Get a GitHub user's public repositories",
        "input_schema": {
            "type": "object",
            "properties": {
                "username": {"type": "string"},
                "sort": {"type": "string", "enum": ["updated", "pushed", "created"]},
                "per_page": {"type": "integer"},
            },
            "required": ["username"],
        },
    },
    {
        "name": "get_repo_details",
        "description": "Get details about a specific repository",
        "input_schema": {
            "type": "object",
            "properties": {
                "owner": {"type": "string"},
                "repo": {"type": "string"},
            },
            "required": ["owner", "repo"],
        },
    },
    {
        "name": "get_repo_readme",
        "description": "Get the README content of a repository",
        "input_schema": {
            "type": "object",
            "properties": {
                "owner": {"type": "string"},
                "repo": {"type": "string"},
            },
            "required": ["owner", "repo"],
        },
    },
    {
        "name": "search_repositories",
        "description": "Search GitHub repositories by query. Supports sorting by stars.",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Search query (e.g. 'user:username' or 'topic:ml')",
                },
                "sort": {"type": "string", "enum": ["stars", "forks", "updated"]},
                "per_page": {"type": "integer"},
            },
            "required": ["query"],
        },
    },
]

# --- GitHub API constants ---
GITHUB_USER_AGENT: str = "zerostars-research-agent"
GITHUB_TIMEOUT: int = 15  # seconds


def _load_system_prompt() -> str:
    """Read prompts/research.md from disk.

    Uses LAMBDA_TASK_ROOT (set by AWS Lambda runtime) to locate the prompt file,
    falling back to the handler's directory for local testing.
    """
    base_dir = os.environ.get("LAMBDA_TASK_ROOT", os.path.dirname(__file__))
    prompt_path = os.path.join(base_dir, "prompts", "research.md")
    with open(prompt_path) as f:
        return f.read()


def _execute_get_github_user(tool_input: dict[str, Any]) -> dict[str, Any]:
    """Call GitHub Users API. Returns curated field subset.

    Returns {"error": "..."} on HTTPError or socket.timeout.
    """
    username: str = tool_input["username"]
    url = f"https://api.github.com/users/{username}"
    req = urllib.request.Request(
        url,
        headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": GITHUB_USER_AGENT,
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=GITHUB_TIMEOUT) as resp:
            data: dict[str, Any] = json.loads(resp.read())
        return {
            "login": data["login"],
            "name": data["name"],
            "bio": data["bio"],
            "public_repos": data["public_repos"],
            "followers": data["followers"],
            "created_at": data["created_at"],
            "html_url": data["html_url"],
        }
    except (TimeoutError, urllib.error.HTTPError) as exc:
        return {"error": str(exc)}


def _execute_get_user_repos(tool_input: dict[str, Any]) -> list[dict[str, Any]] | dict[str, Any]:
    """Call GitHub user repos API. Returns curated array of repo objects on success,
    or {"error": "..."} dict on failure.
    """
    username: str = tool_input["username"]
    sort: str = tool_input.get("sort", "pushed")
    per_page: int = tool_input.get("per_page", 30)
    url = f"https://api.github.com/users/{username}/repos?sort={sort}&per_page={per_page}"
    req = urllib.request.Request(
        url,
        headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": GITHUB_USER_AGENT,
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=GITHUB_TIMEOUT) as resp:
            data: list[dict[str, Any]] = json.loads(resp.read())
        return [
            {
                "name": repo["name"],
                "description": repo["description"],
                "stargazers_count": repo["stargazers_count"],
                "language": repo["language"],
                "html_url": repo["html_url"],
                "pushed_at": repo["pushed_at"],
                "fork": repo["fork"],
            }
            for repo in data
        ]
    except (TimeoutError, urllib.error.HTTPError) as exc:
        return {"error": str(exc)}


def _execute_get_repo_details(tool_input: dict[str, Any]) -> dict[str, Any]:
    """Call GitHub repos API. Returns curated field subset.

    Returns {"error": "..."} on HTTPError or socket.timeout.
    """
    owner: str = tool_input["owner"]
    repo: str = tool_input["repo"]
    url = f"https://api.github.com/repos/{owner}/{repo}"
    req = urllib.request.Request(
        url,
        headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": GITHUB_USER_AGENT,
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=GITHUB_TIMEOUT) as resp:
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
            "updated_at": data["updated_at"],
            "html_url": data["html_url"],
        }
    except (TimeoutError, urllib.error.HTTPError) as exc:
        return {"error": str(exc)}


def _execute_get_repo_readme(tool_input: dict[str, Any]) -> dict[str, Any]:
    """Call GitHub README API. Base64-decodes the content field before returning.

    Returns {"content": <decoded_text>} on success, {"error": "..."} on failure.
    """
    owner: str = tool_input["owner"]
    repo: str = tool_input["repo"]
    url = f"https://api.github.com/repos/{owner}/{repo}/readme"
    req = urllib.request.Request(
        url,
        headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": GITHUB_USER_AGENT,
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=GITHUB_TIMEOUT) as resp:
            data: dict[str, Any] = json.loads(resp.read())
        decoded = base64.b64decode(data["content"]).decode()
        return {"content": decoded}
    except (TimeoutError, urllib.error.HTTPError) as exc:
        return {"error": str(exc)}


def _execute_search_repositories(tool_input: dict[str, Any]) -> dict[str, Any]:
    """Call GitHub search API. Returns curated {total_count, items} dict.

    Returns {"error": "..."} on HTTPError or socket.timeout.
    """
    query: str = tool_input["query"]
    sort: str = tool_input.get("sort", "stars")
    per_page: int = tool_input.get("per_page", 10)
    url = (
        f"https://api.github.com/search/repositories"
        f"?q={urllib.parse.quote(query)}&sort={sort}&per_page={per_page}"
    )
    req = urllib.request.Request(
        url,
        headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": GITHUB_USER_AGENT,
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=GITHUB_TIMEOUT) as resp:
            data: dict[str, Any] = json.loads(resp.read())
        return {
            "total_count": data["total_count"],
            "items": [
                {
                    "name": item["name"],
                    "full_name": item["full_name"],
                    "description": item["description"],
                    "stargazers_count": item["stargazers_count"],
                    "language": item["language"],
                    "html_url": item["html_url"],
                }
                for item in data["items"]
            ],
        }
    except (TimeoutError, urllib.error.HTTPError) as exc:
        return {"error": str(exc)}


def _execute_tool(tool_name: str, tool_input: dict[str, Any]) -> str:
    """Dispatch to the correct tool function, return JSON string."""
    result: dict[str, Any] | list[dict[str, Any]]
    if tool_name == "get_github_user":
        result = _execute_get_github_user(tool_input)
    elif tool_name == "get_user_repos":
        result = _execute_get_user_repos(tool_input)
    elif tool_name == "get_repo_details":
        result = _execute_get_repo_details(tool_input)
    elif tool_name == "get_repo_readme":
        result = _execute_get_repo_readme(tool_input)
    elif tool_name == "search_repositories":
        result = _execute_search_repositories(tool_input)
    else:
        result = {"error": f"Unknown tool: {tool_name}"}
    return json.dumps(result)


def _build_user_message(event: PipelineState) -> str:
    """Assemble discovery fields into a user message for the Research agent.

    Extracts $.discovery.developer_github, $.discovery.repo_name, and
    $.discovery.repo_url from the pipeline state. Returns structured
    plain-text with section headers.
    """
    discovery = event["discovery"]
    developer_github: str = discovery["developer_github"]
    repo_name: str = discovery["repo_name"]
    repo_url: str = discovery["repo_url"]

    return (
        f"Developer GitHub username: {developer_github}\n"
        f"Featured repository name: {repo_name}\n"
        f"Featured repository URL: {repo_url}\n"
        f"\n"
        f"Research this developer and produce the structured profile for this week's episode."
    )


def _parse_research_output(text: str) -> ResearchOutput:
    """Parse agent text response to ResearchOutput. Strips markdown fences, validates.

    Coerces public_repos_count from string to int if needed.
    Coerces null developer_bio to empty string.
    Validates notable_repos sub-objects have name, description, stars, language.
    Raises ValueError if required fields missing or validation fails.
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
        "developer_name",
        "developer_github",
        "developer_bio",
        "public_repos_count",
        "notable_repos",
        "commit_patterns",
        "technical_profile",
        "interesting_findings",
        "hiring_signals",
    ]
    for field in required_fields:
        if field not in data:
            raise ValueError(f"Missing required field: {field}")

    # Coerce public_repos_count from string to int if needed
    public_repos_count = int(data["public_repos_count"])

    # Coerce null developer_bio to empty string
    developer_bio: str = data["developer_bio"] if data["developer_bio"] is not None else ""

    # Validate notable_repos sub-objects
    notable_repos: list[NotableRepo] = []
    for i, repo in enumerate(data["notable_repos"]):
        for sub_field in ("name", "description", "stars", "language"):
            if sub_field not in repo:
                raise ValueError(f"notable_repos[{i}] missing required field: {sub_field}")
        notable_repos.append(
            NotableRepo(
                name=str(repo["name"]),
                description=str(repo["description"]) if repo["description"] is not None else "",
                stars=int(repo["stars"]),
                language=str(repo["language"]) if repo["language"] is not None else "Unknown",
            )
        )

    return ResearchOutput(
        developer_name=str(data["developer_name"]),
        developer_github=str(data["developer_github"]),
        developer_bio=developer_bio,
        public_repos_count=public_repos_count,
        notable_repos=notable_repos,
        commit_patterns=str(data["commit_patterns"]),
        technical_profile=str(data["technical_profile"]),
        interesting_findings=list(data["interesting_findings"]),
        hiring_signals=list(data["hiring_signals"]),
    )


@logger.inject_lambda_context(clear_state=True)
@tracer.capture_lambda_handler
@metrics.log_metrics
def lambda_handler(event: PipelineState, context: LambdaContext) -> ResearchOutput:
    system_prompt = _load_system_prompt()
    execution_id = event.get("metadata", {}).get("execution_id", "unknown")
    logger.info("Starting research", extra={"execution_id": execution_id})

    user_message = _build_user_message(event)
    tool_executor: ToolExecutor = _execute_tool
    result_text = invoke_with_tools(
        user_message=user_message,
        system_prompt=system_prompt,
        tools=TOOL_DEFINITIONS,
        tool_executor=tool_executor,
    )

    output = _parse_research_output(result_text)
    logger.info(
        "Research complete",
        extra={
            "developer_github": output["developer_github"],
            "public_repos_count": output["public_repos_count"],
        },
    )
    return output
