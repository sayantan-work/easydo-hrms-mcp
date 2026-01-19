"""MCP Tools for EasyDo HRMS - Auto-registration module."""

from . import (
    analytics,
    attendance,
    auth,
    employee,
    leave,
    location,
    organization,
    policy,
    reports,
    salary,
    self_service,
    sql,
    tasks,
    team,
)

# All tool modules in registration order
_TOOL_MODULES = [
    auth,
    employee,
    attendance,
    leave,
    salary,
    team,
    organization,
    policy,
    reports,
    tasks,
    sql,
    analytics,
    location,
    self_service,
]


def register_all_tools(mcp) -> None:
    """Register all tools with the MCP server."""
    for module in _TOOL_MODULES:
        module.register(mcp)


__all__ = ["register_all_tools"]
