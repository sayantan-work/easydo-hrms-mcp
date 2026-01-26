"""Salary tools for MCP server."""
from ..auth import get_user_context
from ..db import fetch_all, fetch_one
from ..rbac import apply_company_filter


def register(mcp):
    """Register salary tools with MCP server."""

    @mcp.tool()
    def get_salary(employee_name: str = None, company_name: str = None, branch_name: str = None, list_all: bool = False) -> dict:
        """
        Get current salary details including basic pay, allowances, and deductions.

        Usage modes:
        - No params: Returns your own salary
        - employee_name: Returns specific employee's salary
        - company_name + list_all=True: Returns all salaries in that company (sorted by net salary desc)
        - branch_name + list_all=True: Returns all salaries in that branch
        - company_name/branch_name without list_all: Returns your salary filtered by company/branch

        Use list_all=True with company_name or branch_name to get salary list for analytics.
        """
        ctx = get_user_context()
        if not ctx:
            return {"error": "Not authenticated. Please login first."}

        # Mode: List all salaries for company/branch
        if list_all and (company_name or branch_name):
            query = """
                SELECT ce.employee_name, ce.designation, c.name as company_name,
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
            query += " ORDER BY ce.basic_salary DESC NULLS LAST"
            rows = fetch_all(query, params)

            if not rows:
                return {"error": "No employees found with the given filters"}

            # Calculate net salary for each employee
            salaries = []
            for row in rows:
                basic = row.get("basic_salary") or 0
                hra = row.get("house_rent_allowance") or 0
                da = row.get("dearness_allowance") or 0
                ta = row.get("travel_allowance") or 0
                ca = row.get("conveyance_allowance") or 0
                ma = row.get("medical_allowance") or 0
                sa = row.get("special_allowance") or 0
                ba = row.get("bonus_allowance") or 0
                gross = basic + hra + da + ta + ca + ma + sa + ba

                pf = row.get("provident_fund") or 0
                esi = row.get("esi") or 0
                pt = row.get("professional_tax") or 0
                tds = row.get("tds") or 0
                nps = row.get("national_pension_system") or 0
                total_ded = pf + esi + pt + tds + nps
                net = gross - total_ded

                salaries.append({
                    "employee_name": row.get("employee_name"),
                    "designation": row.get("designation"),
                    "branch": row.get("branch_name"),
                    "company": row.get("company_name"),
                    "gross_salary": gross,
                    "total_deductions": total_ded,
                    "net_salary": net
                })

            # Sort by net salary descending
            salaries.sort(key=lambda x: x["net_salary"], reverse=True)

            result = {
                "count": len(salaries),
                "salaries": salaries,
                "highest_earner": salaries[0] if salaries else None,
                "lowest_earner": salaries[-1] if salaries else None
            }
            if company_name:
                result["company_filter"] = company_name
            if branch_name:
                result["branch_filter"] = branch_name
            return result

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
        import calendar
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

        # Parse month for calendar days calculation
        try:
            year_num, month_num = map(int, month.split("-"))
            days_in_month = calendar.monthrange(year_num, month_num)[1]
        except:
            days_in_month = 30  # fallback

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
                       ss.this_month_paid_leave_taken, ss.unpaid_leave_taken,
                       cb.allowed_late_day, cb.salary_calculation_type,
                       ce.date_of_joining
                FROM company_employee_salary_slip ss
                JOIN company_employee ce ON ce.id = ss.company_employee_id
                LEFT JOIN company_branch cb ON cb.id = ce.company_branch_id
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
                       ss.this_month_paid_leave_taken, ss.unpaid_leave_taken,
                       cb.allowed_late_day, cb.salary_calculation_type,
                       ce.date_of_joining
                FROM company_employee_salary_slip ss
                JOIN company_employee ce ON ce.id = ss.company_employee_id
                LEFT JOIN company_branch cb ON cb.id = ce.company_branch_id
                WHERE ss.company_employee_id = $1
                  AND TO_CHAR(ss.date, 'YYYY-MM') = $2
                  AND ss.status = 1
            """
            row = fetch_one(query, [pc.company_employee_id, month])

            if not row:
                return {"error": f"No salary slip found for {month}"}

        # Calculate attendance-based deductions breakdown
        # Note: gross_salary field may contain JSON, use total_allowance instead
        total_allowance = row.get("total_allowance")
        try:
            gross = float(total_allowance) if total_allowance else 0
        except (ValueError, TypeError):
            gross = 0

        absent_days = float(row.get("absent") or 0)
        half_days = float(row.get("half_day") or 0)
        late_days = float(row.get("late_day") or 0)
        allowed_late = row.get("allowed_late_day") or 0
        salary_calc_type = row.get("salary_calculation_type") or "month_total_day"

        # Use day_in_month from salary slip (actual pay period days) instead of calculated month days
        try:
            pay_period_days = int(float(row.get("day_in_month") or days_in_month))
        except (ValueError, TypeError):
            pay_period_days = days_in_month

        # Calculate pre-joining days if employee joined mid-month
        date_of_joining = row.get("date_of_joining")
        from_date = row.get("from_date")
        pre_joining_days = 0
        is_joining_month = False

        if date_of_joining and from_date:
            try:
                # Parse dates - handle both string and datetime formats
                doj_str = str(date_of_joining).split("T")[0].split(" ")[0]
                from_str = str(from_date).split("T")[0].split(" ")[0]

                doj_parts = doj_str.split("-")
                from_parts = from_str.split("-")

                # Check if DOJ is in the pay period month
                if len(doj_parts) >= 3 and len(from_parts) >= 3:
                    doj_year, doj_month, doj_day = int(doj_parts[0]), int(doj_parts[1]), int(doj_parts[2])
                    from_year, from_month = int(from_parts[0]), int(from_parts[1])

                    if doj_year == from_year and doj_month == from_month:
                        # Employee joined in this pay period month
                        is_joining_month = True
                        pre_joining_days = doj_day - 1  # Days before joining
            except:
                pass

        # Calculate daily rate based on salary calculation type
        if salary_calc_type == "month_total_day":
            daily_rate = round(gross / pay_period_days, 2) if pay_period_days > 0 else 0
            rate_basis = "calendar_days"
        else:
            working_days = float(row.get("working_day_in_month") or pay_period_days)
            daily_rate = round(gross / working_days, 2) if working_days > 0 else 0
            rate_basis = "working_days"

        # Calculate deductions
        absent_deduction = round(absent_days * daily_rate, 2)
        half_day_deduction = round(half_days * 0.5 * daily_rate, 2)

        # Late deduction (every X lates = 1 absent, only whole multiples count)
        # e.g., if allowed_late=3: 1-2 lates=0, 3 lates=1, 4-5 lates=1, 6 lates=2
        if allowed_late and allowed_late > 0 and late_days >= allowed_late:
            effective_absent_from_late = int(late_days // allowed_late)  # floor division
            late_deduction = round(effective_absent_from_late * daily_rate, 2)
            late_policy_note = f"{int(late_days)} late days // {allowed_late} = {effective_absent_from_late} absent deductions"
        else:
            effective_absent_from_late = 0
            late_deduction = 0
            if allowed_late and allowed_late > 0 and late_days > 0:
                late_policy_note = f"{int(late_days)} late days (within {allowed_late}-day allowance, no penalty)"
            else:
                late_policy_note = "No late deduction policy applied"

        total_attendance_deduction = round(absent_deduction + half_day_deduction + late_deduction, 2)

        return {
            "employee_name": row.get("employee_name"),
            "company_name": row.get("company_name"),
            "designation": row.get("designation"),
            "date_of_joining": str(date_of_joining).split("T")[0].split(" ")[0] if date_of_joining else None,
            "pay_period": {
                "from_date": str(row.get("from_date")),
                "to_date": str(row.get("to_date")),
                "slip_date": str(row.get("slip_date")),
                "is_joining_month": is_joining_month
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
            "statutory_deductions": {
                "provident_fund": row.get("provident_fund"),
                "esi": row.get("esi"),
                "professional_tax": row.get("professional_tax"),
                "tds": row.get("tds"),
                "national_pension_system": row.get("national_pension_system"),
                "advance_salary_installment": row.get("advance_salary_installment"),
                "total_statutory": row.get("total_deduction")
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
            "attendance_deductions": {
                "daily_rate": daily_rate,
                "daily_rate_basis": rate_basis,
                "absent_deduction": {
                    "days": absent_days,
                    "pre_joining_days": pre_joining_days if is_joining_month else None,
                    "actual_absent_days": max(0, absent_days - pre_joining_days) if is_joining_month and pre_joining_days > 0 else absent_days,
                    "amount": absent_deduction,
                    "formula": f"{absent_days} days x {daily_rate} = {absent_deduction}",
                    "_note": f"Includes {pre_joining_days} pre-joining days (joined on day {pre_joining_days + 1})" if is_joining_month and pre_joining_days > 0 else None
                },
                "half_day_deduction": {
                    "days": half_days,
                    "amount": half_day_deduction,
                    "formula": f"{half_days} days x 0.5 x {daily_rate} = {half_day_deduction}"
                },
                "late_deduction": {
                    "late_days": late_days,
                    "lates_per_absent": allowed_late if allowed_late else None,
                    "effective_absent": round(effective_absent_from_late, 2),
                    "amount": late_deduction,
                    "_note": late_policy_note
                },
                "total_attendance_deduction": total_attendance_deduction,
                "_note": f"Daily Rate = Gross ({gross}) / {pay_period_days if rate_basis == 'calendar_days' else 'Working'} Days = {daily_rate}"
            },
            "net_pay": {
                "gross_salary": gross,
                "total_deductions": row.get("total_deduction"),
                "net_pay_amount": row.get("net_pay_amount"),
                "in_words": row.get("net_pay_amount_in_words")
            },
            "_note": "Net Pay = Gross Salary - Total Deductions (statutory + attendance-based)"
        }
