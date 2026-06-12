#!/usr/bin/env bash
# CliTer launcher — place this in PATH (e.g. /usr/local/bin or ~/.local/bin)
# Usage: cliter

SCRIPT_DIR="$(cd "$(dirname "$(readlink -f "$0")")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR" && git rev-parse --show-toplevel 2>/dev/null || echo "$SCRIPT_DIR")"

# Try python venv first, then system python
if [ -f "$PROJECT_DIR/.venv/bin/python" ]; then
    PYTHON="$PROJECT_DIR/.venv/bin/python"
elif [ -f "$PROJECT_DIR/.venv/Scripts/python" ]; then
    PYTHON="$PROJECT_DIR/.venv/Scripts/python"
elif command -v python3 &>/dev/null; then
    PYTHON="python3"
else
    PYTHON="python"
fi

exec "$PYTHON" -m cliter "$@"
