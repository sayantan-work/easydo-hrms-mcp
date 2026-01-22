"""SQL query tools for MCP server."""
import json
import os
import re
from ..auth import get_user_context
from ..db import fetch_all, fetch_one
from ..rbac import apply_company_filter

# Load table access configuration
TABLE_ACCESS_FILE = os.path.join(os.path.dirname(__file__), "..", "table_access.json")


def _load_table_access() -> dict:
    """Load table access configuration from JSON file."""
    try:
        with open(TABLE_ACCESS_FILE, "r") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {"level_1_2": [], "level_3": []}


def _get_allowed_tables(ctx) -> list | None:
    """
    Get list of allowed tables for the user's role.
    Returns None for super admin (all tables allowed).
    """
    if ctx.is_super_admin:
        return None  # No restriction

    config = _load_table_access()
    role_id = ctx.role_id

    if role_id in (1, 2):  # Company Admin or Branch Manager
        return config.get("level_1_2", [])
    else:  # Employee (level 3)
        return config.get("level_3", [])


def _extract_tables_from_query(query: str) -> set:
    """Extract table names from a SQL query."""
    # Remove string literals to avoid false matches
    query_clean = re.sub(r"'[^']*'", "", query)

    # Common patterns: FROM table, JOIN table, FROM table AS alias
    patterns = [
        r'\bFROM\s+([a-zA-Z_][a-zA-Z0-9_]*)',
        r'\bJOIN\s+([a-zA-Z_][a-zA-Z0-9_]*)',
        r'\bINTO\s+([a-zA-Z_][a-zA-Z0-9_]*)',
        r'\bUPDATE\s+([a-zA-Z_][a-zA-Z0-9_]*)',
    ]

    tables = set()
    for pattern in patterns:
        matches = re.findall(pattern, query_clean, re.IGNORECASE)
        tables.update(m.lower() for m in matches)

    # Remove common SQL keywords that might be misidentified
    keywords = {'select', 'where', 'and', 'or', 'not', 'null', 'true', 'false', 'as', 'on', 'in'}
    tables -= keywords

    return tables


