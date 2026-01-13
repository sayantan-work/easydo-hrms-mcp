"""EasyDo HRMS MCP Server - Main Entry Point."""
from mcp.server.fastmcp import FastMCP
from .tools import register_all_tools

# Create MCP server instance
mcp = FastMCP("EasyDo HRMS")

# Register all tools from the tools/ module
register_all_tools(mcp)


if __name__ == "__main__":
    mcp.run()
