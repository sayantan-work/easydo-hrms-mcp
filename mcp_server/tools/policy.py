"""Policy tools for MCP server."""
from ..auth import get_user_context
from ..db import fetch_all, fetch_one
from ..rbac import apply_company_filter


def register(mcp):
    """Register policy tools with MCP server."""

    # Internal helper functions (not exposed as tools)
    def _get_leave_policy_data(ctx, company_name: str = None, branch_name: str = None) -> dict:
        """Internal: Get leave policy data."""
        base_select = """
            SELECT cb.name as branch_name, c.name as company_name,
                   cl.sick_leave, cl.sick_leave_max_month,
                   cl.casual_leave, cl.casual_leave_max_month, cl.max_consequently_casual_leave,
                   cl.earned_leave, cl.earned_leave_max_month, cl.other_leave, cl.other_leave_max_month,
                   cl.paid_leave_year, cl.carry_forward_leave, cl.is_carry_forward_leave_allowed,
                   cl.holiday, cl.year
            FROM company_leave cl
            JOIN company_branch cb ON cb.id = cl.company_branch_id
            JOIN company c ON c.id = cl.company_id
            WHERE cl.is_current = 1
        """

        if company_name and branch_name:
            query = base_select + " AND LOWER(c.name) LIKE LOWER($1) AND LOWER(cb.name) LIKE LOWER($2)"
            rows = fetch_all(query, [f"%{company_name}%", f"%{branch_name}%"])
        elif company_name:
            query = base_select + " AND LOWER(c.name) LIKE LOWER($1)"
            rows = fetch_all(query, [f"%{company_name}%"])
        elif branch_name:
            query = base_select + " AND LOWER(cb.name) LIKE LOWER($1)"
            rows = fetch_all(query, [f"%{branch_name}%"])
        else:
            if not ctx.company_branch_id:
                return {"error": "No branch found. Please specify branch_name."}
            query = base_select + " AND cl.company_branch_id = $1"
            rows = fetch_all(query, [ctx.company_branch_id])

        policies = []
        for row in rows:
            casual_quota = row.get("casual_leave", 0) or 0
            earned_quota = row.get("earned_leave", 0) or 0

            policy = {
                "company_name": row.get("company_name"),
                "branch_name": row.get("branch_name"),
                "year": row.get("year"),
                "leave_quotas": {
                    "sick_leave": {
                        "annual_quota": row.get("sick_leave", 0),
                        "max_per_month": row.get("sick_leave_max_month", 0),
                        "allocation": "upfront"
                    },
                    "casual_leave": {
                        "annual_quota": casual_quota,
                        "monthly_accrual": round(casual_quota / 12, 2),
                        "max_per_month": row.get("casual_leave_max_month", 0),
                        "max_consecutive_days": row.get("max_consequently_casual_leave", 0),
                        "allocation": "accrued"
                    },
                    "earned_leave": {
                        "annual_quota": earned_quota,
                        "monthly_accrual": round(earned_quota / 12, 2),
                        "max_per_month": row.get("earned_leave_max_month", 0),
                        "allocation": "accrued"
                    },
                    "other_leave": {
                        "annual_quota": row.get("other_leave", 0),
                        "max_per_month": row.get("other_leave_max_month", 0)
                    }
                },
                "carry_forward": {
                    "allowed": row.get("is_carry_forward_leave_allowed") == 1,
                    "max_days": row.get("carry_forward_leave", 0)
                },
                "holidays": row.get("holiday", 0),
                "total_annual_paid_leave": row.get("paid_leave_year", 0)
            }
            policies.append(policy)

        if not policies:
            return {"error": "No leave policy found"}
        if len(policies) == 1:
            return policies[0]
        return {"count": len(policies), "leave_policies": policies}

    def _get_attendance_policy_data(ctx, company_name: str = None, branch_name: str = None) -> dict:
        """Internal: Get attendance policy data."""
        query = """
            SELECT cb.name as branch_name, c.name as company_name,
                   cb.working_hours, cb.start_time, cb.end_time,
                   cb.working_day, cb.saturday_working_days, cb.check_in_grace_period,
                   cb.check_out_grace_period, cb.late_period, cb.half_period, cb.full_day_absent,
                   cb.allowed_late_day, cb.break_time, cb.probation_period, cb.is_shift_rotational,
                   cb.salary_calculation_type
            FROM company_branch cb
            JOIN company c ON c.id = cb.company_id
            WHERE cb.status = 1
        """
        params = []
        param_idx = 1

        if branch_name:
            query += f" AND LOWER(cb.name) LIKE LOWER(${param_idx})"
            params.append(f"%{branch_name}%")
            param_idx += 1

        if company_name:
            query += f" AND LOWER(c.name) LIKE LOWER(${param_idx})"
            params.append(f"%{company_name}%")
            param_idx += 1

        if not branch_name and not company_name:
            if not ctx.company_branch_id:
                return {"error": "No branch found. Please specify branch_name."}
            query += f" AND cb.id = ${param_idx}"
            params.append(ctx.company_branch_id)

        rows = fetch_all(query, params) if params else fetch_all(query)

        if not rows:
            return {"error": "Branch policy not found"}

        policies = []
        for row in rows:
            grace_in = float(row.get("check_in_grace_period") or 0)
            grace_out = float(row.get("check_out_grace_period") or 0)
            late_period = float(row.get("late_period") or 0)
            half_period = float(row.get("half_period") or 0)
            full_day_absent = float(row.get("full_day_absent") or 0)
            allowed_late = row.get("allowed_late_day") or 0
            salary_calc_type = row.get("salary_calculation_type") or "month_total_day"

            late_after = grace_in
            half_day_after = grace_in + late_period
            absent_after_calculated = grace_in + late_period + half_period

            if full_day_absent > 0 and full_day_absent <= 2:
                absent_after_mins = full_day_absent * 60
            elif full_day_absent > half_day_after:
                absent_after_mins = full_day_absent
            else:
                absent_after_mins = absent_after_calculated

            policies.append({
                "branch_name": row.get("branch_name"),
                "company_name": row.get("company_name"),
                "working_hours": {
                    "start_time": row.get("start_time"),
                    "end_time": row.get("end_time"),
                    "total_hours": row.get("working_hours"),
                    "break_time_mins": row.get("break_time"),
                },
                "working_days": {
                    "days": row.get("working_day", ""),
                    "saturday_working": row.get("saturday_working_days")
                },
                "check_in_rules": {
                    "grace_period_mins": grace_in,
                    "late_after_mins": late_after,
                    "half_day_after_mins": half_day_after,
                    "absent_after_mins": absent_after_mins
                },
                "check_out_rules": {
                    "grace_period_mins": grace_out
                },
                "late_deduction_policy": {
                    "allowed_late_days": allowed_late,
                    "lates_per_absent_deduction": allowed_late if allowed_late > 0 else None
                },
                "salary_calculation": {
                    "type": salary_calc_type,
                    "daily_rate_basis": "calendar_days" if salary_calc_type == "month_total_day" else "working_days"
                },
                "probation_period_months": row.get("probation_period"),
                "is_shift_rotational": row.get("is_shift_rotational") == 1
            })

        if len(policies) == 1:
            return policies[0]
        return {"count": len(policies), "attendance_policies": policies}

    def _get_statutory_rules_data() -> dict:
        """Internal: Get statutory rules data."""
        rules_query = """
            SELECT sr.financial_year, sr.epf_present as epf_percentage,
                   sr.esi_present as esi_percentage, sr.esi_min_amount, sr.esi_max_amount, sr.nps_min
            FROM statutory_rules sr
            WHERE sr.status = 1
            ORDER BY sr.financial_year DESC LIMIT 1
        """
        rules = fetch_one(rules_query)

        tax_query = """
            SELECT ts.start_amount, ts.end_amount, ts.total_tax as tax_percentage
            FROM tax_slabs ts ORDER BY ts.start_amount
        """
        tax_slabs = fetch_all(tax_query)

        return {
            "statutory_rules": rules if rules else {},
            "tax_slabs": tax_slabs,
            "_note": "Government-mandated statutory deduction rates"
        }

    @mcp.tool()
    def get_policy(
        policy_type: str = "all",
        company_name: str = None,
        branch_name: str = None
    ) -> dict:
        """
        Get company/branch policies.

        Policy type options:
        - 'leave': Leave quotas, carry forward rules
        - 'attendance': Working hours, grace period, late rules
        - 'statutory': PF, ESI percentages, tax slabs (government-mandated)
        - 'all': All policies combined

        Use company_name and/or branch_name to filter (defaults to your branch).
        """
        ctx = get_user_context()
        if not ctx:
            return {"error": "Not authenticated. Please login first."}

        policy_type = policy_type.lower().strip()
        valid_types = ['leave', 'attendance', 'statutory', 'all']
        if policy_type not in valid_types:
            return {"error": f"Invalid policy_type '{policy_type}'. Use: {', '.join(valid_types)}"}

        result = {}

        if policy_type == 'leave':
            return _get_leave_policy_data(ctx, company_name, branch_name)
        elif policy_type == 'attendance':
            return _get_attendance_policy_data(ctx, company_name, branch_name)
        elif policy_type == 'statutory':
            return _get_statutory_rules_data()
        else:  # all
            leave_data = _get_leave_policy_data(ctx, company_name, branch_name)
            attendance_data = _get_attendance_policy_data(ctx, company_name, branch_name)
            statutory_data = _get_statutory_rules_data()

            result = {
                "leave_policy": leave_data if "error" not in leave_data else None,
                "attendance_policy": attendance_data if "error" not in attendance_data else None,
                "statutory_rules": statutory_data
            }

            # Add filter info
            if company_name:
                result["company_filter"] = company_name
            if branch_name:
                result["branch_filter"] = branch_name

            return result
