"""Leave tools for MCP server."""
from datetime import datetime

from ..auth import get_user_context
from ..db import fetch_all, fetch_one
from ..rbac import apply_company_filter


# Authentication helper
def _require_auth():
    """Get user context or return error dict."""
    ctx = get_user_context()
    if not ctx:
        return None, {"error": "Not authenticated. Please login first."}
    return ctx, None


# Query building helpers
def _build_filtered_query(base_query: str, ctx, params: list, param_idx: int,
                          company_name: str = None, branch_name: str = None,
                          table_alias: str = "ce"):
    """Build query with company/branch filters and RBAC. Returns (query, params, param_idx)."""
    if company_name:
        base_query += f" AND LOWER(c.name) LIKE LOWER(${param_idx})"
        params.append(f"%{company_name}%")
        param_idx += 1

    if branch_name:
        base_query += f" AND LOWER(cb.name) LIKE LOWER(${param_idx})"
        params.append(f"%{branch_name}%")
        param_idx += 1

    return apply_company_filter(ctx, base_query, table_alias), params, param_idx


def _add_filters_to_result(result: dict, company_name: str = None, branch_name: str = None) -> dict:
    """Add filter info to result dict if filters were applied."""
    if company_name:
        result["company_filter"] = company_name
    if branch_name:
        result["branch_filter"] = branch_name
    return result


# Leave balance helpers
def _get_value(row: dict, key: str, default: int = 0) -> int:
    """Get value from row dict with default fallback for None values."""
    value = row.get(key)
    return value if value is not None else default


def _build_leave_policy(policy_row: dict) -> dict:
    """Build leave policy breakdown from policy row data."""
    if not policy_row:
        return {"_note": "Policy details not available"}

    casual_quota = _get_value(policy_row, "casual_leave")
    earned_quota = _get_value(policy_row, "earned_leave")

    return {
        "sick_leave": {
            "annual_quota": _get_value(policy_row, "sick_leave"),
            "max_per_month": _get_value(policy_row, "sick_leave_max_month"),
            "allocation": "upfront",
            "_note": "Credited at start of year"
        },
        "casual_leave": {
            "annual_quota": casual_quota,
            "monthly_accrual": round(casual_quota / 12, 2),
            "max_per_month": _get_value(policy_row, "casual_leave_max_month"),
            "max_consecutive_days": _get_value(policy_row, "max_consequently_casual_leave"),
            "allocation": "accrued"
        },
        "earned_leave": {
            "annual_quota": earned_quota,
            "monthly_accrual": round(earned_quota / 12, 2),
            "max_per_month": _get_value(policy_row, "earned_leave_max_month"),
            "allocation": "accrued"
        },
        "carry_forward": {
            "allowed": policy_row.get("is_carry_forward_leave_allowed") == 1,
            "max_days": _get_value(policy_row, "carry_forward_leave")
        }
    }


def _fetch_branch_policy(branch_id: int) -> dict:
    """Fetch leave policy for a branch."""
    if not branch_id:
        return None

    query = """
        SELECT cl.sick_leave, cl.sick_leave_max_month,
               cl.casual_leave, cl.casual_leave_max_month, cl.max_consequently_casual_leave,
               cl.earned_leave, cl.earned_leave_max_month,
               cl.other_leave, cl.other_leave_max_month,
               cl.carry_forward_leave, cl.is_carry_forward_leave_allowed
        FROM company_leave cl
        WHERE cl.company_branch_id = $1 AND cl.is_current = 1
    """
    return fetch_one(query, [branch_id])


def _build_leave_balance(row: dict) -> dict:
    """Build leave balance dict from row data."""
    return {
        "earned_leave": _get_value(row, "earned_leave"),
        "casual_leave": _get_value(row, "casual_leave"),
        "sick_leave": _get_value(row, "sick_leave"),
        "other_leave": _get_value(row, "other_leave"),
    }


