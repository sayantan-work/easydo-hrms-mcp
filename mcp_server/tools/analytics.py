"""Company-level analytics tools for MCP server."""
import calendar
from datetime import datetime

from ..auth import get_user_context
from ..db import fetch_all, fetch_one
from ..rbac import apply_company_filter


# Authentication error constant
AUTH_ERROR = {"error": "Not authenticated. Please login first."}


def _get_previous_month(month: str) -> str:
    """Calculate previous month from YYYY-MM format."""
    year, mon = map(int, month.split("-"))
    if mon == 1:
        return f"{year - 1}-12"
    return f"{year}-{mon - 1:02d}"


def _get_default_month() -> str:
    """Get current month in YYYY-MM format."""
    return datetime.now().strftime("%Y-%m")


def _get_previous_salary_month() -> str:
    """Get previous month in YYYY-MM format (default for salary queries)."""
    now = datetime.now()
    if now.month == 1:
        return f"{now.year - 1}-12"
    return f"{now.year}-{now.month - 1:02d}"


def _safe_float(value, default: float = 0.0) -> float:
    """Safely convert value to float."""
    if value is None:
        return default
    try:
        return float(value)
    except (ValueError, TypeError):
        return default


def _safe_int(value, default: int = 0) -> int:
    """Safely convert value to int."""
    if value is None:
        return default
    try:
        return int(value)
    except (ValueError, TypeError):
        return default


def _round_float(value, decimals: int = 2) -> float:
    """Round a value to specified decimals, handling None."""
    return round(_safe_float(value), decimals)


def _calculate_trend(current: float, previous: float) -> str:
    """Determine trend direction from current vs previous values."""
    if current > previous:
        return "up"
    if current < previous:
        return "down"
    return "unchanged"


def _add_filters(result: dict, company_name: str, branch_name: str) -> None:
    """Add filter info to result dict if filters were applied."""
    if company_name:
        result["company_filter"] = company_name
    if branch_name:
        result["branch_filter"] = branch_name


class QueryBuilder:
    """Helper class for building parameterized SQL queries with filters."""

    def __init__(self, base_query: str, initial_params: list = None):
        self.query = base_query
        self.params = list(initial_params) if initial_params else []
        self.param_idx = len(self.params) + 1

    def add_company_filter(self, company_name: str) -> "QueryBuilder":
        """Add company name filter if provided."""
        if company_name:
            self.query += f" AND LOWER(c.name) LIKE LOWER(${self.param_idx})"
            self.params.append(f"%{company_name}%")
            self.param_idx += 1
        return self

    def add_branch_filter(self, branch_name: str) -> "QueryBuilder":
        """Add branch name filter if provided."""
        if branch_name:
            self.query += f" AND LOWER(cb.name) LIKE LOWER(${self.param_idx})"
            self.params.append(f"%{branch_name}%")
            self.param_idx += 1
        return self

    def apply_rbac(self, ctx, table_alias: str) -> "QueryBuilder":
        """Apply RBAC filter to query."""
        self.query = apply_company_filter(ctx, self.query, table_alias)
        return self

    def append(self, sql: str) -> "QueryBuilder":
        """Append additional SQL to query."""
        self.query += sql
        return self


