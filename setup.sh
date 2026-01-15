#!/bin/bash
# EasyDo HRMS MCP Setup Script for macOS/Linux
# Run: chmod +x setup.sh && ./setup.sh

set -e

echo ""
echo "========================================"
echo "  EasyDo HRMS MCP Server Setup"
echo "========================================"
echo ""

# Get script directory
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# Step 1: Check/Install Python
echo "[1/4] Checking Python..."

PYTHON_CMD=""

for cmd in python3 python; do
    if command -v $cmd &> /dev/null; then
        version=$($cmd --version 2>&1)
        if [[ $version =~ Python\ 3\.([9]|[1-9][0-9]) ]]; then
            PYTHON_CMD=$cmd
            echo "       Found: $version"
            break
        fi
    fi
done

if [ -z "$PYTHON_CMD" ]; then
    echo "       Python 3.9+ not found. Installing..."

    # Detect OS and install
    if [[ "$OSTYPE" == "darwin"* ]]; then
        # macOS
        if command -v brew &> /dev/null; then
            echo "       Using Homebrew..."
            brew install python@3.12
            PYTHON_CMD="python3"
        else
            echo "       Installing Homebrew first..."
            /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
            brew install python@3.12
            PYTHON_CMD="python3"
        fi
    elif [[ -f /etc/debian_version ]]; then
        # Debian/Ubuntu
        echo "       Using apt..."
        sudo apt update
        sudo apt install -y python3.12 python3.12-venv python3-pip
        PYTHON_CMD="python3.12"
    elif [[ -f /etc/redhat-release ]]; then
        # RHEL/CentOS/Fedora
        echo "       Using dnf..."
        sudo dnf install -y python3.12
        PYTHON_CMD="python3.12"
    else
        echo "       ERROR: Could not auto-install Python. Please install Python 3.9+ manually."
        exit 1
    fi

    # Verify
    version=$($PYTHON_CMD --version 2>&1)
    echo "       Installed: $version"
fi

# Step 2: Create virtual environment
echo "[2/4] Setting up virtual environment..."

if [ ! -d ".venv" ]; then
    $PYTHON_CMD -m venv .venv
fi
echo "       Virtual environment ready"

# Step 3: Install dependencies
echo "[3/4] Installing dependencies..."

.venv/bin/pip install --upgrade pip --quiet
.venv/bin/pip install -r requirements.txt --quiet
.venv/bin/pip install -e . --quiet
echo "       Dependencies installed"

# Step 4: Configure MCP
echo "[4/4] Configuring Claude Code MCP..."

VENV_PYTHON="$SCRIPT_DIR/.venv/bin/python"
HOME_MCP="$HOME/.mcp.json"

MCP_CONFIG=$(cat <<EOF
{
    "mcpServers": {
        "easydo-hrms": {
            "command": "$VENV_PYTHON",
            "args": ["-m", "mcp_server.server"],
            "cwd": "$SCRIPT_DIR"
        }
    }
}
EOF
)

if [ -f "$HOME_MCP" ]; then
    if command -v jq &> /dev/null; then
        jq --arg cmd "$VENV_PYTHON" --arg cwd "$SCRIPT_DIR" \
            '.mcpServers["easydo-hrms"] = {"command": $cmd, "args": ["-m", "mcp_server.server"], "cwd": $cwd}' \
            "$HOME_MCP" > "${HOME_MCP}.tmp" && mv "${HOME_MCP}.tmp" "$HOME_MCP"
    else
        echo "$MCP_CONFIG" > "$HOME_MCP"
    fi
else
    echo "$MCP_CONFIG" > "$HOME_MCP"
fi
echo "       Config saved to: $HOME_MCP"

# Done
echo ""
echo "========================================"
echo "  Setup Complete!"
echo "========================================"
echo ""
echo "Next steps:"
echo "  1. Open/restart Claude Code"
echo "  2. Type: /mcp"
echo "  3. Say: login to prod with <your-phone>"
echo ""
echo "Example: login to prod with 98XXXXXXXX"
echo ""
