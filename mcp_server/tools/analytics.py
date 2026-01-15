"""Company-level analytics tools for MCP server."""
from datetime import datetime
from ..auth import get_user_context
from ..db import fetch_all, fetch_one
from ..rbac import apply_company_filter


def register(mcp):
    """Register company-level analytics tools with MCP server."""

    @mcp.tool()
    def get_salary_expenditure(month: str = None, company_name: str = None, branch_name: str = None, compare: bool = False) -> dict:
        """
        Get total salary expenditure for a month.
        Month format: YYYY-MM (defaults to previous month).
        Use compare=True to include previous month comparison.
        Use company_name and/or branch_name to filter.
        """
        ctx = get_user_context()
        if not ctx:
            return {"error": "Not authenticated. Please login first."}

        if not month:
            now = datetime.now()
            if now.month == 1:
                month = f"{now.year - 1}-12"
            else:
                month = f"{now.year}-{now.month - 1:02d}"

        def get_expenditure_for_month(target_month, for_branch=None):
            query = """
                SELECT
                    COUNT(DISTINCT ss.company_employee_id) as employee_count,
                    SUM(ss.basic_salary) as total_basic,
                    AVG(ss.basic_salary) as avg_basic,
                    SUM(CAST(ss.total_allowance AS DECIMAL)) as total_allowances,
                    AVG(CAST(ss.total_allowance AS DECIMAL)) as avg_allowances,
                    SUM(ss.total_gross_salary) as total_gross,
                    AVG(ss.total_gross_salary) as avg_gross,
                    SUM(CAST(ss.total_deduction AS DECIMAL)) as total_deductions,
                    AVG(CAST(ss.total_deduction AS DECIMAL)) as avg_deductions,
                    SUM(CAST(ss.net_pay_amount AS DECIMAL)) as total_net_pay,
                    AVG(CAST(ss.net_pay_amount AS DECIMAL)) as avg_net_pay
                FROM company_employee_salary_slip ss
                JOIN company_employee ce ON ce.id = ss.company_employee_id
                LEFT JOIN company c ON c.id = ce.company_id
                LEFT JOIN company_branch cb ON cb.id = ce.company_branch_id
                WHERE ss.status = 1 AND ce.is_deleted = '0'
                  AND TO_CHAR(ss.date, 'YYYY-MM') = $1
            """
            params = [target_month]
            param_idx = 2

            if company_name:
                query += f" AND LOWER(c.name) LIKE LOWER(${param_idx})"
                params.append(f"%{company_name}%")
                param_idx += 1

            # Use for_branch parameter if provided (for branch breakdown), else use branch_name filter
            branch_filter = for_branch if for_branch else branch_name
            if branch_filter:
                query += f" AND LOWER(cb.name) LIKE LOWER(${param_idx})"
                params.append(f"%{branch_filter}%")
                param_idx += 1

            query = apply_company_filter(ctx, query, "ce")
            return fetch_one(query, params)

        def get_branch_breakdown(target_month):
            """Get salary breakdown by branch"""
            query = """
                SELECT
                    cb.name as branch_name,
                    COUNT(DISTINCT ss.company_employee_id) as employee_count,
                    SUM(ss.basic_salary) as total_basic,
                    AVG(ss.basic_salary) as avg_basic,
                    SUM(ss.total_gross_salary) as total_gross,
                    AVG(ss.total_gross_salary) as avg_gross,
                    SUM(CAST(ss.total_deduction AS DECIMAL)) as total_deductions,
                    AVG(CAST(ss.total_deduction AS DECIMAL)) as avg_deductions,
                    SUM(CAST(ss.net_pay_amount AS DECIMAL)) as total_net_pay,
                    AVG(CAST(ss.net_pay_amount AS DECIMAL)) as avg_net_pay
                FROM company_employee_salary_slip ss
                JOIN company_employee ce ON ce.id = ss.company_employee_id
                LEFT JOIN company c ON c.id = ce.company_id
                LEFT JOIN company_branch cb ON cb.id = ce.company_branch_id
                WHERE ss.status = 1 AND ce.is_deleted = '0'
                  AND TO_CHAR(ss.date, 'YYYY-MM') = $1
            """
            params = [target_month]
            param_idx = 2

            if company_name:
                query += f" AND LOWER(c.name) LIKE LOWER(${param_idx})"
                params.append(f"%{company_name}%")
                param_idx += 1

            query = apply_company_filter(ctx, query, "ce")
            query += " GROUP BY cb.name ORDER BY total_net_pay DESC"
            return fetch_all(query, params)

        current_data = get_expenditure_for_month(month)

        result = {
            "month": month,
            "expenditure": {
                "employee_count": current_data.get("employee_count") if current_data else 0,
                "basic": {
                    "total": round(float(current_data.get("total_basic") or 0), 2) if current_data else 0,
                    "avg": round(float(current_data.get("avg_basic") or 0), 2) if current_data else 0
                },
                "gross": {
                    "total": round(float(current_data.get("total_gross") or 0), 2) if current_data else 0,
                    "avg": round(float(current_data.get("avg_gross") or 0), 2) if current_data else 0
                },
                "deductions": {
                    "total": round(float(current_data.get("total_deductions") or 0), 2) if current_data else 0,
                    "avg": round(float(current_data.get("avg_deductions") or 0), 2) if current_data else 0
                },
                "net_pay": {
                    "total": round(float(current_data.get("total_net_pay") or 0), 2) if current_data else 0,
                    "avg": round(float(current_data.get("avg_net_pay") or 0), 2) if current_data else 0
                }
            }
        }

        # Add branch-wise breakdown if no specific branch filter
        if not branch_name:
            branch_data = get_branch_breakdown(month)
            branch_breakdown = []
            for row in branch_data:
                branch_breakdown.append({
                    "branch_name": row.get("branch_name"),
                    "employee_count": int(row.get("employee_count") or 0),
                    "avg_basic": round(float(row.get("avg_basic") or 0), 2),
                    "avg_gross": round(float(row.get("avg_gross") or 0), 2),
                    "avg_deductions": round(float(row.get("avg_deductions") or 0), 2),
                    "avg_net_pay": round(float(row.get("avg_net_pay") or 0), 2),
                    "total_net_pay": round(float(row.get("total_net_pay") or 0), 2)
                })
            result["branch_breakdown"] = branch_breakdown
        else:
            # When branch filter is applied, show branch-specific averages
            result["branch_averages"] = {
                "avg_basic": result["expenditure"]["basic"]["avg"],
                "avg_gross": result["expenditure"]["gross"]["avg"],
                "avg_deductions": result["expenditure"]["deductions"]["avg"],
                "avg_net_pay": result["expenditure"]["net_pay"]["avg"]
            }

        if compare:
            # Calculate previous month
            year, mon = map(int, month.split("-"))
            if mon == 1:
                prev_month = f"{year - 1}-12"
            else:
                prev_month = f"{year}-{mon - 1:02d}"

            prev_data = get_expenditure_for_month(prev_month)

            prev_net = float(prev_data.get("total_net_pay") or 0) if prev_data else 0
            curr_net = result["expenditure"]["net_pay"]["total"]

            change = curr_net - prev_net
            change_pct = round((change / prev_net * 100), 2) if prev_net > 0 else 0

            result["previous_month"] = {
                "month": prev_month,
                "total_net_pay": prev_net,
                "total_gross": float(prev_data.get("total_gross") or 0) if prev_data else 0,
                "employee_count": prev_data.get("employee_count") if prev_data else 0
            }
            result["comparison"] = {
                "net_pay_change": round(change, 2),
                "change_percentage": change_pct,
                "trend": "up" if change > 0 else "down" if change < 0 else "unchanged"
            }

        if company_name:
            result["company_filter"] = company_name
        if branch_name:
            result["branch_filter"] = branch_name

        return result

    @mcp.tool()
    def get_headcount_summary(company_name: str = None, branch_name: str = None, group_by: str = "branch", compare: bool = False) -> dict:
        """
        Get employee headcount summary.
        group_by: 'branch', 'department', or 'designation' (default: branch).
        Use compare=True to include previous month comparison.
        """
        ctx = get_user_context()
        if not ctx:
            return {"error": "Not authenticated. Please login first."}

        # Map group_by to SQL columns
        group_map = {
            "branch": ("cb.name", "branch_name"),
            "department": ("cd.name", "department_name"),
            "designation": ("ce.designation", "designation")
        }

        if group_by not in group_map:
            return {"error": f"Invalid group_by. Use: {', '.join(group_map.keys())}"}

        group_col, alias = group_map[group_by]

        def get_headcount(as_of_date=None):
            query = f"""
                SELECT {group_col} as {alias}, COUNT(*) as count
                FROM company_employee ce
                LEFT JOIN company c ON c.id = ce.company_id
                LEFT JOIN company_branch cb ON cb.id = ce.company_branch_id
                LEFT JOIN company_department cd ON cd.id = ce.company_role_id
                WHERE ce.is_deleted = '0' AND ce.employee_status = 3
            """
            params = []
            param_idx = 1

            if as_of_date:
                query += f" AND (ce.date_of_joining IS NULL OR ce.date_of_joining <= ${param_idx})"
                params.append(as_of_date)
                param_idx += 1

            if company_name:
                query += f" AND LOWER(c.name) LIKE LOWER(${param_idx})"
                params.append(f"%{company_name}%")
                param_idx += 1

            if branch_name:
                query += f" AND LOWER(cb.name) LIKE LOWER(${param_idx})"
                params.append(f"%{branch_name}%")
                param_idx += 1

            query = apply_company_filter(ctx, query, "ce")
            query += f" GROUP BY {group_col} ORDER BY count DESC"

            return fetch_all(query, params) if params else fetch_all(query)

        current_data = get_headcount()
        total = sum(int(row.get("count", 0) or 0) for row in current_data)

        result = {
            "as_of": datetime.now().strftime("%Y-%m-%d"),
            "group_by": group_by,
            "total_headcount": total,
            "breakdown": current_data
        }

        if compare:
            # Get headcount as of last month end
            now = datetime.now()
            if now.month == 1:
                prev_month_end = f"{now.year - 1}-12-31"
            else:
                import calendar
                last_day = calendar.monthrange(now.year, now.month - 1)[1]
                prev_month_end = f"{now.year}-{now.month - 1:02d}-{last_day}"

            prev_data = get_headcount(prev_month_end)
            prev_total = sum(int(row.get("count", 0) or 0) for row in prev_data)

            change = total - prev_total

            result["previous_month"] = {
                "as_of": prev_month_end,
                "total_headcount": prev_total
            }
            result["comparison"] = {
                "change": change,
                "trend": "up" if change > 0 else "down" if change < 0 else "unchanged"
            }

        if company_name:
            result["company_filter"] = company_name
        if branch_name:
            result["branch_filter"] = branch_name

        return result

    @mcp.tool()
    def get_attendance_summary(month: str = None, company_name: str = None, branch_name: str = None, compare: bool = False) -> dict:
        """
        Get company-wide attendance summary for a month.
        Month format: YYYY-MM (defaults to current month).
        Use compare=True to include previous month comparison.
        """
        ctx = get_user_context()
        if not ctx:
            return {"error": "Not authenticated. Please login first."}

        if not month:
            month = datetime.now().strftime("%Y-%m")

        def get_attendance_for_month(target_month):
            # Parse month to get year and month number
            try:
                yr, mn = map(int, target_month.split("-"))
            except:
                yr, mn = datetime.now().year, datetime.now().month

            query = """
                SELECT
                    COUNT(DISTINCT ams.company_employee_id) as employee_count,
                    SUM(ams.working_days) as total_working_days,
                    SUM(ams.present_days) as total_present_days,
                    SUM(ams.absent_days) as total_absent_days,
                    SUM(ams.late_days) as total_late_days,
                    SUM(ams.half_days) as total_half_days,
                    SUM(ams.leave_days) as total_leave_days,
                    AVG(ams.attendance_percentage) as avg_attendance_pct
                FROM attendance_monthly_summary ams
                JOIN company_employee ce ON ce.id = ams.company_employee_id
                LEFT JOIN company c ON c.id = ce.company_id
                LEFT JOIN company_branch cb ON cb.id = ce.company_branch_id
                WHERE ce.is_deleted = '0' AND ams.year = $1 AND ams.month = $2
            """
            params = [yr, mn]
            param_idx = 3

            if company_name:
                query += f" AND LOWER(c.name) LIKE LOWER(${param_idx})"
                params.append(f"%{company_name}%")
                param_idx += 1

            if branch_name:
                query += f" AND LOWER(cb.name) LIKE LOWER(${param_idx})"
                params.append(f"%{branch_name}%")
                param_idx += 1

            query = apply_company_filter(ctx, query, "ce")
            return fetch_one(query, params)

        current_data = get_attendance_for_month(month)

        result = {
            "month": month,
            "summary": {
                "employee_count": current_data.get("employee_count") if current_data else 0,
                "total_working_days": float(current_data.get("total_working_days") or 0) if current_data else 0,
                "total_present_days": float(current_data.get("total_present_days") or 0) if current_data else 0,
                "total_absent_days": float(current_data.get("total_absent_days") or 0) if current_data else 0,
                "total_late_days": float(current_data.get("total_late_days") or 0) if current_data else 0,
                "total_half_days": float(current_data.get("total_half_days") or 0) if current_data else 0,
                "total_leave_days": float(current_data.get("total_leave_days") or 0) if current_data else 0,
                "avg_attendance_percentage": round(float(current_data.get("avg_attendance_pct") or 0), 2) if current_data else 0
            }
        }

        if compare:
            year, mon = map(int, month.split("-"))
            if mon == 1:
                prev_month = f"{year - 1}-12"
            else:
                prev_month = f"{year}-{mon - 1:02d}"

            prev_data = get_attendance_for_month(prev_month)

            curr_pct = result["summary"]["avg_attendance_percentage"]
            prev_pct = round(float(prev_data.get("avg_attendance_pct") or 0), 2) if prev_data else 0
            change_pct = round(curr_pct - prev_pct, 2)

            result["previous_month"] = {
                "month": prev_month,
                "avg_attendance_percentage": prev_pct,
                "employee_count": prev_data.get("employee_count") if prev_data else 0
            }
            result["comparison"] = {
                "attendance_change": change_pct,
                "trend": "improved" if change_pct > 0 else "declined" if change_pct < 0 else "unchanged"
            }

        if company_name:
            result["company_filter"] = company_name
        if branch_name:
            result["branch_filter"] = branch_name

        return result

    @mcp.tool()
    def get_leave_utilization(year: int = None, company_name: str = None, branch_name: str = None) -> dict:
        """
        Get leave utilization statistics for a year.
        Year defaults to current year.
        Shows leave taken vs available by type.
        """
        ctx = get_user_context()
        if not ctx:
            return {"error": "Not authenticated. Please login first."}

        if not year:
            year = datetime.now().year

        # Get leave taken from attendance_monthly_summary (aggregated by year)
        taken_query = """
            SELECT
                COUNT(DISTINCT ams.company_employee_id) as employee_count,
                SUM(ams.sick_leaves_taken) as sick_leave_taken,
                SUM(ams.casual_leaves_taken) as casual_leave_taken,
                SUM(ams.earned_leaves_taken) as earned_leave_taken,
                SUM(ams.other_leaves_taken) as other_leave_taken,
                SUM(ams.leave_days) as total_leave_days
            FROM attendance_monthly_summary ams
            JOIN company_employee ce ON ce.id = ams.company_employee_id
            LEFT JOIN company c ON c.id = ce.company_id
            LEFT JOIN company_branch cb ON cb.id = ce.company_branch_id
            WHERE ce.is_deleted = '0' AND ams.year = $1
        """

        # Get current leave balances from company_employee_leave
        balance_query = """
            SELECT
                SUM(COALESCE(cel.sick_leave, 0)) as sick_leave_balance,
                SUM(COALESCE(cel.casual_leave, 0)) as casual_leave_balance,
                SUM(COALESCE(cel.earned_leave, 0)) as earned_leave_balance,
                SUM(COALESCE(cel.other_leave, 0)) as other_leave_balance
            FROM company_employee ce
            LEFT JOIN company_employee_leave cel ON cel.company_employee_id = ce.id
                AND cel.year = $1 AND cel.is_current = 1
            LEFT JOIN company c ON c.id = ce.company_id
            LEFT JOIN company_branch cb ON cb.id = ce.company_branch_id
            WHERE ce.is_deleted = '0' AND ce.employee_status = 3
        """

        params = [year]
        param_idx = 2

        if company_name:
            taken_query += f" AND LOWER(c.name) LIKE LOWER(${param_idx})"
            balance_query += f" AND LOWER(c.name) LIKE LOWER(${param_idx})"
            params.append(f"%{company_name}%")
            param_idx += 1

        if branch_name:
            taken_query += f" AND LOWER(cb.name) LIKE LOWER(${param_idx})"
            balance_query += f" AND LOWER(cb.name) LIKE LOWER(${param_idx})"
            params.append(f"%{branch_name}%")
            param_idx += 1

        taken_query = apply_company_filter(ctx, taken_query, "ce")
        balance_query = apply_company_filter(ctx, balance_query, "ce")

        # attendance_monthly_summary.year is smallint, company_employee_leave.year is varchar
        taken_data = fetch_one(taken_query, params)
        balance_params = [str(year)] + params[1:]  # Convert year to string for balance query
        balance_data = fetch_one(balance_query, balance_params)

        if not taken_data:
            return {"error": "No leave data found"}

        def calc_utilization(taken, remaining):
            taken = float(taken or 0)
            remaining = float(remaining or 0)
            total = taken + remaining
            pct = round((taken / total * 100), 2) if total > 0 else 0
            return {"taken": taken, "remaining": remaining, "total_quota": total, "utilization_pct": pct}

        sick_taken = float(taken_data.get("sick_leave_taken") or 0)
        casual_taken = float(taken_data.get("casual_leave_taken") or 0)
        earned_taken = float(taken_data.get("earned_leave_taken") or 0)
        other_taken = float(taken_data.get("other_leave_taken") or 0)

        sick_balance = float(balance_data.get("sick_leave_balance") or 0) if balance_data else 0
        casual_balance = float(balance_data.get("casual_leave_balance") or 0) if balance_data else 0
        earned_balance = float(balance_data.get("earned_leave_balance") or 0) if balance_data else 0
        other_balance = float(balance_data.get("other_leave_balance") or 0) if balance_data else 0

        result = {
            "year": year,
            "employee_count": int(taken_data.get("employee_count") or 0),
            "leave_utilization": {
                "sick_leave": calc_utilization(sick_taken, sick_balance),
                "casual_leave": calc_utilization(casual_taken, casual_balance),
                "earned_leave": calc_utilization(earned_taken, earned_balance),
                "other_leave": calc_utilization(other_taken, other_balance)
            }
        }

        # Calculate total
        total_taken = sick_taken + casual_taken + earned_taken + other_taken
        total_remaining = sick_balance + casual_balance + earned_balance + other_balance
        total_all = total_taken + total_remaining

        result["total"] = {
            "total_taken": total_taken,
            "total_remaining": total_remaining,
            "total_quota": total_all,
            "overall_utilization_pct": round((total_taken / total_all * 100), 2) if total_all > 0 else 0
        }

        if company_name:
            result["company_filter"] = company_name
        if branch_name:
            result["branch_filter"] = branch_name

        return result

    @mcp.tool()
    def get_attrition_report(month: str = None, company_name: str = None, branch_name: str = None, compare: bool = False) -> dict:
        """
        Get attrition report showing new joiners vs exits.
        Month format: YYYY-MM (defaults to current month).
        Use compare=True to include previous month comparison.
        """
        ctx = get_user_context()
        if not ctx:
            return {"error": "Not authenticated. Please login first."}

        if not month:
            month = datetime.now().strftime("%Y-%m")

        def get_attrition_for_month(target_month):
            # New joiners - using LIKE pattern for varchar date field
            joiner_query = """
                SELECT COUNT(*) as count
                FROM company_employee ce
                LEFT JOIN company c ON c.id = ce.company_id
                LEFT JOIN company_branch cb ON cb.id = ce.company_branch_id
                WHERE ce.is_deleted = '0'
                  AND ce.date_of_joining IS NOT NULL
                  AND ce.date_of_joining LIKE $1
            """

            # Exits
            exit_query = """
                SELECT COUNT(*) as count
                FROM company_employee ce
                LEFT JOIN company c ON c.id = ce.company_id
                LEFT JOIN company_branch cb ON cb.id = ce.company_branch_id
                WHERE ce.date_of_exit IS NOT NULL
                  AND TO_CHAR(ce.date_of_exit, 'YYYY-MM') = $1
            """

            month_pattern = f"{target_month}-%"
            params_joiner = [month_pattern]
            params_exit = [target_month]
            param_idx = 2

            if company_name:
                joiner_query += f" AND LOWER(c.name) LIKE LOWER(${param_idx})"
                exit_query += f" AND LOWER(c.name) LIKE LOWER(${param_idx})"
                params_joiner.append(f"%{company_name}%")
                params_exit.append(f"%{company_name}%")
                param_idx += 1

            if branch_name:
                joiner_query += f" AND LOWER(cb.name) LIKE LOWER(${param_idx})"
                exit_query += f" AND LOWER(cb.name) LIKE LOWER(${param_idx})"
                params_joiner.append(f"%{branch_name}%")
                params_exit.append(f"%{branch_name}%")
                param_idx += 1

            joiner_query = apply_company_filter(ctx, joiner_query, "ce")
            exit_query = apply_company_filter(ctx, exit_query, "ce")

            joiners = fetch_one(joiner_query, params_joiner)
            exits = fetch_one(exit_query, params_exit)

            return {
                "new_joiners": int(joiners.get("count") or 0) if joiners else 0,
                "exits": int(exits.get("count") or 0) if exits else 0
            }

        current_data = get_attrition_for_month(month)
        net_change = current_data["new_joiners"] - current_data["exits"]

        result = {
            "month": month,
            "new_joiners": current_data["new_joiners"],
            "exits": current_data["exits"],
            "net_change": net_change,
            "trend": "growing" if net_change > 0 else "shrinking" if net_change < 0 else "stable"
        }

        if compare:
            year, mon = map(int, month.split("-"))
            if mon == 1:
                prev_month = f"{year - 1}-12"
            else:
                prev_month = f"{year}-{mon - 1:02d}"

            prev_data = get_attrition_for_month(prev_month)
            prev_net = prev_data["new_joiners"] - prev_data["exits"]

            result["previous_month"] = {
                "month": prev_month,
                "new_joiners": prev_data["new_joiners"],
                "exits": prev_data["exits"],
                "net_change": prev_net
            }
            result["comparison"] = {
                "joiner_change": current_data["new_joiners"] - prev_data["new_joiners"],
                "exit_change": current_data["exits"] - prev_data["exits"],
                "net_change_diff": net_change - prev_net
            }

        if company_name:
            result["company_filter"] = company_name
        if branch_name:
            result["branch_filter"] = branch_name

        return result
