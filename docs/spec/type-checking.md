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
import urllib.request
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
    """Fetch Exa API key from Secrets Manager (zerostars/exa-api-key), cached across warm starts."""
    ...


def _load_system_prompt() -> str:
    """Read prompts/discovery.md from disk.

    Uses LAMBDA_TASK_ROOT (set by AWS Lambda runtime) to locate the prompt file,
    falling back to the handler's directory for local testing.
    """
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

### Research Handler Internal Function Signatures

The Research handler (`lambdas/research/handler.py`) follows the same agentic pattern as Discovery — it uses `invoke_with_tools` with a tool executor callback. The key difference is that Research calls the GitHub REST API (5 tools) instead of Exa/Postgres/GitHub (3 tools). Research does not access Secrets Manager or Postgres.

```python
from __future__ import annotations

import base64
import json
import os
import urllib.request
from typing import Any

from aws_lambda_powertools.utilities.typing import LambdaContext

from shared.bedrock import ToolDefinition, ToolExecutor, invoke_with_tools
from shared.logging import get_logger
from shared.types import PipelineState, ResearchOutput

logger = get_logger("research")

# --- Tool definitions (module-level constant) ---
TOOL_DEFINITIONS: list[ToolDefinition] = [...]  # populated per [External API Contracts](./external-api-contracts.md)

# --- GitHub API constants ---
GITHUB_USER_AGENT: str = "zerostars-research-agent"
GITHUB_TIMEOUT: int = 15  # seconds


def _load_system_prompt() -> str:
    """Read prompts/research.md from disk.

    Uses LAMBDA_TASK_ROOT (set by AWS Lambda runtime) to locate the prompt file,
    falling back to the handler's directory for local testing.
    """
    ...


def _execute_get_github_user(tool_input: dict[str, Any]) -> dict[str, Any]:
    """Call GitHub Users API. Returns curated field subset.

    Returns {"error": "..."} on HTTPError or socket.timeout.
    """
    ...


def _execute_get_user_repos(tool_input: dict[str, Any]) -> list[dict[str, Any]] | dict[str, Any]:
    """Call GitHub user repos API. Returns curated array of repo objects on success,
    or {"error": "..."} dict on failure.
    """
    ...


def _execute_get_repo_details(tool_input: dict[str, Any]) -> dict[str, Any]:
    """Call GitHub repos API. Returns curated field subset.

    Returns {"error": "..."} on HTTPError or socket.timeout.
    """
    ...


def _execute_get_repo_readme(tool_input: dict[str, Any]) -> dict[str, Any]:
    """Call GitHub README API. Base64-decodes the content field before returning.

    Returns {"content": <decoded_text>} on success, {"error": "..."} on failure.
    """
    ...


def _execute_search_repositories(tool_input: dict[str, Any]) -> dict[str, Any]:
    """Call GitHub search API. Returns curated {total_count, items} dict.

    Returns {"error": "..."} on HTTPError or socket.timeout.
    """
    ...


def _execute_tool(tool_name: str, tool_input: dict[str, Any]) -> str:
    """Dispatch to the correct tool function, return JSON string."""
    ...


def _build_user_message(event: PipelineState) -> str:
    """Assemble discovery fields into a user message for the Research agent.

    Extracts $.discovery.developer_github, $.discovery.repo_name, and
    $.discovery.repo_url from the pipeline state. Returns structured
    plain-text with section headers.
    """
    ...


def _parse_research_output(text: str) -> ResearchOutput:
    """Parse agent text response to ResearchOutput. Strips markdown fences, validates.

    Coerces public_repos_count from string to int if needed.
    Coerces null developer_bio to empty string.
    Validates notable_repos sub-objects have name, description, stars, language.
    Raises ValueError if required fields missing or validation fails.
    """
    ...


@logger.inject_lambda_context(clear_state=True)
def lambda_handler(event: PipelineState, context: LambdaContext) -> ResearchOutput:
    ...
```

**Key typing notes:**

