"""EasyDo HRMS MCP Server - Main Entry Point."""
import os
from fastmcp import FastMCP
from .tools import register_all_tools

# Create MCP server instance
mcp = FastMCP("EasyDo HRMS")

# Register all tools from the tools/ module
register_all_tools(mcp)


def run_stdio():
    """Run with stdio transport (for local MCP clients like Claude Desktop)."""
    mcp.run()


def run_sse():
    """Run with SSE transport (for remote hosting / FastMCP Cloud)."""
    host = os.getenv("MCP_HOST", "0.0.0.0")
    port = int(os.getenv("MCP_PORT", "8080"))
    mcp.run(transport="sse", host=host, port=port)


if __name__ == "__main__":
    # Use MCP_TRANSPORT env var to switch transport mode
    # Default: stdio (for local Claude Desktop/Code)
    # Set MCP_TRANSPORT=sse for remote hosting
    transport = os.getenv("MCP_TRANSPORT", "stdio")
    if transport == "sse":
        run_sse()
    else:
        run_stdio()
