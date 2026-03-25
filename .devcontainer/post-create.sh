#!/usr/bin/env bash
set -euo pipefail

echo "=== Post-create setup ==="

echo "--- Tool versions ---"
python --version
terraform version | head -1
sam --version
aws --version
node --version
claude --version 2>/dev/null || echo "Claude Code: installed (run 'claude' to authenticate)"
psql --version
ffmpeg -version | head -1
docker --version
jq --version
echo "---------------------"

# Terraform: initialize provider plugins if terraform dir exists
if [ -d "terraform" ]; then
    echo "Initializing Terraform..."
    cd terraform && terraform init -backend=false && cd ..
fi

# Git: mark workspace as safe directory (container UID may differ from host)
git config --global --add safe.directory /workspaces/closed-loop-ai-podcast

echo "=== Post-create setup complete ==="
