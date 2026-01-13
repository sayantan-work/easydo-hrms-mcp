"""Organization tools for MCP server."""
from datetime import datetime
from ..auth import get_user_context
from ..db import fetch_all, fetch_one
from ..rbac import apply_company_filter


def register(mcp):
    """Register organization tools with MCP server."""

    @mcp.tool()
    def get_branches(company_name: str = None) -> dict:
        """
        Get list of company branches.
        Use company_name to filter by specific company.
        Defaults to your primary company.
        """
        ctx = get_user_context()
        if not ctx:
            return {"error": "Not authenticated. Please login first."}

        if company_name:
            query = """
                SELECT cb.id, cb.name, cb.address, cb.branch_type, cb.working_hours,
                       cb.start_time, cb.end_time, cb.status, c.name as company_name
                FROM company_branch cb
                JOIN company c ON c.id = cb.company_id
                WHERE cb.status = 1 AND LOWER(c.name) LIKE LOWER($1)
                ORDER BY cb.name
            """
            rows = fetch_all(query, [f"%{company_name}%"])
        else:
            # Default to user's company
            if not ctx.company_id:
                return {"error": "No company association found."}

            query = """
                SELECT cb.id, cb.name, cb.address, cb.branch_type, cb.working_hours,
                       cb.start_time, cb.end_time, cb.status, c.name as company_name
                FROM company_branch cb
                JOIN company c ON c.id = cb.company_id
                WHERE cb.company_id = $1 AND cb.status = 1
                ORDER BY cb.name
            """
            rows = fetch_all(query, [ctx.company_id])

        result = {"count": len(rows), "branches": rows}
        if company_name:
            result["company_filter"] = company_name

        return result

    @mcp.tool()
    def get_holidays(year: int = None, branch_name: str = None, company_name: str = None) -> dict:
        """
        Get holiday calendar.
        Year defaults to current year.
        Use branch_name and/or company_name to filter.
        """
        ctx = get_user_context()
        if not ctx:
            return {"error": "Not authenticated. Please login first."}

        if not year:
            year = datetime.now().year

        query = """
            SELECT ch.name, ch.date, ch.type, c.name as company_name, cb.name as branch_name
            FROM company_holiday ch
            JOIN company c ON c.id = ch.company_id
            LEFT JOIN company_branch cb ON cb.id = ch.company_branch_id
            WHERE ch.year = $1
        """
        params = [year]
        param_idx = 2

        if company_name:
            query += f" AND LOWER(c.name) LIKE LOWER(${param_idx})"
            params.append(f"%{company_name}%")
            param_idx += 1
        elif ctx.company_id:
            # Default to user's company if no filter specified
            query += f" AND ch.company_id = ${param_idx}"
            params.append(ctx.company_id)
            param_idx += 1

        if branch_name:
            query += f" AND LOWER(cb.name) LIKE LOWER(${param_idx})"
            params.append(f"%{branch_name}%")
            param_idx += 1

        query += " ORDER BY ch.date"
        rows = fetch_all(query, params)

        result = {"year": year, "count": len(rows), "holidays": rows}
        if company_name:
            result["company_filter"] = company_name
        if branch_name:
            result["branch_filter"] = branch_name

        return result

    @mcp.tool()
    def get_announcements(company_name: str = None) -> dict:
        """
        Get company announcements.
        Use company_name to filter by specific company.
        Defaults to your primary company.
        """
        ctx = get_user_context()
        if not ctx:
            return {"error": "Not authenticated. Please login first."}

        query = """
            SELECT a.id, a.title, a.description, a.type, a.announcement_date,
                   ce.employee_name as created_by, c.name as company_name
            FROM announcement a
            LEFT JOIN company_employee ce ON ce.id = a.created_by
            JOIN company c ON c.id = a.company_id
            WHERE a.status = 1
        """
        params = []
        param_idx = 1

        if company_name:
            query += f" AND LOWER(c.name) LIKE LOWER(${param_idx})"
            params.append(f"%{company_name}%")
            param_idx += 1
        elif ctx.company_id:
            # Default to user's company
            query += f" AND a.company_id = ${param_idx}"
            params.append(ctx.company_id)
            param_idx += 1

        query += " ORDER BY a.announcement_date DESC LIMIT 20"
        rows = fetch_all(query, params) if params else fetch_all(query)

        result = {"count": len(rows), "announcements": rows}
        if company_name:
            result["company_filter"] = company_name

        return result
