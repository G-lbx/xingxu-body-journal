#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")/.."
if [ "$(uname -s)" != Darwin ]; then
    echo 'Build this component on macOS.' >&2
    exit 1
fi
xcrun swiftc -O -target "$(uname -m)-apple-macos13.0" scripts/macos_ocr.swift -o scripts/macos_ocr
scripts/macos_ocr --check
