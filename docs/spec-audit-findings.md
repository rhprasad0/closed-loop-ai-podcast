# Spec Audit: Contradictions and Holes

Audit date: 2026-03-28. Covers all 15 spec documents in `docs/spec/`, `IMPLEMENTATION_SPEC.md`, and top-level docs (`README.md`, `CLAUDE.md`, `architecture.mermaid`).

**User decisions baked in:**
- MCP Lambda in separate `terraform/mcp.tf` (not `lambdas.tf`)
- DB access unified to `shared/db.py` with `DB_CONNECTION_STRING` env var everywhere
- 9 Lambdas total: 7 pipeline + site + MCP

---

## BLOCKING Issues (26)

Issues that would cause a coding agent to produce broken, crashing, or contradictory code.

### B1. TTS Lambda missing S3 permissions and `S3_BUCKET` env var

**Source:** `terraform-resource-map.md` lines 67, 78
**Conflict:** `interface-contracts.md` line 207, `file-manifest.md` line 140

TTS uploads MP3 to S3 (returns `s3_key`), but `terraform-resource-map.md` only lists `Secrets Manager read (ElevenLabs key)` for TTS IAM permissions — no `s3:PutObject`. The `S3_BUCKET` env var table lists Cover Art, Post-Production, Site but omits TTS. The TTS Lambda cannot write its output without both the env var and the IAM permission.

### B2. `DB_CONNECTION_STRING` env var missing for 5 Lambdas

**Source:** `terraform-resource-map.md` lines 69-81
**Conflict:** User decision (unified `shared/db.py`)

These Lambdas need DB access but have no `DB_CONNECTION_STRING` in their Terraform env var config:

| Lambda | Why it needs DB | IAM DB permission? |
|--------|----------------|-------------------|
| Discovery | `featured_developers` exclusion, `episodes` history | No (only SSM, which is now obsolete) |
| Producer | Benchmark query (`episodes` + `episode_metrics`) | No (only `bedrock:InvokeModel`) |
| Post-Production | Writes to `episodes` and `featured_developers` | Not specified |
| Site | Queries `episodes` table | Not specified |
| MCP | All data tools, resources, health checks | No (only SSM, now obsolete) |

### B3. Producer `BENCHMARK_QUERY` uses INNER JOIN on empty `episode_metrics`

**Source:** `type-checking.md` line 375+

The query `SELECT e.script_text FROM episodes e JOIN episode_metrics em ON e.episode_id = em.episode_id ORDER BY (...) DESC LIMIT 3` uses INNER JOIN. When `episode_metrics` has zero rows (true for all early runs and indefinitely until metrics are manually populated), this returns zero rows even when `episodes` has scripts. The quality ratchet is silently disabled. Fix: `LEFT JOIN` with `COALESCE`.

### B4. PostProduction interface contract omits `featured_developers` INSERT

**Source:** `interface-contracts.md` (PostProduction section)
**Conflict:** `file-manifest.md`, `testing.md`

The file manifest and testing spec both say PostProduction writes to `featured_developers`, but the interface contract makes zero mention of it. Without this INSERT, Discovery's duplicate-developer exclusion query will never have data.

### B5. `episodes.air_date` and `featured_developers.featured_date` computation unspecified

**Source:** `database-schema.md` (both are `DATE NOT NULL`)
**Conflict:** No spec documents how these dates are computed

An implementer must guess: `date.today()`? Next Sunday? Scheduled execution date? Both columns are NOT NULL so a value is required.

### B6. `terraform/mcp.tf` missing from `file-manifest.md`

**Source:** `mcp-server.md` line 825 ("New file: `terraform/mcp.tf`")
**Conflict:** `file-manifest.md` lines 7-21 (tree) and 104-116 (table)

The tree and table both omit `mcp.tf`. A coding agent using only `file-manifest.md` will not create this file and its 7 resources (Lambda, IAM, Function URL, log group, etc.).

