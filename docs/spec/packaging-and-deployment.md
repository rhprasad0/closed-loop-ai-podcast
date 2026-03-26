> Part of the [Implementation Spec](../../IMPLEMENTATION_SPEC.md)

# Lambda Packaging & Deployment

Each Lambda needs its dependencies available at runtime. This section specifies how.

### Shared Layer

The shared layer at `lambdas/shared/` provides `bedrock.py`, `db.py`, `s3.py`, `logging.py`, and `types.py`. It also needs `psycopg2` for Postgres access and `aws-lambda-powertools` for structured logging.

Use `psycopg2-binary` is not compatible with Lambda's Amazon Linux environment. Use the `aws-psycopg2` package or include a pre-compiled `psycopg2` for Linux x86_64.

**Recommended approach:** Use a Lambda-compatible psycopg2 build. The `build.sh` pattern:

```bash
cd lambdas/shared
pip install aws-lambda-powertools psycopg2-binary -t python/ --platform manylinux2014_x86_64 --only-binary=:all:
# shared Python modules are already in python/shared/
zip -r ../../build/shared-layer.zip python/
```

Note: `psycopg2-binary` wheels for `manylinux2014_x86_64` DO work on Lambda. The old advice about needing a special build is outdated for Python 3.12 + `manylinux2014` wheels.

> **TODO:** Add a `lambdas/shared/build.sh` script to the file manifest that automates this (pip install + zip). Currently not in the manifest — the build steps above are manual.

### Site Lambda

The site Lambda needs `jinja2`. Include it in the deployment package:

```bash
cd lambdas/site
pip install jinja2 -t .
zip -r ../../build/site.zip .
```

### TTS Lambda

The TTS Lambda needs `requests` (or use `urllib3` from botocore to avoid an extra dependency). If using the bundled `urllib3`:

```python
from botocore.vendored import requests  # Don't do this — deprecated
# Instead, use urllib.request from stdlib
import urllib.request
```

**Decision:** Use `urllib.request` from Python stdlib for the ElevenLabs API call. No extra dependencies needed for the TTS Lambda.

### Other Pipeline Lambdas

Research, Script, Producer, Cover Art — these only need `boto3` (pre-installed on Lambda) and the shared layer. No additional dependencies.

Discovery additionally needs the psql Lambda layer (see below) and uses `urllib.request` from stdlib for the Exa and GitHub API calls — no extra pip dependencies.

### psql Layer

Built by `layers/psql/build.sh`. Provides the `psql` binary and `libpq` shared library for Lambda (Amazon Linux 2023, x86_64). Used by the Discovery Lambda's `query_postgres` tool to run SQL queries via subprocess.

Lambda extracts layers to `/opt`. The layer structure places `bin/psql` at `/opt/bin/psql` (in Lambda's default `PATH`) and `lib/libpq.so*` at `/opt/lib/` (in Lambda's default `LD_LIBRARY_PATH`). No additional environment configuration needed.

```bash
#!/usr/bin/env bash
set -euo pipefail

# Build a Lambda layer containing the psql binary for Amazon Linux 2023 (x86_64).
# The binary and libpq are extracted from official PostgreSQL PGDG RPMs for RHEL 9,
# which are binary-compatible with AL2023.
#
# Layer structure:
#   bin/psql      -> /opt/bin/psql on Lambda (in default PATH)
#   lib/libpq.so* -> /opt/lib/ on Lambda (in default LD_LIBRARY_PATH)

OUTPUT_DIR="$(cd "$(dirname "$0")" && pwd)"
BUILD_DIR=$(mktemp -d)
POSTGRES_VERSION="16"
AL2023_REPO="https://download.postgresql.org/pub/repos/yum/${POSTGRES_VERSION}/redhat/rhel-9-x86_64"

echo "Downloading PostgreSQL ${POSTGRES_VERSION} RPMs for RHEL 9 (AL2023-compatible)..."

# Download the psql binary RPM
RPM_URL=$(curl -sL "${AL2023_REPO}/" \
    | grep -oP "postgresql${POSTGRES_VERSION}-${POSTGRES_VERSION}\.[0-9.]+-[0-9]+PGDG\.rhel9\.x86_64\.rpm" \
    | sort -V | tail -1)
if [ -z "$RPM_URL" ]; then
    echo "ERROR: Could not find PostgreSQL RPM in PGDG repo."
    exit 1
fi
echo "  psql RPM: $RPM_URL"
curl -sL "${AL2023_REPO}/${RPM_URL}" -o "$BUILD_DIR/postgresql.rpm"

# Download the libpq shared library RPM
LIBPQ_URL=$(curl -sL "${AL2023_REPO}/" \
    | grep -oP "postgresql${POSTGRES_VERSION}-libs-${POSTGRES_VERSION}\.[0-9.]+-[0-9]+PGDG\.rhel9\.x86_64\.rpm" \
    | sort -V | tail -1)
if [ -z "$LIBPQ_URL" ]; then
    echo "ERROR: Could not find PostgreSQL libs RPM in PGDG repo."
    exit 1
fi
echo "  libpq RPM: $LIBPQ_URL"
curl -sL "${AL2023_REPO}/${LIBPQ_URL}" -o "$BUILD_DIR/postgresql-libs.rpm"

echo "Extracting RPMs..."
cd "$BUILD_DIR"
rpm2cpio postgresql.rpm | cpio -idmv 2>/dev/null
rpm2cpio postgresql-libs.rpm | cpio -idmv 2>/dev/null

echo "Packaging Lambda layer..."
mkdir -p "$BUILD_DIR/layer/bin" "$BUILD_DIR/layer/lib"
cp "$BUILD_DIR/usr/pgsql-${POSTGRES_VERSION}/bin/psql" "$BUILD_DIR/layer/bin/psql"
cp "$BUILD_DIR/usr/pgsql-${POSTGRES_VERSION}/lib/"libpq.so* "$BUILD_DIR/layer/lib/"
chmod +x "$BUILD_DIR/layer/bin/psql"

cd "$BUILD_DIR/layer"
zip -r "$OUTPUT_DIR/psql-layer.zip" .

echo "Done: $OUTPUT_DIR/psql-layer.zip"
echo "Layer size: $(du -h "$OUTPUT_DIR/psql-layer.zip" | cut -f1)"
rm -rf "$BUILD_DIR"
```

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

### Dev Dependencies

These packages are needed in the development environment (devcontainer) but are NOT deployed to Lambda:

```bash
pip install pytest pytest-cov moto mypy ruff \
    "boto3-stubs[bedrock-runtime,s3,secretsmanager,ssm]" \
    aws-lambda-powertools
```

The devcontainer Dockerfile installs these automatically. They support type checking (`mypy`, `boto3-stubs`), testing (`pytest`, `pytest-cov`, `moto`), and linting (`ruff`).

## Deployment Sequence

Steps to deploy the pipeline from scratch, in order:

1. **Run `layers/ffmpeg/build.sh`** to create `ffmpeg-layer.zip`.
2. **Database already created.** The `zerostars` database and all tables (see [Database Schema](./database-schema.md)) have been provisioned on the RDS instance.
3. **Build the shared layer** (install psycopg2, zip).
4. **Run `terraform init` and `terraform apply`** in `terraform/`.
5. **Enable Bedrock model access** for Claude and Nova Canvas in the AWS console (this cannot be done via Terraform).
6. **Verify:** Manually trigger the Step Functions state machine to test an end-to-end run.
