#!/bin/zsh
set -euo pipefail

cd "$(dirname "$0")"

.venv/bin/python -m breath_midi.app

