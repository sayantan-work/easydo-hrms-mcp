"""
Test script to dynamically check all MCP tools.
Run this to verify tool consolidation and ensure nothing is broken.
"""
import sys
import os

# Add project to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from mcp_server.server import mcp


def get_all_tools():
    """Get all registered tools from MCP server."""
    tools = []

    if hasattr(mcp, '_tool_manager'):
        tool_manager = mcp._tool_manager

        if hasattr(tool_manager, '_tools'):
            for name, tool in tool_manager._tools.items():
                desc = getattr(tool, 'description', '') or ''
                tools.append({
                    'name': name,
                    'description': desc[:100] + '...' if len(desc) > 100 else desc,
                    'is_deprecated': '[DEPRECATED]' in desc
                })

    return tools


def categorize_tools(tools):
    """Categorize tools by type."""
    categories = {
        'auth': [],
        'employee': [],
        'attendance': [],
        'leave': [],
        'salary': [],
        'team': [],
        'organization': [],
        'policy': [],
        'reports': [],
        'tasks': [],
        'sql': [],
        'location': [],
        'other': []
    }

    for tool in tools:
        name = tool['name'].lower()

        if name in ['login', 'logout', 'verify_otp', 'whoami', 'status', 'get_my_access', 'list_tools', 'get_my_companies']:
            categories['auth'].append(tool)
        elif 'employee' in name or name in ['search_employee_directory', 'get_document_verification_status']:
            categories['employee'].append(tool)
        elif any(kw in name for kw in ['attendance', 'punch', 'present', 'absent', 'late']):
            categories['attendance'].append(tool)
        elif 'leave' in name:
            categories['leave'].append(tool)
        elif any(kw in name for kw in ['salary', 'payslip']):
            categories['salary'].append(tool)
        elif any(kw in name for kw in ['team', 'manager', 'org_chart', 'pending_approvals']):
            categories['team'].append(tool)
        elif any(kw in name for kw in ['company', 'branch', 'holiday', 'announcement', 'birthday']):
            categories['organization'].append(tool)
        elif 'policy' in name or 'statutory' in name:
            categories['policy'].append(tool)
        elif any(kw in name for kw in ['summary', 'utilization', 'attrition', 'expenditure', 'headcount', 'report']):
            categories['reports'].append(tool)
        elif 'task' in name:
            categories['tasks'].append(tool)
        elif any(kw in name for kw in ['sql', 'table', 'query']):
            categories['sql'].append(tool)
        elif any(kw in name for kw in ['location', 'at_work', 'outside', 'offline']):
            categories['location'].append(tool)
        else:
            categories['other'].append(tool)

    return {k: v for k, v in categories.items() if v}


def print_report(tools):
    """Print a detailed report of all tools."""

    print("=" * 70)
    print("MCP TOOLS ANALYSIS REPORT")
    print("=" * 70)

    # Summary
    total = len(tools)
    deprecated = [t for t in tools if t['is_deprecated']]
    active = [t for t in tools if not t['is_deprecated']]

    print(f"\nTOTAL TOOLS: {total}")
    print(f"  - Active:     {len(active)}")
    print(f"  - Deprecated: {len(deprecated)}")

    # Categorized view
    categories = categorize_tools(tools)

    print("\n" + "-" * 70)
    print("TOOLS BY CATEGORY")
    print("-" * 70)

    for category, cat_tools in sorted(categories.items()):
        active_count = len([t for t in cat_tools if not t['is_deprecated']])
        deprecated_count = len([t for t in cat_tools if t['is_deprecated']])

        print(f"\n{category.upper()} ({len(cat_tools)} tools, {deprecated_count} deprecated):")
        for tool in cat_tools:
            status = "[DEPRECATED]" if tool['is_deprecated'] else "[ACTIVE]"
            print(f"  {status:13} {tool['name']}")

    # Deprecated tools list
    if deprecated:
        print("\n" + "-" * 70)
        print("DEPRECATED TOOLS TO REMOVE")
        print("-" * 70)
        for tool in deprecated:
            print(f"  - {tool['name']}")
            # Extract replacement from description
            desc = tool['description']
            if 'Use ' in desc and ' instead' in desc:
                start = desc.find('Use ') + 4
                end = desc.find(' instead')
                replacement = desc[start:end]
                print(f"    -> Replace with: {replacement}")

    # Active tools count after removal
    print("\n" + "-" * 70)
    print("AFTER REMOVING DEPRECATED TOOLS")
    print("-" * 70)
    print(f"Tool count will be: {len(active)}")

    return {
        'total': total,
        'active': len(active),
        'deprecated': len(deprecated),
        'categories': {k: len(v) for k, v in categories.items()}
    }


def list_all_tools():
    """List all tool names (for quick reference)."""
    tools = get_all_tools()
    active = [t['name'] for t in tools if not t['is_deprecated']]
    deprecated = [t['name'] for t in tools if t['is_deprecated']]

    print("\nACTIVE TOOLS:")
    for name in sorted(active):
        print(f"  - {name}")

    print(f"\nDEPRECATED TOOLS ({len(deprecated)}):")
    for name in sorted(deprecated):
        print(f"  - {name}")


if __name__ == '__main__':
    print("Loading MCP server tools...")
    tools = get_all_tools()

    if not tools:
        print("ERROR: No tools found! Check MCP server initialization.")
        sys.exit(1)

    stats = print_report(tools)

    print("\n" + "=" * 70)
    print("SUMMARY")
    print("=" * 70)
    print(f"Current: {stats['total']} tools")
    print(f"After cleanup: {stats['active']} tools")
    print(f"Reduction: {stats['deprecated']} tools ({stats['deprecated']/stats['total']*100:.1f}%)")
