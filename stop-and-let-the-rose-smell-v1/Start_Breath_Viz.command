#!/bin/zsh
set -euo pipefail

cd "$(dirname "$0")"

python3 totem_breath_viz.py