### B7. `terraform/observability.tf` missing from `file-manifest.md` tree

**Source:** `file-manifest.md` line 116 (table mentions it)
**Conflict:** `file-manifest.md` lines 13-20 (tree ends at `secrets.tf`)

Internal contradiction: the table row exists but the directory tree omits the file.

### B8. Lambda count inconsistency: "8" vs "9" across specs

**Source:** Multiple specs

| Spec | Says | Should Say |
|------|------|-----------|
| `terraform-resource-map.md` line 49 | "all 8 functions" | "all 9 functions" (or "8 in lambdas.tf + MCP in mcp.tf") |
| `terraform-resource-map.md` line 63 | Lists 9 service names under "all 8" heading | Fix heading |
| `packaging-and-deployment.md` line 267 | "All 8 Lambda functions" | 9 |
| `file-manifest.md` line 111 | "All 8 Lambda functions" | 8 in lambdas.tf (note MCP separately) |
| `mcp-server.md` line 908 | "All 8 Lambda log group ARNs" | 9 (include MCP's own) |

`observability.md` and `instrumentation.md` correctly say 9.

### B9. ResumeRouter ASL state missing from `step-functions-asl.md`

**Source:** `mcp-server.md` lines 917-936
**Conflict:** `step-functions-asl.md` line 61 (`InitializeMetadata.Next = "Discovery"`)

The MCP spec defines a `ResumeRouter` Choice state inserted after `InitializeMetadata` to support `retry_from_step`. This state is completely absent from the ASL spec. A coding agent implementing the ASL will produce a state machine incompatible with MCP's `retry_from_step` tool.

### B10. X-Ray tracing config missing from `terraform-resource-map.md`

**Source:** `instrumentation.md` lines 243-267
**Conflict:** `terraform-resource-map.md` (entire file)

Every Lambda needs `tracing_config { mode = "Active" }` and `AWSXrayWriteOnlyAccess` managed policy. The Terraform resource map mentions neither. A coding agent using this spec will produce Lambdas with no X-Ray tracing.

### B11. MCP Lambda Terraform HCL incomplete

**Source:** `mcp-server.md` lines 839-870
**Conflict:** `instrumentation.md` lines 233-267

The MCP HCL snippet is missing vs the standard Lambda pattern:

| Missing Element | Effect |
|----------------|--------|
| `POWERTOOLS_METRICS_NAMESPACE = "ZeroStars"` | Metrics `SchemaValidationError` at runtime |
| `POWERTOOLS_TRACER_CAPTURE_RESPONSE = "false"` | Defaults to true, risks X-Ray 64KB overflow on streamed responses |
| `tracing_config { mode = "Active" }` | No X-Ray tracing, `xray_trace_id` absent from logs |
| `depends_on` block | Race conditions during `terraform apply` |
| `DB_CONNECTION_STRING` env var | Cannot access Postgres |

### B12. `variables.tf` missing 6+ variables

**Source:** `terraform-resource-map.md` lines 19-25 (lists 5 variables)
**Conflict:** `observability.md`, `mcp-server.md`

Missing variables:

| Variable | Referenced In |
|----------|-------------|
| `alert_email` | `observability.md` (SNS subscription) |
| `mcp_allowed_principal` | `mcp-server.md` line 879 |
| `pipeline_failure_threshold` | `observability.md` line 70 |
| `lambda_error_threshold` | `observability.md` line 110 |
| `lambda_timeout_threshold_ms` | `observability.md` |
| `producer_fail_threshold` | `observability.md` |

`file-manifest.md` line 109 also only lists 4 of 10+ variables.

### B13. Discovery Lambda: psql subprocess and SSM references contradict DB unification

**Source:** `interface-contracts.md` lines 60-66, `external-api-contracts.md` lines 271-309
**Conflict:** User decision (unified `shared/db.py`)

Multiple specs describe Discovery using `psql` binary subprocess with SSM Parameter Store. Under the unification decision, Discovery must use `shared/db.py` with `DB_CONNECTION_STRING`. Affected specs (22+ references across 12 files — see SSM Reference Table below).

### B14. MCP `tools/` subdirectory missing from `file-manifest.md`

**Source:** `mcp-server.md` lines 794-806
**Conflict:** `file-manifest.md` lines 65-67

`mcp-server.md` defines `tools/` with 7 files (`__init__.py`, `pipeline.py`, `agents.py`, `observation.py`, `data.py`, `assets.py`, `site.py`) plus `resources.py`. `file-manifest.md` only lists `handler.py` and `build.sh` under `lambdas/mcp/`. A coding agent following file-manifest will miss 8 files.

### B15. MCP `archive_file` contents spec omits `tools/` and `resources.py`

**Source:** `packaging-and-deployment.md` line 283
**Conflict:** `mcp-server.md` lines 794-806

The packaging spec says MCP archive contains "handler.py, pip-installed mcp[cli]" — omits the entire `tools/` directory and `resources.py`.

### B16. `tests/e2e/` directory missing from `file-manifest.md`

**Source:** `testing.md` (defines 6 e2e test files in `tests/e2e/`)
**Conflict:** `file-manifest.md` (no `tests/e2e/` directory)

`file-manifest.md` says "Every file below must be created. No other files should be created." An implementer following it will skip all e2e tests.

### B17. `test_discovery_e2e.py` placed in conflicting locations

**Source:** `file-manifest.md` → `tests/integration/test_discovery_e2e.py` with `@pytest.mark.integration`
**Conflict:** `testing.md` → `tests/e2e/test_discovery_e2e.py` with `@pytest.mark.e2e`

Different path and different marker. CI commands will collect differently.

### B18. All MCP test files (13) missing from `file-manifest.md`

**Source:** `testing.md`, `testing-mcp.md`
**Conflict:** `file-manifest.md`

Missing files: 10 unit tests (`tests/unit/test_mcp/`), 3 integration tests (`test_mcp_pipeline_live.py`, `test_mcp_data_live.py`, `test_mcp_assets_live.py`). Since `file-manifest.md` is the authoritative file list, a coding agent won't create MCP tests.

### B19. CI pipeline does not install `mcp[cli]`

**Source:** `ci-pipeline.md` lines 32-34
**Conflict:** `testing.md`, `testing-mcp.md`

`pytest tests/unit/` recursively discovers `tests/unit/test_mcp/`, which imports from MCP SDK. CI will fail with ImportError.

### B20. CI pipeline has no pinned versions for pip dependencies

**Source:** `ci-pipeline.md` lines 32-34
**Conflict:** `packaging-and-deployment.md` lines 59-60, 106

CI installs `psycopg2-binary`, `jinja2`, `aws-lambda-powertools` without version pins. Packaging spec pins `==2.9.11`, `==3.26.0`, `==3.1.6`. CI could test against different versions than what deploys.

### B21. `test_research_live.py` missing from `file-manifest.md`

**Source:** `testing.md`
**Conflict:** `file-manifest.md`

Integration test with 5 test functions not in the file manifest.

### B22. Discovery `episode_metrics` contradiction (README/architecture vs spec)

**Source:** `README.md` lines 109-110, 149; `architecture.mermaid` line 54
**Conflict:** `interface-contracts.md` line 62 ("does not read `episode_metrics` in v1")

README says "Queries episode metrics to bias toward what performs well." Architecture mermaid draws `RDS -> DISCOVERY` with label "episode history + metrics feed search objectives." The spec explicitly defers this.

### B23. PostProduction IC describes S3 keys only as ffmpeg inputs, not DB column sources

**Source:** `interface-contracts.md` (PostProduction section)

The IC lists `$.tts.s3_key` and `$.cover_art.s3_key` for ffmpeg use but these same values must also be written to `s3_mp3_path` and `s3_cover_art_path` DB columns. The documentation gap could cause an implementer to skip the DB writes.

### B24. psql Lambda Layer may be entirely unnecessary

**Source:** `packaging-and-deployment.md` (psql layer section), `terraform-resource-map.md` line 41
**Conflict:** User decision (unified `shared/db.py`)

Discovery was the sole consumer of the psql layer. If Discovery uses `shared/db.py` with psycopg2, no Lambda needs the psql layer. References to remove span 6+ spec files (see psql Layer References below).

### B25. README repo structure diverges from spec

**Source:** `README.md` lines 174-218
**Conflict:** `file-manifest.md`, `terraform-resource-map.md`

| README Shows | Spec Says |
|-------------|-----------|
| `terraform/modules/lambda/` | Does not exist |
| `terraform/mcp.tf` | Correct per mcp-server.md, but missing from file-manifest |
| `terraform/rds.tf` | Does not exist (RDS already provisioned) |
| `lambdas/cover-art/` (hyphenated) | `lambdas/cover_art/` (underscored) |
| `lambdas/post-production/` (hyphenated) | `lambdas/post_production/` (underscored) |
| `lambdas/mcp/tools/` | Missing from file-manifest but correct per mcp-server.md |
| `site/` top-level directory | Does not exist in spec |
| No `terraform/observability.tf` | Required per observability.md |
| No `terraform/secrets.tf` | Required per terraform-resource-map.md |
| No `layers/psql/` | In file-manifest (though may be removed per B24) |

### B26. `interface-contracts.md` TODO at line 261 should be removed

**Source:** `interface-contracts.md` line 261
**Status:** Already resolved in `prompt-files.md`

The TODO says the script format spec must be embedded in prompts. Both the Script prompt (`<script_format>` section) and Producer rubric (criterion 9) already contain it. The TODO is stale and would confuse a coding agent into thinking work remains.

---

## WARNING Issues (30)

Issues that won't cause crashes but create confusion, incomplete coverage, or subtle bugs.

### Infrastructure & Config Warnings

| # | Issue | Source | Details |
|---|-------|--------|---------|
| W1 | `terraform-resource-map.md` has no `mcp.tf` section | `mcp-server.md` | Resource map documents every other .tf file but has no MCP section or cross-reference |
| W2 | `terraform-resource-map.md` IAM table has no MCP row | Lines 69-80 | Only 8 Lambdas in the IAM table; MCP permissions only in `mcp-server.md` |
| W3 | `outputs.tf` missing `mcp_function_url` | `terraform-resource-map.md` lines 29-33 | Only 3 outputs listed; MCP URL defined only in `mcp-server.md` |
| W4 | MCP IAM `ssm:GetParameter` is obsolete | `mcp-server.md` line 911 | Per DB unification, no Lambda reads from SSM |
| W5 | Discovery IAM `SSM GetParameter` is obsolete | `terraform-resource-map.md` line 73 | Same reason |
| W6 | MCP `get_agent_logs` says "All 8 Lambda log group ARNs" | `mcp-server.md` line 908 | Should be 9 (include its own) |
| W7 | Alarm threshold variables implied but never defined as HCL | `observability.md` | `pipeline_timeout_threshold`, `lambda_throttle_threshold`, `script_length_threshold` implied but no `variable` blocks shown |
| W8 | Script length alarm hardcodes threshold 4,900 | `observability.md` line 121 | Producer fail alarm uses a variable; script length does not. Inconsistent pattern |
| W9 | API key secret ARN/name not documented in Terraform env vars | `terraform-resource-map.md` | TTS and Discovery must know which Secrets Manager secret to fetch — neither hardcoded name nor env var is documented |
| W10 | Terraform `logging_config` drift bug workaround may be unnecessary | `instrumentation.md` line 269 | Bug #42181 fixed in provider >= 6.1.0. `lifecycle { ignore_changes }` no longer needed if targeting >= 6.1.0 |

### Data Flow Warnings

| # | Issue | Source | Details |
|---|-------|--------|---------|
| W11 | No `execution_id` column in `episodes` table | `database-schema.md` | No DB-level traceability to Step Functions executions |
| W12 | No `language` column in `episodes` table | `database-schema.md` | Discovery's `language` field is lost after pipeline completion |
| W13 | `discovery_rationale` not persisted | `interface-contracts.md` | Available in state but not written to DB |
| W14 | `producer_score` and `producer_notes` not persisted | `interface-contracts.md` | Available in state but not written to DB |
| W15 | `episode_metrics` unique constraint gap | `mcp-server.md` line 642, `database-schema.md` | MCP `upsert_metrics` needs `UNIQUE (episode_id, snapshot_date)` but DDL doesn't have it |
| W16 | Discovery prompt DB schema shows 7 of 15 columns | `prompt-files.md` lines 63-80 | Likely intentional simplification but undocumented as deliberate |

### Testing Warnings

| # | Issue | Source | Details |
|---|-------|--------|---------|
| W17 | `test_cover_art_e2e.py` missing from BOTH directory trees | `testing.md`, `file-manifest.md` | Referenced in code sections and table, but absent from both directory tree listings |
| W18 | `query_metrics` MCP tool has no test code shown | `testing-mcp.md` | Requirements table says to test it, but no code in `test_data.py` |
| W19 | `invoke_tts` and `invoke_post_production` agent tests have no code | `testing-mcp.md` | Requirements listed but `test_agents.py` code only covers through `invoke_cover_art` |
| W20 | Packaging test checks 6 of 8 shared modules | `testing.md` | Missing: `tracing.py`, `metrics.py` |
| W21 | `mock_db_connection` fixture comment omits Producer | `testing.md` line 154 | Says "Post-Production, Site" but Producer also uses `shared.db.query` |
| W22 | TTS, Post-Production, Site have no E2E tests | `testing.md` | Likely intentional (cost, complexity) but is a coverage gap |
| W23 | TTS, Post-Production, Site unit test code not shown | `testing.md` | Requirements listed but no actual test code (other handlers have full code) |
| W24 | MCP test fixtures missing 3 env vars | `testing-mcp.md` lines 48-57 | Missing `POWERTOOLS_METRICS_NAMESPACE`, `POWERTOOLS_TRACER_CAPTURE_RESPONSE`, `DB_CONNECTION_STRING` |

### Prompt & Contract Warnings

| # | Issue | Source | Details |
|---|-------|--------|---------|
| W25 | Cover art template base length is 622 chars, not ~571 | `prompt-files.md` | Reduces variable headroom from ~453 to ~402 characters against 1024 char Nova Canvas limit |
| W26 | Research prompt `developer_bio` default to `""` on null undocumented | `prompt-files.md` | Interface contract schema does not document this convention |
| W27 | Producer rubric doesn't verify `character_count` equals actual `text` length | `prompt-files.md` | A Script agent reporting incorrect count would pass the Producer |
| W28 | Observability alarm fires at 4,900 chars; Producer auto-fails at 5,000 | `observability.md`, `prompt-files.md` | Scripts 4,900-4,999 trigger alarm but pass Producer. Appears intentional (early warning) |
| W29 | MCP spec SSM prose references in multiple sections | `mcp-server.md` lines 479, 944 | Beyond IAM, the design narrative references "connection string from SSM" |
| W30 | Powertools `log_uncaught_exceptions` may not work in Lambda runtime | Powertools docs | Feature is correct API but Powertools maintainers warn it may not function in Lambda |

---

## External API Validation Summary

All external API claims verified against current documentation. Everything checks out.

| API | Claims Checked | Result |
|-----|---------------|--------|
| AWS Bedrock (Claude) | 7 (model ID, Messages API, tool use, thinking, Nova Canvas, States.MathAdd, invoke_model) | All CONFIRMED |
| ElevenLabs | 8 (endpoint, request format, model ID, output format, char limit, voice IDs, auth) | All CONFIRMED |
| Terraform Provider | 8 (logging_config, Function URL, OAC, ACM, jsonencode, tracing_config, archive_file) | All CONFIRMED |
| GitHub REST API | 5 (endpoints, rate limits, User-Agent, base64, search syntax) | All CONFIRMED |
| Exa Search API | 4 (endpoint, request format, auth, response format) | All CONFIRMED |
| Python Libraries | 11 (Powertools 3.26.0, Logger/Tracer/Metrics API, psycopg2, mcp, jinja2, boto3) | All CONFIRMED |

**Minor notes from external validation:**
- Bedrock `effort` parameter is still labeled **(beta)** in docs; may need `anthropic_beta` header
- Terraform `logging_config` drift bug (#42181) is fixed in provider >= 6.1.0; workaround can be removed
- Powertools `log_uncaught_exceptions=True` has a runtime warning from maintainers

---

## SSM References to Remove (DB Unification)

All references to SSM Parameter Store for DB connection strings must be replaced with `DB_CONNECTION_STRING` env var.

| File | Location | Current Reference | Replacement |
|------|----------|-------------------|-------------|
| `IMPLEMENTATION_SPEC.md` | Line 54, Appendix A | SSM path `/zerostars/db-connection-string` | Remove row or note `DB_CONNECTION_STRING` env var |
| `terraform-resource-map.md` | Line 73, Discovery IAM | `SSM GetParameter` | Remove |
| `interface-contracts.md` | Lines 60-61, Discovery section | "fetches DB connection string from SSM" + psql subprocess | "uses `DB_CONNECTION_STRING` env var via `shared/db.py`" |
| `external-api-contracts.md` | Lines 271-309, `query_postgres` handler | Full psql subprocess implementation with SSM | Rewrite to `shared/db.py` + psycopg2 |
| `mcp-server.md` | Line 479, Data tools | "Connection string from SSM" | "via `DB_CONNECTION_STRING` env var" |
| `mcp-server.md` | Line 911, IAM table | `ssm:GetParameter` | Remove row |
| `mcp-server.md` | Line 944, Design Decisions | "connection string from SSM" | "via `DB_CONNECTION_STRING` env var" |
| `instrumentation.md` | Line 92 | "SSM/Secrets Manager values" | Clarify: env var for DB, Secrets Manager for API keys only |
| `type-checking.md` | Lines 228, 235-236 | `_db_connection_string` from SSM, cached | Remove SSM caching pattern for Discovery |
| `type-checking.md` | Line 287 | `_db_connection_string and _exa_api_key` | Remove `_db_connection_string` (only `_exa_api_key` remains) |
| `type-checking.md` | Lines 437, 443 | "not fetched from SSM like Discovery's" | Remove comparison |
| `type-checking.md` | Line 563 | "ssm extra needed for Discovery" | Remove SSM reference |
| `testing.md` | Lines 166-179 | `mock_ssm` fixture | Remove fixture |
| `testing.md` | Line 509 | SSM mock row in table | Remove |
| `testing.md` | Lines 594-647 | Tests using `mock_ssm` | Remove SSM dependency from tests |
| `testing.md` | Lines 2567-2584 | `test_ssm_parameter_exists` | Remove or repurpose |
| `testing.md` | Lines 3126-3128 | Integration test using SSM | Use `DB_CONNECTION_STRING` env var |
| `testing-mcp.md` | Lines 1088-1092 | Integration test fetches from SSM | Use `DB_CONNECTION_STRING` env var |
| `testing-mcp.md` | Lines 1110-1114 | Integration test fetches from SSM | Use `DB_CONNECTION_STRING` env var |
| `testing-mcp.md` | Lines 1128-1132 | Integration test fetches from SSM | Use `DB_CONNECTION_STRING` env var |
| `file-manifest.md` | Line 173 | "Discovery external deps (psql, SSM, GitHub API)" | Remove `SSM` |
| `ci-pipeline.md` | Lines 34, 85 | `boto3-stubs[...,ssm]` | Remove `ssm` extra |

---

## psql Layer References to Remove

If Discovery uses `shared/db.py`, no Lambda needs the psql layer.

| File | Location | Reference |
|------|----------|-----------|
| `packaging-and-deployment.md` | Line 22 | Layer table entry |
| `packaging-and-deployment.md` | Line 135 | Discovery description |
| `packaging-and-deployment.md` | Lines 166-229 | Entire "psql Layer" section |
| `packaging-and-deployment.md` | Line 293 | Build artifacts table |
| `packaging-and-deployment.md` | Line 305 | `.gitignore` entry |
| `packaging-and-deployment.md` | Lines 352, 372 | `build-all.sh` script |
| `terraform-resource-map.md` | Line 41 | psql layer resource in `lambdas.tf` |
| `terraform-resource-map.md` | Line 73 | Discovery layers: "shared + psql" |
| `file-manifest.md` | Lines 71-72 | `layers/psql/` in tree |
| `file-manifest.md` | Line 187 | `layers/psql/build.sh` table row |
| `file-manifest.md` | Line 111 | lambdas.tf description mentioning psql |
| `file-manifest.md` | Lines 170, 173-174 | Test descriptions referencing psql |
| `interface-contracts.md` | Lines 60, 66 | psql subprocess references |
| `external-api-contracts.md` | Lines 74-75, 271-300 | `query_postgres` psql handler implementation |
| `prompt-files.md` | Line 57 | psql reference in Discovery prompt |
| `type-checking.md` | Lines 215, 255-283 | psql subprocess types |
| `testing.md` | Multiple locations | `mock_subprocess` fixture, Discovery psql tests |

---

## Master Environment Variable Table

| Lambda | Env Var | Needed For | In Terraform? |
|--------|---------|-----------|---------------|
| **All 9** | `POWERTOOLS_SERVICE_NAME` | Logging/metrics/tracing | YES (8 in TF resource map + MCP in mcp-server.md) |
| **All 9** | `POWERTOOLS_LOG_LEVEL` | Log level | YES |
| **All 9** | `POWERTOOLS_METRICS_NAMESPACE` | Metrics namespace | **NO for MCP** |
| **All 9** | `POWERTOOLS_TRACER_CAPTURE_RESPONSE` | Disable response capture | **NO for MCP** |
| Discovery | `DB_CONNECTION_STRING` | Postgres access | **NO** |
| Producer | `DB_CONNECTION_STRING` | Benchmark queries | **NO** |
| Post-Production | `DB_CONNECTION_STRING` | Write episode records | **NO** |
| Site | `DB_CONNECTION_STRING` | Query episodes | **NO** |
| MCP | `DB_CONNECTION_STRING` | All data tools | **NO** |
| Cover Art | `S3_BUCKET` | Upload PNG | YES |
| TTS | `S3_BUCKET` | Upload MP3 | **NO** |
| Post-Production | `S3_BUCKET` | Read/write MP3, PNG, MP4 | YES |
| Site | `S3_BUCKET` | Presigned URLs | YES |
| MCP | `S3_BUCKET` | Asset tools | YES (mcp-server.md) |
| MCP | `STATE_MACHINE_ARN` | Pipeline control | YES (mcp-server.md) |
| MCP | `CLOUDFRONT_DISTRIBUTION_ID` | Cache invalidation | YES (mcp-server.md) |
| MCP | `ACM_CERTIFICATE_ARN` | SSL status check | YES (mcp-server.md) |
| MCP | `SITE_DOMAIN` | Domain display | YES (mcp-server.md) |

**10 env var gaps** across 6 Lambdas (5x `DB_CONNECTION_STRING`, 1x `S3_BUCKET` for TTS, 2x Powertools for MCP, plus corresponding IAM permissions).

---

## Test File Discrepancy Table

Files present in `testing.md` / `testing-mcp.md` but absent from `file-manifest.md`:

| Test File | Status |
|-----------|--------|
| `tests/unit/test_mcp/__init__.py` | Missing from file-manifest |
| `tests/unit/test_mcp/conftest.py` | Missing from file-manifest |
| `tests/unit/test_mcp/test_pipeline.py` | Missing from file-manifest |
| `tests/unit/test_mcp/test_agents.py` | Missing from file-manifest |
| `tests/unit/test_mcp/test_observation.py` | Missing from file-manifest |
| `tests/unit/test_mcp/test_data.py` | Missing from file-manifest |
| `tests/unit/test_mcp/test_assets.py` | Missing from file-manifest |
| `tests/unit/test_mcp/test_site.py` | Missing from file-manifest |
| `tests/unit/test_mcp/test_resources.py` | Missing from file-manifest |
| `tests/unit/test_mcp/test_handler.py` | Missing from file-manifest |
| `tests/integration/test_research_live.py` | Missing from file-manifest |
| `tests/integration/test_mcp_pipeline_live.py` | Missing from file-manifest |
| `tests/integration/test_mcp_data_live.py` | Missing from file-manifest |
| `tests/integration/test_mcp_assets_live.py` | Missing from file-manifest |
| `tests/e2e/__init__.py` | Missing (entire `e2e/` dir absent) |
| `tests/e2e/test_discovery_e2e.py` | **CONFLICT**: file-manifest puts it in `integration/` |
| `tests/e2e/test_research_e2e.py` | Missing from file-manifest |
| `tests/e2e/test_script_e2e.py` | Missing from file-manifest |
| `tests/e2e/test_producer_e2e.py` | Missing from file-manifest |
| `tests/e2e/test_cover_art_e2e.py` | Missing from both trees (referenced in code/tables only) |
| `tests/e2e/test_mcp_e2e.py` | Missing from file-manifest |

**21 test files** in the testing specs but not in the file manifest.

---

## Top-Level Document Updates Needed

### README.md
1. **Repo Structure** (lines 174-218): Replace with spec-accurate tree. Fix hyphens to underscores, remove nonexistent dirs, add missing dirs.
2. **Pipeline Flow** (lines 109-110): Remove "Queries episode metrics to bias toward what performs well" — deferred in v1.
3. **Agent Design Patterns** (lines 149): Fix "Cross-episode learning" — remove Discovery metrics claim. Keep Producer benchmark claim.
4. **Verify Deployment section** (lines 295-305): Add `build-all.sh` step. Verify required variables match spec.

### CLAUDE.md
1. **Repo Layout** (lines 13-21): Add `layers/psql/` (if kept) or remove. Ensure matches spec.

### architecture.mermaid
1. **Line 54**: Change `"episode history + metrics feed search objectives"` to `"episode history + featured devs exclusion list"` — Discovery does not read metrics in v1.
2. **Update README's inline copy** (lines 12-94) to match.

---

## Priority Order for Fixes

**Fix first (implementation-blocking):**
1. B2 — `DB_CONNECTION_STRING` env var gaps (5 Lambdas)
2. B1 — TTS `S3_BUCKET` + IAM
3. B13 — Discovery psql→shared/db.py rewrite + B24 psql layer removal
4. B6/B7/B14 — file-manifest gaps (mcp.tf, observability.tf, MCP tools/, e2e tests)
5. B9 — ResumeRouter ASL state
6. B10/B11 — X-Ray tracing + MCP HCL completeness
7. B12 — variables.tf gaps
8. B3 — Producer BENCHMARK_QUERY JOIN fix
9. B4/B5/B23 — PostProduction contract gaps

**Fix second (confusion risk):**
10. B8 — Lambda count references (8→9)
11. B16-B21 — Test file/CI alignment
12. B22/B25/B26 — README, architecture, stale TODO

**Fix last (nice-to-have):**
13. W11-W16 — Untracked data fields, schema gaps
14. W17-W24 — Test coverage gaps
15. W25-W30 — Minor prompt/observability notes
