#!/usr/bin/env bash
set -e
cd "$(dirname "$0")"
echo "Building video-mask..."
pyinstaller video-mask.spec
echo ""
echo "Done. Executable: dist/video-mask"
