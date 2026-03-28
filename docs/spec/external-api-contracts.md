> Part of the [Implementation Spec](../../IMPLEMENTATION_SPEC.md)

# External API Contracts

Exact endpoints, request/response formats, and credentials for every external service the pipeline calls.

### AWS Bedrock — Claude (Agent Reasoning)

Used by: Discovery, Research, Script, Producer Lambdas.

```python
# Via shared/bedrock.py
import boto3
import json

client = boto3.client("bedrock-runtime")

# Basic invocation (Script, Producer)
response = client.invoke_model(
    modelId="us.anthropic.claude-sonnet-4-6",
    contentType="application/json",
    accept="application/json",
    body=json.dumps({
        "anthropic_version": "bedrock-2023-05-31",
        "max_tokens": 4096,
        "system": system_prompt,
        "messages": [
            {"role": "user", "content": user_prompt}
        ]
    })
)
result = json.loads(response["body"].read())
text = result["content"][0]["text"]

# With tool use (Discovery, Research) — agentic loop via shared/bedrock.py
#
# The invoke_with_tools() function takes a tool_executor callback so each
# Lambda provides its own tool implementations. This keeps bedrock.py generic.
#
# Signature:
#   invoke_with_tools(
#       user_message: str,
#       system_prompt: str,
#       tools: list[dict],
#       tool_executor: Callable[[str, dict], str],  # (tool_name, tool_input) -> JSON string
#       model_id: str = DEFAULT_MODEL_ID,
#       max_turns: int = 25,  # safety valve on loop iterations
#   ) -> str
#
# The function loops internally:
#   1. Invoke Bedrock with tools
#   2. If stop_reason == "tool_use": extract tool_use blocks, call tool_executor
#      for each, append tool_result messages, re-invoke
#   3. If stop_reason == "end_turn": return the text response
#   4. Retry on ThrottlingException with exponential backoff (3 retries, 1s base)
#
# Example handler usage (Discovery):

from shared.bedrock import invoke_with_tools

def _execute_tool(tool_name: str, tool_input: dict) -> str:
    """Dispatch to the right tool function, return JSON string."""
    if tool_name == "exa_search":
        result = _execute_exa_search(tool_input)
    elif tool_name == "query_postgres":
        result = _execute_query_postgres(tool_input)
    elif tool_name == "get_github_repo":
        result = _execute_get_github_repo(tool_input)
    else:
        result = {"error": f"Unknown tool: {tool_name}"}
    return json.dumps(result)

result_text = invoke_with_tools(
    user_message="Find one underrated GitHub repository to feature.",
    system_prompt=system_prompt,
    tools=TOOL_DEFINITIONS,
    tool_executor=_execute_tool,
)

# Tool errors should return {"error": "..."} dicts instead of raising,
# so the agent sees errors and can adapt (retry, pick a different candidate).

# The underlying Bedrock API call is invoke_model with the Anthropic
# Messages API body format — tools array in the body, stop_reason in response:
response = client.invoke_model(
    modelId="us.anthropic.claude-sonnet-4-6",
    contentType="application/json",
    accept="application/json",
    body=json.dumps({
        "anthropic_version": "bedrock-2023-05-31",
        "max_tokens": 4096,
        "system": system_prompt,
        "messages": messages,
        "tools": tool_definitions
    })
)
result = json.loads(response["body"].read())
# result["stop_reason"] is "tool_use" or "end_turn"
# result["content"] contains text blocks and/or tool_use blocks
```

### AWS Bedrock — Nova Canvas (Cover Art)

Used by: Cover Art Lambda.

**Client configuration:** The boto3 Bedrock Runtime client must be created with `read_timeout=300` (via `botocore.config.Config`). The default 60-second timeout is too short for Nova Canvas image generation per AWS documentation.

```python
from botocore.config import Config

client = boto3.client("bedrock-runtime", config=Config(read_timeout=300))

response = client.invoke_model(
    modelId="amazon.nova-canvas-v1:0",
    contentType="application/json",
    accept="application/json",
    body=json.dumps({
        "taskType": "TEXT_IMAGE",
        "textToImageParams": {
            "text": cover_art_prompt  # 1-1024 characters (hard limit)
        },
        "imageGenerationConfig": {
            "numberOfImages": 1,
            "width": 1024,
            "height": 1024,
            "quality": "standard"
        }
    })
)
result = json.loads(response["body"].read())
# Check for RAI policy error — images may be filtered or absent
if result.get("error"):
    raise RuntimeError(f"Nova Canvas RAI policy: {result['error']}")
image_bytes = base64.b64decode(result["images"][0])
```

**Request body fields:**

