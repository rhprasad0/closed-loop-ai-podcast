> Part of the [Implementation Spec](../../IMPLEMENTATION_SPEC.md)

# Lambda Packaging & Deployment

Each Lambda needs its dependencies available at runtime. This section specifies how.

### Architecture & Constraints

All Lambda functions and layers target **x86_64** (Lambda's default architecture). This applies to pip `--platform` flags, static binaries (ffmpeg), and the `compatible_architectures` attribute on every `aws_lambda_layer_version` resource in Terraform.

Lambda limits that shape packaging decisions:

| Limit | Value |
|-------|-------|
| Layers per function | 5 |
| Total unzipped size (function + all layers) | 250 MB |

Layer attachment by function:

| Lambda | Layers | Est. Unzipped Size |
|--------|--------|--------------------|
| Discovery | shared | ~35 MB |
| Research, Script, Producer, Cover Art | shared | ~35 MB |
| TTS | shared | ~35 MB |
| Post-Production | shared + ffmpeg | ~115 MB |
| Site | shared | ~35 MB |
| MCP | shared | ~35 MB |

Post-Production is the tightest at ~115 MB — well within the 250 MB ceiling. No function uses more than 2 layers.

### Shared Layer

The shared layer at `lambdas/shared/` provides `bedrock.py`, `db.py`, `s3.py`, `logging.py`, and `types.py`. It also bundles `psycopg2` for Postgres access and `aws-lambda-powertools` for structured logging.

Use `psycopg2-binary` with `--platform manylinux2014_x86_64 --only-binary=:all:`. The manylinux2014 wheels are compatible with Lambda's Amazon Linux 2023 runtime for Python 3.12. The older advice about needing `aws-psycopg2` or a Docker-compiled build is outdated.

Built by `lambdas/shared/build.sh`:

```bash
#!/usr/bin/env bash
set -euo pipefail

# Build the shared Lambda Layer zip.
# Installs pip dependencies alongside the shared Python modules,
# then packages everything into a zip for Terraform to reference.
#
# Layer structure (extracted to /opt on Lambda):
#   python/shared/         -> shared utility modules (committed source)
#   python/psycopg2/       -> Postgres driver (pip-installed)
#   python/aws_lambda_powertools/ -> structured logging (pip-installed)

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

mkdir -p ../../build

echo "Installing dependencies into python/..."
pip install \
    psycopg2-binary==2.9.11 \
    aws-lambda-powertools==3.26.0 \
    -t python/ \
    --platform manylinux2014_x86_64 \
    --only-binary=:all: \
    --upgrade \
    --quiet

echo "Packaging shared layer..."
zip -r ../../build/shared-layer.zip python/

echo "Done: build/shared-layer.zip"
echo "Layer size: $(du -h ../../build/shared-layer.zip | cut -f1)"
```

**Directory structure clarification:** The `lambdas/shared/python/shared/` directory is committed source code. The pip-installed packages (`psycopg2/`, `aws_lambda_powertools/`, etc.) in `lambdas/shared/python/` are NOT committed — they are created by `build.sh` and excluded via `.gitignore`. See [Build Artifacts & .gitignore](#build-artifacts--gitignore).

**Terraform integration:** The shared layer is referenced in `lambdas.tf` as a pre-built zip:

```hcl
resource "aws_lambda_layer_version" "shared" {
  filename                 = "${path.module}/../build/shared-layer.zip"
  source_code_hash         = filebase64sha256("${path.module}/../build/shared-layer.zip")
  layer_name               = "${var.project_prefix}-shared"
  compatible_runtimes      = ["python3.12"]
  compatible_architectures = ["x86_64"]
}
```

The zip must exist before `terraform plan`. This is the same pattern used for the ffmpeg layer.

### Site Lambda

The site Lambda needs `jinja2`. Built by `lambdas/site/build.sh`:

```bash
#!/usr/bin/env bash
set -euo pipefail

# Install pip dependencies for the Site Lambda.
# Terraform's archive_file zips this directory — pip packages must be
# present before terraform plan.

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

echo "Installing dependencies into lambdas/site/..."
pip install jinja2==3.1.6 -t . --upgrade --quiet

echo "Done: lambdas/site/ ready for terraform plan"
```

Jinja2 is pure Python — no `--platform` flag needed (unlike `psycopg2-binary` or `mcp[cli]`, which include native extensions). Terraform's `data "archive_file"` on `lambdas/site/` zips `handler.py`, `templates/`, and the pip-installed jinja2 package.

### TTS Lambda

The TTS Lambda needs `requests` (or use `urllib3` from botocore to avoid an extra dependency). If using the bundled `urllib3`:

```python
from botocore.vendored import requests  # Don't do this — deprecated
# Instead, use urllib.request from stdlib
import urllib.request
```

**Decision:** Use `urllib.request` from Python stdlib for the ElevenLabs API call. No extra dependencies needed for the TTS Lambda.

### Post-Production Lambda

The Post-Production Lambda combines audio (MP3) and cover art (PNG) into a video (MP4) using ffmpeg. It attaches the **shared layer** (for S3/DB access) and the **ffmpeg layer** (for the `/opt/bin/ffmpeg` binary). No additional pip dependencies.

The deployment package is just `handler.py` — all heavy lifting comes from layers. This Lambda gets 1024 MB memory (ffmpeg needs more than the default 512 MB; see [Appendix A](../../IMPLEMENTATION_SPEC.md)).

### Discovery, Research, Script, Producer, Cover Art

Research, Script, Producer, and Cover Art only need `boto3` (pre-installed on Lambda) and the shared layer. No additional dependencies.

Discovery only needs `boto3` (pre-installed on Lambda), the shared layer (which includes `psycopg2` for the `query_postgres` tool), and `urllib.request` from stdlib for the Exa and GitHub API calls — no extra pip dependencies.

### MCP Lambda

The MCP Lambda bundles `mcp[cli]` into its deployment package and attaches the shared layer. Built by `lambdas/mcp/build.sh`:

```bash
#!/usr/bin/env bash
set -euo pipefail

# Install pip dependencies for the MCP Lambda.
# Terraform's archive_file zips this directory — pip packages must be
# present before terraform plan.

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

echo "Installing dependencies into lambdas/mcp/..."
pip install \
    "mcp[cli]==1.26.0" \
    -t . \
    --platform manylinux2014_x86_64 \
    --only-binary=:all: \
    --upgrade \
    --quiet

echo "Done: lambdas/mcp/ ready for terraform plan"
```

See [MCP Server — Dependencies](./mcp-server.md#dependencies) for the full dependency rationale.

### ffmpeg Layer

Built by `layers/ffmpeg/build.sh`:

```bash
#!/usr/bin/env bash
set -euo pipefail

# Download a static ffmpeg build compatible with Lambda (Amazon Linux 2023, x86_64)
FFMPEG_URL="https://johnvansickle.com/ffmpeg/releases/ffmpeg-release-amd64-static.tar.xz"
OUTPUT_DIR="$(dirname "$0")"
BUILD_DIR=$(mktemp -d)

echo "Downloading ffmpeg..."
curl -L "$FFMPEG_URL" -o "$BUILD_DIR/ffmpeg.tar.xz"

echo "Extracting..."
tar -xf "$BUILD_DIR/ffmpeg.tar.xz" -C "$BUILD_DIR"

echo "Packaging Lambda layer..."
mkdir -p "$BUILD_DIR/layer/bin"
cp "$BUILD_DIR"/ffmpeg-*-amd64-static/ffmpeg "$BUILD_DIR/layer/bin/ffmpeg"
chmod +x "$BUILD_DIR/layer/bin/ffmpeg"

cd "$BUILD_DIR/layer"
zip -r "$OUTPUT_DIR/ffmpeg-layer.zip" .

echo "Done: $OUTPUT_DIR/ffmpeg-layer.zip"
rm -rf "$BUILD_DIR"
```

**Fallback source:** The `johnvansickle.com` static builds are the standard source for static ffmpeg on Linux. If the site becomes unavailable, the [BtbN/FFmpeg-Builds](https://github.com/BtbN/FFmpeg-Builds) GitHub repository provides equivalent `linux64-gpl` static builds with daily automated releases. Substitute the download URL and adjust the tar extraction path (`ffmpeg-master-latest-linux64-gpl/bin/ffmpeg`).

### Lambda Deployment Packages

All 9 Lambda functions use Terraform's `data "archive_file"` to create their deployment zips — no manual `zip` commands needed. Terraform zips each Lambda's source directory at plan time and tracks changes via `source_code_hash`. See [Terraform Resource Map — lambdas.tf](./terraform-resource-map.md) for the full resource definitions.

For Lambdas with pip dependencies (Site, MCP), run their `build.sh` scripts before `terraform plan` so the pip packages are present in the source directory when `archive_file` runs.

What each Lambda's `archive_file` captures:

| Lambda | Source dir | Contents |
|--------|-----------|----------|
| Discovery | `lambdas/discovery/` | `handler.py`, `prompts/` |
| Research | `lambdas/research/` | `handler.py`, `prompts/` |
| Script | `lambdas/script/` | `handler.py`, `prompts/` |
| Producer | `lambdas/producer/` | `handler.py`, `prompts/` |
| Cover Art | `lambdas/cover_art/` | `handler.py`, `prompts/` |
| TTS | `lambdas/tts/` | `handler.py` |
| Post-Production | `lambdas/post_production/` | `handler.py` |
| Site | `lambdas/site/` | `handler.py`, `templates/`, pip-installed jinja2 |
| MCP | `lambdas/mcp/` | `handler.py`, `tools/`, `resources.py`, pip-installed mcp[cli] |

### Build Artifacts & .gitignore

Build scripts output artifacts that must NOT be committed to git:

| Artifact | Created by | Path |
|----------|-----------|------|
| Shared layer zip | `lambdas/shared/build.sh` | `build/shared-layer.zip` |
| ffmpeg layer zip | `layers/ffmpeg/build.sh` | `layers/ffmpeg/ffmpeg-layer.zip` |
| Pip packages in shared layer | `lambdas/shared/build.sh` | `lambdas/shared/python/*` (except `shared/`) |
| Pip packages in site Lambda | `lambdas/site/build.sh` | `lambdas/site/*` (except committed source) |
| Pip packages in MCP Lambda | `lambdas/mcp/build.sh` | `lambdas/mcp/*` (except committed source) |

The `build/` directory is created by `mkdir -p` in build scripts — it does not need to exist in the repo. Terraform's `archive_file` data sources also write Lambda deployment zips into `build/`, covered by the same gitignore entry.

Required `.gitignore` entries:

```
build/
layers/ffmpeg/ffmpeg-layer.zip
# Pip-installed packages in shared layer (source code in python/shared/ IS committed)
lambdas/shared/python/*
!lambdas/shared/python/shared/

# Pip-installed packages in site Lambda (handler.py, build.sh, templates/ ARE committed)
lambdas/site/*
!lambdas/site/handler.py
!lambdas/site/build.sh
!lambdas/site/templates/

# Pip-installed packages in MCP Lambda (handler.py, build.sh, tools/, resources.py ARE committed)
lambdas/mcp/*
!lambdas/mcp/handler.py
!lambdas/mcp/build.sh
!lambdas/mcp/tools/
!lambdas/mcp/resources.py
```

### Dev Dependencies

These packages are needed in the development environment (devcontainer) but are NOT deployed to Lambda:

```bash
pip install pytest pytest-cov moto mypy ruff \
    "boto3-stubs[bedrock-runtime,s3,secretsmanager]" \
    aws-lambda-powertools
```

The devcontainer Dockerfile installs these automatically. They support type checking (`mypy`, `boto3-stubs`), testing (`pytest`, `pytest-cov`, `moto`), and linting (`ruff`).

### Build Orchestration

`build-all.sh` at the repo root runs every build step in the correct order:

```bash
#!/usr/bin/env bash
set -euo pipefail

# Build all Lambda layers and install pip dependencies.
# Run this before terraform plan/apply.

REPO_ROOT="$(cd "$(dirname "$0")" && pwd)"

echo "=== Building layers and Lambda dependencies ==="

# Step 1: Build layers and install Lambda pip deps (all independent — run in parallel)
lambdas/shared/build.sh &
layers/ffmpeg/build.sh &
lambdas/site/build.sh &
lambdas/mcp/build.sh &

# Wait for all background jobs; fail if any failed
FAILED=0
for job in $(jobs -p); do
    wait "$job" || FAILED=1
done

if [ "$FAILED" -ne 0 ]; then
    echo "ERROR: One or more build steps failed."
    exit 1
fi

echo ""
echo "=== Build complete ==="
echo "Shared layer:  $(du -h build/shared-layer.zip 2>/dev/null | cut -f1 || echo 'MISSING')"
echo "ffmpeg layer:  $(du -h layers/ffmpeg/ffmpeg-layer.zip 2>/dev/null | cut -f1 || echo 'MISSING')"
echo ""
echo "Ready for: cd terraform && terraform init && terraform apply"
```

## Deployment Sequence

**Quick path:** Run `./build-all.sh` then `cd terraform && terraform init && terraform apply`.

Full steps for a from-scratch deploy:

1. **`./build-all.sh`** — builds all layers and installs Lambda pip dependencies in parallel.
2. **Database already provisioned.** The `zerostars` database and all tables (see [Database Schema](./database-schema.md)) exist on the RDS instance.
3. **Run `terraform init` and `terraform apply`** in `terraform/`.
4. **Enable Bedrock model access** for Claude and Nova Canvas in the AWS console (this cannot be done via Terraform).
5. **Verify:** Trigger a pipeline run via the [MCP server](./mcp-server.md) or manually start the Step Functions state machine from the AWS console.
