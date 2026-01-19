"""Employee tools for MCP server."""
import calendar
from datetime import datetime, date
from ..auth import get_user_context
from ..db import fetch_all, fetch_one
from ..rbac import apply_company_filter, filter_sensitive_fields


def _add_months(source_date, months):
    """Add months to a date, handling year/month overflow."""
    month = source_date.month - 1 + months
    year = source_date.year + month // 12
    month = month % 12 + 1
    # Handle day overflow (e.g., Jan 31 + 1 month = Feb 28)
    max_day = calendar.monthrange(year, month)[1]
    day = min(source_date.day, max_day)
    return date(year, month, day)


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

    @mcp.tool()
    def get_document_verification_status(employee_name: str = None, company_name: str = None) -> dict:
        """
        Get document verification status for an employee.
        If employee_name is not provided, returns your own verification status.
        Use company_name to filter by specific company.
        """
        ctx = get_user_context()
        if not ctx:
            return {"error": "Not authenticated. Please login first."}

        emp_id, emp_name, comp_name, branch_name, error = _resolve_employee(ctx, employee_name, company_name)
        if error:
            return error if isinstance(error, dict) else {"error": error}

        # Get user_id from company_employee
        query = """
            SELECT ce.user_id, ce.employee_name, ce.pan_number, ce.aadhar_card_number, ce.uan_number,
                   u.is_document_verified, u.is_pan_verified, u.is_aadhaar_card_verified,
                   u.is_uan_number_verified, u.is_face_match_verified, u.is_certificate_verified,
                   u.is_email_verified
            FROM company_employee ce
            LEFT JOIN users u ON u.id = ce.user_id
            WHERE ce.id = $1
        """
        row = fetch_one(query, [emp_id])

        if not row:
            return {"error": "Employee not found"}

        return {
            "employee_name": emp_name,
            "company_name": comp_name,
            "branch_name": branch_name,
            "documents": {
                "pan_number": row.get("pan_number") or None,
                "aadhar_number": row.get("aadhar_card_number") or None,
                "uan_number": row.get("uan_number") or None
            },
            "verification_status": {
                "overall": row.get("is_document_verified"),
                "pan_verified": bool(row.get("is_pan_verified")),
                "aadhaar_verified": bool(row.get("is_aadhaar_card_verified")),
                "uan_verified": bool(row.get("is_uan_number_verified")),
                "face_match_verified": bool(row.get("is_face_match_verified")),
                "certificate_verified": bool(row.get("is_certificate_verified")),
                "email_verified": bool(row.get("is_email_verified"))
            }
        }

    @mcp.tool()
    def get_employees(company_name: str = None, branch_name: str = None) -> dict:
        """
        Get list of employees for a company/branch.
        If branch_name is not provided, returns all employees for the company.
        Defaults to your primary company if no filters provided.
        """
        ctx = get_user_context()
        if not ctx:
            return {"error": "Not authenticated. Please login first."}

        query = """
            SELECT ce.employee_name, cb.name as branch_name
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
        elif ctx.company_id:
            # Default to user's company
            query += f" AND ce.company_id = ${param_idx}"
            params.append(ctx.company_id)
            param_idx += 1

        if branch_name:
            query += f" AND LOWER(cb.name) LIKE LOWER(${param_idx})"
            params.append(f"%{branch_name}%")
            param_idx += 1

        query = apply_company_filter(ctx, query, "ce")
        query += " ORDER BY cb.name, ce.employee_name"
        rows = fetch_all(query, params) if params else fetch_all(query)

        # Group employees by branch
        branches = {}
        for row in rows:
            branch = row.get("branch_name") or "Unknown"
            if branch not in branches:
                branches[branch] = []
            branches[branch].append(row["employee_name"])

        result = {"count": len(rows), "branches": branches}
        if company_name:
            result["company_filter"] = company_name
        if branch_name:
            result["branch_filter"] = branch_name

        return result

    @mcp.tool()
    def search_company(query: str) -> dict:
        """
        Search for companies by name.
        Returns company details including branches count.
        """
        ctx = get_user_context()
        if not ctx:
            return {"error": "Not authenticated. Please login first."}

        # Simple query first
        sql = "SELECT id, name as company_name FROM company WHERE status = 1 AND LOWER(name) LIKE LOWER($1) ORDER BY name LIMIT 20"
        rows = fetch_all(sql, [f"%{query}%"])

        # Get counts for each company
        for row in rows:
            branch_sql = "SELECT COUNT(*) as count FROM company_branch WHERE company_id = $1 AND status = 1"
            emp_sql = "SELECT COUNT(*) as count FROM company_employee WHERE company_id = $1 AND is_deleted = '0' AND employee_status = 3"
            branch_count = fetch_one(branch_sql, [row["id"]])
            emp_count = fetch_one(emp_sql, [row["id"]])
            row["branch_count"] = branch_count["count"] if branch_count else 0
            row["employee_count"] = emp_count["count"] if emp_count else 0

        return {"count": len(rows), "companies": rows}

    @mcp.tool()
    def get_employees_in_probation(company_name: str = None, branch_name: str = None, include_overdue: bool = True) -> dict:
        """
        Get employees who are currently in probation period.
        Shows probation end date and flags overdue probations.
        Use company_name and/or branch_name to filter.
        Set include_overdue=False to exclude employees whose probation has ended but flag not updated.
        """
        ctx = get_user_context()
        if not ctx:
            return {"error": "Not authenticated. Please login first."}

        query = """
            SELECT ce.employee_name, ce.designation, ce.date_of_joining,
                   ce.probation_period, c.name as company_name, cb.name as branch_name,
                   cd.name as department_name
            FROM company_employee ce
            JOIN company c ON c.id = ce.company_id
            LEFT JOIN company_branch cb ON cb.id = ce.company_branch_id
            LEFT JOIN company_department cd ON cd.id = ce.company_role_id
            WHERE ce.is_deleted = '0'
              AND ce.employee_status = 3
              AND ce.is_probation_period_running = '1'
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
        query += " ORDER BY ce.date_of_joining DESC"

        rows = fetch_all(query, params) if params else fetch_all(query)

        today = datetime.now().date()
        employees = []
        overdue_count = 0
        ending_soon_count = 0  # Within 30 days

        for row in rows:
            doj_raw = row.get("date_of_joining")
            probation_months = row.get("probation_period") or 0

            # Parse DOJ
            doj_date = None
            if doj_raw:
                if isinstance(doj_raw, str):
                    doj_date = datetime.strptime(doj_raw.split('T')[0], "%Y-%m-%d").date()
                elif hasattr(doj_raw, 'date'):
                    doj_date = doj_raw.date() if callable(getattr(doj_raw, 'date', None)) else doj_raw
                elif hasattr(doj_raw, 'year'):
                    doj_date = date(doj_raw.year, doj_raw.month, doj_raw.day)

            # Calculate probation end date
            probation_end = None
            is_overdue = False
            days_remaining = None

            if doj_date and probation_months > 0:
                probation_end = _add_months(doj_date, probation_months)
                if probation_end < today:
                    is_overdue = True
                    overdue_count += 1
                    days_remaining = (probation_end - today).days  # Negative
                else:
                    days_remaining = (probation_end - today).days
                    if days_remaining <= 30:
                        ending_soon_count += 1

            # Skip overdue if not included
            if is_overdue and not include_overdue:
                continue

            emp_data = {
                "employee_name": row.get("employee_name"),
                "designation": row.get("designation"),
                "department": row.get("department_name"),
                "company_name": row.get("company_name"),
                "branch_name": row.get("branch_name"),
                "date_of_joining": str(doj_date) if doj_date else None,
                "probation_months": probation_months,
                "probation_end_date": str(probation_end) if probation_end else None,
                "days_remaining": days_remaining,
                "is_overdue": is_overdue
            }
            employees.append(emp_data)

        # Sort: overdue first, then by days remaining
        employees.sort(key=lambda x: (not x["is_overdue"], x["days_remaining"] if x["days_remaining"] is not None else 9999))

        result = {
            "total_in_probation": len(employees),
            "overdue_count": overdue_count,
            "ending_within_30_days": ending_soon_count,
            "employees": employees
        }

        if company_name:
            result["company_filter"] = company_name
        if branch_name:
            result["branch_filter"] = branch_name

        return result
