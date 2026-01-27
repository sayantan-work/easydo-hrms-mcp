# EasyDo HRMS MCP Server

MCP server with 52 HRMS tools for natural language HR queries.

## Features

- **52 HRMS Tools** - Attendance, leave, salary, reports, location, and more
- **Phone OTP Authentication** - Secure login with SMS verification
- **Multi-Environment** - Production and staging support
- **RBAC Enforcement** - Automatic data filtering by role
- **Dual Transport** - stdio (local) and SSE (remote hosting)
- **API Mode** - Internal tools for multi-user API integration

## Quick Start

### Local (Claude Code/Desktop)

```bash
# Install
pip install -e .

# Configure MCP (Claude Code)
# Add to .mcp.json:
{
  "mcpServers": {
    "easydo-hrms": {
      "command": "python",
      "args": ["-m", "mcp_server.server"],
      "cwd": "/path/to/easydo-mcp-v2"
    }
  }
}
```

### Remote (Docker/FastMCP Cloud)

```bash
# Run with SSE transport
MCP_TRANSPORT=sse MCP_PORT=8080 python -m mcp_server.server

# Or use Docker
docker build -t easydo-hrms-mcp .
docker run -p 8080:8080 --env-file .env easydo-hrms-mcp
```

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                      MCP Server                             │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────────────┐  │
│  │    Auth     │  │    RBAC     │  │      52 Tools       │  │
│  │  (OTP/API)  │  │  (Filter)   │  │  (HRMS Queries)     │  │
│  └──────┬──────┘  └──────┬──────┘  └──────────┬──────────┘  │
│         │                │                     │             │
│         └────────────────┼─────────────────────┘             │
│                          ▼                                   │
│  ┌───────────────────────────────────────────────────────┐  │
│  │                    Database Layer                      │  │
│  │   n8n Webhook (default)  │  Direct PostgreSQL (opt)   │  │
│  └───────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────┘
         │                              │
         ▼                              ▼
┌─────────────────┐            ┌─────────────────┐
│   Supabase      │            │   EasyDo API    │
│   (Sessions)    │            │   (OTP Auth)    │
└─────────────────┘            └─────────────────┘
```

## RBAC Roles

| Role | Level | Data Access |
|------|-------|-------------|
| Super Admin | - | All companies, all data |
| Company Admin | 1 | All data within company |
| Branch Manager | 2 | Own branch only |
| Employee | 3 | Own data only |

## Tool Categories

| Category | Tools | Examples |
|----------|-------|----------|
| Auth | 7 | login, verify_otp, whoami, get_my_access |
| Employee | 6 | get_employee, search_employee_directory |
| Attendance | 5 | get_attendance, get_daily_attendance, get_punch_history |
| Leave | 2 | get_leave_balance, get_leave_history |
| Salary | 4 | get_salary, get_salary_slip, get_salary_expenditure |
| Team | 3 | get_team, get_my_manager, get_pending_approvals |
| Organization | 7 | get_branches, get_holidays, get_org_chart |
| Reports | 6 | get_attendance_report, get_attrition_report |
| Location | 4 | get_employee_location, get_location_history |
| SQL | 3 | run_sql_query, list_tables, get_table_schema |
| **Total** | **52** | |

## Environment Variables

```bash
# Database Mode
DB_MODE=n8n                    # n8n (webhook) or direct (PostgreSQL)

# n8n Mode
N8N_WEBHOOK_PROD=https://...
N8N_WEBHOOK_STAGING=https://...

# Direct Mode (optional)
DB_HOST_PROD=localhost
DB_PORT_PROD=5432
DB_NAME_PROD=hrms
DB_USER_PROD=postgres
DB_PASSWORD_PROD=...

# Auth
API_BASE_PROD=https://api-prod.easydoochat.com
API_BASE_STAGING=https://api-staging.easydoochat.com
DEVICE_ID=mcp-server
DEVICE_TYPE=ios

# Session Store
SUPABASE_URL=https://...
SUPABASE_SERVICE_KEY=...

# Super Admin (bypasses RBAC)
SUPER_ADMIN_PHONE=+91...

# Remote Hosting (optional)
MCP_TRANSPORT=stdio            # stdio or sse
MCP_HOST=0.0.0.0
MCP_PORT=8080
```

## API Mode

For multi-user API integration, two internal tools are available:

```python
# Set user context (called by API before processing)
set_request_context(user_id=123, environment="prod")

# Clear context (called by API after processing)
clear_context()
```

These tools are filtered from the agent's tool list and only exposed to the API layer.

See [easydo-mcp-api-v2](https://github.com/sayantan-work/easydo-mcp-api-v2) for the API implementation.

## Project Structure

```
easydo-mcp-v2/
├── mcp_server/
│   ├── server.py           # Entry point (FastMCP)
│   ├── auth.py             # User context & session management
│   ├── db.py               # Database layer (n8n/direct)
│   ├── rbac.py             # RBAC query filtering
│   ├── supabase_client.py  # Session store
│   └── tools/              # 52 MCP tools
│       ├── auth.py         # Login, logout, internal tools
│       ├── employee.py     # Employee queries
│       ├── attendance.py   # Attendance & punch history
│       ├── leave.py        # Leave balance & history
│       ├── salary.py       # Salary & payslips
│       ├── team.py         # Team & approvals
│       ├── organization.py # Branches, holidays
│       ├── policy.py       # Company policies
│       ├── analytics.py    # HR analytics
│       ├── reports.py      # HR reports
│       ├── location.py     # Location tracking
│       ├── self_service.py # My documents, payslips
│       ├── tasks.py        # Task management
│       └── sql.py          # Custom SQL queries
├── Dockerfile              # Container deployment
├── SETUP.md                # Installation guide
└── .env.example            # Environment template
```

## License

Internal use only - EasyDo Technologies
