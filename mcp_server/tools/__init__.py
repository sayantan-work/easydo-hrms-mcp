"""MCP Tools for EasyDo HRMS - Auto-registration module."""

from . import auth
from . import employee
from . import attendance
from . import leave
from . import salary
from . import team
from . import organization
from . import policy
from . import reports
from . import tasks
from . import sql
from . import analytics
from . import location
from . import self_service


def register_all_tools(mcp):
    """Register all tools with the MCP server."""
    auth.register(mcp)
    employee.register(mcp)
    attendance.register(mcp)
    leave.register(mcp)
    salary.register(mcp)
    team.register(mcp)
    organization.register(mcp)
    policy.register(mcp)
    reports.register(mcp)
    tasks.register(mcp)
    sql.register(mcp)
    analytics.register(mcp)
    location.register(mcp)
    self_service.register(mcp)


__all__ = [
    "register_all_tools",
    "auth",
    "employee",
    "attendance",
    "leave",
    "salary",
    "team",
    "organization",
    "policy",
    "reports",
    "tasks",
    "sql",
    "analytics",
    "location",
    "self_service",
]