- `_execute_get_user_repos` has a dual return type: `list[dict[str, Any]]` on success (array of curated repo objects), `dict[str, Any]` on failure (error dict). This differs from the other tool functions which always return `dict[str, Any]`.
- `_build_user_message` reads `event["discovery"]["developer_github"]`, `event["discovery"]["repo_name"]`, and `event["discovery"]["repo_url"]` to assemble the user message.
- `_parse_research_output` coerces `public_repos_count` from string to int (models sometimes return numeric values as strings) and `developer_bio` from `None` to `""` (GitHub API returns null when bio is not set).
- `GITHUB_USER_AGENT` is `"zerostars-research-agent"` — all GitHub API calls include a `User-Agent` header with this value. GitHub returns 403 without it. Same pattern as Discovery's `"zerostars-discovery-agent"`.
- `_load_system_prompt` uses `os.environ.get("LAMBDA_TASK_ROOT", os.path.dirname(__file__))` — identical pattern to Discovery and Cover Art.
- No `boto3` import — Research does not fetch secrets from Secrets Manager. It calls Bedrock via `invoke_with_tools` (which manages the boto3 client internally) and GitHub via `urllib.request`.
- `TOOL_DEFINITIONS` typed as `list[ToolDefinition]` with 5 tools matching the [GitHub API](./external-api-contracts.md#github-api) section.
- `_execute_tool` calls `json.dumps()` on the return value of the tool functions, so its return type is `str`.

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
    """Read prompts/script.md from disk.

    Uses LAMBDA_TASK_ROOT (set by AWS Lambda runtime) to locate the prompt file,
    falling back to the handler's directory for local testing.
    """
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
    """Read prompts/producer.md from disk.

    Uses LAMBDA_TASK_ROOT (set by AWS Lambda runtime) to locate the prompt file,
    falling back to the handler's directory for local testing.
    """
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

### TTS Handler Internal Function Signatures

The TTS handler (`lambdas/tts/handler.py`) parses the approved script into dialogue turns, calls the ElevenLabs text-to-dialogue API, and uploads the resulting MP3 to S3. It has no Bedrock interaction — the script has already been written and approved by upstream agents.

```python
from __future__ import annotations

import json
import os
import re
import urllib.request
from typing import Any

import boto3
from aws_lambda_powertools.utilities.typing import LambdaContext

from shared.logging import get_logger
from shared.s3 import upload_bytes
from shared.types import PipelineState, TTSOutput

logger = get_logger("tts")

# --- Module-level constants ---

ELEVENLABS_ENDPOINT: str = "https://api.elevenlabs.io/v1/text-to-dialogue"
ELEVENLABS_MODEL_ID: str = "eleven_v3"
ELEVENLABS_OUTPUT_FORMAT: str = "mp3_44100_128"

SPEAKER_VOICE_MAP: dict[str, str] = {
    "Hype": "cjVigY5qzO86Huf0OWal",
    "Roast": "JBFqnCBsd6RMkjVDRZzb",
    "Phil": "cgSgspJ2msm6clMCkdW9",
}

SPEAKER_PATTERN: re.Pattern[str] = re.compile(
    r"^\*\*(?P<speaker>Hype|Roast|Phil):\*\*\s*(?P<text>.+)$"
)

MAX_CHARACTER_COUNT: int = 5000

# --- Module-level cached credentials ---
_elevenlabs_api_key: str | None = None


def _get_elevenlabs_api_key() -> str:
    """Fetch ElevenLabs API key from Secrets Manager, cached across warm starts.

    Secret name: zerostars/elevenlabs-api-key.
    """
    ...


def _parse_dialogue_turns(script_text: str) -> list[dict[str, str]]:
    """Parse script text into ElevenLabs dialogue turn format.

    Splits on newlines, matches each line against SPEAKER_PATTERN.
    Maps speaker names to voice IDs via SPEAKER_VOICE_MAP.
    Returns list of {"text": "...", "voice_id": "..."} dicts.

    Raises ValueError on:
    - Lines that do not match SPEAKER_PATTERN (malformed or unknown speaker)
    - Blank lines (the script format does not allow blank lines)
    """
    ...


def _call_elevenlabs(inputs: list[dict[str, str]]) -> bytes:
    """POST to ElevenLabs text-to-dialogue API and return raw MP3 bytes.

    Sends request body: {"inputs": inputs, "model_id": ELEVENLABS_MODEL_ID}
    with output_format query parameter.

    Raises RuntimeError on non-200 responses (422 validation error, 5xx server error).
    """
    ...


@logger.inject_lambda_context(clear_state=True)
def lambda_handler(event: PipelineState, context: LambdaContext) -> TTSOutput:
    ...
```

**Key typing notes:**

- `SPEAKER_VOICE_MAP` maps the three persona names to their ElevenLabs voice IDs. These are the same IDs defined in [CLAUDE.md](../../CLAUDE.md) and [External API Contracts](./external-api-contracts.md#elevenlabs--text-to-dialogue-tts).
- `_parse_dialogue_turns` is strict: any line that doesn't match `SPEAKER_PATTERN` raises `ValueError`. This is intentional — the Script Text Format spec in [Interface Contracts](./interface-contracts.md#script-text-format) says "Lines that don't match are an error."
- `_call_elevenlabs` returns raw `bytes` (MP3 data from the response body). The ElevenLabs API returns `200 OK` with binary MP3 on success, or a JSON error body on failure.
- `duration_seconds` is estimated from the MP3 byte length: `int(len(mp3_bytes) / (128000 / 8))`. The `output_format=mp3_44100_128` parameter specifies 128kbps bitrate. This is an approximation, not frame-accurate parsing — sufficient for podcast-length audio. The value is `int`, not `float` — sub-second accuracy is not meaningful at podcast scale (~180s episodes).
- Secrets Manager secret name is `zerostars/elevenlabs-api-key`, following the same naming convention as Discovery's `zerostars/exa-api-key`.
- `_elevenlabs_api_key` is cached at module level with the same pattern as Discovery's `_exa_api_key`.
- No `shared.bedrock` import — TTS does not call Bedrock. It parses a pre-approved script and calls ElevenLabs directly.

### Post-Production Handler Internal Function Signatures

The Post-Production handler (`lambdas/post_production/handler.py`) is the final pipeline step. It downloads the cover art PNG and episode MP3 from S3, uses ffmpeg to combine them into an MP4, uploads the MP4 to S3, and writes the episode record to Postgres. It creates two database rows: one in `episodes` and one in `featured_developers`.

```python
from __future__ import annotations

import json
import os
import subprocess
from datetime import date
from typing import Any
from zoneinfo import ZoneInfo

from aws_lambda_powertools.utilities.typing import LambdaContext

from shared.db import get_connection
from shared.logging import get_logger
from shared.s3 import download_file, upload_file
from shared.types import PipelineState, PostProductionOutput

logger = get_logger("post_production")

# --- Module-level constants ---
EASTERN_TZ: ZoneInfo = ZoneInfo("America/New_York")
FFMPEG_PATH: str = "/opt/bin/ffmpeg"  # from the ffmpeg Lambda Layer


def _download_s3_file(bucket: str, key: str, local_path: str) -> None:
    """Download an S3 object to a local file path using shared.s3.download_file."""
    ...


def _run_ffmpeg(mp3_path: str, png_path: str, mp4_path: str) -> None:
    """Run ffmpeg to combine MP3 audio + PNG cover art into MP4 video.

    Command: ffmpeg -loop 1 -i {png_path} -i {mp3_path}
             -c:v libx264 -tune stillimage -c:a aac -b:a 128k
             -pix_fmt yuv420p -shortest {mp4_path}

    Uses subprocess.run with check=True.
    Raises RuntimeError on non-zero exit code.
    """
    ...


def _insert_episode(
    conn: Any,
    execution_id: str,
    repo_url: str,
    repo_name: str,
    developer_github: str,
    developer_name: str,
    star_count: int,
    language: str,
    script_text: str,
    research_json: str,
    cover_art_prompt: str,
    s3_cover_art_path: str,
    s3_mp3_path: str,
    s3_mp4_path: str,
    producer_attempts: int,
    air_date: str,
) -> int:
    """INSERT into episodes table. Returns episode_id via RETURNING clause.

    Uses the connection's cursor directly (not shared.db.query) because this
    runs inside a transaction with _insert_featured_developer.
    """
    ...


def _insert_featured_developer(
    conn: Any,
    developer_github: str,
    episode_id: int,
    featured_date: str,
) -> None:
    """INSERT into featured_developers table.

    Uses the same connection/transaction as _insert_episode.
    """
    ...


@logger.inject_lambda_context(clear_state=True)
def lambda_handler(event: PipelineState, context: LambdaContext) -> PostProductionOutput:
    ...
```

**Key typing notes:**

- Uses `shared.db.get_connection()` directly (not `query()` or `execute()`) because it needs to execute two INSERTs in a single transaction. The handler opens a connection, inserts into `episodes` (with `RETURNING episode_id`), inserts into `featured_developers` using the returned `episode_id`, commits, then closes.
- Uses `shared.s3.download_file` (the function added to `s3.py` for this handler).
- `air_date` is computed as `date.today()` in Eastern Time (`America/New_York` timezone), formatted as `YYYY-MM-DD` (ISO 8601 date). Uses `zoneinfo.ZoneInfo` (Python 3.9+ stdlib, available on Lambda Python 3.12).
- `research_json` is serialized via `json.dumps()`, not psycopg2 auto-JSONB adaptation. The raw JSON string is inserted into the `research_json` column (type `jsonb` in Postgres, which accepts text).
- `/tmp` is used for intermediate files: `/tmp/episode.mp3`, `/tmp/cover.png`, `/tmp/episode.mp4`. Lambda provides 512 MB of `/tmp` storage by default.
- `_run_ffmpeg` uses `subprocess.run([FFMPEG_PATH, ...], check=True, capture_output=True)`. The ffmpeg binary is at `/opt/bin/ffmpeg`, provided by the ffmpeg Lambda Layer.
- `FFMPEG_PATH` points to `/opt/bin/ffmpeg` because Lambda Layers extract to `/opt`.
- No `shared.bedrock` import — Post-Production does not call Bedrock.
- No `boto3` import — S3 access is via `shared.s3`, database access via `shared.db.get_connection()`.

### Site Handler Internal Function Signatures

The Site handler (`lambdas/site/handler.py`) serves the podcast website via a Lambda Function URL. It queries the database for episodes, renders Jinja2 templates, and returns HTML responses. It does not participate in the pipeline state machine — it receives Lambda Function URL events, not `PipelineState`.

```python
from __future__ import annotations

import os
from typing import Any

from aws_lambda_powertools.utilities.typing import LambdaContext
from jinja2 import Environment, FileSystemLoader

from shared.db import get_connection
from shared.logging import get_logger
from shared.s3 import generate_presigned_url

logger = get_logger("site")

# --- Module-level constants ---
PRESIGNED_URL_EXPIRY: int = 3600  # 1 hour for audio player URLs


def _get_episodes() -> list[dict[str, Any]]:
    """Query episodes table, ordered by air_date DESC (most recent first).

    Returns list of dicts with episode metadata for the listing page.
    Excludes large fields (script_text, research_json, cover_art_prompt).
    On DB error, the handler returns a 500 response (not an unhandled exception).
    """
    ...


def _render_template(template_name: str, **context: Any) -> str:
    """Render a Jinja2 template from the templates/ directory.

    Uses FileSystemLoader with the templates directory resolved via
    LAMBDA_TASK_ROOT (falling back to handler directory for local testing).
    """
    ...


def _build_response(
    status_code: int,
    body: str,
    content_type: str = "text/html",
) -> dict[str, object]:
    """Build a Lambda Function URL response dict.

    Returns {"statusCode": int, "headers": {"Content-Type": content_type}, "body": str}.
    """
    ...


def lambda_handler(event: dict[str, object], context: LambdaContext) -> dict[str, object]:
    """Handle Lambda Function URL requests.

    Routing:
    - "/" → episode listing page (200 with HTML)
    - All other paths → 404

    Event format: Lambda Function URL events use rawPath for the request path,
    requestContext for metadata. See AWS docs for full event schema.
    """
    ...
```

**Key typing notes:**

- **Different type signature than pipeline handlers:** The handler receives `dict[str, object]` (Lambda Function URL event), not `PipelineState`. It returns `dict[str, object]` (Function URL response), not a TypedDict.
- `_get_episodes` uses `shared.db.get_connection()` directly because it needs to build dicts from `cursor.description` column names. On DB error, the exception propagates to the handler's top-level try/except, which returns a 500 response.
- `_render_template` uses Jinja2's `FileSystemLoader`. The `jinja2` package is pip-installed into the Lambda deployment package by `lambdas/site/build.sh`.
- `_build_response` builds the Function URL response format: `{"statusCode": 200, "headers": {...}, "body": "<html>..."}`.
- `generate_presigned_url` from `shared.s3` creates time-limited URLs for the HTML5 audio player. The 1-hour expiry (`PRESIGNED_URL_EXPIRY`) is long enough for a listening session.
- Cover art images are served via CloudFront at `/assets/*` (backed by S3 via OAC), not via presigned URLs. Only MP3 audio uses presigned S3 URLs.
- No `shared.bedrock` import — the site does not call Bedrock.
- The handler routes on `event["rawPath"]` — only `/` is a valid route in v1. Future routes could be added for individual episode pages.

### Shared Module: `db.py` Function Signatures

`lambdas/shared/python/shared/db.py` provides Postgres access via `psycopg2`. Every function must have full type annotations for mypy strict.

```python
from __future__ import annotations

import os

import psycopg2


def get_connection() -> psycopg2.extensions.connection:
    """Create a new Postgres connection using DB_CONNECTION_STRING env var.

    Uses sslmode=require. Returns a psycopg2 connection object.
    Callers are responsible for closing the connection.
    """
    ...


def query(sql: str, params: tuple[object, ...] | None = None) -> list[tuple[object, ...]]:
    """Execute a SELECT query and return all rows.

    Opens a connection, executes the query, fetches all rows, closes connection.
    Returns rows as a list of tuples (column values in select order).
    For INSERT...RETURNING queries that need a result row, use this function.
    """
    ...


def execute(sql: str, params: tuple[object, ...] | None = None) -> int:
    """Execute an INSERT/UPDATE/DELETE statement.

    Opens a connection, executes the statement, commits, closes connection.
    Returns the rowcount (number of affected rows).
    """
    ...
```

**Key typing notes:**

- `get_connection()` reads `os.environ["DB_CONNECTION_STRING"]` and passes `sslmode=require` to `psycopg2.connect()`.
- `query()` and `execute()` each open and close their own connection. There is no connection pooling — Lambda warm starts reuse the runtime, but each function call gets a fresh connection.
- `query()` returns `list[tuple]`, not `list[dict]`. Callers that need column names must use `cursor.description` (the Discovery and MCP handlers do this internally).
- The `params` parameter uses `tuple[object, ...] | None` to satisfy mypy strict. Under `psycopg2`, params can be a tuple or None.

### Shared Module: `s3.py` Function Signatures

`lambdas/shared/python/shared/s3.py` provides S3 helpers via `boto3`. The `bucket` parameter is passed explicitly by callers — callers read the `S3_BUCKET` environment variable and pass the value.

```python
from __future__ import annotations

import boto3


def upload_bytes(bucket: str, key: str, data: bytes, content_type: str) -> None:
    """Upload raw bytes to S3 via put_object."""
    ...


def upload_file(bucket: str, key: str, filepath: str, content_type: str) -> None:
    """Upload a local file to S3 via upload_file."""
    ...


def download_file(bucket: str, key: str, local_path: str) -> None:
    """Download an S3 object to a local file path via download_file."""
    ...


def generate_presigned_url(bucket: str, key: str, expiry: int = 3600) -> str:
    """Generate a presigned GET URL for an S3 object.

    Default expiry is 3600 seconds (1 hour).
    """
    ...
```

**Key typing notes:**

- `bucket` is an explicit parameter, not read from env internally. Callers read `os.environ["S3_BUCKET"]` and pass it. The `file-manifest.md` note "Bucket name from `S3_BUCKET` env var" describes where callers get the value, not how the functions work internally.
- `download_file` is needed by the Post-Production handler to download MP3 and cover art PNG from S3 to `/tmp` for ffmpeg processing.
- `generate_presigned_url` default expiry of 3600s (1 hour) matches the Site handler's `PRESIGNED_URL_EXPIRY` constant.
- The module creates a `boto3.client("s3")` at module level, cached across Lambda warm starts.

### Typing Conventions

- Every function in shared modules (`bedrock.py`, `db.py`, `s3.py`, `logging.py`) must have full type annotations — parameters and return types.
- No bare `Any` without an explicit `# type: ignore[...]` comment explaining why.
- `boto3-stubs` (already in devcontainer) provides typed clients: `mypy_boto3_bedrock_runtime`, `mypy_boto3_s3`, `mypy_boto3_secretsmanager`.
- Use `from __future__ import annotations` at the top of every file for PEP 604 union syntax (`X | Y`) and forward references.