| Field | Type | Required | Constraint | Default |
|-------|------|----------|------------|---------|
| `taskType` | string | yes | `"TEXT_IMAGE"` | — |
| `textToImageParams.text` | string | yes | **1-1024 characters** | — |
| `textToImageParams.negativeText` | string | no | 1-1024 characters | — |
| `textToImageParams.style` | string | no | One of 8 presets (not used in v1) | — |
| `imageGenerationConfig.numberOfImages` | int | no | 1-5 | 1 |
| `imageGenerationConfig.width` | int | no | 320-4096, divisible by 16 | 1024 |
| `imageGenerationConfig.height` | int | no | 320-4096, divisible by 16 | 1024 |
| `imageGenerationConfig.quality` | string | no | `"standard"` or `"premium"` | `"standard"` |
| `imageGenerationConfig.cfgScale` | float | no | 1.1-10.0 | 6.5 |
| `imageGenerationConfig.seed` | int | no | 0-2,147,483,646 | 12 |

**Resolution constraints:** Each side 320-4096px, divisible by 16, aspect ratio between 1:4 and 4:1, total pixels < 4,194,304.

**Response body:**

```json
{
    "images": ["<base64-encoded PNG>"],
    "error": "string (present only when RAI flags the image)"
}
```

The `images` array may contain fewer entries than `numberOfImages` if some are blocked by AWS Responsible AI content moderation. The `error` field is present only when at least one image was flagged.

### ElevenLabs — Text-to-Dialogue (TTS)

Used by: TTS Lambda.

```
POST https://api.elevenlabs.io/v1/text-to-dialogue?output_format=mp3_44100_128
Headers:
  Content-Type: application/json
  xi-api-key: <from Secrets Manager>

Request body:
{
  "inputs": [
    {"text": "First speaker's line", "voice_id": "cjVigY5qzO86Huf0OWal"},
    {"text": "Second speaker's line", "voice_id": "JBFqnCBsd6RMkjVDRZzb"},
    ...
  ],
  "model_id": "eleven_v3"
}

Response: Raw MP3 binary (on 200 OK)
Error: JSON body with "detail" field (on 4xx/5xx)
```

**Voice IDs:**

| Persona | Voice Name | Voice ID |
|---------|------------|----------|
| Hype | Eric | `cjVigY5qzO86Huf0OWal` |
| Roast | George | `JBFqnCBsd6RMkjVDRZzb` |
| Phil | Jessica | `cgSgspJ2msm6clMCkdW9` |

**Hard constraint:** 5,000 character limit across all `text` fields combined.

### Exa Search API

Used by: Discovery Lambda (via Bedrock tool use).

The Discovery agent uses Bedrock's tool-use capability to call Exa. Define Exa search as a tool in the Bedrock request:

```json
{
  "name": "exa_search",
  "description": "Search for GitHub repositories and web content using Exa's neural search.",
  "input_schema": {
    "type": "object",
    "properties": {
      "query": {"type": "string", "description": "Natural language search query"},
      "include_domains": {"type": "array", "items": {"type": "string"}, "description": "Limit results to these domains (e.g. [\"github.com\"])"},
      "num_results": {"type": "integer", "description": "Number of results to return (max 10)"},
      "start_published_date": {"type": "string", "description": "ISO date, filter results after this date"},
      "exclude_text": {"type": "string", "description": "Exclude results containing this text"}
    },
    "required": ["query"]
  }
}
```

When Bedrock returns a `tool_use` block for `exa_search`, the Lambda translates snake_case tool inputs to camelCase and executes the actual Exa API call:

```
POST https://api.exa.ai/search
Headers:
  Content-Type: application/json
  x-api-key: <from Secrets Manager>

Request body:
{
  "query": "...",
  "includeDomains": ["github.com"],
  "numResults": 10,
  "startPublishedDate": "2024-01-01",
  "contents": {
    "text": true
  }
}

Response (200 OK):
{
  "requestId": "...",
  "results": [
    {
      "title": "owner/repo-name",
      "url": "https://github.com/owner/repo-name",
      "id": "...",
      "publishedDate": "2024-06-15T00:00:00.000Z",
      "author": "...",
      "text": "README and repo description text..."
    }
  ]
}
```

### Discovery Postgres Tool (`query_postgres`)

Used by: Discovery Lambda (via Bedrock tool use).

The Discovery agent queries Postgres directly through a `psql` subprocess to check whether candidate projects/developers have already been featured. The `psql` binary is provided by the psql Lambda layer (see [Lambda Packaging & Deployment](./packaging-and-deployment.md)).

**Tool definition for Bedrock:**

```json
{
  "name": "query_postgres",
  "description": "Run a read-only SQL query against the podcast database. Only SELECT statements are allowed. Returns rows as pipe-delimited text.",
  "input_schema": {
    "type": "object",
    "properties": {
      "sql": {"type": "string", "description": "A SELECT SQL query to execute"}
    },
    "required": ["sql"]
  }
}
```

**Handler implementation:** When Bedrock returns a `tool_use` block for `query_postgres`, the handler:

