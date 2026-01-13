"""Team management tools for MCP server."""
from ..auth import get_user_context
from ..db import fetch_all, fetch_one
from ..rbac import apply_company_filter


def _get_team_recursive(manager_id: int, include_info: bool = True, max_depth: int = 10):
    """
    Helper function to get all team members recursively.
    Returns list of employee dicts with level field.
    """
    def fetch_reports(mgr_id: int, depth: int = 0):
        if depth >= max_depth:
            return []

        query = """
            SELECT ce.id, ce.employee_name, ce.designation, ce.employee_email,
                   cd.name as department_name, cb.name as branch_name,
                   ce.employee_status, ce.date_of_joining
            FROM company_employee ce
            LEFT JOIN company_department cd ON cd.id = ce.company_role_id
            LEFT JOIN company_branch cb ON cb.id = ce.company_branch_id
            WHERE ce.reporting_manager_id = $1 AND ce.is_deleted = '0'
            ORDER BY ce.employee_name
        """
        rows = fetch_all(query, [mgr_id])
        result = []

        for r in rows:
            if include_info:
                result.append({
                    "id": r["id"],
                    "employee_name": r["employee_name"],
                    "email": r.get("employee_email"),
                    "designation": r.get("designation"),
                    "department": r.get("department_name"),
                    "branch": r.get("branch_name"),
                    "date_of_joining": str(r.get("date_of_joining")),
                    "status": "active" if r.get("employee_status") == 3 else "inactive",
                    "level": depth + 1,
                    "reports_to_you": depth == 0
                })
            else:
                result.append(r["id"])

            # Recursively get sub-reports
            sub_reports = fetch_reports(r["id"], depth + 1)
            result.extend(sub_reports)

        return result

    return fetch_reports(manager_id)


def register(mcp):
    """Register team tools with MCP server."""

    @mcp.tool()
    def get_team(employee_name: str = None, recursive: bool = False) -> dict:
        """
        Get team members (direct reports).
        If employee_name is not provided, returns your team.
        Use recursive=True to get all employees in hierarchy (reports of reports).
        """
        ctx = get_user_context()
        if not ctx:
            return {"error": "Not authenticated. Please login first."}

        if employee_name:
            # Search for the manager
            emp_query = """
                SELECT ce.id, ce.employee_name, c.name as company_name
                FROM company_employee ce
                JOIN company c ON c.id = ce.company_id
                WHERE LOWER(ce.employee_name) LIKE LOWER($1) AND ce.is_deleted = '0'
            """
            emp_query = apply_company_filter(ctx, emp_query, "ce")
            emp_rows = fetch_all(emp_query, [f"%{employee_name}%"])

            if not emp_rows:
                return {"error": f"Employee '{employee_name}' not found or not accessible"}
            if len(emp_rows) > 1:
                return {
                    "error": "Multiple employees found. Please be more specific.",
                    "matches": [{"name": r["employee_name"], "company": r["company_name"]} for r in emp_rows]
                }

            manager_id = emp_rows[0]["id"]
            manager_name = emp_rows[0]["employee_name"]
            company_name = emp_rows[0]["company_name"]
        else:
            # Default to self
            pc = ctx.primary_company
            if not pc:
                return {"error": "No company association found."}
            manager_id = pc.company_employee_id
            manager_name = ctx.user_name
            company_name = pc.company_name

        if recursive:
            team = _get_team_recursive(manager_id, include_info=True)
        else:
            # Direct reports only
            query = """
                SELECT ce.id, ce.employee_name, ce.employee_email, ce.designation,
                       cd.name as department_name, cb.name as branch_name,
                       ce.employee_status, ce.date_of_joining
                FROM company_employee ce
                LEFT JOIN company_department cd ON cd.id = ce.company_role_id
                LEFT JOIN company_branch cb ON cb.id = ce.company_branch_id
                WHERE ce.reporting_manager_id = $1 AND ce.is_deleted = '0'
                ORDER BY ce.employee_name
            """
            rows = fetch_all(query, [manager_id])
            team = [
                {
                    "id": r["id"],
                    "employee_name": r["employee_name"],
                    "email": r.get("employee_email"),
                    "designation": r.get("designation"),
                    "department": r.get("department_name"),
                    "branch": r.get("branch_name"),
                    "date_of_joining": str(r.get("date_of_joining")),
                    "status": "active" if r.get("employee_status") == 3 else "inactive",
                    "level": 1,
                    "reports_to_you": True
                }
                for r in rows
            ]

        # Summary by level
        if recursive and team:
            levels = {}
            for emp in team:
                lvl = emp["level"]
                levels[lvl] = levels.get(lvl, 0) + 1
            level_summary = {f"level_{k}_count": v for k, v in sorted(levels.items())}
        else:
            level_summary = {"direct_reports": len(team)}

        return {
            "manager_name": manager_name,
            "company_name": company_name,
            "recursive": recursive,
            "total_team_size": len(team),
            "summary": level_summary,
            "team": team,
            "_note": "level=1 are direct reports, level=2 are reports of your reports, etc."
        }

    @mcp.tool()
    def get_pending_approvals() -> dict:
        """
        Get pending approval requests (leave, expenses, etc.) that need your action.
        """
        ctx = get_user_context()
        if not ctx:
            return {"error": "Not authenticated. Please login first."}

        pc = ctx.primary_company
        if not pc:
            return {"error": "No company association found."}

        query = """
            SELECT ca.id, ce.employee_name, ca.media_type, ca.title, ca.leave_type,
                   ca.start_date, ca.end_date, ca.no_of_leave_day, ca.amount, ca.notes, ca.created_at
            FROM company_approval ca
            JOIN company_employee ce ON ce.id = ca.company_employee_id
            WHERE ca.reporting_manager_id = $1 AND ca.status = 'pending'
            ORDER BY ca.created_at DESC
        """
        rows = fetch_all(query, [pc.company_employee_id])

        # Group by type
        by_type = {}
        for r in rows:
            t = r.get("media_type", "other")
            if t not in by_type:
                by_type[t] = []
            by_type[t].append(r)

        return {
            "count": len(rows),
            "summary_by_type": {k: len(v) for k, v in by_type.items()},
            "pending_approvals": [
                {
                    "id": r.get("id"),
                    "employee_name": r.get("employee_name"),
                    "type": r.get("media_type"),
                    "title": r.get("title"),
                    "leave_type": r.get("leave_type"),
                    "start_date": str(r.get("start_date")) if r.get("start_date") else None,
                    "end_date": str(r.get("end_date")) if r.get("end_date") else None,
                    "days": r.get("no_of_leave_day"),
                    "amount": r.get("amount"),
                    "notes": r.get("notes"),
                    "requested_on": str(r.get("created_at"))
                }
                for r in rows
            ]
        }
