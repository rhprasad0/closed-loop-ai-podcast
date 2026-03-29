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
