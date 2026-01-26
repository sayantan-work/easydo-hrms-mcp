"""HR Reports tools for MCP server."""
from datetime import datetime
from ..auth import get_user_context
from ..db import fetch_all, fetch_one
from ..rbac import apply_company_filter


def register(mcp):
    """Register HR reports tools with MCP server."""

    @mcp.tool()
    def get_birthdays(month: int = None, company_name: str = None, branch_name: str = None) -> dict:
        """
        Get birthdays for a month.
        Month defaults to current month (1-12).
        Use company_name and/or branch_name to filter.
        """
        ctx = get_user_context()
        if not ctx:
            return {"error": "Not authenticated. Please login first."}

        if not month:
            month = datetime.now().month

        # Format month as -MM- pattern for LIKE matching (date_of_birth is varchar YYYY-MM-DD)
        month_pattern = f"%-{month:02d}-%"

        query = """
            SELECT ce.employee_name, ce.designation, ce.date_of_birth,
                   cd.name as department_name, cb.name as branch_name, c.name as company_name
            FROM company_employee ce
            LEFT JOIN company_department cd ON cd.id = ce.company_role_id
            LEFT JOIN company_branch cb ON cb.id = ce.company_branch_id
            LEFT JOIN company c ON c.id = ce.company_id
            WHERE ce.is_deleted = '0' AND ce.employee_status = 3
            AND ce.date_of_birth IS NOT NULL AND ce.date_of_birth != ''
            AND ce.date_of_birth LIKE $1
        """
        params = [month_pattern]
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
        query += " ORDER BY SUBSTRING(ce.date_of_birth, 9, 2)"

        try:
            rows = fetch_all(query, params)
        except Exception:
            rows = []

        # Group by upcoming (today and later in month) vs passed
        today = datetime.now()
        today_day = today.day
        today_month = today.month
        current_year = today.year
        upcoming = []
        passed = []
        birthdays_with_age = []

        for r in rows:
            dob = r.get("date_of_birth")
            if dob:
                try:
                    dob_str = str(dob).split(" ")[0]  # Handle datetime format
                    year = int(dob_str.split("-")[0])
                    day = int(dob_str.split("-")[2])

                    # Calculate nth birthday
                    nth_birthday = current_year - year
                    r["nth_birthday"] = nth_birthday
                    r["birthday_label"] = f"{nth_birthday}{'st' if nth_birthday % 10 == 1 and nth_birthday != 11 else 'nd' if nth_birthday % 10 == 2 and nth_birthday != 12 else 'rd' if nth_birthday % 10 == 3 and nth_birthday != 13 else 'th'} birthday"

                    # Determine if birthday is upcoming or passed
                    # Compare month first, then day if same month
                    if month > today_month:
                        # Future month - all are upcoming
                        upcoming.append(r)
                    elif month < today_month:
                        # Past month - all have passed
                        passed.append(r)
                    else:
                        # Current month - compare day
                        if day >= today_day:
                            upcoming.append(r)
                        else:
                            passed.append(r)
                except:
                    r["nth_birthday"] = None
                    r["birthday_label"] = None
                    upcoming.append(r)

            birthdays_with_age.append(r)

        result = {
            "month": month,
            "count": len(rows),
            "upcoming_this_month": len(upcoming),
            "already_passed": len(passed),
            "birthdays": birthdays_with_age
        }

        if company_name:
            result["company_filter"] = company_name
        if branch_name:
            result["branch_filter"] = branch_name

        return result

    @mcp.tool()
    def get_employee_movements(
        movement_type: str = "all",
        month: str = None,
        company_name: str = None,
        branch_name: str = None
    ) -> dict:
        """
        Get employee movements (joiners and/or exits) for a month.

        Movement type options:
        - 'joined': Employees who joined in the month
        - 'exited': Employees who left/exited in the month
        - 'all': Both joiners and exits with summary

        Month format: YYYY-MM (defaults to current month).
        Use company_name and/or branch_name to filter.
        """
        ctx = get_user_context()
        if not ctx:
            return {"error": "Not authenticated. Please login first."}

        movement_type = movement_type.lower().strip()
        valid_types = ['joined', 'exited', 'all']
        if movement_type not in valid_types:
            return {"error": f"Invalid movement_type '{movement_type}'. Use: {', '.join(valid_types)}"}

        if not month:
            month = datetime.now().strftime("%Y-%m")

        result = {"month": month}

        def add_filters(res):
            if company_name:
                res["company_filter"] = company_name
            if branch_name:
                res["branch_filter"] = branch_name
            return res

        def build_base_params():
            params = []
            param_idx = 1
            return params, param_idx

        def add_company_branch_filters(query, params, param_idx):
            if company_name:
                query += f" AND LOWER(c.name) LIKE LOWER(${param_idx})"
                params.append(f"%{company_name}%")
                param_idx += 1
            if branch_name:
                query += f" AND LOWER(cb.name) LIKE LOWER(${param_idx})"
                params.append(f"%{branch_name}%")
                param_idx += 1
            return query, params, param_idx

        # JOINED employees
        joiners = []
        if movement_type in ['joined', 'all']:
            month_pattern = f"{month}-%"
            query = """
                SELECT ce.employee_name, ce.designation, ce.date_of_joining,
                       cd.name as department_name, cb.name as branch_name, c.name as company_name
                FROM company_employee ce
                LEFT JOIN company_department cd ON cd.id = ce.company_role_id
                LEFT JOIN company_branch cb ON cb.id = ce.company_branch_id
                LEFT JOIN company c ON c.id = ce.company_id
                WHERE ce.is_deleted = '0'
                AND ce.date_of_joining IS NOT NULL AND ce.date_of_joining != ''
                AND ce.date_of_joining LIKE $1
            """
            params = [month_pattern]
            param_idx = 2
            query, params, param_idx = add_company_branch_filters(query, params, param_idx)
            query = apply_company_filter(ctx, query, "ce")
            query += " ORDER BY ce.date_of_joining DESC"

            try:
                rows = fetch_all(query, params)
                joiners = [
                    {
                        "employee_name": r.get("employee_name"),
                        "designation": r.get("designation"),
                        "department": r.get("department_name"),
                        "branch": r.get("branch_name"),
                        "company": r.get("company_name"),
                        "date_of_joining": str(r.get("date_of_joining"))
                    }
                    for r in rows
                ]
            except Exception:
                joiners = []

            if movement_type == 'joined':
                result["count"] = len(joiners)
                result["new_joiners"] = joiners
                return add_filters(result)

        # EXITED employees
        exits = []
        if movement_type in ['exited', 'all']:
            query = """
                SELECT ce.employee_name, ce.designation, ce.employee_email,
                       ce.date_of_joining, ce.date_of_exit,
                       cd.name as department_name, cb.name as branch_name, c.name as company_name
                FROM company_employee ce
                LEFT JOIN company_department cd ON cd.id = ce.company_role_id
                LEFT JOIN company_branch cb ON cb.id = ce.company_branch_id
                LEFT JOIN company c ON c.id = ce.company_id
                WHERE ce.date_of_exit IS NOT NULL
                  AND TO_CHAR(ce.date_of_exit, 'YYYY-MM') = $1
            """
            params = [month]
            param_idx = 2
            query, params, param_idx = add_company_branch_filters(query, params, param_idx)
            query = apply_company_filter(ctx, query, "ce")
            query += " ORDER BY ce.date_of_exit DESC"

            rows = fetch_all(query, params)
            exits = [
                {
                    "employee_name": r.get("employee_name"),
                    "designation": r.get("designation"),
                    "department": r.get("department_name"),
                    "branch": r.get("branch_name"),
                    "company": r.get("company_name"),
                    "date_of_joining": str(r.get("date_of_joining")),
                    "date_of_exit": str(r.get("date_of_exit"))
                }
                for r in rows
            ]

            if movement_type == 'exited':
                result["count"] = len(exits)
                result["exits"] = exits
                return add_filters(result)

        # ALL - return both with summary
        result["summary"] = {
            "joined": len(joiners),
            "exited": len(exits),
            "net_change": len(joiners) - len(exits)
        }
        result["new_joiners"] = joiners
        result["exits"] = exits
        return add_filters(result)
