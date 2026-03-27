> Part of the [Implementation Spec](../../IMPLEMENTATION_SPEC.md)

# Type Checking

All Python code uses strict type annotations enforced by mypy. TypedDict definitions in the shared layer provide compile-time validation that Lambda inputs and outputs match the [Interface Contracts](./interface-contracts.md).

### mypy Configuration

In `pyproject.toml`:

```toml
[tool.mypy]
python_version = "3.12"
strict = true
warn_unused_ignores = true

[[tool.mypy.overrides]]
module = "psycopg2.*"
ignore_missing_imports = true

[[tool.mypy.overrides]]
module = "aws_lambda_powertools.*"
ignore_missing_imports = true
```

`strict = true` enables: `disallow_untyped_defs`, `disallow_any_generics`, `warn_return_any`, `no_implicit_reexport`, `strict_equality`, and all other strict flags. This means every function must have full parameter and return type annotations.

Run locally: `mypy lambdas/` with `PYTHONPATH=lambdas/shared/python`.

### TypedDict Definitions

`lambdas/shared/python/shared/types.py` defines typed interfaces matching [Interface Contracts](./interface-contracts.md) exactly. Every Lambda imports its input/output types from here.

```python
from __future__ import annotations

from typing import NotRequired, TypedDict


class PipelineMetadata(TypedDict):
    execution_id: str
    script_attempt: int


class DiscoveryOutput(TypedDict):
    repo_url: str
    repo_name: str
    repo_description: str
    developer_github: str
    star_count: int
    language: str
    discovery_rationale: str
    key_files: list[str]
    technical_highlights: list[str]


class NotableRepo(TypedDict):
    name: str
    description: str
    stars: int
    language: str


class ResearchOutput(TypedDict):
    developer_name: str
    developer_github: str
    developer_bio: str
    public_repos_count: int
    notable_repos: list[NotableRepo]
    commit_patterns: str
    technical_profile: str
    interesting_findings: list[str]
    hiring_signals: list[str]


class ScriptOutput(TypedDict):
    text: str
    character_count: int
    segments: list[str]
    featured_repo: str
    featured_developer: str
    cover_art_suggestion: str


class ProducerOutput(TypedDict):
    """Unified producer output. PASS includes `notes`; FAIL includes `feedback` and `issues`."""
    verdict: str
    score: int
    notes: NotRequired[str]
    feedback: NotRequired[str]
    issues: NotRequired[list[str]]


class CoverArtOutput(TypedDict):
    s3_key: str
    prompt_used: str


class TTSOutput(TypedDict):
    s3_key: str
    duration_seconds: int
    character_count: int


class PostProductionOutput(TypedDict):
    s3_mp4_key: str
    episode_id: int
    air_date: str


class PipelineState(TypedDict, total=False):
    """Full accumulated state object passed through Step Functions.

    Each key is populated by ResultPath as the pipeline progresses.
    total=False because early Lambdas see a partial state.
    """
    metadata: PipelineMetadata
    discovery: DiscoveryOutput
    research: ResearchOutput
    script: ScriptOutput
    producer: ProducerOutput
    cover_art: CoverArtOutput
    tts: TTSOutput
    post_production: PostProductionOutput
```

### Handler Type Annotation Pattern

Every Lambda handler is annotated with its specific input/output types:

```python
from aws_lambda_powertools.utilities.typing import LambdaContext
from shared.types import PipelineState, DiscoveryOutput


def lambda_handler(event: PipelineState, context: LambdaContext) -> DiscoveryOutput:
    ...
```

The site Lambda is different — it receives a Lambda Function URL event, not pipeline state:

```python
def lambda_handler(event: dict[str, object], context: LambdaContext) -> dict[str, object]:
    ...
```

### `invoke_with_tools` Strict Type Annotations

The `invoke_with_tools` signature shown in [External API Contracts](./external-api-contracts.md) uses `list[dict]` and `Callable[[str, dict], str]` for brevity. Under mypy strict, the actual implementation in `shared/bedrock.py` must use these precise types:

