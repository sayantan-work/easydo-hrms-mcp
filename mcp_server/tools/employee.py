"""Employee tools for MCP server."""
import calendar
from datetime import datetime, date

from ..auth import get_user_context
from ..db import fetch_all, fetch_one
from ..rbac import apply_company_filter, filter_sensitive_fields


# SQL query fragments
EMPLOYEE_BASE_SELECT = """
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
"""

EMPLOYEE_SELF_SELECT = """
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


def _require_auth():
    """Get user context or return error dict."""
    ctx = get_user_context()
    if not ctx:
        return None, {"error": "Not authenticated. Please login first."}
    return ctx, None


def _add_months(source_date, months):
    """Add months to a date, handling year/month overflow."""
    month = source_date.month - 1 + months
    year = source_date.year + month // 12
    month = month % 12 + 1
    max_day = calendar.monthrange(year, month)[1]
    day = min(source_date.day, max_day)
    return date(year, month, day)


def _parse_date(date_raw):
    """Parse various date formats to date object."""
    if not date_raw:
        return None
    if isinstance(date_raw, str):
        return datetime.strptime(date_raw.split('T')[0], "%Y-%m-%d").date()
    if hasattr(date_raw, 'date') and callable(date_raw.date):
        return date_raw.date()
    if hasattr(date_raw, 'year'):
        return date(date_raw.year, date_raw.month, date_raw.day)
    return None


def _resolve_employee(ctx, employee_name: str = None, company_name: str = None):
    """
    Resolve employee by name or default to self.
    Returns (employee_id, employee_name, company_name, branch_name, error).
    """
    if employee_name:
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
        row = rows[0]
        return row["id"], row["employee_name"], row["company_name"], row["branch_name"], None

    # Default to self
    pc = ctx.primary_company
    if not pc:
        return None, None, None, None, "No company association found for your account."
    return pc.company_employee_id, ctx.user_name, pc.company_name, pc.branch_name, None


def _build_filtered_query(base_query: str, ctx, params: list, param_idx: int,
                          company_name: str = None, branch_name: str = None,
                          table_alias: str = "ce"):
    """Build query with company/branch filters and RBAC. Returns (query, params)."""
    if company_name:
        base_query += f" AND LOWER(c.name) LIKE LOWER(${param_idx})"
        params.append(f"%{company_name}%")
        param_idx += 1

    if branch_name:
        base_query += f" AND LOWER(cb.name) LIKE LOWER(${param_idx})"
        params.append(f"%{branch_name}%")

    return apply_company_filter(ctx, base_query, table_alias), params


def _add_filters_to_result(result: dict, company_name: str = None, branch_name: str = None) -> dict:
    """Add filter info to result dict if filters were applied."""
    if company_name:
        result["company_filter"] = company_name
    if branch_name:
        result["branch_filter"] = branch_name
    return result


def _get_super_admin_profile(ctx):
    """Get profile for super admin or user without company association."""
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


def _search_employee_profile(ctx, employee_name: str, company_name: str = None):
    """Search for employee profile by name."""
    query = EMPLOYEE_BASE_SELECT + """
        WHERE ce.is_deleted = '0' AND LOWER(ce.employee_name) LIKE LOWER($1)
    """
    params = [f"%{employee_name}%"]

    if company_name:
        query += " AND LOWER(c.name) LIKE LOWER($2)"
        params.append(f"%{company_name}%")

    query = apply_company_filter(ctx, query, "ce")
    query += " ORDER BY ce.employee_name LIMIT 10"
    return fetch_all(query, params)


def _calculate_probation_status(doj_date, probation_months, today):
    """Calculate probation end date and status."""
    if not doj_date or probation_months <= 0:
        return None, False, None

    probation_end = _add_months(doj_date, probation_months)
    is_overdue = probation_end < today
    days_remaining = (probation_end - today).days
    return probation_end, is_overdue, days_remaining


def register(mcp):
    """Register employee tools with MCP server."""

    @mcp.tool()
    def get_employee(employee_name: str = None, company_name: str = None) -> dict:
        """
        Get employee profile/details.
        If employee_name is not provided, returns your own profile.
        Use company_name to filter by specific company.
        """
        ctx, err = _require_auth()
        if err:
            return err

        if employee_name:
            rows = _search_employee_profile(ctx, employee_name, company_name)

            if not rows:
                return {"error": f"Employee '{employee_name}' not found or not accessible"}
            if len(rows) > 1 and not company_name:
                return {
                    "error": "Multiple employees found. Please specify company_name.",
                    "matches": [{"employee_name": r["employee_name"], "company_name": r["company_name"]} for r in rows]
                }

            row = rows[0]
            return filter_sensitive_fields(ctx, row, row["id"])

        # Default to self - get own profile
        pc = ctx.primary_company
        if not pc:
            return _get_super_admin_profile(ctx)

        row = fetch_one(EMPLOYEE_SELF_SELECT, [pc.company_employee_id])
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
        ctx, err = _require_auth()
        if err:
            return err

        query = """
            SELECT COUNT(*) as count
            FROM company_employee ce
            LEFT JOIN company c ON c.id = ce.company_id
            LEFT JOIN company_branch cb ON cb.id = ce.company_branch_id
            WHERE ce.is_deleted = '0' AND ce.employee_status = 3
        """
        params = []
        query, params = _build_filtered_query(query, ctx, params, 1, company_name, branch_name)

        row = fetch_one(query, params) if params else fetch_one(query)
        result = {"total_employees": row["count"] if row else 0}
        return _add_filters_to_result(result, company_name, branch_name)

    @mcp.tool()
    def search_employee_directory(query: str) -> dict:
        """
        Search employee directory for public info (name, department, designation).
        Returns basic public information only.
        Supports fuzzy matching for typos.
        """
        ctx, err = _require_auth()
        if err:
            return err

        from ..fuzzy import fuzzy_match

        # First try exact LIKE match
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

        # If no results, try fuzzy matching
        if not rows:
            # Get all employee names for fuzzy matching
            all_sql = """
                SELECT ce.id, ce.employee_name, ce.designation,
                       cd.name as department_name, cb.name as branch_name, c.name as company_name
                FROM company_employee ce
                LEFT JOIN company c ON c.id = ce.company_id
                LEFT JOIN company_branch cb ON cb.id = ce.company_branch_id
                LEFT JOIN company_department cd ON cd.id = ce.company_role_id
                WHERE ce.is_deleted = '0' AND ce.employee_status = 3
            """
            all_sql = apply_company_filter(ctx, all_sql, "ce")
            all_employees = fetch_all(all_sql)

            employee_names = [e["employee_name"] for e in all_employees]
            matches = fuzzy_match(query, employee_names, threshold=60, limit=20)

            if matches:
                matched_names = {m[0] for m in matches}
                rows = [e for e in all_employees if e["employee_name"] in matched_names]

        return {"count": len(rows), "employees": rows}

    @mcp.tool()
    def get_document_verification_status(employee_name: str = None, company_name: str = None) -> dict:
        """
        Get document verification status for an employee.
        If employee_name is not provided, returns your own verification status.
        Use company_name to filter by specific company.
        """
        ctx, err = _require_auth()
        if err:
            return err

        emp_id, emp_name, comp_name, branch_name, error = _resolve_employee(ctx, employee_name, company_name)
        if error:
            return error if isinstance(error, dict) else {"error": error}

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
        ctx, err = _require_auth()
        if err:
            return err

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
            query += f" AND ce.company_id = ${param_idx}"
            params.append(ctx.company_id)
            param_idx += 1

        query, params = _build_filtered_query(query, ctx, params, param_idx, branch_name=branch_name)
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
        return _add_filters_to_result(result, company_name, branch_name)

    @mcp.tool()
    def search_company(query: str) -> dict:
        """
        Search for companies by name.
        Returns company details including branches count.
        Supports fuzzy matching for typos (e.g., "liberty infospce" -> "Liberty Infospace").
        """
        ctx, err = _require_auth()
        if err:
            return err

        from ..fuzzy import fuzzy_match, normalize_company_name, build_fuzzy_sql_pattern

        # First try exact LIKE match
        sql = """
            SELECT id, name as company_name
            FROM company
            WHERE status = 1 AND LOWER(name) LIKE LOWER($1)
            ORDER BY name LIMIT 20
        """
        rows = fetch_all(sql, [f"%{query}%"])

        # If no results, try fuzzy matching
        if not rows:
            # Get all company names for fuzzy matching
            all_companies = fetch_all("SELECT id, name FROM company WHERE status = 1")
            company_names = [c["name"] for c in all_companies]

            # Find fuzzy matches (lower threshold to catch typos like "infspace" -> "infospace")
            matches = fuzzy_match(query, company_names, threshold=40, limit=10)

            if matches:
                # Get IDs for matched companies
                matched_names = [m[0] for m in matches]
                rows = [
                    {"id": c["id"], "company_name": c["name"], "fuzzy_score": score}
                    for c in all_companies
                    for name, score in matches
                    if c["name"] == name
                ]

        for row in rows:
            company_id = row["id"]
            branch_count = fetch_one(
                "SELECT COUNT(*) as count FROM company_branch WHERE company_id = $1 AND status = 1",
                [company_id]
            )
            emp_count = fetch_one(
                "SELECT COUNT(*) as count FROM company_employee WHERE company_id = $1 AND is_deleted = '0' AND employee_status = 3",
                [company_id]
            )
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
        ctx, err = _require_auth()
        if err:
            return err

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
        query, params = _build_filtered_query(query, ctx, params, 1, company_name, branch_name)
        query += " ORDER BY ce.date_of_joining DESC"

        rows = fetch_all(query, params) if params else fetch_all(query)

        today = datetime.now().date()
        employees = []
        overdue_count = 0
        ending_soon_count = 0

        for row in rows:
            doj_date = _parse_date(row.get("date_of_joining"))
            probation_months = row.get("probation_period") or 0

            probation_end, is_overdue, days_remaining = _calculate_probation_status(
                doj_date, probation_months, today
            )

            if is_overdue:
                overdue_count += 1
            elif days_remaining is not None and days_remaining <= 30:
                ending_soon_count += 1

            if is_overdue and not include_overdue:
                continue

            employees.append({
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
            })

        # Sort: overdue first, then by days remaining
        employees.sort(key=lambda x: (not x["is_overdue"], x["days_remaining"] if x["days_remaining"] is not None else 9999))

        result = {
            "total_in_probation": len(employees),
            "overdue_count": overdue_count,
            "ending_within_30_days": ending_soon_count,
            "employees": employees
        }
        return _add_filters_to_result(result, company_name, branch_name)
