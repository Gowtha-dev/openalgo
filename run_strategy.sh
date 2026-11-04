#!/usr/bin/env bash
# ==============================================================================
# Runner script for SRB1EquityNifty50Stocks5Min strategy
# Starts OpenAlgo environment via `uv run`
# ==============================================================================

set -e

# Resolve script directory and openalgo directory
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# If running from root (/Users/.../work/openalgo), enter the inner openalgo directory
if [ -d "$SCRIPT_DIR/openalgo" ]; then
    TARGET_DIR="$SCRIPT_DIR/openalgo"
else
    TARGET_DIR="$SCRIPT_DIR"
fi

cd "$TARGET_DIR"

echo "============================================================"
echo "Starting SRB1EquityNifty50Stocks5Min Strategy via uv"
echo "Working Directory: $(pwd)"
echo "============================================================"

# Strategy file path relative to openalgo folder
STRATEGY_FILE="strategies/scripts/SRB1EquityNifty50Stocks5Min.py"

if [ ! -f "$STRATEGY_FILE" ]; then
    echo "Error: Strategy file not found at $STRATEGY_FILE"
    exit 1
fi

# Load environment variables if .env exists
if [ -f ".env" ]; then
    echo "Loading environment variables from .env..."
    set -a
    # Filter and export valid KEY=VALUE lines
    eval "$(grep -E '^(OPENALGO_API_KEY|HOST_SERVER|WEBSOCKET_URL|API_KEY)=' .env 2>/dev/null || true)"
    set +a
fi

# Fallback defaults if not set in environment or .env
export HOST_SERVER="${HOST_SERVER:-http://127.0.0.1:5000}"
export WEBSOCKET_URL="${WEBSOCKET_URL:-ws://127.0.0.1:8765}"

# Prompt for API key if missing
if [ -z "$OPENALGO_API_KEY" ] && [ -n "$API_KEY" ]; then
    export OPENALGO_API_KEY="$API_KEY"
fi

if [ -z "$OPENALGO_API_KEY" ]; then
    echo "Warning: OPENALGO_API_KEY is not defined in environment or .env."
    read -r -p "Please enter your OpenAlgo API Key: " user_api_key
    export OPENALGO_API_KEY="$user_api_key"
fi

# Run the strategy using `uv run`
echo "Executing: uv run python $STRATEGY_FILE"
exec uv run python "$STRATEGY_FILE" "$@"