```python
from __future__ import annotations

from collections.abc import Callable
from typing import Any

# The Bedrock Messages API tool definition schema. Each tool is a dict
# with "name", "description", and "input_schema" keys. We use
# dict[str, Any] because the input_schema sub-object has recursive
# JSON Schema structure that cannot be expressed as a TypedDict without
# losing practical usability.
ToolDefinition = dict[str, Any]  # type alias

# The tool_executor callback receives (tool_name, tool_input) and must
# return a JSON-encoded string. tool_input is dict[str, Any] because
# the shape depends on the tool's input_schema.
ToolExecutor = Callable[[str, dict[str, Any]], str]

DEFAULT_MODEL_ID: str = "us.anthropic.claude-sonnet-4-6"


def invoke_model(
    user_message: str,
    system_prompt: str,
    model_id: str = DEFAULT_MODEL_ID,
    max_tokens: int = MAX_TOKENS,
) -> str: ...


def invoke_with_tools(
    user_message: str,
    system_prompt: str,
    tools: list[ToolDefinition],
    tool_executor: ToolExecutor,
    model_id: str = DEFAULT_MODEL_ID,
    max_tokens: int = MAX_TOKENS,
    max_turns: int = 25,
) -> str: ...
```

The `ToolDefinition` and `ToolExecutor` type aliases are module-level exports so handler code can import them for annotation:

```python
from shared.bedrock import invoke_with_tools, ToolDefinition, ToolExecutor
```

### Discovery Handler Internal Function Signatures

The Discovery handler (`lambdas/discovery/handler.py`) contains private helper functions that must all have full type annotations for mypy strict. The exact signatures:

```python
from __future__ import annotations

import json
import os
import subprocess
from typing import Any

import boto3
from aws_lambda_powertools.utilities.typing import LambdaContext

from shared.bedrock import ToolDefinition, ToolExecutor, invoke_with_tools
from shared.logging import get_logger
from shared.types import DiscoveryOutput, PipelineState

logger = get_logger("discovery")

# --- Module-level cached credentials ---
_db_connection_string: str | None = None
_exa_api_key: str | None = None

# --- Tool definitions (module-level constant) ---
TOOL_DEFINITIONS: list[ToolDefinition] = [...]  # populated per [External API Contracts](./external-api-contracts.md)


def _get_db_connection_string() -> str:
    """Fetch DB connection string from SSM, cached across warm starts."""
    ...


def _get_exa_api_key() -> str:
    """Fetch Exa API key from Secrets Manager, cached across warm starts."""
    ...


def _load_system_prompt() -> str:
    """Read prompts/discovery.md from disk. Uses LAMBDA_TASK_ROOT."""
    ...


def _execute_exa_search(tool_input: dict[str, Any]) -> dict[str, Any]:
    """Call Exa API. Maps snake_case keys to camelCase. Returns parsed JSON."""
    ...


def _execute_query_postgres(tool_input: dict[str, Any]) -> dict[str, str]:
    """Run read-only SQL via psql subprocess. Returns {"rows": ...} or {"error": ...}."""
    ...


def _execute_get_github_repo(tool_input: dict[str, Any]) -> dict[str, Any]:
    """Call GitHub REST API. Returns curated field subset."""
    ...


def _execute_tool(tool_name: str, tool_input: dict[str, Any]) -> str:
    """Dispatch to the correct tool function, return JSON string."""
    ...


def _parse_discovery_output(text: str) -> DiscoveryOutput:
    """Parse agent text response to DiscoveryOutput. Strips markdown fences, validates."""
    ...


@logger.inject_lambda_context(clear_state=True)
def lambda_handler(event: PipelineState, context: LambdaContext) -> DiscoveryOutput:
    ...
```

**Key typing notes:**

- `_execute_exa_search` returns `dict[str, Any]` because the Exa response contains nested lists of result objects with mixed-type values.
- `_execute_query_postgres` returns `dict[str, str]` — always either `{"rows": "<stdout>"}` or `{"error": "<stderr>"}`. The narrower return type (vs `dict[str, Any]`) is intentional and passes strict checks.
- `_execute_get_github_repo` returns `dict[str, Any]` because the curated GitHub response includes `str`, `int`, `list[str]`, and `None` values.
- `_execute_tool` calls `json.dumps()` on the return value of the tool functions, so its return type is `str`.
- `_parse_discovery_output` returns `DiscoveryOutput` (a TypedDict), which provides compile-time field validation at every call site.
- The module-level globals `_db_connection_string` and `_exa_api_key` are typed as `str | None` and narrowed inside their getter functions via the `global` + `if is None` pattern.
- `TOOL_DEFINITIONS` is typed as `list[ToolDefinition]` (alias for `list[dict[str, Any]]`).

