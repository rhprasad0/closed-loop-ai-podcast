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
    resume_from: NotRequired[str]


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
from typing import Any, Literal

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
MAX_TOKENS: int = 16384  # room for adaptive thinking at medium/high effort

# Effort levels for Sonnet 4.6. "high" for agentic multi-turn (Discovery,
# Research); "medium" for single-turn (Script, Producer).
Effort = Literal["low", "medium", "high", "max"]
DEFAULT_EFFORT_AGENTIC: Effort = "high"
DEFAULT_EFFORT_SINGLE_TURN: Effort = "medium"


def invoke_model(
    user_message: str,
    system_prompt: str,
    model_id: str = DEFAULT_MODEL_ID,
    max_tokens: int = MAX_TOKENS,
    effort: Effort = DEFAULT_EFFORT_SINGLE_TURN,
) -> str: ...


def invoke_with_tools(
    user_message: str,
    system_prompt: str,
    tools: list[ToolDefinition],
    tool_executor: ToolExecutor,
    model_id: str = DEFAULT_MODEL_ID,
    max_tokens: int = MAX_TOKENS,
    max_turns: int = 25,
    effort: Effort = DEFAULT_EFFORT_AGENTIC,
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
from typing import Any

import boto3
from aws_lambda_powertools.utilities.typing import LambdaContext

from shared.bedrock import ToolDefinition, ToolExecutor, invoke_with_tools
from shared.db import query as db_query
from shared.logging import get_logger
from shared.types import DiscoveryOutput, PipelineState

logger = get_logger("discovery")

# --- Module-level cached credentials ---
_exa_api_key: str | None = None

# --- Tool definitions (module-level constant) ---
TOOL_DEFINITIONS: list[ToolDefinition] = [...]  # populated per [External API Contracts](./external-api-contracts.md)


def _get_exa_api_key() -> str:
    """Fetch Exa API key from Secrets Manager, cached across warm starts."""
    ...


def _load_system_prompt() -> str:
    """Read prompts/discovery.md from disk. Uses LAMBDA_TASK_ROOT."""
    ...


def _execute_exa_search(tool_input: dict[str, Any]) -> dict[str, Any]:
    """Call Exa API. Maps snake_case keys to camelCase. Returns parsed JSON."""
    ...


def _execute_query_postgres(tool_input: dict[str, Any]) -> dict[str, Any]:
    """Run read-only SQL via shared/db.py. Returns {"rows": ...} or {"error": ...}."""
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
- `_execute_query_postgres` returns `dict[str, Any]` — either `{"rows": <list of row dicts>}` or `{"error": "<message>"}`. Uses `shared.db.query()` instead of subprocess.
- `_execute_get_github_repo` returns `dict[str, Any]` because the curated GitHub response includes `str`, `int`, `list[str]`, and `None` values.
- `_execute_tool` calls `json.dumps()` on the return value of the tool functions, so its return type is `str`.
- `_parse_discovery_output` returns `DiscoveryOutput` (a TypedDict), which provides compile-time field validation at every call site.
- The module-level global `_exa_api_key` is typed as `str | None` and narrowed inside its getter function via the `global` + `if is None` pattern. The DB connection string comes from `os.environ["DB_CONNECTION_STRING"]` via `shared/db.py`.
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

- No `boto3` import — Script does not fetch secrets from Secrets Manager. It only calls Bedrock via the shared `invoke_model` function, which manages the boto3 client internally.
- No `ToolDefinition`, `ToolExecutor`, or `_execute_tool` — Script has no Bedrock tools. It sends a single prompt and receives a single response.
- `_build_user_message` returns `str` (plain text with section headers, not JSON). The function reads `event["discovery"]`, `event["research"]`, and optionally `event["producer"]` (when `event["metadata"]["script_attempt"] > 1`).
- `_parse_script_output` returns `ScriptOutput` (TypedDict). It overwrites the `character_count` field with `len(data["text"])` rather than trusting the model's self-reported count, since LLMs frequently miscount characters. The actual length is then validated against `MAX_SCRIPT_CHARACTERS`.
- `SPEAKER_PATTERN` is typed as `re.Pattern[str]` (compiled regex). It is used for warning-level validation of script line format — lines that do not match are logged but do not cause a `ValueError`. Hard rejection of malformed lines belongs in the TTS Lambda.
- `REQUIRED_SEGMENTS` is typed as `list[str]`. The parser checks `data["segments"] == REQUIRED_SEGMENTS` (exact match, order matters).

### Producer Handler Internal Function Signatures

The Producer handler (`lambdas/producer/handler.py`) follows the same pattern as the Script handler — it uses `invoke_model` (single prompt-response) rather than `invoke_with_tools`. The key difference is that the Producer also queries Postgres via the shared `db` module to fetch benchmark scripts from top-performing past episodes.

```python
from __future__ import annotations

import json
import os

from aws_lambda_powertools.utilities.typing import LambdaContext

from shared.bedrock import invoke_model
from shared.db import query
from shared.logging import get_logger
from shared.types import PipelineState, ProducerOutput

logger = get_logger("producer")

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
    """Read prompts/producer.md from disk. Uses LAMBDA_TASK_ROOT."""
    ...


def _fetch_benchmark_scripts() -> list[str]:
    """Fetch top-performing episode scripts from Postgres for quality calibration.

    Returns a list of 0-3 script_text strings, ordered by engagement score.
    Returns an empty list if no episodes exist yet or if the DB query fails.
    """
    ...


def _build_user_message(event: PipelineState, benchmarks: list[str]) -> str:
    """Assemble script + discovery + research + benchmarks into a user message.

    Extracts $.script.text, $.script.character_count, $.script.segments,
    $.discovery.repo_name, $.discovery.repo_description,
    $.research.hiring_signals from the pipeline state. Appends benchmark
    scripts (if any) in a clearly labeled section. Returns a structured
    plain-text message with clear section headers.
    """
    ...


def _parse_producer_output(text: str) -> ProducerOutput:
    """Parse agent text response to ProducerOutput. Strips markdown fences, validates.

    Validates:
    - verdict is exactly "PASS" or "FAIL"
    - score is an integer 1-10 (coerces string to int)
    - FAIL verdicts must include feedback (str) and issues (list[str])
    - PASS verdicts may include notes (str)
    Raises ValueError if validation fails.
    """
    ...


@logger.inject_lambda_context(clear_state=True)
def lambda_handler(event: PipelineState, context: LambdaContext) -> ProducerOutput:
    ...
```

**Key typing notes:**

- No `boto3` import — Producer does not fetch secrets from Secrets Manager. It accesses Postgres via the shared `db.query` function (which reads `DB_CONNECTION_STRING` from the environment) and calls Bedrock via `invoke_model` (which manages the boto3 client internally).
- No `ToolDefinition`, `ToolExecutor`, or `_execute_tool` — Producer has no Bedrock tools. It sends a single prompt and receives a single response, identical to Script's pattern.
- `_fetch_benchmark_scripts` returns `list[str]` — a list of raw `script_text` values from the database. Returns an empty list when no episodes exist (early pipeline runs) or if the query fails. The function wraps the `shared.db.query` call and handles exceptions internally rather than propagating them (benchmark absence should not crash the evaluation).
- `_build_user_message` takes both `PipelineState` and `benchmarks: list[str]` because the benchmarks come from a separate DB query, not from the pipeline state. The function reads `event["script"]`, `event["discovery"]`, and `event["research"]`.
- `_parse_producer_output` returns `ProducerOutput` (TypedDict with `NotRequired` fields). It validates `verdict` against the literal values `"PASS"` and `"FAIL"`, coerces `score` from string to int if needed, and enforces that FAIL verdicts contain both `feedback` and `issues` fields while PASS verdicts may optionally contain `notes`.
- `BENCHMARK_QUERY` is typed as `str` (module-level constant). Uses `LEFT JOIN` + `COALESCE` so it returns scripts even when `episode_metrics` has no rows. When metrics exist, orders by engagement score: views(1x) + likes(2x) + comments(3x) + shares(5x). When metrics don't exist, falls back to most recent episodes by `created_at`.
- No module-level credential caching is needed — the shared `db` module handles connection management, and `DB_CONNECTION_STRING` is an environment variable.

### Cover Art Handler Internal Function Signatures

The Cover Art handler (`lambdas/cover_art/handler.py`) is the simplest pipeline handler — no agent loop, no tool dispatch, no output parsing of model-generated JSON. It builds a prompt from a template, calls Nova Canvas for image generation, uploads the PNG to S3, and returns the S3 key. The handler creates its own `boto3.client("bedrock-runtime")` because Nova Canvas uses a completely different request body format than the Claude Messages API in `shared/bedrock.py`.

```python
from __future__ import annotations

import base64
import json
import os
from typing import Any

import boto3
from aws_lambda_powertools.utilities.typing import LambdaContext

from shared.logging import get_logger
from shared.s3 import upload_bytes
from shared.types import CoverArtOutput, PipelineState

logger = get_logger("cover_art")

# --- Module-level constants ---

NOVA_CANVAS_MODEL_ID: str = "amazon.nova-canvas-v1:0"
IMAGE_WIDTH: int = 1024
IMAGE_HEIGHT: int = 1024
IMAGE_QUALITY: str = "standard"
MAX_PROMPT_LENGTH: int = 1024  # Nova Canvas text field hard limit
PNG_MAGIC_BYTES: bytes = b"\x89PNG"
BEDROCK_READ_TIMEOUT: int = 300  # AWS recommends >= 300s for image generation

LANGUAGE_COLOR_MOODS: dict[str, str] = {
    "Python": "warm yellows, blues, and greens inspired by the Python ecosystem",
    "Rust": "deep oranges, warm reds, and metallic copper tones",
    "Go": "cool cyan, teal, and clean white accents",
    "JavaScript": "bright yellows, warm blacks, and neon highlights",
    "TypeScript": "rich blues, white, and subtle purple accents",
    "Ruby": "deep reds, crimson, and gemstone sparkle highlights",
    "C": "steely grays, dark blues, and sharp neon green accents",
    "C++": "similar to C but with warmer blue and subtle gold accents",
    "Java": "warm orange-red, deep brown, and coffee-inspired tones",
    "Shell": "terminal green on dark backgrounds with neon cyan accents",
    "Lua": "deep navy blue, soft purple, and moonlight silver",
    "Zig": "warm amber, bright orange, and golden lightning accents",
    "Haskell": "rich purple, deep violet, and abstract geometric highlights",
    "Elixir": "royal purple, deep magenta, and alchemical gold accents",
    "Swift": "bright orange, gradient warm tones, and clean white",
    "Kotlin": "gradient purple to orange, with modern clean accents",
}
DEFAULT_COLOR_MOOD: str = "vibrant blues, purples, and electric greens"

# --- Module-level cached client ---

_bedrock_client: Any | None = None


def _get_bedrock_client() -> Any:
    """Return a Bedrock Runtime boto3 client, cached across warm starts.

    Configures read_timeout=300s (AWS recommends this for image generation;
    the boto3 default of 60s is too short for Nova Canvas).
    """
    ...


def _load_prompt_template() -> str:
    """Read prompts/cover_art.md from disk.

    Uses LAMBDA_TASK_ROOT (set by AWS Lambda runtime) to locate the prompt file,
    falling back to the handler's directory for local testing.
    """
    ...


def _build_cover_art_prompt(
    cover_art_suggestion: str,
    repo_name: str,
    language: str,
) -> str:
    """Substitute {{visual_concept}}, {{episode_subtitle}}, {{color_mood}} into template.

    Falls back to a generic description if cover_art_suggestion is empty.
    Falls back to DEFAULT_COLOR_MOOD if language is not in LANGUAGE_COLOR_MOODS.
    Truncates final prompt to MAX_PROMPT_LENGTH (1024 chars) if needed.
    """
    ...


def _generate_image(prompt: str) -> bytes:
    """Call Nova Canvas TEXT_IMAGE and return decoded PNG bytes.

    Raises RuntimeError on content policy violation (ValidationException),
    empty images array, or RAI-flagged response (error field in response body).
    Lets ThrottlingException propagate for Step Functions retry.
    """
    ...


@logger.inject_lambda_context(clear_state=True)
def lambda_handler(event: PipelineState, context: LambdaContext) -> CoverArtOutput:
    ...
```

**Key typing notes:**

- **Own `boto3` import** — Cover Art creates its own `boto3.client("bedrock-runtime")` rather than using `shared.bedrock.invoke_model()`. Nova Canvas uses a `TEXT_IMAGE` request body with `textToImageParams` and `imageGenerationConfig`, which has zero overlap with the Claude Messages API body. A shared wrapper would serve exactly one consumer.
- **`read_timeout` configuration** — `_get_bedrock_client` creates the client with `botocore.config.Config(read_timeout=300)`. The boto3 default `read_timeout` is 60 seconds, which AWS documentation explicitly warns is too short for Nova Canvas image generation. 300 seconds matches the Lambda timeout.
- `_bedrock_client` is cached at module level (`Any | None`) using the same pattern as Discovery's credential caching. `Any` is necessary because `boto3-stubs` types the client as `BedrockRuntimeClient`, but the module-level cache starts as `None`.
- `_build_cover_art_prompt` uses three `str.replace()` calls — no template engine needed for 3 variables. Returns `str`. **Truncates the final prompt to 1024 characters** (Nova Canvas hard limit on the `text` field). The template is ~571 chars of fixed text, leaving ~453 chars for variable substitution, so truncation should rarely trigger in practice.
- `_generate_image` returns `bytes` (raw PNG data after base64 decode). It checks for the `error` field in the Nova Canvas response (set when AWS Responsible AI policy flags the image). It catches `botocore.exceptions.ClientError` for `ValidationException` (content policy violation) and re-raises as `RuntimeError`. `ThrottlingException` is not caught — Step Functions handles retries.
- `_load_prompt_template` uses `os.environ.get("LAMBDA_TASK_ROOT", os.path.dirname(__file__))` — identical pattern to Discovery, Research, Script, and Producer.
- The handler validates PNG magic bytes (`b"\x89PNG"`) after decoding. This is a lightweight sanity check, not full image validation.
- No `_parse_*_output` function — unlike the agent handlers, Cover Art does not parse model-generated JSON. The output is constructed programmatically from the S3 key and prompt string.

### Typing Conventions

- Every function in shared modules (`bedrock.py`, `db.py`, `s3.py`, `logging.py`) must have full type annotations — parameters and return types.
- No bare `Any` without an explicit `# type: ignore[...]` comment explaining why.
- `boto3-stubs` (already in devcontainer) provides typed clients: `mypy_boto3_bedrock_runtime`, `mypy_boto3_s3`, `mypy_boto3_secretsmanager`.
- Use `from __future__ import annotations` at the top of every file for PEP 604 union syntax (`X | Y`) and forward references.