# Employee lookup helpers
def _search_employee_for_leave(ctx, employee_name: str = None, company_name: str = None, employee_id: int = None):
    """Search for employee with leave balance data."""
    # If employee_id is provided, use it directly
    if employee_id:
        query = """
            SELECT ce.id, ce.employee_name, ce.designation, c.name as company_name, cb.name as branch_name,
                   cel.earned_leave, cel.casual_leave, cel.sick_leave,
                   cel.other_leave, cel.carry_forward_leave, cel.year,
                   ce.company_branch_id
            FROM company_employee ce
            JOIN company c ON c.id = ce.company_id
            LEFT JOIN company_branch cb ON cb.id = ce.company_branch_id
            LEFT JOIN company_employee_leave cel ON cel.company_employee_id = ce.id AND cel.is_current = 1
            WHERE ce.is_deleted = '0' AND ce.id = $1
        """
        query = apply_company_filter(ctx, query, "ce")
        rows = fetch_all(query, [employee_id])
        return rows

    # Search by name
    query = """
        SELECT ce.id, ce.employee_name, ce.designation, c.name as company_name, cb.name as branch_name,
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
    return fetch_all(query, params)


def _get_self_leave_balance(ctx):
    """Get leave balance for the current user."""
    pc = ctx.primary_company
    if not pc:
        return None, None, {"error": "No company association found."}

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

    if not row:
        return None, None, {"error": "No leave balance found"}

    row["employee_name"] = ctx.user_name
    return row, pc.company_branch_id, None


def _search_employee_basic(ctx, employee_name: str = None, company_name: str = None, employee_id: int = None):
    """Search for basic employee info."""
    # If employee_id is provided, use it directly
    if employee_id:
        query = """
            SELECT ce.id, ce.employee_name, ce.designation, c.name as company_name, cb.name as branch_name
            FROM company_employee ce
            JOIN company c ON c.id = ce.company_id
            LEFT JOIN company_branch cb ON cb.id = ce.company_branch_id
            WHERE ce.id = $1 AND ce.is_deleted = '0'
        """
        query = apply_company_filter(ctx, query, "ce")
        rows = fetch_all(query, [employee_id])
        return rows

    # Search by name
    query = """
        SELECT ce.id, ce.employee_name, ce.designation, c.name as company_name, cb.name as branch_name
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
    return fetch_all(query, params)


def _format_leave_request(row: dict) -> dict:
    """Format a single leave request row for output."""
    return {
        "leave_type": row.get("leave_type"),
        "start_date": str(row.get("start_date")),
        "end_date": str(row.get("end_date")),
        "days": row.get("days"),
        "is_paid": row.get("is_paid_leave") == 1,
        "reason": row.get("reason"),
        "status": row.get("status"),
        "requested_on": str(row.get("requested_on"))
    }


def register(mcp):
    """Register leave tools with MCP server."""

    @mcp.tool()
    def get_leave_balance(employee_name: str = None, company_name: str = None, employee_id: int = None) -> dict:
        """
        Get leave balance for an employee.
        If employee_name is not provided, returns your own leave balance.
        Use company_name to filter by specific company.
        """
        ctx, err = _require_auth()
        if err:
            return err

        if employee_id:
            rows = _search_employee_for_leave(ctx, employee_id=employee_id)

            if not rows:
                return {"error": f"Employee ID {employee_id} not found or not accessible"}

            row = rows[0]
            branch_id = row.get("company_branch_id")

        elif employee_name:
            rows = _search_employee_for_leave(ctx, employee_name=employee_name, company_name=company_name)

            if not rows:
                return {"error": f"Employee '{employee_name}' not found or no leave balance data"}

            if len(rows) > 1:
                return {
                    "error": "Multiple employees found with this name. Use employee_id to specify.",
                    "hint": "Use employee_id parameter for exact match",
                    "matches": [
                        {
                            "employee_id": r["id"],
                            "employee_name": r["employee_name"],
                            "designation": r.get("designation"),
                            "company_name": r["company_name"],
                            "branch_name": r.get("branch_name")
                        } for r in rows
                    ]
                }

            row = rows[0]
            branch_id = row.get("company_branch_id")
        else:
            row, branch_id, error = _get_self_leave_balance(ctx)
            if error:
                return error

        policy_row = _fetch_branch_policy(branch_id)
        branch_policy = _build_leave_policy(policy_row)
        balance = _build_leave_balance(row)

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
    def get_leave_history(employee_name: str = None, year: int = None, company_name: str = None, employee_id: int = None) -> dict:
        """
        Get leave history showing all leave requests with dates and status.
        If employee_name is not provided, returns your own leave history.
        Year defaults to current year.
        """
        ctx, err = _require_auth()
        if err:
            return err

        if not year:
            year = datetime.now().year

        if employee_id:
            emp_rows = _search_employee_basic(ctx, employee_id=employee_id)

            if not emp_rows:
                return {"error": f"Employee ID {employee_id} not found or not accessible"}

            target_emp_id = emp_rows[0]["id"]
            target_name = emp_rows[0]["employee_name"]
            target_company = emp_rows[0]["company_name"]

        elif employee_name:
            emp_rows = _search_employee_basic(ctx, employee_name=employee_name, company_name=company_name)

            if not emp_rows:
                return {"error": f"Employee '{employee_name}' not found or not accessible"}

            if len(emp_rows) > 1:
                return {
                    "error": "Multiple employees found with this name. Use employee_id to specify.",
                    "hint": "Use employee_id parameter for exact match",
                    "matches": [
                        {
                            "employee_id": r["id"],
                            "employee_name": r["employee_name"],
                            "designation": r.get("designation"),
                            "company_name": r["company_name"],
                            "branch_name": r.get("branch_name")
                        } for r in emp_rows
                    ]
                }

            target_emp_id = emp_rows[0]["id"]
            target_name = emp_rows[0]["employee_name"]
            target_company = emp_rows[0]["company_name"]
        else:
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
            "leave_requests": [_format_leave_request(r) for r in rows]
        }
