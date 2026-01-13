# EasyDo HRMS MCP Server

## Overview
This is an MCP (Model Context Protocol) server for EasyDo HRMS. It allows users to query HR data using natural language.

## Setup Instructions
If the user asks to set up this MCP server, read `SETUP.md` and follow the OS-specific instructions.

## Auto-Setup for Users
When a user asks Claude to set up this server:

1. **Detect OS:**
   - Check `process.platform` or ask the user
   - Windows: Use `python` command, paths with `\\`
   - macOS/Linux: Use `python3` command, paths with `/`

2. **Install dependencies:**
   ```bash
   pip install -e .
   ```

3. **Configure MCP:**
   - For Claude Code: Create/update `.mcp.json` in project or home directory
   - For Claude Desktop: Update the config file at:
     - Windows: `%APPDATA%\Claude\claude_desktop_config.json`
     - macOS: `~/Library/Application Support/Claude/claude_desktop_config.json`
     - Linux: `~/.config/Claude/claude_desktop_config.json`

4. **Get the absolute path** to this folder for the `cwd` field

## Available Tools
After connecting, users can:
- Login with phone OTP
- Query their own salary, leave, profile
- Search employees (based on RBAC)
- View attendance, policies, holidays
- Run custom SQL queries (SELECT only, RBAC enforced)

## RBAC Roles
- `role_id = 1`: Company Admin (Authority Level 1)
- `role_id = 2`: Branch Manager (Authority Level 2)
- `role_id = 3`: Employee (Authority Level 3)
- Super Admin: Hardcoded user_id 6148 (bypasses RBAC)

## Primary Company Behavior
- Users may belong to multiple companies
- By default, queries return **primary company** data only
- Primary = company with most attendance records
- Use `company_name="all"` for all companies
- Use `company_name="CompanyName"` for specific company
