"""SQL query tools for MCP server."""
import re
from ..auth import get_user_context
from ..db import fetch_all, fetch_one
from ..rbac import apply_company_filter


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

        # Try to apply RBAC filter to common employee tables
        query_to_run = query

        # List of table patterns that should have RBAC applied
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
        ]

        # Try to detect if query uses employee tables and apply filter
        for table, alias in employee_tables:
            if table.lower() in query.lower():
                # Apply filter to the alias or table
                if f" {alias} " in query.lower() or f" {alias}." in query.lower():
                    query_to_run = apply_company_filter(ctx, query_to_run, alias)
                    break
                elif f" {table} " in query.lower() or f" {table}." in query.lower():
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
