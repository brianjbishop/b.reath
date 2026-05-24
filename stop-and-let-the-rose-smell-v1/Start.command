#!/bin/zsh
set -euo pipefail

cd "$(dirname "$0")"

source ".venv/bin/activate"
python -m breath_midi.app

