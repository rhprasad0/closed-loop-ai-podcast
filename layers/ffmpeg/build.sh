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
