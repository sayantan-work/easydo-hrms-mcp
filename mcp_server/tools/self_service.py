"""Self-service tools for employees - MCP server."""
from datetime import datetime
from ..auth import get_user_context
from ..db import fetch_all, fetch_one
from ..rbac import apply_company_filter


def register(mcp):
    """Register self-service tools with MCP server."""

    @mcp.tool()
    def get_my_documents(employee_name: str = None, company_name: str = None, employee_id: int = None) -> dict:
        """
        Get list of documents for an employee.
        If employee_name is not provided, returns your own documents.
        Use company_name to filter by specific company.
        """
        ctx = get_user_context()
        if not ctx:
            return {"error": "Not authenticated. Please login first."}

        if employee_id:
            emp_query = """
                SELECT ce.id, ce.user_id, ce.employee_name, ce.designation, c.name as company_name, cb.name as branch_name
                FROM company_employee ce
                JOIN company c ON c.id = ce.company_id
                LEFT JOIN company_branch cb ON cb.id = ce.company_branch_id
                WHERE ce.id = $1 AND ce.is_deleted = '0'
            """
            emp_query = apply_company_filter(ctx, emp_query, "ce")
            emp_rows = fetch_all(emp_query, [employee_id])

            if not emp_rows:
                return {"error": f"Employee ID {employee_id} not found or not accessible"}

            target_user_id = emp_rows[0]["user_id"]
            target_name = emp_rows[0]["employee_name"]
            target_company = emp_rows[0]["company_name"]

        elif employee_name:
            emp_query = """
                SELECT ce.id, ce.user_id, ce.employee_name, ce.designation, c.name as company_name, cb.name as branch_name
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
                return {"error": f"Employee '{employee_name}' not found"}
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

            target_user_id = emp_rows[0]["user_id"]
            target_name = emp_rows[0]["employee_name"]
            target_company = emp_rows[0]["company_name"]
        else:
            target_user_id = ctx.user_id
            target_name = ctx.user_name
            target_company = ctx.primary_company.company_name if ctx.primary_company else None

        query = """
            SELECT cd.name, cd.number, cd.value, cd.created_at, cd.updated_at,
                   c.name as company_name, cb.name as branch_name
            FROM company_document cd
            LEFT JOIN company c ON c.id = cd.company_id
            LEFT JOIN company_branch cb ON cb.id = cd.company_branch_id
            WHERE cd.user_id = $1
            ORDER BY cd.created_at DESC
        """
        rows = fetch_all(query, [target_user_id])

        return {
            "employee_name": target_name,
            "company": target_company,
            "document_count": len(rows),
            "documents": [
                {
                    "name": r.get("name"),
                    "number": r.get("number"),
                    "value": r.get("value"),
                    "company": r.get("company_name"),
                    "branch": r.get("branch_name"),
                    "created_at": str(r.get("created_at")) if r.get("created_at") else None
                }
                for r in rows
            ]
        }

    @mcp.tool()
    def get_my_manager(employee_name: str = None, company_name: str = None, employee_id: int = None) -> dict:
        """
        Get reporting manager details for an employee.
        If employee_name is not provided, returns your own manager.
        Use company_name to filter by specific company.
        """
        ctx = get_user_context()
        if not ctx:
            return {"error": "Not authenticated. Please login first."}

        if employee_id:
            emp_query = """
                SELECT ce.id, ce.employee_name, ce.designation, ce.reporting_manager_id,
                       c.name as company_name, cb.name as branch_name
                FROM company_employee ce
                JOIN company c ON c.id = ce.company_id
                LEFT JOIN company_branch cb ON cb.id = ce.company_branch_id
                WHERE ce.id = $1 AND ce.is_deleted = '0'
            """
            emp_query = apply_company_filter(ctx, emp_query, "ce")
            emp_rows = fetch_all(emp_query, [employee_id])

            if not emp_rows:
                return {"error": f"Employee ID {employee_id} not found or not accessible"}

            target_emp = emp_rows[0]

        elif employee_name:
            emp_query = """
                SELECT ce.id, ce.employee_name, ce.designation, ce.reporting_manager_id,
                       c.name as company_name, cb.name as branch_name
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
                return {"error": f"Employee '{employee_name}' not found"}
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

            target_emp = emp_rows[0]
        else:
            pc = ctx.primary_company
            if not pc:
                return {"error": "No company association found."}

            emp_query = """
                SELECT ce.id, ce.employee_name, ce.reporting_manager_id,
                       c.name as company_name, cb.name as branch_name
                FROM company_employee ce
                JOIN company c ON c.id = ce.company_id
                LEFT JOIN company_branch cb ON cb.id = ce.company_branch_id
                WHERE ce.id = $1
            """
            target_emp = fetch_one(emp_query, [pc.company_employee_id])

        if not target_emp:
            return {"error": "Employee record not found."}

        manager_id = target_emp.get("reporting_manager_id")
        if not manager_id or manager_id == 0:
            return {
                "employee_name": target_emp.get("employee_name"),
                "company": target_emp.get("company_name"),
                "branch": target_emp.get("branch_name"),
                "manager": None,
                "_note": "No reporting manager assigned"
            }

        manager_query = """
            SELECT ce.employee_name, ce.designation, ce.employee_mobile, ce.employee_email,
                   c.name as company_name, cb.name as branch_name, cd.name as department
            FROM company_employee ce
            JOIN company c ON c.id = ce.company_id
            LEFT JOIN company_branch cb ON cb.id = ce.company_branch_id
            LEFT JOIN company_department cd ON cd.id = ce.company_role_id
            WHERE ce.id = $1 AND ce.is_deleted = '0'
        """
        manager = fetch_one(manager_query, [manager_id])

        if not manager:
            return {
                "employee_name": target_emp.get("employee_name"),
                "company": target_emp.get("company_name"),
                "manager": None,
                "_note": "Reporting manager record not found"
            }

        return {
            "employee_name": target_emp.get("employee_name"),
            "company": target_emp.get("company_name"),
            "branch": target_emp.get("branch_name"),
            "manager": {
                "name": manager.get("employee_name"),
                "designation": manager.get("designation"),
                "department": manager.get("department"),
                "phone": manager.get("employee_mobile"),
                "email": manager.get("employee_email"),
                "branch": manager.get("branch_name")
            }
        }

    @mcp.tool()
    def get_org_chart(company_name: str = None, branch_name: str = None, max_depth: int = 5) -> dict:
        """
        Get organization hierarchy chart.
        Shows reporting structure from top-level managers down.
        Use company_name and/or branch_name to filter.
        max_depth limits how deep the hierarchy goes (default: 5).
        """
        ctx = get_user_context()
        if not ctx:
            return {"error": "Not authenticated. Please login first."}

        if ctx.primary_company and ctx.primary_company.role_id not in [1, 2] and not ctx.is_super_admin:
            return {"error": "Access denied. This tool is for Company Admins and Branch Managers only."}

        query = """
            SELECT ce.id, ce.employee_name, ce.designation, ce.reporting_manager_id,
                   c.name as company_name, cb.name as branch_name, cd.name as department
            FROM company_employee ce
            JOIN company c ON c.id = ce.company_id
            LEFT JOIN company_branch cb ON cb.id = ce.company_branch_id
            LEFT JOIN company_department cd ON cd.id = ce.company_role_id
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
        query += " ORDER BY ce.employee_name"

        rows = fetch_all(query, params)

        if not rows:
            return {"error": "No employees found"}

        employees_by_id = {}
        for r in rows:
            emp_id = int(r["id"]) if r["id"] else None
            mgr_id = int(r["reporting_manager_id"]) if r.get("reporting_manager_id") else None
            employees_by_id[emp_id] = {
                "id": emp_id,
                "name": r["employee_name"],
                "designation": r["designation"],
                "department": r.get("department"),
                "branch": r.get("branch_name"),
                "company": r.get("company_name"),
                "manager_id": mgr_id,
                "reports": []
            }

        def find_cycle_members(start_id):
            visited = []
            current = start_id
            while current and current in employees_by_id:
                if current in visited:
                    cycle_start_idx = visited.index(current)
                    return set(visited[cycle_start_idx:])
                visited.append(current)
                current = employees_by_id[current]["manager_id"]
            return set()

        all_cycle_members = set()
        for emp_id in employees_by_id:
            cycle = find_cycle_members(emp_id)
            all_cycle_members.update(cycle)

        top_level_ids = set()
        for emp_id, emp in employees_by_id.items():
            manager_id = emp["manager_id"]
            if not manager_id or manager_id not in employees_by_id:
                top_level_ids.add(emp_id)
            elif emp_id in all_cycle_members:
                top_level_ids.add(emp_id)

        for emp_id, emp in employees_by_id.items():
            manager_id = emp["manager_id"]
            if manager_id and manager_id in employees_by_id:
                if emp_id not in all_cycle_members:
                    employees_by_id[manager_id]["reports"].append(emp)

        top_level = []
        for emp_id in top_level_ids:
            if emp_id in employees_by_id:
                top_level.append(employees_by_id[emp_id])

        top_level.sort(key=lambda x: (x.get("branch") or "", x.get("name") or ""))

        def count_reports(emp):
            count = len(emp.get("reports", []))
            for r in emp.get("reports", []):
                count += count_reports(r)
            return count

        def build_tree(emp, depth=0):
            emp["reports"].sort(key=lambda x: x.get("name", ""))

            if depth >= max_depth and emp["reports"]:
                total = count_reports(emp)
                emp["reports"] = f"[{total} more employees...]"
                return emp

            for report in emp.get("reports", []):
                if isinstance(report, dict):
                    build_tree(report, depth + 1)
            return emp

        for emp in top_level:
            build_tree(emp)

        def clean_for_output(emp, depth=0):
            indent = "  " * depth
            result = {
                "name": emp["name"],
                "designation": emp["designation"],
                "department": emp.get("department"),
                "branch": emp.get("branch"),
                "direct_reports": len(emp["reports"]) if isinstance(emp["reports"], list) else emp["reports"]
            }
            if emp.get("reports") and isinstance(emp["reports"], list) and len(emp["reports"]) > 0:
                result["reports"] = [clean_for_output(r, depth + 1) for r in emp["reports"]]
            elif isinstance(emp.get("reports"), str):
                result["reports"] = emp["reports"]
            return result

        return {
            "total_employees": len(rows),
            "top_level_count": len(top_level),
            "hierarchy": [clean_for_output(emp) for emp in top_level],
            "_note": f"Full org chart from top to bottom. Depth limited to {max_depth} levels."
        }

    @mcp.tool()
    def get_my_payslips(employee_name: str = None, year: int = None, company_name: str = None, employee_id: int = None) -> dict:
        """
        Get list of all salary slips for an employee.
        If employee_name is not provided, returns your own payslips.
        Year defaults to current year.
        """
        ctx = get_user_context()
        if not ctx:
            return {"error": "Not authenticated. Please login first."}

        if not year:
            year = datetime.now().year

        if employee_id:
            emp_query = """
                SELECT ce.id, ce.employee_name, ce.designation, c.name as company_name, cb.name as branch_name
                FROM company_employee ce
                JOIN company c ON c.id = ce.company_id
                LEFT JOIN company_branch cb ON cb.id = ce.company_branch_id
                WHERE ce.id = $1 AND ce.is_deleted = '0'
            """
            emp_query = apply_company_filter(ctx, emp_query, "ce")
            emp_rows = fetch_all(emp_query, [employee_id])

            if not emp_rows:
                return {"error": f"Employee ID {employee_id} not found or not accessible"}

            target_emp_id = emp_rows[0]["id"]
            target_name = emp_rows[0]["employee_name"]
            target_company = emp_rows[0]["company_name"]

        elif employee_name:
            emp_query = """
                SELECT ce.id, ce.employee_name, ce.designation, c.name as company_name, cb.name as branch_name
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
                return {"error": f"Employee '{employee_name}' not found"}
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
            SELECT id, from_date, to_date, date,
                   basic_salary, total_allowance, total_deduction,
                   gross_amount, net_pay_amount, net_pay_amount_in_words,
                   present, absent, half_day, late_day, holiday,
                   file_url, status, generated_at
            FROM company_employee_salary_slip
            WHERE company_employee_id = $1
              AND EXTRACT(YEAR FROM date) = $2
            ORDER BY date DESC
        """
        rows = fetch_all(query, [target_emp_id, year])

        payslips = []
        for r in rows:
            date_val = r.get("date")
            if date_val:
                if hasattr(date_val, 'strftime'):
                    month_str = date_val.strftime("%B %Y")
                else:
                    month_str = str(date_val)[:7]
            else:
                month_str = "Unknown"

            payslips.append({
                "id": r.get("id"),
                "month": month_str,
                "from_date": str(r.get("from_date")) if r.get("from_date") else None,
                "to_date": str(r.get("to_date")) if r.get("to_date") else None,
                "basic_salary": r.get("basic_salary"),
                "total_allowance": r.get("total_allowance"),
                "total_deduction": r.get("total_deduction"),
                "gross_amount": r.get("gross_amount"),
                "net_pay": r.get("net_pay_amount"),
                "present_days": r.get("present"),
                "absent_days": r.get("absent"),
                "late_days": r.get("late_day"),
                "file_url": r.get("file_url"),
                "generated_at": str(r.get("generated_at")) if r.get("generated_at") else None
            })

        return {
            "employee_name": target_name,
            "company": target_company,
            "year": year,
            "payslip_count": len(payslips),
            "payslips": payslips
        }

    @mcp.tool()
    def get_my_team_calendar(month: str = None, employee_name: str = None) -> dict:
        """
        Get team's leave and attendance calendar for a month.
        Shows who is present, absent, on leave, or on holiday for each day.
        Month format: YYYY-MM (defaults to current month).
        If employee_name is provided, shows that person's team. Otherwise shows your team.
        """
        ctx = get_user_context()
        if not ctx:
            return {"error": "Not authenticated. Please login first."}

        if not month:
            month = datetime.now().strftime("%Y-%m")

        if employee_name:
            emp_query = """
                SELECT ce.id, ce.employee_name, c.name as company_name
                FROM company_employee ce
                JOIN company c ON c.id = ce.company_id
                WHERE LOWER(ce.employee_name) LIKE LOWER($1) AND ce.is_deleted = '0'
            """
            emp_query = apply_company_filter(ctx, emp_query, "ce")
            emp_rows = fetch_all(emp_query, [f"%{employee_name}%"])

            if not emp_rows:
                return {"error": f"Employee '{employee_name}' not found"}
            if len(emp_rows) > 1:
                return {
                    "error": "Multiple employees found.",
                    "matches": [{"name": r["employee_name"], "company": r["company_name"]} for r in emp_rows]
                }
            manager_id = emp_rows[0]["id"]
            manager_name = emp_rows[0]["employee_name"]
        else:
            pc = ctx.primary_company
            if not pc:
                return {"error": "No company association found."}
            manager_id = pc.company_employee_id
            manager_name = ctx.user_name

        team_query = """
            SELECT ce.id, ce.employee_name, ce.designation, cb.name as branch_name
            FROM company_employee ce
            LEFT JOIN company_branch cb ON cb.id = ce.company_branch_id
            WHERE ce.reporting_manager_id = $1 AND ce.is_deleted = '0' AND ce.employee_status = 3
            ORDER BY ce.employee_name
        """
        team_members = fetch_all(team_query, [manager_id])

        if not team_members:
            return {
                "manager": manager_name,
                "month": month,
                "team_count": 0,
                "team_calendar": [],
                "_note": "No direct reports found"
            }

        team_ids = [m["id"] for m in team_members]
        team_ids_str = ",".join(str(i) for i in team_ids)

        attendance_query = f"""
            SELECT ca.company_employee_id, ca.date, ca.is_late, ca.is_half_day
            FROM company_attendance ca
            WHERE ca.company_employee_id IN ({team_ids_str})
              AND TO_CHAR(ca.date, 'YYYY-MM') = $1
        """
        attendance_rows = fetch_all(attendance_query, [month])

        attendance_map = {}
        for r in attendance_rows:
            emp_id = r["company_employee_id"]
            date_val = r["date"]
            if hasattr(date_val, 'day'):
                day = date_val.day
            else:
                day = int(str(date_val).split('-')[2].split('T')[0])

            if emp_id not in attendance_map:
                attendance_map[emp_id] = {}
            status = "P"
            if r.get("is_half_day") == 1:
                status = "H"
            elif r.get("is_late") == 1:
                status = "L"
            attendance_map[emp_id][day] = status

        leave_query = f"""
            SELECT cap.company_employee_id, cap.start_date, cap.end_date
            FROM company_approval cap
            WHERE cap.company_employee_id IN ({team_ids_str})
              AND cap.media_type = 'leave'
              AND cap.status = 'approved'
              AND (
                  TO_CHAR(cap.start_date, 'YYYY-MM') = $1
                  OR TO_CHAR(cap.end_date, 'YYYY-MM') = $1
              )
        """
        leave_rows = fetch_all(leave_query, [month])

        leave_map = {}
        year_val, month_val = map(int, month.split('-'))
        for r in leave_rows:
            emp_id = r["company_employee_id"]
            start = r["start_date"]
            end = r["end_date"]

            if hasattr(start, 'day'):
                start_day = start.day if start.month == month_val and start.year == year_val else 1
                end_day = end.day if end.month == month_val and end.year == year_val else 31
            else:
                start_day = 1
                end_day = 31

            if emp_id not in leave_map:
                leave_map[emp_id] = set()
            for d in range(start_day, end_day + 1):
                leave_map[emp_id].add(d)

        import calendar
        _, days_in_month = calendar.monthrange(year_val, month_val)

        team_calendar = []
        for member in team_members:
            emp_id = member["id"]
            days = {}
            for day in range(1, days_in_month + 1):
                if emp_id in leave_map and day in leave_map[emp_id]:
                    days[day] = "LV"
                elif emp_id in attendance_map and day in attendance_map[emp_id]:
                    days[day] = attendance_map[emp_id][day]
                else:
                    days[day] = "-"

            team_calendar.append({
                "name": member["employee_name"],
                "designation": member["designation"],
                "branch": member.get("branch_name"),
                "days": days
            })

        return {
            "manager": manager_name,
            "month": month,
            "days_in_month": days_in_month,
            "team_count": len(team_members),
            "legend": {
                "P": "Present",
                "L": "Late",
                "H": "Half Day",
                "LV": "Leave",
                "-": "Absent/No Data"
            },
            "team_calendar": team_calendar
        }
