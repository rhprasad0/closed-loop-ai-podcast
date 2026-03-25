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

# Configure Claude Code MCP servers (aws-mcp for AWS CLI access)
echo "Configuring Claude Code MCP servers..."
CLAUDE_CONFIG="/home/vscode/.claude.json"
if [ -f "$CLAUDE_CONFIG" ]; then
    jq '.mcpServers.aws = {
        "command": "uvx",
        "args": ["aws-mcp"],
        "env": {
            "AWS_PROFILE": "default",
            "AWS_REGION": "us-east-1"
        }
    }' "$CLAUDE_CONFIG" > "${CLAUDE_CONFIG}.tmp" && mv "${CLAUDE_CONFIG}.tmp" "$CLAUDE_CONFIG"
else
    cat > "$CLAUDE_CONFIG" << 'MCPEOF'
{
    "mcpServers": {
        "aws": {
            "command": "uvx",
            "args": ["aws-mcp"],
            "env": {
                "AWS_PROFILE": "default",
                "AWS_REGION": "us-east-1"
            }
        }
    }
}
MCPEOF
fi

echo "=== Post-create setup complete ==="