### Script Handler Internal Function Signatures

The Script handler (`lambdas/script/handler.py`) is simpler than Discovery and Research because it uses `invoke_model` (single prompt-response) rather than `invoke_with_tools` (agentic tool loop). There are no tool definitions, no tool executor functions, and no dispatcher. The handler's job is to assemble a user message from upstream state, call Bedrock once, and parse the response.

```python
from __future__ import annotations

import json
import os
import re

from aws_lambda_powertools.utilities.typing import LambdaContext

from shared.bedrock import invoke_model
from shared.logging import get_logger
from shared.types import PipelineState, ScriptOutput

logger = get_logger("script")

# --- Module-level constants ---
MAX_SCRIPT_CHARACTERS: int = 5000

REQUIRED_SEGMENTS: list[str] = [
    "intro", "core_debate", "developer_deep_dive",
    "technical_appreciation", "hiring_manager", "outro",
]

SPEAKER_PATTERN: re.Pattern[str] = re.compile(
    r"^\*\*(?:Hype|Roast|Phil):\*\*\s+.+$"
)


def _load_system_prompt() -> str:
    """Read prompts/script.md from disk. Uses LAMBDA_TASK_ROOT."""
    ...


def _build_user_message(event: PipelineState) -> str:
    """Assemble discovery + research + optional producer feedback into a user message.

    Extracts $.discovery.*, $.research.*, and (on retry) $.producer.feedback
    and $.producer.issues from the pipeline state. Returns a structured plain-text
    message with clear section headers.
    """
    ...


def _parse_script_output(text: str) -> ScriptOutput:
    """Parse agent text response to ScriptOutput. Strips markdown fences, validates.

    Overwrites character_count with actual len(text) if the model miscounted.
    Raises ValueError if character_count >= 5000 or required fields/segments are wrong.
    """
    ...


@logger.inject_lambda_context(clear_state=True)
def lambda_handler(event: PipelineState, context: LambdaContext) -> ScriptOutput:
    ...
```

**Key typing notes:**

- No `boto3` import — Script does not fetch secrets from SSM or Secrets Manager. It only calls Bedrock via the shared `invoke_model` function, which manages the boto3 client internally.
- No `ToolDefinition`, `ToolExecutor`, or `_execute_tool` — Script has no Bedrock tools. It sends a single prompt and receives a single response.
- `_build_user_message` returns `str` (plain text with section headers, not JSON). The function reads `event["discovery"]`, `event["research"]`, and optionally `event["producer"]` (when `event["metadata"]["script_attempt"] > 1`).
- `_parse_script_output` returns `ScriptOutput` (TypedDict). It overwrites the `character_count` field with `len(data["text"])` rather than trusting the model's self-reported count, since LLMs frequently miscount characters. The actual length is then validated against `MAX_SCRIPT_CHARACTERS`.
- `SPEAKER_PATTERN` is typed as `re.Pattern[str]` (compiled regex). It is used for warning-level validation of script line format — lines that do not match are logged but do not cause a `ValueError`. Hard rejection of malformed lines belongs in the TTS Lambda.
- `REQUIRED_SEGMENTS` is typed as `list[str]`. The parser checks `data["segments"] == REQUIRED_SEGMENTS` (exact match, order matters).

### Typing Conventions

- Every function in shared modules (`bedrock.py`, `db.py`, `s3.py`, `logging.py`) must have full type annotations — parameters and return types.
- No bare `Any` without an explicit `# type: ignore[...]` comment explaining why.
- `boto3-stubs` (already in devcontainer) provides typed clients: `mypy_boto3_bedrock_runtime`, `mypy_boto3_s3`, `mypy_boto3_secretsmanager`, `mypy_boto3_ssm`. The `ssm` extra is needed for the Discovery handler's SSM `GetParameter` call.
- Use `from __future__ import annotations` at the top of every file for PEP 604 union syntax (`X | Y`) and forward references.
