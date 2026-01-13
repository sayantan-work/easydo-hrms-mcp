"""Attendance tools for MCP server."""
from datetime import datetime
from ..auth import get_user_context
from ..db import fetch_all, fetch_one
from ..rbac import apply_company_filter


def register(mcp):
    """Register attendance tools with MCP server."""

    @mcp.tool()
    def get_attendance(employee_name: str = None, month: str = None, company_name: str = None) -> dict:
        """
        Get monthly attendance summary.
        If employee_name is not provided, returns your own attendance.
        Month format: YYYY-MM (defaults to current month).
        """
        ctx = get_user_context()
        if not ctx:
            return {"error": "Not authenticated. Please login first."}

        if not month:
            month = datetime.now().strftime("%Y-%m")

        if employee_name:
            # Search for the employee
            emp_query = """
                SELECT ce.id, ce.employee_name, c.name as company_name, cb.name as branch_name
                FROM company_employee ce
                JOIN company c ON c.id = ce.company_id
                LEFT JOIN company_branch cb ON cb.id = ce.company_branch_id
                WHERE LOWER(ce.employee_name) LIKE LOWER($1) AND ce.is_deleted = '0'
            """
            params = [f"%{employee_name}%"]

            if company_name:
                emp_query += " AND LOWER(c.name) LIKE LOWER($2)"
                params.append(f"%{company_name}%")

            emp_query = apply_company_filter(ctx, emp_query, "ce")
            emp_rows = fetch_all(emp_query, params)

            if not emp_rows:
                return {"error": f"Employee '{employee_name}' not found or not accessible"}
            if len(emp_rows) > 1 and not company_name:
                return {
                    "error": "Multiple employees found. Please specify company_name.",
                    "matches": [{"name": r["employee_name"], "company": r["company_name"]} for r in emp_rows]
                }

            target_emp_id = emp_rows[0]["id"]
            target_name = emp_rows[0]["employee_name"]
            target_company = emp_rows[0]["company_name"]
            target_branch = emp_rows[0]["branch_name"]
        else:
            # Default to self
            pc = ctx.primary_company
            if not pc:
                return {"error": "No company association found."}
            target_emp_id = pc.company_employee_id
            target_name = ctx.user_name
            target_company = pc.company_name
            target_branch = pc.branch_name

        query = """
            SELECT cam.month, cam.working_day, cam.present_day, cam.absent_day,
                   cam.late_day, cam.half_day, cam.leave_day, cam.holiday,
                   cam.weekoff_day, cam.total_hours
            FROM company_attendance_master cam
            WHERE cam.company_employee_id = $1 AND TO_CHAR(cam.month, 'YYYY-MM') = $2
        """
        row = fetch_one(query, [target_emp_id, month])

        if not row:
            return {"error": f"No attendance data found for {month}"}

        # Calculate attendance percentage
        working = float(row.get("working_day") or 0)
        present = float(row.get("present_day") or 0)
        attendance_pct = round((present / working * 100), 1) if working > 0 else 0

        return {
            "employee_name": target_name,
            "month": month,
            "company_name": target_company,
            "branch_name": target_branch,
            "summary": {
                "working_days": row.get("working_day"),
                "present_days": row.get("present_day"),
                "absent_days": row.get("absent_day"),
                "late_days": row.get("late_day"),
                "half_days": row.get("half_day"),
                "leave_days": row.get("leave_day"),
                "holidays": row.get("holiday"),
                "week_offs": row.get("weekoff_day"),
                "total_hours_worked": row.get("total_hours"),
                "attendance_percentage": attendance_pct
            },
            "_note": "Attendance percentage = (present_days / working_days) * 100"
        }

    @mcp.tool()
    def who_is_late_today(company_name: str = None, branch_name: str = None) -> dict:
        """
        Get employees who were late today.
        Also includes employees who took half-day in a separate list.
        Use company_name and/or branch_name to filter.
        """
        ctx = get_user_context()
        if not ctx:
            return {"error": "Not authenticated. Please login first."}

        today = datetime.now().strftime("%Y-%m-%d")

        # Base query for late employees
        late_query = """
            SELECT ce.employee_name, ce.designation, cd.name as department_name,
                   cb.name as branch_name, c.name as company_name,
                   TO_TIMESTAMP(ca.check_in_time / 1000) as check_in_time
            FROM company_attendance ca
            JOIN company_employee ce ON ce.id = ca.company_employee_id
            JOIN company c ON c.id = ce.company_id
            LEFT JOIN company_branch cb ON cb.id = ce.company_branch_id
            LEFT JOIN company_department cd ON cd.id = ce.company_role_id
            WHERE ce.is_deleted = '0' AND ca.date = $1 AND ca.is_late = 1
        """

        # Base query for half-day employees
        half_day_query = """
            SELECT ce.employee_name, ce.designation, cd.name as department_name,
                   cb.name as branch_name, c.name as company_name,
                   TO_TIMESTAMP(ca.check_in_time / 1000) as check_in_time,
                   TO_TIMESTAMP(ca.check_out_time / 1000) as check_out_time
            FROM company_attendance ca
            JOIN company_employee ce ON ce.id = ca.company_employee_id
            JOIN company c ON c.id = ce.company_id
            LEFT JOIN company_branch cb ON cb.id = ce.company_branch_id
            LEFT JOIN company_department cd ON cd.id = ce.company_role_id
            WHERE ce.is_deleted = '0' AND ca.date = $1 AND ca.is_half_day = 1
        """

        params = [today]
        param_idx = 2

        if company_name:
            late_query += f" AND LOWER(c.name) LIKE LOWER(${param_idx})"
            half_day_query += f" AND LOWER(c.name) LIKE LOWER(${param_idx})"
            params.append(f"%{company_name}%")
            param_idx += 1

        if branch_name:
            late_query += f" AND LOWER(cb.name) LIKE LOWER(${param_idx})"
            half_day_query += f" AND LOWER(cb.name) LIKE LOWER(${param_idx})"
            params.append(f"%{branch_name}%")
            param_idx += 1

        late_query = apply_company_filter(ctx, late_query, "ce")
        late_query += " ORDER BY ca.check_in_time DESC"

        half_day_query = apply_company_filter(ctx, half_day_query, "ce")
        half_day_query += " ORDER BY ca.check_in_time DESC"

        late_rows = fetch_all(late_query, params)
        half_day_rows = fetch_all(half_day_query, params)

        result = {
            "date": today,
            "late_count": len(late_rows),
            "half_day_count": len(half_day_rows),
            "late_employees": late_rows,
            "half_day_employees": half_day_rows
        }
        if company_name:
            result["company_filter"] = company_name
        if branch_name:
            result["branch_filter"] = branch_name

        return result

    @mcp.tool()
    def get_present_employees(date: str = None, company_name: str = None, branch_name: str = None) -> dict:
        """
        Get employees who are present (checked in) on a specific date.
        Date format: YYYY-MM-DD (defaults to today).
        Use company_name and/or branch_name to filter.
        """
        ctx = get_user_context()
        if not ctx:
            return {"error": "Not authenticated. Please login first."}

        if not date:
            date = datetime.now().strftime("%Y-%m-%d")

        query = """
            SELECT ce.employee_name, ce.designation, cd.name as department_name,
                   cb.name as branch_name, c.name as company_name,
                   TO_TIMESTAMP(ca.check_in_time / 1000) as check_in_time,
                   TO_TIMESTAMP(ca.check_out_time / 1000) as check_out_time,
                   ca.is_late, ca.is_half_day
            FROM company_attendance ca
            JOIN company_employee ce ON ce.id = ca.company_employee_id
            JOIN company c ON c.id = ce.company_id
            LEFT JOIN company_branch cb ON cb.id = ce.company_branch_id
            LEFT JOIN company_department cd ON cd.id = ce.company_role_id
            WHERE ce.is_deleted = '0' AND ca.date = $1
        """
        params = [date]
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
        query += " ORDER BY ca.check_in_time DESC"

        rows = fetch_all(query, params)

        result = {
            "date": date,
            "count": len(rows),
            "present_employees": [
                {
                    "employee_name": r.get("employee_name"),
                    "designation": r.get("designation"),
                    "department": r.get("department_name"),
                    "branch": r.get("branch_name"),
                    "company": r.get("company_name"),
                    "check_in_time": str(r.get("check_in_time")) if r.get("check_in_time") else None,
                    "check_out_time": str(r.get("check_out_time")) if r.get("check_out_time") else None,
                    "is_late": r.get("is_late") == 1,
                    "is_half_day": r.get("is_half_day") == 1
                }
                for r in rows
            ]
        }

        if company_name:
            result["company_filter"] = company_name
        if branch_name:
            result["branch_filter"] = branch_name

        return result

    @mcp.tool()
    def get_absent_employees(date: str = None, company_name: str = None, branch_name: str = None) -> dict:
        """
        Get employees who were absent on a specific date.
        Date format: YYYY-MM-DD (defaults to today).
        Excludes employees on approved leave.
        """
        ctx = get_user_context()
        if not ctx:
            return {"error": "Not authenticated. Please login first."}

        if not date:
            date = datetime.now().strftime("%Y-%m-%d")

        query = """
            SELECT ce.employee_name, ce.designation, cd.name as department_name,
                   cb.name as branch_name, c.name as company_name
            FROM company_employee ce
            LEFT JOIN company_department cd ON cd.id = ce.company_role_id
            LEFT JOIN company_branch cb ON cb.id = ce.company_branch_id
            LEFT JOIN company c ON c.id = ce.company_id
            WHERE ce.is_deleted = '0' AND ce.employee_status = 3
              AND ce.id NOT IN (
                  SELECT ca.company_employee_id
                  FROM company_attendance ca
                  WHERE ca.date = $1
              )
              AND ce.id NOT IN (
                  SELECT cap.company_employee_id
                  FROM company_approval cap
                  WHERE cap.media_type = 'leave'
                    AND cap.status = 'approved'
                    AND $1 BETWEEN cap.start_date AND cap.end_date
              )
        """
        params = [date]
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
        query += " ORDER BY ce.employee_name"

        rows = fetch_all(query, params)

        result = {
            "date": date,
            "count": len(rows),
            "absent_employees": [
                {
                    "employee_name": r.get("employee_name"),
                    "designation": r.get("designation"),
                    "department": r.get("department_name"),
                    "branch": r.get("branch_name"),
                    "company": r.get("company_name")
                }
                for r in rows
            ],
            "_note": "Excludes employees on approved leave"
        }

        if company_name:
            result["company_filter"] = company_name
        if branch_name:
            result["branch_filter"] = branch_name

        return result
