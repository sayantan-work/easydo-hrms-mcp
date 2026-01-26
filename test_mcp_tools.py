"""
Test MCP Tools - Verify Claude can connect and retrieve info using all tools.
Run this script to check if the MCP server is working correctly.
"""
import sys
import os
import json
from datetime import datetime

# Add project to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Test results tracking
RESULTS = {
    "passed": [],
    "failed": [],
    "skipped": []
}


def log_result(tool_name: str, status: str, message: str = "", data: dict = None):
    """Log test result."""
    result = {"tool": tool_name, "message": message}
    if data:
        result["sample_data"] = str(data)[:200] + "..." if len(str(data)) > 200 else data
    RESULTS[status].append(result)

    icon = "[PASS]" if status == "passed" else "[FAIL]" if status == "failed" else "[SKIP]"
    print(f"  {icon} {tool_name}: {message}")


def test_tool(tool_func, tool_name: str, *args, **kwargs):
    """Test a single tool and log result."""
    try:
        result = tool_func(*args, **kwargs)

        if isinstance(result, dict):
            if "error" in result:
                # Check if it's an auth error (expected when not logged in)
                if "Not authenticated" in str(result.get("error", "")):
                    log_result(tool_name, "skipped", "Requires authentication", result)
                else:
                    log_result(tool_name, "failed", f"Error: {result['error']}", result)
            else:
                log_result(tool_name, "passed", "OK", result)
        else:
            log_result(tool_name, "passed", f"Returned: {type(result).__name__}")

        return result
    except Exception as e:
        log_result(tool_name, "failed", f"Exception: {str(e)}")
        return None


def run_tests():
    """Run all MCP tool tests."""
    print("=" * 70)
    print("MCP TOOLS CONNECTION TEST")
    print("=" * 70)
    print(f"Started at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print()

    # Import MCP server
    print("Loading MCP server...")
    try:
        from mcp_server.server import mcp
        print("  [OK] MCP server loaded successfully")
    except Exception as e:
        print(f"  [X] Failed to load MCP server: {e}")
        return False

    # Get tool manager
    print("\nAccessing tool manager...")
    try:
        if not hasattr(mcp, '_tool_manager'):
            print("  [X] No tool manager found")
            return False

        tool_manager = mcp._tool_manager
        tools = {}

        if hasattr(tool_manager, '_tools'):
            tools = tool_manager._tools
            print(f"  [OK] Found {len(tools)} registered tools")
        else:
            print("  [X] Could not access tools")
            return False
    except Exception as e:
        print(f"  [X] Failed to access tool manager: {e}")
        return False

    # Test 1: list_tools (works without auth)
    print("\n" + "-" * 70)
    print("TEST 1: Core Tools (No Auth Required)")
    print("-" * 70)

    if "list_tools" in tools:
        result = test_tool(tools["list_tools"].fn, "list_tools")
        if result and "total_tools" in result:
            print(f"       -> Total tools available: {result['total_tools']}")

    if "get_time" in tools:
        result = test_tool(tools["get_time"].fn, "get_time")
        if result and "datetime" in result:
            print(f"       -> Current time (IST): {result['datetime']}")

    # Test 2: Auth tools
    print("\n" + "-" * 70)
    print("TEST 2: Authentication Tools")
    print("-" * 70)

    if "whoami" in tools:
        result = test_tool(tools["whoami"].fn, "whoami")
        if result:
            if result.get("logged_in"):
                print(f"       -> Logged in as: {result.get('user_name')} ({result.get('environment', 'unknown')})")
            else:
                print(f"       -> Not logged in (expected if no credentials)")

    # Test 3: Tools requiring auth
    print("\n" + "-" * 70)
    print("TEST 3: Data Tools (Require Auth)")
    print("-" * 70)

    auth_required_tools = [
        ("get_my_access", {}),
        ("get_my_companies", {}),
        ("get_employee", {}),
        ("get_attendance", {}),
        ("get_leave_balance", {}),
        ("get_salary", {}),
        ("get_team", {}),
        ("get_holidays", {}),
        ("get_policy", {}),
        ("get_tasks", {}),
        ("list_tables", {}),
    ]

    for tool_name, kwargs in auth_required_tools:
        if tool_name in tools:
            test_tool(tools[tool_name].fn, tool_name, **kwargs)
        else:
            log_result(tool_name, "skipped", "Tool not found")

    # Test 4: Tools with parameters
    print("\n" + "-" * 70)
    print("TEST 4: Parameterized Tools")
    print("-" * 70)

    param_tools = [
        ("get_time", {"timezone_name": "UTC"}),
        ("get_daily_attendance", {"status": "all"}),
        ("get_employees_by_location", {"status": "all"}),
        ("get_policy", {"policy_type": "all"}),
        ("get_employee_movements", {"movement_type": "all"}),
    ]

    for tool_name, kwargs in param_tools:
        if tool_name in tools:
            test_tool(tools[tool_name].fn, tool_name, **kwargs)
        else:
            log_result(tool_name, "skipped", "Tool not found")

    # Summary
    print("\n" + "=" * 70)
    print("TEST SUMMARY")
    print("=" * 70)

    total = len(RESULTS["passed"]) + len(RESULTS["failed"]) + len(RESULTS["skipped"])
    print(f"Total tests: {total}")
    print(f"  [OK] Passed:  {len(RESULTS['passed'])}")
    print(f"  [X] Failed:  {len(RESULTS['failed'])}")
    print(f"  [-] Skipped: {len(RESULTS['skipped'])} (auth required)")

    if RESULTS["failed"]:
        print("\n" + "-" * 70)
        print("FAILED TESTS:")
        print("-" * 70)
        for f in RESULTS["failed"]:
            print(f"  • {f['tool']}: {f['message']}")

    print("\n" + "=" * 70)

    # Return success if no failures (skipped is OK)
    success = len(RESULTS["failed"]) == 0
    if success:
        print("STATUS: ALL TESTS PASSED [OK]")
    else:
        print("STATUS: SOME TESTS FAILED [X]")

    print("=" * 70)

    return success


def test_with_login():
    """Test tools after logging in (if credentials exist)."""
    print("\n" + "=" * 70)
    print("TESTING WITH AUTHENTICATION")
    print("=" * 70)

    try:
        from mcp_server.auth import get_user_context
        ctx = get_user_context()

        if not ctx:
            print("No credentials found. Skipping authenticated tests.")
            print("To test with auth, run: login(phone, environment) first")
            return

        print(f"Logged in as: {ctx.user_name}")
        print(f"Super Admin: {ctx.is_super_admin}")
        if ctx.primary_company:
            print(f"Primary Company: {ctx.primary_company.company_name}")

        # Re-run tests that need auth
        from mcp_server.server import mcp
        tools = mcp._tool_manager._tools

        print("\nTesting authenticated tools:")

        # Test a few key tools
        test_cases = [
            ("get_my_access", {}),
            ("get_employee", {}),
            ("get_attendance", {}),
            ("get_leave_balance", {}),
            ("get_holidays", {}),
        ]

        for tool_name, kwargs in test_cases:
            if tool_name in tools:
                test_tool(tools[tool_name].fn, tool_name, **kwargs)

    except Exception as e:
        print(f"Error during authenticated tests: {e}")


if __name__ == "__main__":
    print()
    success = run_tests()

    # Check for credentials and run authenticated tests
    test_with_login()

    print()
    sys.exit(0 if success else 1)
