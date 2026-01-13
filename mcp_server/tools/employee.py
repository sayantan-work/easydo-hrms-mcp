"""Employee tools for MCP server."""
from ..auth import get_user_context
from ..db import fetch_all, fetch_one
from ..rbac import apply_company_filter, filter_sensitive_fields


def _resolve_employee(ctx, employee_name: str = None, company_name: str = None):
    """
    Helper to resolve employee. Returns (employee_id, employee_name, company_name, branch_name, error).
    If employee_name is None, uses logged-in user.
    """
    if employee_name:
        # Search for the employee
        query = """
            SELECT ce.id, ce.employee_name, c.name as company_name, cb.name as branch_name
            FROM company_employee ce
            JOIN company c ON c.id = ce.company_id
            LEFT JOIN company_branch cb ON cb.id = ce.company_branch_id
            WHERE LOWER(ce.employee_name) LIKE LOWER($1) AND ce.is_deleted = '0'
        """
        params = [f"%{employee_name}%"]

        if company_name:
            query += " AND LOWER(c.name) LIKE LOWER($2)"
            params.append(f"%{company_name}%")

        query = apply_company_filter(ctx, query, "ce")
        rows = fetch_all(query, params)

        if not rows:
            return None, None, None, None, f"Employee '{employee_name}' not found or not accessible"
        if len(rows) > 1 and not company_name:
            return None, None, None, None, {
                "error": "Multiple employees found. Please specify company_name.",
                "matches": [{"name": r["employee_name"], "company": r["company_name"]} for r in rows]
            }
        return rows[0]["id"], rows[0]["employee_name"], rows[0]["company_name"], rows[0]["branch_name"], None
    else:
        # Default to self
        pc = ctx.primary_company
        if not pc:
            return None, None, None, None, "No company association found for your account."
        return pc.company_employee_id, ctx.user_name, pc.company_name, pc.branch_name, None


