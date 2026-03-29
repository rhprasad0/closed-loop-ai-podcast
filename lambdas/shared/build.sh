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
    aws-xray-sdk==2.14.0 \
    -t python/ \
    --platform manylinux2014_x86_64 \
    --only-binary=:all: \
    --upgrade \
    --quiet

echo "Packaging shared layer..."
zip -r ../../build/shared-layer.zip python/

echo "Done: build/shared-layer.zip"
echo "Layer size: $(du -h ../../build/shared-layer.zip | cut -f1)"
