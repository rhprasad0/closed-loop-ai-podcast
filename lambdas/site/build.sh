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