def register(mcp):
    """Register employee tools with MCP server."""

    @mcp.tool()
    def get_employee(employee_name: str = None, company_name: str = None) -> dict:
        """
        Get employee profile/details.
        If employee_name is not provided, returns your own profile.
        Use company_name to filter by specific company.
        """
        ctx = get_user_context()
        if not ctx:
            return {"error": "Not authenticated. Please login first."}

        if employee_name:
            # Search for the employee
            query = """
                SELECT ce.id, ce.employee_code, ce.employee_name, ce.employee_email,
                       ce.employee_mobile, ce.designation, ce.gender, ce.date_of_birth,
                       ce.date_of_joining, cd.name as department_name, cb.name as branch_name,
                       c.name as company_name, mgr.employee_name as reporting_manager,
                       ce.employee_status, ce.pan_number, ce.aadhar_card_number,
                       ce.uan_number, ce.pf_number, ce.esi_number
                FROM company_employee ce
                LEFT JOIN company c ON c.id = ce.company_id
                LEFT JOIN company_branch cb ON cb.id = ce.company_branch_id
                LEFT JOIN company_department cd ON cd.id = ce.company_role_id
                LEFT JOIN company_employee mgr ON mgr.id = ce.reporting_manager_id
                WHERE ce.is_deleted = '0' AND LOWER(ce.employee_name) LIKE LOWER($1)
            """
            params = [f"%{employee_name}%"]

            if company_name:
                query += " AND LOWER(c.name) LIKE LOWER($2)"
                params.append(f"%{company_name}%")

            query = apply_company_filter(ctx, query, "ce")
            query += " ORDER BY ce.employee_name LIMIT 10"
            rows = fetch_all(query, params)

            if not rows:
                return {"error": f"Employee '{employee_name}' not found or not accessible"}
            if len(rows) > 1 and not company_name:
                return {
                    "error": "Multiple employees found. Please specify company_name.",
                    "matches": [{"employee_name": r["employee_name"], "company_name": r["company_name"]} for r in rows]
                }

            row = rows[0]
            return filter_sensitive_fields(ctx, row, row["id"])
        else:
            # Default to self - get own profile
            pc = ctx.primary_company
            if not pc:
                # Super admin or no company - return basic user info
                query = """
                    SELECT u.id as user_id, u.user_name, u.email, u.contact_number
                    FROM users u WHERE u.id = $1
                """
                row = fetch_one(query, [ctx.user_id])
                return {
                    "user_id": ctx.user_id,
                    "user_name": row.get("user_name") if row else ctx.user_name,
                    "email": row.get("email") if row else None,
                    "contact_number": row.get("contact_number") if row else None,
                    "role": "Super Admin" if ctx.is_super_admin else "User",
                    "_note": "No employee record found. This is your user account info."
                }

            query = """
                SELECT ce.id, ce.employee_code, ce.employee_name, ce.employee_email,
                       ce.employee_mobile, ce.designation, ce.gender, ce.date_of_birth,
                       ce.date_of_joining, cd.name as department_name, cb.name as branch_name,
                       c.name as company_name, mgr.employee_name as reporting_manager,
                       ce.pan_number, ce.aadhar_card_number, ce.uan_number, ce.pf_number, ce.esi_number
                FROM company_employee ce
                LEFT JOIN company c ON c.id = ce.company_id
                LEFT JOIN company_branch cb ON cb.id = ce.company_branch_id
                LEFT JOIN company_department cd ON cd.id = ce.company_role_id
                LEFT JOIN company_employee mgr ON mgr.id = ce.reporting_manager_id
                WHERE ce.id = $1
            """
            row = fetch_one(query, [pc.company_employee_id])
            if row:
                return row
            return {"error": "Profile not found"}

    @mcp.tool()
    def get_employee_count(company_name: str = None, branch_name: str = None) -> dict:
        """
        Get total employee headcount.
        Use company_name and/or branch_name to filter.
        Defaults to your accessible scope based on RBAC.
        """
        ctx = get_user_context()
        if not ctx:
            return {"error": "Not authenticated. Please login first."}

        query = """
            SELECT COUNT(*) as count
            FROM company_employee ce
            LEFT JOIN company c ON c.id = ce.company_id
            LEFT JOIN company_branch cb ON cb.id = ce.company_branch_id
            WHERE ce.is_deleted = '0' AND ce.employee_status = 3
        """
        params = []
        param_idx = 1

        if company_name:
            query += f" AND LOWER(c.name) LIKE LOWER(${param_idx})"
            params.append(f"%{company_name}%")
            param_idx += 1

        if branch_name:
            query += f" AND LOWER(cb.name) LIKE LOWER(${param_idx})"
            params.append(f"%{branch_name}%")
            param_idx += 1

        query = apply_company_filter(ctx, query, "ce")
        row = fetch_one(query, params) if params else fetch_one(query)

        result = {"total_employees": row["count"] if row else 0}
        if company_name:
            result["company_filter"] = company_name
        if branch_name:
            result["branch_filter"] = branch_name

        return result

    @mcp.tool()
    def search_employee_directory(query: str) -> dict:
        """
        Search employee directory for public info (name, department, designation).
        Returns basic public information only.
        """
        ctx = get_user_context()
        if not ctx:
            return {"error": "Not authenticated. Please login first."}

        sql = """
            SELECT ce.id, ce.employee_name, ce.designation,
                   cd.name as department_name, cb.name as branch_name, c.name as company_name
            FROM company_employee ce
            LEFT JOIN company c ON c.id = ce.company_id
            LEFT JOIN company_branch cb ON cb.id = ce.company_branch_id
            LEFT JOIN company_department cd ON cd.id = ce.company_role_id
            WHERE ce.is_deleted = '0' AND ce.employee_status = 3
            AND LOWER(ce.employee_name) LIKE LOWER($1)
        """
        sql = apply_company_filter(ctx, sql, "ce")
        sql += " ORDER BY ce.employee_name LIMIT 20"

        rows = fetch_all(sql, [f"%{query}%"])
        return {"count": len(rows), "employees": rows}
