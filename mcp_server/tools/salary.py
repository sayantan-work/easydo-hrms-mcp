"""Salary tools for MCP server."""
from ..auth import get_user_context
from ..db import fetch_all, fetch_one
from ..rbac import apply_company_filter


def register(mcp):
    """Register salary tools with MCP server."""

    @mcp.tool()
    def get_salary(employee_name: str = None, company_name: str = None) -> dict:
        """
        Get current salary details including basic pay, allowances, and deductions.
        If employee_name is not provided, returns your own salary.
        Use company_name to filter by specific company.
        """
        ctx = get_user_context()
        if not ctx:
            return {"error": "Not authenticated. Please login first."}

        if employee_name:
            # Search for the employee
            query = """
                SELECT ce.id, ce.employee_name, ce.designation, c.name as company_name,
                       cb.name as branch_name, ce.basic_salary,
                       cea.house_rent_allowance, cea.dearness_allowance, cea.travel_allowance,
                       cea.conveyance_allowance, cea.medical_allowance, cea.special_allowance,
                       cea.bonus_allowance,
                       ced.provident_fund, ced.esi, ced.professional_tax, ced.tds,
                       ced.national_pension_system
                FROM company_employee ce
                JOIN company c ON c.id = ce.company_id
                LEFT JOIN company_branch cb ON cb.id = ce.company_branch_id
                LEFT JOIN company_employee_allowance cea ON cea.company_employee_id = ce.id AND cea.is_current = 1
                LEFT JOIN company_employee_deduction ced ON ced.company_employee_id = ce.id AND ced.is_current = 1
                WHERE ce.is_deleted = '0' AND LOWER(ce.employee_name) LIKE LOWER($1)
            """
            params = [f"%{employee_name}%"]

            if company_name:
                query += " AND LOWER(c.name) LIKE LOWER($2)"
                params.append(f"%{company_name}%")

            query = apply_company_filter(ctx, query, "ce")
            rows = fetch_all(query, params)

            if not rows:
                return {"error": f"Employee '{employee_name}' not found or you don't have permission to view this data"}

            if len(rows) > 1 and not company_name:
                return {
                    "error": "Multiple employees found. Please specify company_name.",
                    "matches": [{"employee_name": r["employee_name"], "company_name": r["company_name"], "designation": r["designation"]} for r in rows]
                }

            row = rows[0]
        else:
            # Default to self
            pc = ctx.primary_company
            if not pc:
                return {"error": "No company association found."}

            query = """
                SELECT c.name as company_name, ce.designation, ce.basic_salary,
                       cea.house_rent_allowance, cea.dearness_allowance, cea.travel_allowance,
                       cea.conveyance_allowance, cea.medical_allowance, cea.special_allowance,
                       cea.bonus_allowance,
                       ced.provident_fund, ced.esi, ced.professional_tax, ced.tds,
                       ced.national_pension_system
                FROM company_employee ce
                JOIN company c ON c.id = ce.company_id
                LEFT JOIN company_employee_allowance cea ON cea.company_employee_id = ce.id AND cea.is_current = 1
                LEFT JOIN company_employee_deduction ced ON ced.company_employee_id = ce.id AND ced.is_current = 1
                WHERE ce.id = $1
            """
            row = fetch_one(query, [pc.company_employee_id])

            if not row:
                return {"error": "Salary details not found"}

            row["employee_name"] = ctx.user_name

        # Calculate gross and net
        basic = row.get("basic_salary") or 0
        hra = row.get("house_rent_allowance") or 0
        da = row.get("dearness_allowance") or 0
        ta = row.get("travel_allowance") or 0
        ca = row.get("conveyance_allowance") or 0
        ma = row.get("medical_allowance") or 0
        sa = row.get("special_allowance") or 0
        ba = row.get("bonus_allowance") or 0

        pf = row.get("provident_fund") or 0
        esi = row.get("esi") or 0
        pt = row.get("professional_tax") or 0
        tds = row.get("tds") or 0
        nps = row.get("national_pension_system") or 0

        gross = basic + hra + da + ta + ca + ma + sa + ba
        total_deductions = pf + esi + pt + tds + nps
        net = gross - total_deductions

        return {
            "employee_name": row.get("employee_name"),
            "company_name": row.get("company_name"),
            "designation": row.get("designation"),
            "earnings": {
                "basic_salary": basic,
                "house_rent_allowance": hra,
                "dearness_allowance": da,
                "travel_allowance": ta,
                "conveyance_allowance": ca,
                "medical_allowance": ma,
                "special_allowance": sa,
                "bonus_allowance": ba,
                "total_earnings": gross
            },
            "deductions": {
                "provident_fund": pf,
                "esi": esi,
                "professional_tax": pt,
                "tds": tds,
                "national_pension_system": nps,
                "total_deductions": total_deductions
            },
            "net_salary": net,
            "_note": "Net Salary = Total Earnings - Total Deductions"
        }

    @mcp.tool()
    def get_salary_slip(employee_name: str = None, month: str = None, company_name: str = None) -> dict:
        """
        Get monthly salary slip.
        If employee_name is not provided, returns your own salary slip.
        Month format: YYYY-MM (defaults to previous month).
        """
        from datetime import datetime
        ctx = get_user_context()
        if not ctx:
            return {"error": "Not authenticated. Please login first."}

        if not month:
            # Default to previous month
            now = datetime.now()
            if now.month == 1:
                month = f"{now.year - 1}-12"
            else:
                month = f"{now.year}-{now.month - 1:02d}"

        if employee_name:
            # Search for the employee
            query = """
                SELECT ss.employee_name, ss.company_name, ss.designation,
                       ss.from_date, ss.to_date, ss.date as slip_date,
                       ss.basic_salary, ss.house_rent_allowance, ss.dearness_allowance,
                       ss.bonus_allowance, ss.travel_allowance, ss.conveyance_allowance,
                       ss.medical_allowance, ss.special_allowance, ss.overtime_allowance,
                       ss.provident_fund, ss.esi, ss.professional_tax, ss.tds,
                       ss.national_pension_system, ss.advance_salary_installment,
                       ss.total_allowance, ss.total_deduction,
                       ss.gross_salary, ss.net_pay_amount, ss.net_pay_amount_in_words,
                       ss.day_in_month, ss.working_day_in_month, ss.present, ss.absent,
                       ss.half_day, ss.late_day, ss.holiday, ss.week_off_day,
                       ss.this_month_paid_leave_taken, ss.unpaid_leave_taken
                FROM company_employee_salary_slip ss
                JOIN company_employee ce ON ce.id = ss.company_employee_id
                WHERE LOWER(ce.employee_name) LIKE LOWER($1)
                  AND TO_CHAR(ss.date, 'YYYY-MM') = $2
                  AND ss.status = 1 AND ce.is_deleted = '0'
            """
            params = [f"%{employee_name}%", month]

            if company_name:
                query += " AND LOWER(ss.company_name) LIKE LOWER($3)"
                params.append(f"%{company_name}%")

            query = apply_company_filter(ctx, query, "ss")
            rows = fetch_all(query, params)

            if not rows:
                return {"error": f"No salary slip found for {employee_name} in {month}"}

            if len(rows) > 1 and not company_name:
                return {
                    "error": "Multiple salary slips found. Please specify company_name.",
                    "matches": [{"employee_name": r["employee_name"], "company_name": r["company_name"]} for r in rows]
                }

            row = rows[0]
        else:
            # Default to self
            pc = ctx.primary_company
            if not pc:
                return {"error": "No company association found."}

            query = """
                SELECT ss.employee_name, ss.company_name, ss.designation,
                       ss.from_date, ss.to_date, ss.date as slip_date,
                       ss.basic_salary, ss.house_rent_allowance, ss.dearness_allowance,
                       ss.bonus_allowance, ss.travel_allowance, ss.conveyance_allowance,
                       ss.medical_allowance, ss.special_allowance, ss.overtime_allowance,
                       ss.provident_fund, ss.esi, ss.professional_tax, ss.tds,
                       ss.national_pension_system, ss.advance_salary_installment,
                       ss.total_allowance, ss.total_deduction,
                       ss.gross_salary, ss.net_pay_amount, ss.net_pay_amount_in_words,
                       ss.day_in_month, ss.working_day_in_month, ss.present, ss.absent,
                       ss.half_day, ss.late_day, ss.holiday, ss.week_off_day,
                       ss.this_month_paid_leave_taken, ss.unpaid_leave_taken
                FROM company_employee_salary_slip ss
                WHERE ss.company_employee_id = $1
                  AND TO_CHAR(ss.date, 'YYYY-MM') = $2
                  AND ss.status = 1
            """
            row = fetch_one(query, [pc.company_employee_id, month])

            if not row:
                return {"error": f"No salary slip found for {month}"}

        return {
            "employee_name": row.get("employee_name"),
            "company_name": row.get("company_name"),
            "designation": row.get("designation"),
            "pay_period": {
                "from_date": str(row.get("from_date")),
                "to_date": str(row.get("to_date")),
                "slip_date": str(row.get("slip_date"))
            },
            "earnings": {
                "basic_salary": row.get("basic_salary"),
                "house_rent_allowance": row.get("house_rent_allowance"),
                "dearness_allowance": row.get("dearness_allowance"),
                "travel_allowance": row.get("travel_allowance"),
                "conveyance_allowance": row.get("conveyance_allowance"),
                "medical_allowance": row.get("medical_allowance"),
                "special_allowance": row.get("special_allowance"),
                "bonus_allowance": row.get("bonus_allowance"),
                "overtime_allowance": row.get("overtime_allowance"),
                "total_earnings": row.get("total_allowance")
            },
            "deductions": {
                "provident_fund": row.get("provident_fund"),
                "esi": row.get("esi"),
                "professional_tax": row.get("professional_tax"),
                "tds": row.get("tds"),
                "national_pension_system": row.get("national_pension_system"),
                "advance_salary_installment": row.get("advance_salary_installment"),
                "total_deductions": row.get("total_deduction")
            },
            "attendance_for_month": {
                "days_in_month": row.get("day_in_month"),
                "working_days": row.get("working_day_in_month"),
                "present": row.get("present"),
                "absent": row.get("absent"),
                "half_days": row.get("half_day"),
                "late_days": row.get("late_day"),
                "holidays": row.get("holiday"),
                "week_offs": row.get("week_off_day"),
                "paid_leave_taken": row.get("this_month_paid_leave_taken"),
                "unpaid_leave_taken": row.get("unpaid_leave_taken")
            },
            "net_pay": {
                "gross_salary": row.get("gross_salary"),
                "net_pay_amount": row.get("net_pay_amount"),
                "in_words": row.get("net_pay_amount_in_words")
            },
            "_note": "Net Pay = Gross Salary - Total Deductions"
        }
