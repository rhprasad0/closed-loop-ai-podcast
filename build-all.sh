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