1. **Enforces read-only:** Checks that the SQL starts with `SELECT` (case-insensitive, after stripping whitespace). Rejects INSERT, UPDATE, DELETE, DROP, etc. with an error.
2. **Fetches connection string:** From SSM Parameter Store at `/zerostars/db-connection-string` with `WithDecryption=True`. Cached in a module-level global across warm invocations.
3. **Runs psql subprocess:**

```python
result = subprocess.run(
    ["/opt/bin/psql", conn_str, "-c", sql, "--no-align", "--tuples-only", "--pset", "null=(null)"],
    capture_output=True, text=True, timeout=15,
)
```

- `--no-align --tuples-only` strips headers and alignment, producing clean pipe-delimited output the model can parse.
- `--pset null=(null)` renders NULL as literal `(null)` instead of empty string.
- Timeout of 15 seconds prevents runaway queries from consuming the Lambda's 300s budget.
- On psql error, returns `{"error": "<stderr truncated to 500 chars>"}`.
- On success, returns `{"rows": "<stdout>"}`.

### Discovery GitHub Tool (`get_github_repo`)

Used by: Discovery Lambda (via Bedrock tool use).

The Discovery agent uses this tool to verify star counts and repo metadata before selecting a candidate. This is critical — Exa search results do not include exact star counts.

**Tool definition for Bedrock:**

```json
{
  "name": "get_github_repo",
  "description": "Get metadata for a GitHub repository including star count, language, description, topics, and activity dates.",
  "input_schema": {
    "type": "object",
    "properties": {
      "owner": {"type": "string", "description": "Repository owner (GitHub username)"},
      "repo": {"type": "string", "description": "Repository name"}
    },
    "required": ["owner", "repo"]
  }
}
```

**Handler implementation:** When Bedrock returns a `tool_use` block for `get_github_repo`, the handler calls the GitHub REST API:

```
GET https://api.github.com/repos/{owner}/{repo}
Headers:
  Accept: application/vnd.github.v3+json
  User-Agent: zerostars-discovery-agent
```

The `User-Agent` header is required — GitHub returns 403 without it. No auth key needed (public API, rate limited to 60 req/hour unauthenticated).

The handler returns a curated subset of the response (the full GitHub response is ~3KB and would inflate the Bedrock conversation):

```python
{
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
    "owner_type": data["owner"]["type"],  # "User" vs "Organization"
    "html_url": data["html_url"],
    "default_branch": data["default_branch"],
}
```

### GitHub API

Used by: Discovery Lambda (`get_github_repo` tool) and Research Lambda (via Bedrock tool use).

Public API, no auth key needed (rate limited to 60 req/hour for unauthenticated).

Tools defined for Bedrock:

```json
[
  {
    "name": "get_github_user",
    "description": "Get a GitHub user's profile",
    "input_schema": {
      "type": "object",
      "properties": {
        "username": {"type": "string"}
      },
      "required": ["username"]
    }
  },
  {
    "name": "get_user_repos",
    "description": "Get a GitHub user's public repositories",
    "input_schema": {
      "type": "object",
      "properties": {
        "username": {"type": "string"},
        "sort": {"type": "string", "enum": ["updated", "pushed", "created"]},
        "per_page": {"type": "integer"}
      },
      "required": ["username"]
    }
  },
  {
    "name": "get_repo_details",
    "description": "Get details about a specific repository",
    "input_schema": {
      "type": "object",
      "properties": {
        "owner": {"type": "string"},
        "repo": {"type": "string"}
      },
      "required": ["owner", "repo"]
    }
  },
  {
    "name": "get_repo_readme",
    "description": "Get the README content of a repository",
    "input_schema": {
      "type": "object",
      "properties": {
        "owner": {"type": "string"},
        "repo": {"type": "string"}
      },
      "required": ["owner", "repo"]
    }
  },
  {
    "name": "search_repositories",
    "description": "Search GitHub repositories by query. Supports sorting by stars.",
    "input_schema": {
      "type": "object",
      "properties": {
        "query": {"type": "string", "description": "Search query (e.g. 'user:username' or 'topic:ml')"},
        "sort": {"type": "string", "enum": ["stars", "forks", "updated"]},
        "per_page": {"type": "integer"}
      },
      "required": ["query"]
    }
  }
]
```

API endpoints and key response fields:

- `GET https://api.github.com/users/{username}`
  → `login`, `name`, `bio`, `public_repos`, `followers`, `created_at`, `html_url`

- `GET https://api.github.com/users/{username}/repos?sort={sort}&per_page={per_page}`
  → Array of repo objects (see fields below)

- `GET https://api.github.com/repos/{owner}/{repo}`
  → `name`, `full_name`, `description`, `stargazers_count`, `forks_count`, `language`, `topics`, `created_at`, `updated_at`, `html_url`

- `GET https://api.github.com/repos/{owner}/{repo}/readme`
  → `content` (base64-encoded), `encoding` ("base64")

- `GET https://api.github.com/search/repositories?q={query}&sort={sort}&per_page={per_page}`
  → `total_count`, `items` (array of repo objects with same fields as above)
