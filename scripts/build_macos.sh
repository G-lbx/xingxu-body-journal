#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")/.."
PYTHON="${1:-.venv-build/bin/python}"
"$PYTHON" -c 'import sys; assert sys.platform == "darwin"; import PyInstaller'
bash scripts/build_macos_ocr.sh
"$PYTHON" -m PyInstaller --noconfirm --clean XingxuBodyJournal.spec
codesign --verify --deep --strict dist/XingxuBodyJournal.app
"$PYTHON" scripts/package_macos.py
