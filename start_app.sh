#!/usr/bin/env bash
# ==============================================================================
# OpenAlgo Application Startup Script
# Automatically launches the OpenAlgo app using `uv run app.py`
# ==============================================================================

set -e

# Resolve script directory
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Target directory where app.py and pyproject.toml live
if [ -f "$SCRIPT_DIR/openalgo/app.py" ]; then
    APP_DIR="$SCRIPT_DIR/openalgo"
elif [ -f "$SCRIPT_DIR/app.py" ]; then
    APP_DIR="$SCRIPT_DIR"
else
    echo "Error: app.py not found in $SCRIPT_DIR or $SCRIPT_DIR/openalgo"
    exit 1
fi

cd "$APP_DIR"

echo "============================================================"
echo " Starting OpenAlgo Application"
echo " Directory: $(pwd)"
echo " Command  : uv run app.py"
echo "============================================================"

# Check if uv is installed
if ! command -v uv &> /dev/null; then
    # Check standard install locations for uv on macOS/Linux
    if [ -f "$HOME/.cargo/bin/uv" ]; then
        export PATH="$HOME/.cargo/bin:$PATH"
    elif [ -f "$HOME/.local/bin/uv" ]; then
        export PATH="$HOME/.local/bin:$PATH"
    elif [ -f "/opt/homebrew/bin/uv" ]; then
        export PATH="/opt/homebrew/bin:$PATH"
    elif [ -f "/usr/local/bin/uv" ]; then
        export PATH="/usr/local/bin:$PATH"
    else
        echo "Error: 'uv' command not found. Please install uv (https://docs.astral.sh/uv/) or ensure it is in PATH."
        exit 1
    fi
fi

# Execute OpenAlgo application via uv
exec uv run app.py "$@"
