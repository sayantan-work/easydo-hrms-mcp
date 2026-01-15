# EasyDo HRMS MCP Server

An MCP (Model Context Protocol) server that enables natural language queries for EasyDo HRMS data through Claude.

## What is this?

This MCP server connects Claude (Code or Desktop) to the EasyDo HRMS system, allowing employees, managers, and admins to query HR data using plain English instead of navigating through the app.

**Example queries:**
- "What's my leave balance?"
- "Who is on leave today?"
- "Show attendance summary for December"
- "How many employees joined this month?"

## Features

- **Phone OTP Authentication** - Secure login with SMS verification
- **Multi-Environment Support** - Connect to production or staging
- **Role-Based Access Control** - Data access based on your role (Admin/Manager/Employee)
- **50+ Query Tools** - Attendance, leave, salary, reports, and more
- **Custom SQL Queries** - Run SELECT queries with automatic RBAC filtering

## Getting Started

See [SETUP.md](SETUP.md) for installation instructions.

**Quick start:**
1. Clone the repo
2. Get `.env` file from your team lead
3. Open Claude Code and say: "Set up this MCP server for me"

## Architecture

```
┌─────────────────┐     ┌─────────────────┐     ┌─────────────────┐
│   Claude Code   │────▶│   MCP Server    │────▶│   n8n Webhook   │
│   (Natural      │     │   (Python)      │     │   (Database)    │
│    Language)    │◀────│                 │◀────│                 │
└─────────────────┘     └─────────────────┘     └─────────────────┘
                               │
                               ▼
                        ┌─────────────────┐
                        │   EasyDo API    │
                        │   (Auth/OTP)    │
                        └─────────────────┘
```

## RBAC (Role-Based Access Control)

| Role | Level | Data Access |
|------|-------|-------------|
| Super Admin | - | All companies, all data |
| Company Admin | 1 | All data within company |
| Branch Manager | 2 | Data within branch only |
| Employee | 3 | Own data only |

## Project Structure

```
easy-do-hrms-mcp/
├── mcp_server/
│   ├── server.py          # MCP server entry point
│   ├── auth.py            # User context & RBAC logic
│   ├── db.py              # Database connection (n8n webhook)
│   └── tools/             # MCP tool implementations
│       ├── auth.py        # Login, logout, status
│       ├── employee.py    # Employee queries
│       ├── attendance.py  # Attendance & punch history
│       ├── salary.py      # Salary & payslips
│       ├── organization.py# Branches, holidays, org chart
│       ├── policy.py      # Leave & attendance policies
│       ├── reports.py     # HR reports & analytics
│       └── location.py    # Location tracking
├── scripts/
│   └── generate_schema.py # Database schema generator
├── api/schema/            # Generated database schemas
├── setup.ps1              # Windows setup script
├── setup.sh               # macOS/Linux setup script
└── .env.example           # Environment variables template
```

## Environment Variables

All secrets are stored in `.env` (not committed to git):

| Variable | Description |
|----------|-------------|
| `N8N_WEBHOOK_PROD` | Production database webhook |
| `N8N_WEBHOOK_STAGING` | Staging database webhook |
| `API_BASE_PROD` | Production API URL |
| `API_BASE_STAGING` | Staging API URL |
| `DEVICE_ID` | Device identifier for API |
| `DEVICE_TYPE` | Device type for API |

## Tech Stack

- **Python 3.10+**
- **MCP SDK** - Model Context Protocol
- **python-dotenv** - Environment management
- **requests** - HTTP client

## License

Internal use only - EasyDo Technologies
