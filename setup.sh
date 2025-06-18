#!/usr/bin/env bash
# Setup script for installing Solomon dependencies
# Requires internet access to download Python packages
set -euo pipefail

# Optionally install system packages
if command -v apt-get &>/dev/null; then
    sudo apt-get update
    sudo apt-get install -y python3-venv python3-pip build-essential git
fi

# Create a virtual environment in .venv
python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
# Install Python dependencies for inference
pip install -r inference/requirements.txt

echo "Environment setup complete"