def register(mcp):
    """Register company-level analytics tools with MCP server."""

    @mcp.tool()
    def get_salary_expenditure(
        month: str = None,
        company_name: str = None,
        branch_name: str = None,
        compare: bool = False,
    ) -> dict:
        """
        Get total salary expenditure for a month.
        Month format: YYYY-MM (defaults to previous month).
        Use compare=True to include previous month comparison.
        Use company_name and/or branch_name to filter.
        """
        ctx = get_user_context()
        if not ctx:
            return AUTH_ERROR

        month = month or _get_previous_salary_month()

        def get_expenditure_for_month(target_month, for_branch=None):
            base_query = """
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

            qb = QueryBuilder(base_query, [target_month])
            qb.add_company_filter(company_name)

            # Use for_branch parameter if provided (for branch breakdown), else use branch_name filter
            branch_filter = for_branch if for_branch else branch_name
            qb.add_branch_filter(branch_filter)
            qb.apply_rbac(ctx, "ce")

            return fetch_one(qb.query, qb.params)

        def get_branch_breakdown(target_month):
            """Get salary breakdown by branch."""
            base_query = """
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

            qb = QueryBuilder(base_query, [target_month])
            qb.add_company_filter(company_name)
            qb.apply_rbac(ctx, "ce")
            qb.append(" GROUP BY cb.name ORDER BY total_net_pay DESC")

            return fetch_all(qb.query, qb.params)

        current_data = get_expenditure_for_month(month)

        def build_category(total_key: str, avg_key: str) -> dict:
            return {
                "total": _round_float(current_data.get(total_key) if current_data else 0),
                "avg": _round_float(current_data.get(avg_key) if current_data else 0),
            }

        result = {
            "month": month,
            "expenditure": {
                "employee_count": _safe_int(current_data.get("employee_count") if current_data else 0),
                "basic": build_category("total_basic", "avg_basic"),
                "gross": build_category("total_gross", "avg_gross"),
                "deductions": build_category("total_deductions", "avg_deductions"),
                "net_pay": build_category("total_net_pay", "avg_net_pay"),
            },
        }

        # Add branch-wise breakdown if no specific branch filter
        if not branch_name:
            branch_data = get_branch_breakdown(month)
            result["branch_breakdown"] = [
                {
                    "branch_name": row.get("branch_name"),
                    "employee_count": _safe_int(row.get("employee_count")),
                    "avg_basic": _round_float(row.get("avg_basic")),
                    "avg_gross": _round_float(row.get("avg_gross")),
                    "avg_deductions": _round_float(row.get("avg_deductions")),
                    "avg_net_pay": _round_float(row.get("avg_net_pay")),
                    "total_net_pay": _round_float(row.get("total_net_pay")),
                }
                for row in branch_data
            ]
        else:
            # When branch filter is applied, show branch-specific averages
            result["branch_averages"] = {
                "avg_basic": result["expenditure"]["basic"]["avg"],
                "avg_gross": result["expenditure"]["gross"]["avg"],
                "avg_deductions": result["expenditure"]["deductions"]["avg"],
                "avg_net_pay": result["expenditure"]["net_pay"]["avg"],
            }

        if compare:
            prev_month = _get_previous_month(month)
            prev_data = get_expenditure_for_month(prev_month)

            prev_net = _safe_float(prev_data.get("total_net_pay") if prev_data else 0)
            curr_net = result["expenditure"]["net_pay"]["total"]
            change = curr_net - prev_net
            change_pct = round((change / prev_net * 100), 2) if prev_net > 0 else 0

            result["previous_month"] = {
                "month": prev_month,
                "total_net_pay": prev_net,
                "total_gross": _safe_float(prev_data.get("total_gross") if prev_data else 0),
                "employee_count": _safe_int(prev_data.get("employee_count") if prev_data else 0),
            }
            result["comparison"] = {
                "net_pay_change": round(change, 2),
                "change_percentage": change_pct,
                "trend": _calculate_trend(curr_net, prev_net),
            }

        _add_filters(result, company_name, branch_name)
        return result

    @mcp.tool()
    def get_headcount_summary(
        company_name: str = None,
        branch_name: str = None,
        group_by: str = "branch",
        compare: bool = False,
    ) -> dict:
        """
        Get employee headcount summary.
        group_by: 'branch', 'department', or 'designation' (default: branch).
        Use compare=True to include previous month comparison.
        """
        ctx = get_user_context()
        if not ctx:
            return AUTH_ERROR

        # Map group_by to SQL columns
        group_map = {
            "branch": ("cb.name", "branch_name"),
            "department": ("cd.name", "department_name"),
            "designation": ("ce.designation", "designation"),
        }

        if group_by not in group_map:
            return {"error": f"Invalid group_by. Use: {', '.join(group_map.keys())}"}

        group_col, alias = group_map[group_by]

        def get_headcount(as_of_date=None):
            base_query = f"""
                SELECT {group_col} as {alias}, COUNT(*) as count
                FROM company_employee ce
                LEFT JOIN company c ON c.id = ce.company_id
                LEFT JOIN company_branch cb ON cb.id = ce.company_branch_id
                LEFT JOIN company_department cd ON cd.id = ce.company_role_id
                WHERE ce.is_deleted = '0' AND ce.employee_status = 3
            """

            qb = QueryBuilder(base_query)

            if as_of_date:
                qb.query += f" AND (ce.date_of_joining IS NULL OR ce.date_of_joining <= ${qb.param_idx})"
                qb.params.append(as_of_date)
                qb.param_idx += 1

            qb.add_company_filter(company_name)
            qb.add_branch_filter(branch_name)
            qb.apply_rbac(ctx, "ce")
            qb.append(f" GROUP BY {group_col} ORDER BY count DESC")

            return fetch_all(qb.query, qb.params) if qb.params else fetch_all(qb.query)

        current_data = get_headcount()
        total = sum(_safe_int(row.get("count")) for row in current_data)

        result = {
            "as_of": datetime.now().strftime("%Y-%m-%d"),
            "group_by": group_by,
            "total_headcount": total,
            "breakdown": current_data,
        }

        if compare:
            now = datetime.now()
            if now.month == 1:
                prev_month_end = f"{now.year - 1}-12-31"
            else:
                last_day = calendar.monthrange(now.year, now.month - 1)[1]
                prev_month_end = f"{now.year}-{now.month - 1:02d}-{last_day}"

            prev_data = get_headcount(prev_month_end)
            prev_total = sum(_safe_int(row.get("count")) for row in prev_data)
            change = total - prev_total

            result["previous_month"] = {
                "as_of": prev_month_end,
                "total_headcount": prev_total,
            }
            result["comparison"] = {
                "change": change,
                "trend": _calculate_trend(total, prev_total),
            }

        _add_filters(result, company_name, branch_name)
        return result

    @mcp.tool()
    def get_attendance_summary(
        month: str = None,
        company_name: str = None,
        branch_name: str = None,
        compare: bool = False,
    ) -> dict:
        """
        Get company-wide attendance summary for a month.
        Month format: YYYY-MM (defaults to current month).
        Use compare=True to include previous month comparison.
        """
        ctx = get_user_context()
        if not ctx:
            return AUTH_ERROR

        month = month or _get_default_month()

        def parse_month(target_month: str) -> tuple:
            """Parse YYYY-MM string into (year, month) tuple."""
            try:
                return tuple(map(int, target_month.split("-")))
            except (ValueError, AttributeError):
                now = datetime.now()
                return now.year, now.month

        def get_attendance_for_month(target_month):
            yr, mn = parse_month(target_month)

            base_query = """
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

            qb = QueryBuilder(base_query, [yr, mn])
            qb.add_company_filter(company_name)
            qb.add_branch_filter(branch_name)
            qb.apply_rbac(ctx, "ce")

            return fetch_one(qb.query, qb.params)

        current_data = get_attendance_for_month(month)

        result = {
            "month": month,
            "summary": {
                "employee_count": _safe_int(current_data.get("employee_count") if current_data else 0),
                "total_working_days": _safe_float(current_data.get("total_working_days") if current_data else 0),
                "total_present_days": _safe_float(current_data.get("total_present_days") if current_data else 0),
                "total_absent_days": _safe_float(current_data.get("total_absent_days") if current_data else 0),
                "total_late_days": _safe_float(current_data.get("total_late_days") if current_data else 0),
                "total_half_days": _safe_float(current_data.get("total_half_days") if current_data else 0),
                "total_leave_days": _safe_float(current_data.get("total_leave_days") if current_data else 0),
                "avg_attendance_percentage": _round_float(current_data.get("avg_attendance_pct") if current_data else 0),
            },
        }

        if compare:
            prev_month = _get_previous_month(month)
            prev_data = get_attendance_for_month(prev_month)

            curr_pct = result["summary"]["avg_attendance_percentage"]
            prev_pct = _round_float(prev_data.get("avg_attendance_pct") if prev_data else 0)
            change_pct = round(curr_pct - prev_pct, 2)

            result["previous_month"] = {
                "month": prev_month,
                "avg_attendance_percentage": prev_pct,
                "employee_count": _safe_int(prev_data.get("employee_count") if prev_data else 0),
            }
            result["comparison"] = {
                "attendance_change": change_pct,
                "trend": "improved" if change_pct > 0 else "declined" if change_pct < 0 else "unchanged",
            }

        _add_filters(result, company_name, branch_name)
        return result

    @mcp.tool()
    def get_leave_utilization(
        year: int = None,
        company_name: str = None,
        branch_name: str = None,
    ) -> dict:
        """
        Get leave utilization statistics for a year.
        Year defaults to current year.
        Shows leave taken vs available by type.
        """
        ctx = get_user_context()
        if not ctx:
            return AUTH_ERROR

        year = year or datetime.now().year

        # Get leave taken from attendance_monthly_summary (aggregated by year)
        taken_base = """
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
        balance_base = """
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

        taken_qb = QueryBuilder(taken_base, [year])
        balance_qb = QueryBuilder(balance_base, [str(year)])  # year is varchar in balance table

        taken_qb.add_company_filter(company_name).add_branch_filter(branch_name).apply_rbac(ctx, "ce")
        balance_qb.add_company_filter(company_name).add_branch_filter(branch_name).apply_rbac(ctx, "ce")

        taken_data = fetch_one(taken_qb.query, taken_qb.params)
        balance_data = fetch_one(balance_qb.query, balance_qb.params)

        if not taken_data:
            return {"error": "No leave data found"}

        def calc_utilization(taken: float, remaining: float) -> dict:
            total = taken + remaining
            pct = round((taken / total * 100), 2) if total > 0 else 0
            return {"taken": taken, "remaining": remaining, "total_quota": total, "utilization_pct": pct}

        sick_taken = _safe_float(taken_data.get("sick_leave_taken"))
        casual_taken = _safe_float(taken_data.get("casual_leave_taken"))
        earned_taken = _safe_float(taken_data.get("earned_leave_taken"))
        other_taken = _safe_float(taken_data.get("other_leave_taken"))

        sick_balance = _safe_float(balance_data.get("sick_leave_balance") if balance_data else 0)
        casual_balance = _safe_float(balance_data.get("casual_leave_balance") if balance_data else 0)
        earned_balance = _safe_float(balance_data.get("earned_leave_balance") if balance_data else 0)
        other_balance = _safe_float(balance_data.get("other_leave_balance") if balance_data else 0)

        result = {
            "year": year,
            "employee_count": _safe_int(taken_data.get("employee_count")),
            "leave_utilization": {
                "sick_leave": calc_utilization(sick_taken, sick_balance),
                "casual_leave": calc_utilization(casual_taken, casual_balance),
                "earned_leave": calc_utilization(earned_taken, earned_balance),
                "other_leave": calc_utilization(other_taken, other_balance),
            },
        }

        # Calculate total
        total_taken = sick_taken + casual_taken + earned_taken + other_taken
        total_remaining = sick_balance + casual_balance + earned_balance + other_balance
        total_all = total_taken + total_remaining

        result["total"] = {
            "total_taken": total_taken,
            "total_remaining": total_remaining,
            "total_quota": total_all,
            "overall_utilization_pct": round((total_taken / total_all * 100), 2) if total_all > 0 else 0,
        }

        _add_filters(result, company_name, branch_name)
        return result

    @mcp.tool()
    def get_attrition_report(
        month: str = None,
        company_name: str = None,
        branch_name: str = None,
        compare: bool = False,
    ) -> dict:
        """
        Get attrition report showing new joiners vs exits.
        Month format: YYYY-MM (defaults to current month).
        Use compare=True to include previous month comparison.
        """
        ctx = get_user_context()
        if not ctx:
            return AUTH_ERROR

        month = month or _get_default_month()

        def get_attrition_for_month(target_month):
            month_pattern = f"{target_month}-%"

            # New joiners - using LIKE pattern for varchar date field
            joiner_base = """
                SELECT COUNT(*) as count
                FROM company_employee ce
                LEFT JOIN company c ON c.id = ce.company_id
                LEFT JOIN company_branch cb ON cb.id = ce.company_branch_id
                WHERE ce.is_deleted = '0'
                  AND ce.date_of_joining IS NOT NULL
                  AND ce.date_of_joining LIKE $1
            """

            # Exits
            exit_base = """
                SELECT COUNT(*) as count
                FROM company_employee ce
                LEFT JOIN company c ON c.id = ce.company_id
                LEFT JOIN company_branch cb ON cb.id = ce.company_branch_id
                WHERE ce.date_of_exit IS NOT NULL
                  AND TO_CHAR(ce.date_of_exit, 'YYYY-MM') = $1
            """

            joiner_qb = QueryBuilder(joiner_base, [month_pattern])
            exit_qb = QueryBuilder(exit_base, [target_month])

            joiner_qb.add_company_filter(company_name).add_branch_filter(branch_name).apply_rbac(ctx, "ce")
            exit_qb.add_company_filter(company_name).add_branch_filter(branch_name).apply_rbac(ctx, "ce")

            joiners = fetch_one(joiner_qb.query, joiner_qb.params)
            exits = fetch_one(exit_qb.query, exit_qb.params)

            return {
                "new_joiners": _safe_int(joiners.get("count") if joiners else 0),
                "exits": _safe_int(exits.get("count") if exits else 0),
            }

        current_data = get_attrition_for_month(month)
        net_change = current_data["new_joiners"] - current_data["exits"]

        def get_growth_trend(net: int) -> str:
            if net > 0:
                return "growing"
            if net < 0:
                return "shrinking"
            return "stable"

        result = {
            "month": month,
            "new_joiners": current_data["new_joiners"],
            "exits": current_data["exits"],
            "net_change": net_change,
            "trend": get_growth_trend(net_change),
        }

        if compare:
            prev_month = _get_previous_month(month)
            prev_data = get_attrition_for_month(prev_month)
            prev_net = prev_data["new_joiners"] - prev_data["exits"]

            result["previous_month"] = {
                "month": prev_month,
                "new_joiners": prev_data["new_joiners"],
                "exits": prev_data["exits"],
                "net_change": prev_net,
            }
            result["comparison"] = {
                "joiner_change": current_data["new_joiners"] - prev_data["new_joiners"],
                "exit_change": current_data["exits"] - prev_data["exits"],
                "net_change_diff": net_change - prev_net,
            }

        _add_filters(result, company_name, branch_name)
        return result
