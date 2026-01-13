# EasyDo HRMS MCP Server - Setup Guide

This MCP server allows you to query EasyDo HRMS data using natural language through Claude Code or Claude Desktop.

## Prerequisites

- Python 3.10 or higher
- Claude Code CLI or Claude Desktop installed
- Access to EasyDo HRMS (you'll need to login with your phone number)

## Quick Setup (Let Claude Do It)

Just tell Claude Code:
> "Read the SETUP.md file in this folder and set up the MCP server for me"

Claude will detect your OS and configure everything automatically.

---

## Manual Setup

### Step 1: Install the MCP Server

Open a terminal in this folder and run:

```bash
pip install -e .
```

This installs the MCP server and its dependencies.

### Step 2: Configure Claude Code or Claude Desktop

#### For Claude Code (CLI)

Create a file named `.mcp.json` in your project folder (or home directory for global access):

**Windows:**
```json
{
  "mcpServers": {
    "easydo-hrms": {
      "command": "python",
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
      "command": "python3",
      "args": ["-m", "mcp_server.server"],
      "cwd": "/path/to/easy-do-hrms-mcp"
    }
  }
}
```

#### For Claude Desktop

Edit the Claude Desktop config file:

**Windows:** `%APPDATA%\Claude\claude_desktop_config.json`
**macOS:** `~/Library/Application Support/Claude/claude_desktop_config.json`
**Linux:** `~/.config/Claude/claude_desktop_config.json`

Add the MCP server configuration:

**Windows:**
```json
{
  "mcpServers": {
    "easydo-hrms": {
      "command": "python",
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
      "command": "python3",
      "args": ["-m", "mcp_server.server"],
      "cwd": "/path/to/easy-do-hrms-mcp"
    }
  }
}
```

### Step 3: Restart Claude

- **Claude Code:** Type `/mcp` to reconnect, or restart the CLI
- **Claude Desktop:** Quit and reopen the app

### Step 4: Login

Once connected, tell Claude:
> "Login to EasyDo HRMS with my phone number: XXXXXXXXXX"

You'll receive an OTP to complete the login.

---

## Available Commands

Once logged in, you can ask things like:

### Self-Service
- "What is my salary?"
- "Show my leave balance"
- "What is my profile?"
- "Show my attendance for December 2025"

### For Managers
- "Who reports to me?"
- "Show pending approvals"
- "Who is on leave today?"
- "Who was late today?"

### HR Queries
- "Search for employee John"
- "Get salary details for Rahul"
- "Show birthdays this month"
- "List new joiners in January"

### Policies
- "What is the leave policy?"
- "Show attendance policy"
- "Get statutory rules"

### Multi-Company Support
If you belong to multiple companies:
- Default queries return your **primary company** data
- Use `company_name="all"` to see all companies
- Use `company_name="CompanyName"` for a specific company

Example: "Show my salary for all companies"

---

## Troubleshooting

### "Not authenticated" error
Run the login command with your phone number.

### MCP server not connecting
1. Check Python is installed: `python --version` or `python3 --version`
2. Verify the path in your config file is correct
3. Try running manually: `python -m mcp_server.server`

### "Module not found" error
Install dependencies: `pip install -e .` in the MCP folder

---

## Security Notes

- Your login credentials are stored locally in `~/.easydo/credentials.json`
- The server only allows SELECT queries (no data modification)
- RBAC (Role-Based Access Control) is enforced based on your role:
  - **Super Admin:** Full access to all data
  - **Company Admin:** Access to their company's data
  - **Branch Manager:** Access to their branch's data
  - **Employee:** Access to their own data only

---

## Support

For issues or questions, contact the EasyDo development team.
