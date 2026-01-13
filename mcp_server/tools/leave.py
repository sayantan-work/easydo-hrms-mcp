"""Leave tools for MCP server."""
from datetime import datetime
from ..auth import get_user_context
from ..db import fetch_all, fetch_one
from ..rbac import apply_company_filter


def register(mcp):
    """Register leave tools with MCP server."""

    @mcp.tool()
    def get_leave_balance(employee_name: str = None, company_name: str = None) -> dict:
        """
        Get leave balance for an employee.
        If employee_name is not provided, returns your own leave balance.
        Use company_name to filter by specific company.
        """
        ctx = get_user_context()
        if not ctx:
            return {"error": "Not authenticated. Please login first."}

        if employee_name:
            # Search for the employee
            query = """
                SELECT ce.id, ce.employee_name, c.name as company_name, cb.name as branch_name,
                       cel.earned_leave, cel.casual_leave, cel.sick_leave,
                       cel.other_leave, cel.carry_forward_leave, cel.year,
                       ce.company_branch_id
                FROM company_employee ce
                JOIN company c ON c.id = ce.company_id
                LEFT JOIN company_branch cb ON cb.id = ce.company_branch_id
                LEFT JOIN company_employee_leave cel ON cel.company_employee_id = ce.id AND cel.is_current = 1
                WHERE ce.is_deleted = '0' AND LOWER(ce.employee_name) LIKE LOWER($1)
            """
            params = [f"%{employee_name}%"]

            if company_name:
                query += " AND LOWER(c.name) LIKE LOWER($2)"
                params.append(f"%{company_name}%")

            query = apply_company_filter(ctx, query, "ce")
            rows = fetch_all(query, params)

            if not rows:
                return {"error": f"Employee '{employee_name}' not found or no leave balance data"}

            if len(rows) > 1 and not company_name:
                return {
                    "error": "Multiple employees found. Please specify company_name.",
                    "matches": [{"employee_name": r["employee_name"], "company_name": r["company_name"]} for r in rows]
                }

            row = rows[0]
            branch_id = row.get("company_branch_id")
        else:
            # Default to self
            pc = ctx.primary_company
            if not pc:
                return {"error": "No company association found."}

            query = """
                SELECT c.name as company_name, cb.name as branch_name,
                       cel.earned_leave, cel.casual_leave, cel.sick_leave,
                       cel.other_leave, cel.carry_forward_leave, cel.year
                FROM company_employee_leave cel
                JOIN company_employee ce ON ce.id = cel.company_employee_id
                JOIN company c ON c.id = ce.company_id
                LEFT JOIN company_branch cb ON cb.id = ce.company_branch_id
                WHERE cel.company_employee_id = $1 AND cel.is_current = 1
            """
            row = fetch_one(query, [pc.company_employee_id])
            branch_id = pc.company_branch_id

            if not row:
                return {"error": "No leave balance found"}

            row["employee_name"] = ctx.user_name

        # Fetch branch leave policy for context
        policy_query = """
            SELECT cl.sick_leave, cl.sick_leave_max_month,
                   cl.casual_leave, cl.casual_leave_max_month, cl.max_consequently_casual_leave,
                   cl.earned_leave, cl.earned_leave_max_month,
                   cl.other_leave, cl.other_leave_max_month,
                   cl.carry_forward_leave, cl.is_carry_forward_leave_allowed
            FROM company_leave cl
            WHERE cl.company_branch_id = $1 AND cl.is_current = 1
        """
        policy_row = fetch_one(policy_query, [branch_id]) if branch_id else None

        # Build policy breakdown
        if policy_row:
            casual_quota = policy_row.get("casual_leave", 0) or 0
            earned_quota = policy_row.get("earned_leave", 0) or 0

            branch_policy = {
                "sick_leave": {
                    "annual_quota": policy_row.get("sick_leave", 0),
                    "max_per_month": policy_row.get("sick_leave_max_month", 0),
                    "allocation": "upfront",
                    "_note": "Credited at start of year"
                },
                "casual_leave": {
                    "annual_quota": casual_quota,
                    "monthly_accrual": round(casual_quota / 12, 2),
                    "max_per_month": policy_row.get("casual_leave_max_month", 0),
                    "max_consecutive_days": policy_row.get("max_consequently_casual_leave", 0),
                    "allocation": "accrued"
                },
                "earned_leave": {
                    "annual_quota": earned_quota,
                    "monthly_accrual": round(earned_quota / 12, 2),
                    "max_per_month": policy_row.get("earned_leave_max_month", 0),
                    "allocation": "accrued"
                },
                "carry_forward": {
                    "allowed": policy_row.get("is_carry_forward_leave_allowed") == 1,
                    "max_days": policy_row.get("carry_forward_leave", 0)
                }
            }
        else:
            branch_policy = {"_note": "Policy details not available"}

        balance = {
            "earned_leave": row.get("earned_leave", 0) or 0,
            "casual_leave": row.get("casual_leave", 0) or 0,
            "sick_leave": row.get("sick_leave", 0) or 0,
            "other_leave": row.get("other_leave", 0) or 0,
        }

        return {
            "employee_name": row.get("employee_name"),
            "company_name": row.get("company_name"),
            "branch_name": row.get("branch_name"),
            "year": row.get("year"),
            "balance": balance,
            "total_available": sum(balance.values()),
            "branch_policy": branch_policy
        }

    @mcp.tool()
    def who_is_on_leave_today(company_name: str = None, branch_name: str = None) -> dict:
        """
        Get list of employees who are on leave today.
        Use company_name and/or branch_name to filter.
        """
        ctx = get_user_context()
        if not ctx:
            return {"error": "Not authenticated. Please login first."}

        today = datetime.now().strftime("%Y-%m-%d")

        query = """
            SELECT ce.employee_name, ce.designation, cd.name as department_name,
                   cb.name as branch_name, c.name as company_name,
                   ca.leave_type, ca.start_date, ca.end_date
            FROM company_approval ca
            JOIN company_employee ce ON ce.id = ca.company_employee_id
            JOIN company c ON c.id = ce.company_id
            LEFT JOIN company_branch cb ON cb.id = ce.company_branch_id
            LEFT JOIN company_department cd ON cd.id = ce.company_role_id
            WHERE ce.is_deleted = '0' AND ca.media_type = 'leave' AND ca.status = 'approved'
            AND $1 BETWEEN ca.start_date AND ca.end_date
        """
        params = [today]
        param_idx = 2

        if company_name:
            query += f" AND LOWER(c.name) LIKE LOWER(${param_idx})"
            params.append(f"%{company_name}%")
            param_idx += 1

        if branch_name:
            query += f" AND LOWER(cb.name) LIKE LOWER(${param_idx})"
            params.append(f"%{branch_name}%")
            param_idx += 1

        query = apply_company_filter(ctx, query, "ce")
        query += " ORDER BY c.name, ce.employee_name"

        rows = fetch_all(query, params)

        result = {"date": today, "count": len(rows), "on_leave": rows}
        if company_name:
            result["company_filter"] = company_name
        if branch_name:
            result["branch_filter"] = branch_name

        return result

    @mcp.tool()
    def get_leave_history(employee_name: str = None, year: int = None, company_name: str = None) -> dict:
        """
        Get leave history showing all leave requests with dates and status.
        If employee_name is not provided, returns your own leave history.
        Year defaults to current year.
        """
        ctx = get_user_context()
        if not ctx:
            return {"error": "Not authenticated. Please login first."}

        if not year:
            year = datetime.now().year

        if employee_name:
            # Search for the employee first
            emp_query = """
                SELECT ce.id, ce.employee_name, c.name as company_name
                FROM company_employee ce
                JOIN company c ON c.id = ce.company_id
                WHERE LOWER(ce.employee_name) LIKE LOWER($1) AND ce.is_deleted = '0'
            """
            emp_params = [f"%{employee_name}%"]

            if company_name:
                emp_query += " AND LOWER(c.name) LIKE LOWER($2)"
                emp_params.append(f"%{company_name}%")

            emp_query = apply_company_filter(ctx, emp_query, "ce")
            emp_rows = fetch_all(emp_query, emp_params)

            if not emp_rows:
                return {"error": f"Employee '{employee_name}' not found or not accessible"}
            if len(emp_rows) > 1 and not company_name:
                return {
                    "error": "Multiple employees found. Please specify company_name.",
                    "matches": [{"employee_name": r["employee_name"], "company_name": r["company_name"]} for r in emp_rows]
                }

            target_emp_id = emp_rows[0]["id"]
            target_name = emp_rows[0]["employee_name"]
            target_company = emp_rows[0]["company_name"]
        else:
            # Default to self
            pc = ctx.primary_company
            if not pc:
                return {"error": "No company association found."}
            target_emp_id = pc.company_employee_id
            target_name = ctx.user_name
            target_company = pc.company_name

        query = """
            SELECT ca.leave_type, ca.start_date, ca.end_date, ca.no_of_leave_day as days,
                   ca.is_paid_leave, ca.notes as reason, ca.status, ca.created_at as requested_on
            FROM company_approval ca
            WHERE ca.media_type = 'leave'
              AND ca.company_employee_id = $1
              AND EXTRACT(YEAR FROM ca.start_date) = $2
            ORDER BY ca.start_date DESC
        """
        rows = fetch_all(query, [target_emp_id, year])

        # Group by status
        approved = [r for r in rows if r.get("status") == "approved"]
        pending = [r for r in rows if r.get("status") == "pending"]
        rejected = [r for r in rows if r.get("status") == "rejected"]

        return {
            "employee_name": target_name,
            "company_name": target_company,
            "year": year,
            "total_requests": len(rows),
            "summary": {
                "approved": len(approved),
                "pending": len(pending),
                "rejected": len(rejected),
                "total_days_taken": sum(float(r.get("days") or 0) for r in approved)
            },
            "leave_requests": [
                {
                    "leave_type": r.get("leave_type"),
                    "start_date": str(r.get("start_date")),
                    "end_date": str(r.get("end_date")),
                    "days": r.get("days"),
                    "is_paid": r.get("is_paid_leave") == 1,
                    "reason": r.get("reason"),
                    "status": r.get("status"),
                    "requested_on": str(r.get("requested_on"))
                }
                for r in rows
            ]
        }