def register(mcp):
    """Register SQL tools with MCP server."""

    @mcp.tool()
    def list_tables() -> dict:
        """
        List all available database tables.
        Use this to explore the database schema.
        """
        ctx = get_user_context()
        if not ctx:
            return {"error": "Not authenticated. Please login first."}

        allowed = _get_allowed_tables(ctx)

        # Super admin - show all tables
        if allowed is None:
            query = """
                SELECT table_name
                FROM information_schema.tables
                WHERE table_schema = 'public'
                ORDER BY table_name
            """
            rows = fetch_all(query)
            return {
                "count": len(rows),
                "tables": [r["table_name"] for r in rows]
            }

        # Restricted user - show only allowed tables
        return {
            "count": len(allowed),
            "tables": sorted(allowed),
            "_note": "Table access restricted based on your role."
        }

    @mcp.tool()
    def get_table_schema(table_name: str) -> dict:
        """
        Get schema (columns and types) for a database table.
        Use this before writing custom SQL queries.
        """
        ctx = get_user_context()
        if not ctx:
            return {"error": "Not authenticated. Please login first."}

        # Sanitize table name
        if not re.match(r"^[a-zA-Z_][a-zA-Z0-9_]*$", table_name):
            return {"error": "Invalid table name"}

        # Check table access
        allowed = _get_allowed_tables(ctx)
        if allowed is not None and table_name.lower() not in [t.lower() for t in allowed]:
            return {
                "error": f"Access denied to table '{table_name}'. Use list_tables to see available tables."
            }

        query = """
            SELECT column_name, data_type, is_nullable, column_default
            FROM information_schema.columns
            WHERE table_name = $1 AND table_schema = 'public'
            ORDER BY ordinal_position
        """
        rows = fetch_all(query, [table_name])

        if not rows:
            return {"error": f"Table '{table_name}' not found"}

        return {
            "table_name": table_name,
            "column_count": len(rows),
            "columns": [
                {
                    "name": r["column_name"],
                    "type": r["data_type"],
                    "nullable": r["is_nullable"] == "YES",
                    "default": r["column_default"]
                }
                for r in rows
            ]
        }

    @mcp.tool()
    def run_sql_query(query: str) -> dict:
        """
        Run a custom SQL query with RBAC filtering. Only SELECT queries are allowed.
        Use get_table_schema first to check column names.

        RBAC is auto-applied:
        - Super admin: No filter
        - Company admin: Filters by company_id
        - Branch manager: Filters by company_id and company_branch_id
        - Employee: Filters by company_employee_id (own data only)
        """
        ctx = get_user_context()
        if not ctx:
            return {"error": "Not authenticated. Please login first."}

        # Validate query
        if not query or not query.strip():
            return {"error": "Query cannot be empty"}

        query_upper = query.upper().strip()

        # Allow SELECT and WITH (for CTEs)
        if not (query_upper.startswith("SELECT") or query_upper.startswith("WITH")):
            return {"error": "Only SELECT queries are allowed. Query must start with SELECT or WITH."}

        # Block dangerous keywords
        dangerous = ["INSERT", "UPDATE", "DELETE", "DROP", "TRUNCATE", "ALTER", "CREATE", "GRANT", "REVOKE"]
        for keyword in dangerous:
            # Use word boundary to avoid false positives like "SELECTED"
            if re.search(rf"\b{keyword}\b", query_upper):
                return {"error": f"Query contains forbidden keyword: {keyword}"}

        # Check table access
        allowed = _get_allowed_tables(ctx)
        if allowed is not None:
            tables_in_query = _extract_tables_from_query(query)
            allowed_lower = {t.lower() for t in allowed}
            forbidden = tables_in_query - allowed_lower

            if forbidden:
                return {
                    "error": f"Access denied to table(s): {', '.join(sorted(forbidden))}. Use list_tables to see available tables."
                }

        # Try to apply RBAC filter to common employee tables
        query_to_run = query

        # List of table patterns that should have RBAC applied
        # These tables have company_id and/or company_branch_id columns
        employee_tables = [
            ("company_employee", "ce"),
            ("company_attendance", "ca"),
            ("company_approval", "cap"),
            ("company_employee_salary_slip", "ss"),
            ("company_employee_leave", "cel"),
            ("company_employee_allowance", "cea"),
            ("company_employee_deduction", "ced"),
            ("attendance_report", "ar"),
            ("company_attendance_master", "cam"),
            ("task_management", "t"),
            ("meeting_management", "m"),
            ("company_document", "cd"),
            ("company_holiday", "ch"),
            ("announcement", "a"),
            ("roster", "r"),
            ("company_employee_location", "loc"),
            ("company_employee_location_history", "loch"),
            ("company_employee_of_month", "eom"),
            ("attendance_daily_summary", "ads"),
            ("attendance_monthly_summary", "ams"),
            ("attendance_branch_daily_summary", "abds"),
            ("attendance_branch_monthly_summary", "abms"),
        ]

        # Try to detect if query uses employee tables and apply filter
        # Use regex to handle whitespace (spaces, newlines, tabs)
        for table, alias in employee_tables:
            if table.lower() in query.lower():
                # Check for alias with whitespace boundaries
                alias_pattern = rf'\s{alias}\s|\s{alias}\.'
                table_pattern = rf'\s{table}\s|\s{table}\.'

                if re.search(alias_pattern, query, re.IGNORECASE):
                    query_to_run = apply_company_filter(ctx, query_to_run, alias)
                    break
                elif re.search(table_pattern, query, re.IGNORECASE):
                    query_to_run = apply_company_filter(ctx, query_to_run, table)
                    break

        try:
            rows = fetch_all(query_to_run)

            return {
                "success": True,
                "row_count": len(rows),
                "data": rows[:100],  # Limit to 100 rows
                "_note": "Results limited to 100 rows. RBAC filter applied based on your role."
            }
        except Exception as e:
            return {"error": f"Query failed: {str(e)}"}
