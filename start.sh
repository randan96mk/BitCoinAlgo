#!/bin/bash
# BTC Trading Alerts — One-command launcher
# Usage: ./start.sh

set -e

cd "$(dirname "$0")"

# Find Python 3
if command -v python3 &>/dev/null; then
    PY=python3
elif command -v python &>/dev/null; then
    PY=python
else
    echo "❌ Python 3 not found. Install it:"
    echo "   brew install python"
    exit 1
fi

echo "Using: $($PY --version)"

# Create venv if missing
if [ ! -d ".venv" ]; then
    echo "📦 Creating virtual environment..."
    $PY -m venv .venv
fi

# Activate
source .venv/bin/activate

# Install/update deps
echo "📦 Installing dependencies..."
pip install --quiet --upgrade pip
pip install --quiet --upgrade -r requirements.txt

# Create required dirs
mkdir -p logs database

# Start server
echo ""
echo "🚀 Starting BTC Trading Alerts..."
echo "   Dashboard: http://localhost:8000"
echo "   Press Ctrl+C to stop"
echo ""

# Open browser once server is ready
(
    while ! curl -s http://localhost:8000 >/dev/null 2>&1; do
        sleep 1
    done
    open http://localhost:8000
) &

python run.py
