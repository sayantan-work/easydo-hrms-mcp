# EasyDo HRMS MCP Server - Setup Guide

## Quick Setup (Recommended)

1. Clone the repository
2. Get the `.env` file from your team lead and place it in the project folder
3. Open Claude Code in this folder
4. Say: **"Set up this MCP server for me"**

Claude will automatically detect your OS and run the appropriate setup script.

---

## Setup Instructions for Claude

> **For Claude:** Follow these steps to set up the MCP server.

### Step 1: Detect OS and Run Setup Script

Check the platform and run the appropriate setup script:

**Windows (win32):**
```powershell
.\setup.ps1
```

**macOS/Linux (darwin/linux):**
```bash
chmod +x setup.sh && ./setup.sh
```

### Step 2: Verify .env File

Check if `.env` file exists in the project root. If not, inform the user:

> ".env file is missing. Please get it from your team lead or copy .env.example to .env and fill in the values."

Required variables in `.env`:
- `N8N_WEBHOOK_PROD`
- `N8N_WEBHOOK_STAGING`
- `API_BASE_PROD`
- `API_BASE_STAGING`
- `DEVICE_ID`
- `DEVICE_TYPE`

### Step 3: Restart and Verify

After setup completes:
1. Tell user to restart Claude Code (or type `/mcp` to reconnect)
2. Verify `easydo-hrms` appears in the MCP server list

### Step 4: Login

Guide user to login:
```
login to prod with <phone-number>
```

or for staging:
```
login to staging with <phone-number>
```

---

## Manual Setup

If the automated setup doesn't work:

### Windows

```powershell
# Create virtual environment
python -m venv .venv

# Activate it
.\.venv\Scripts\Activate.ps1

# Install dependencies
pip install -r requirements.txt
pip install -e .
```

### macOS/Linux

```bash
# Create virtual environment
python3 -m venv .venv

# Activate it
source .venv/bin/activate

# Install dependencies
pip install -r requirements.txt
pip install -e .
```

### Configure MCP

Create/update `~/.mcp.json` (home directory):

**Windows:**
```json
{
  "mcpServers": {
    "easydo-hrms": {
      "command": "C:\\path\\to\\easy-do-hrms-mcp\\.venv\\Scripts\\python.exe",
      "args": ["-m", "mcp_server.server"],
      "cwd": "C:\\path\\to\\easy-do-hrms-mcp"
    }
  }
}
```

**macOS/Linux:**
```json
{
  "mcpServers": {
    "easydo-hrms": {
      "command": "/path/to/easy-do-hrms-mcp/.venv/bin/python",
      "args": ["-m", "mcp_server.server"],
      "cwd": "/path/to/easy-do-hrms-mcp"
    }
  }
}
```

---

## Remote Hosting (FastMCP)

The server supports SSE transport for remote hosting. You can deploy to FastMCP Cloud or any container platform.

### Run Locally with SSE

```bash
# Start server on port 8080 with SSE transport
MCP_TRANSPORT=sse python -m mcp_server.server

# Or with custom port
MCP_TRANSPORT=sse MCP_PORT=3000 python -m mcp_server.server
```

Server will be available at `http://localhost:8080/sse`

### Deploy to FastMCP Cloud

1. Sign up at https://fastmcp.cloud
2. Install FastMCP CLI: `pip install fastmcp`
3. Deploy: `fastmcp deploy`

### Deploy with Docker

```bash
# Build image
docker build -t easydo-hrms-mcp .

# Run container
docker run -d -p 8080:8080 \
  -e N8N_WEBHOOK_PROD=your_webhook \
  -e N8N_WEBHOOK_STAGING=your_staging_webhook \
  -e API_BASE_PROD=your_api \
  -e API_BASE_STAGING=your_staging_api \
  -e DEVICE_ID=your_device_id \
  easydo-hrms-mcp
```

### Connect Claude Desktop to Remote Server

Use `mcp-remote` to connect local Claude to remote MCP:

```bash
pip install mcp-remote
```

Add to Claude Desktop config:
```json
{
  "mcpServers": {
    "easydo-hrms-remote": {
      "command": "npx",
      "args": ["mcp-remote", "https://your-server.com/sse"]
    }
  }
}
```

---

## Troubleshooting

| Issue | Solution |
|-------|----------|
| `.env` file missing | Get it from team lead or copy from `.env.example` |
| Python not found | Setup script will auto-install Python 3.12 |
| MCP not showing | Restart Claude Code and type `/mcp` |
| "Not authenticated" | Run `login to prod with <phone>` |
| Permission denied (Linux/Mac) | Run `chmod +x setup.sh` first |

---

## Support

Contact the EasyDo development team for help.
