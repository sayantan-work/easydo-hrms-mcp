"""Location tracking tools for MCP server."""
from datetime import datetime
from ..auth import get_user_context
from ..db import fetch_all, fetch_one
from ..rbac import apply_company_filter


def register(mcp):
    """Register location tracking tools with MCP server."""

    @mcp.tool()
    def get_employee_location(employee_name: str = None, company_name: str = None, employee_id: int = None) -> dict:
        """
        Get current/last known location of an employee.
        If employee_name is not provided, returns your own location.
        """
        ctx = get_user_context()
        if not ctx:
            return {"error": "Not authenticated. Please login first."}

        query = """
            SELECT ce.employee_name, cb.name as branch_name, c.name as company_name,
                   lh.address, lh.city, lh.state, lh.country,
                   lh.latitude, lh.longitude,
                   lh.location_add_date, lh.location_add_time,
                   lh.is_location_match, lh.battery_percentage,
                   lh.activity_status, lh.wifi_name, lh.accuracy
            FROM company_employee_location_history lh
            JOIN company_employee ce ON ce.id = lh.company_employee_id
            LEFT JOIN company c ON c.id = ce.company_id
            LEFT JOIN company_branch cb ON cb.id = ce.company_branch_id
            WHERE ce.is_deleted = '0'
        """
        params = []
        param_idx = 1

        # Priority: employee_id > employee_name > self
        if employee_id:
            query += f" AND ce.id = ${param_idx}"
            params.append(employee_id)
            param_idx += 1
        elif employee_name:
            # First check if multiple employees match
            check_query = """
                SELECT ce.id, ce.employee_name, ce.designation, c.name as company_name, cb.name as branch_name
                FROM company_employee ce
                JOIN company c ON c.id = ce.company_id
                LEFT JOIN company_branch cb ON cb.id = ce.company_branch_id
                WHERE ce.is_deleted = '0' AND LOWER(ce.employee_name) LIKE LOWER($1)
            """
            check_params = [f"%{employee_name}%"]
            if company_name:
                check_query += " AND LOWER(c.name) LIKE LOWER($2)"
                check_params.append(f"%{company_name}%")
            check_query = apply_company_filter(ctx, check_query, "ce")
            check_rows = fetch_all(check_query, check_params)

            if not check_rows:
                return {"error": f"Employee '{employee_name}' not found"}
            if len(check_rows) > 1:
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
                        } for r in check_rows
                    ]
                }

            query += f" AND LOWER(ce.employee_name) LIKE LOWER(${param_idx})"
            params.append(f"%{employee_name}%")
            param_idx += 1
        elif ctx.primary_company:
            query += f" AND ce.id = ${param_idx}"
            params.append(ctx.primary_company.company_employee_id)
            param_idx += 1

        if company_name and not employee_id:
            query += f" AND LOWER(c.name) LIKE LOWER(${param_idx})"
            params.append(f"%{company_name}%")
            param_idx += 1

        query = apply_company_filter(ctx, query, "ce")
        query += " ORDER BY lh.created_at DESC LIMIT 1"

        row = fetch_one(query, params)

        if not row:
            return {"error": "No location data found for this employee"}

        return {
            "employee_name": row.get("employee_name"),
            "branch": row.get("branch_name"),
            "company": row.get("company_name"),
            "location": {
                "address": row.get("address"),
                "city": row.get("city"),
                "state": row.get("state"),
                "country": row.get("country"),
                "coordinates": {
                    "latitude": row.get("latitude"),
                    "longitude": row.get("longitude")
                },
                "accuracy": row.get("accuracy")
            },
            "timestamp": {
                "date": str(row.get("location_add_date"))[:10] if row.get("location_add_date") else None,
                "time": row.get("location_add_time")
            },
            "status": {
                "at_work_location": row.get("is_location_match") == 1,
                "activity": row.get("activity_status"),
                "battery": row.get("battery_percentage"),
                "wifi": row.get("wifi_name")
            }
        }

    @mcp.tool()
    def get_location_history(employee_name: str = None, date: str = None, company_name: str = None, employee_id: int = None) -> dict:
        """
        Get location trail/history for an employee on a specific date.
        Date format: YYYY-MM-DD (defaults to today).
        """
        ctx = get_user_context()
        if not ctx:
            return {"error": "Not authenticated. Please login first."}

        if not date:
            date = datetime.now().strftime("%Y-%m-%d")

        # Need either employee_id or employee_name
        if not employee_id and not employee_name:
            return {"error": "Please provide either employee_name or employee_id"}

        # If employee_id provided, use it directly
        if employee_id:
            query = """
                SELECT ce.employee_name, cb.name as branch_name,
                       lh.address, lh.city, lh.state,
                       lh.latitude, lh.longitude,
                       lh.location_add_time,
                       lh.is_location_match, lh.battery_percentage,
                       lh.activity_status, lh.distance
                FROM company_employee_location_history lh
                JOIN company_employee ce ON ce.id = lh.company_employee_id
                LEFT JOIN company c ON c.id = ce.company_id
                LEFT JOIN company_branch cb ON cb.id = ce.company_branch_id
                WHERE ce.is_deleted = '0'
                  AND ce.id = $1
                  AND lh.location_add_date = $2
            """
            query = apply_company_filter(ctx, query, "ce")
            query += " ORDER BY lh.location_time ASC"
            rows = fetch_all(query, [employee_id, date])

            if not rows:
                return {"error": f"No location history found for employee ID {employee_id} on {date}"}
        else:
            # Check for multiple matches first
            check_query = """
                SELECT ce.id, ce.employee_name, ce.designation, c.name as company_name, cb.name as branch_name
                FROM company_employee ce
                JOIN company c ON c.id = ce.company_id
                LEFT JOIN company_branch cb ON cb.id = ce.company_branch_id
                WHERE ce.is_deleted = '0' AND LOWER(ce.employee_name) LIKE LOWER($1)
            """
            check_params = [f"%{employee_name}%"]
            if company_name:
                check_query += " AND LOWER(c.name) LIKE LOWER($2)"
                check_params.append(f"%{company_name}%")
            check_query = apply_company_filter(ctx, check_query, "ce")
            check_rows = fetch_all(check_query, check_params)

            if not check_rows:
                return {"error": f"Employee '{employee_name}' not found"}
            if len(check_rows) > 1:
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
                        } for r in check_rows
                    ]
                }

            query = """
                SELECT ce.employee_name, cb.name as branch_name,
                       lh.address, lh.city, lh.state,
                       lh.latitude, lh.longitude,
                       lh.location_add_time,
                       lh.is_location_match, lh.battery_percentage,
                       lh.activity_status, lh.distance
                FROM company_employee_location_history lh
                JOIN company_employee ce ON ce.id = lh.company_employee_id
                LEFT JOIN company c ON c.id = ce.company_id
                LEFT JOIN company_branch cb ON cb.id = ce.company_branch_id
                WHERE ce.is_deleted = '0'
                  AND LOWER(ce.employee_name) LIKE LOWER($1)
                  AND lh.location_add_date = $2
            """
            params = [f"%{employee_name}%", date]
            param_idx = 3

            if company_name:
                query += f" AND LOWER(c.name) LIKE LOWER(${param_idx})"
                params.append(f"%{company_name}%")
                param_idx += 1

            query = apply_company_filter(ctx, query, "ce")
            query += " ORDER BY lh.location_time ASC"

            rows = fetch_all(query, params)

            if not rows:
                return {"error": f"No location history found for '{employee_name}' on {date}"}

        # Build location trail
        trail = []
        for row in rows:
            trail.append({
                "time": row.get("location_add_time"),
                "address": row.get("address") or row.get("city") or "Unknown",
                "coordinates": {
                    "lat": row.get("latitude"),
                    "lng": row.get("longitude")
                },
                "at_work": row.get("is_location_match") == 1,
                "activity": row.get("activity_status"),
                "battery": row.get("battery_percentage"),
                "distance": row.get("distance")
            })

        return {
            "employee_name": rows[0].get("employee_name"),
            "branch": rows[0].get("branch_name"),
            "date": date,
            "total_points": len(trail),
            "trail": trail
        }

    @mcp.tool()
    def get_location_summary(company_name: str = None, branch_name: str = None) -> dict:
        """
        Get location summary counts: at work, outside work, offline (no update today).
        Use company_name and/or branch_name to filter.
        """
        ctx = get_user_context()
        if not ctx:
            return {"error": "Not authenticated. Please login first."}

        # Get all active employees
        emp_query = """
            SELECT ce.id, ce.employee_name, cb.name as branch_name
            FROM company_employee ce
            LEFT JOIN company c ON c.id = ce.company_id
            LEFT JOIN company_branch cb ON cb.id = ce.company_branch_id
            WHERE ce.is_deleted = '0' AND ce.employee_status = 3
        """
        params = []
        param_idx = 1

        if company_name:
            emp_query += f" AND LOWER(c.name) LIKE LOWER(${param_idx})"
            params.append(f"%{company_name}%")
            param_idx += 1

        if branch_name:
            emp_query += f" AND LOWER(cb.name) LIKE LOWER(${param_idx})"
            params.append(f"%{branch_name}%")
            param_idx += 1

        emp_query = apply_company_filter(ctx, emp_query, "ce")
        all_employees = fetch_all(emp_query, params) if params else fetch_all(emp_query)
        total_employees = len(all_employees)
        emp_ids = {row["id"] for row in all_employees}

        # Get today's location data with latest per employee
        loc_query = """
            SELECT DISTINCT ON (lh.company_employee_id)
                   lh.company_employee_id, lh.is_location_match
            FROM company_employee_location_history lh
            JOIN company_employee ce ON ce.id = lh.company_employee_id
            LEFT JOIN company c ON c.id = ce.company_id
            LEFT JOIN company_branch cb ON cb.id = ce.company_branch_id
            WHERE ce.is_deleted = '0' AND ce.employee_status = 3
              AND lh.location_add_date = CURRENT_DATE
        """
        loc_params = []
        loc_idx = 1

        if company_name:
            loc_query += f" AND LOWER(c.name) LIKE LOWER(${loc_idx})"
            loc_params.append(f"%{company_name}%")
            loc_idx += 1

        if branch_name:
            loc_query += f" AND LOWER(cb.name) LIKE LOWER(${loc_idx})"
            loc_params.append(f"%{branch_name}%")
            loc_idx += 1

        loc_query = apply_company_filter(ctx, loc_query, "ce")
        loc_query += " ORDER BY lh.company_employee_id, lh.created_at DESC"

        loc_rows = fetch_all(loc_query, loc_params) if loc_params else fetch_all(loc_query)

        at_work = 0
        outside_work = 0
        tracked_ids = set()

        for row in loc_rows:
            tracked_ids.add(row["company_employee_id"])
            if row.get("is_location_match") == 1:
                at_work += 1
            else:
                outside_work += 1

        offline = len(emp_ids - tracked_ids)

        result = {
            "date": datetime.now().strftime("%Y-%m-%d"),
            "total_employees": total_employees,
            "at_work": at_work,
            "outside_work": outside_work,
            "offline": offline,
            "_note": "offline = employees with no location update today"
        }

        if company_name:
            result["company_filter"] = company_name
        if branch_name:
            result["branch_filter"] = branch_name

        return result

    @mcp.tool()
    def get_employees_by_location(
        status: str = "all",
        company_name: str = None,
        branch_name: str = None
    ) -> dict:
        """
        Get employees grouped by their location status.
        Based on today's latest location update.

        Status options:
        - 'at_work': Employees at their designated work location
        - 'outside': Employees outside work location (field staff, remote, in transit)
        - 'offline': Employees with no location update today
        - 'all': Summary with counts for all statuses

        Use company_name and/or branch_name to filter.
        """
        ctx = get_user_context()
        if not ctx:
            return {"error": "Not authenticated. Please login first."}

        status = status.lower().strip()
        valid_statuses = ['at_work', 'outside', 'offline', 'all']
        if status not in valid_statuses:
            return {"error": f"Invalid status '{status}'. Use: {', '.join(valid_statuses)}"}

        result = {"date": datetime.now().strftime("%Y-%m-%d")}

        def add_filters(result):
            if company_name:
                result["company_filter"] = company_name
            if branch_name:
                result["branch_filter"] = branch_name
            return result

        def group_by_branch(rows, include_location=False):
            branches = {}
            for row in rows:
                branch = row.get("branch_name") or "Unknown"
                if branch not in branches:
                    branches[branch] = []
                emp_data = {
                    "name": row.get("employee_name"),
                    "last_update": row.get("location_add_time"),
                    "battery": row.get("battery_percentage")
                }
                if include_location:
                    emp_data["location"] = row.get("address") or row.get("city") or "Unknown"
                    emp_data["activity"] = row.get("activity_status")
                branches[branch].append(emp_data)
            return branches

        # Build base subquery for location data
        def build_location_subquery():
            params = []
            param_idx = 1
            subquery = """
                SELECT DISTINCT ON (ce.id)
                       ce.id, ce.employee_name, cb.name as branch_name,
                       lh.address, lh.city,
                       lh.location_add_time, lh.battery_percentage,
                       lh.activity_status, lh.is_location_match
                FROM company_employee_location_history lh
                JOIN company_employee ce ON ce.id = lh.company_employee_id
                LEFT JOIN company c ON c.id = ce.company_id
                LEFT JOIN company_branch cb ON cb.id = ce.company_branch_id
                WHERE ce.is_deleted = '0' AND ce.employee_status = 3
                  AND lh.location_add_date = CURRENT_DATE
            """
            if company_name:
                subquery += f" AND LOWER(c.name) LIKE LOWER(${param_idx})"
                params.append(f"%{company_name}%")
                param_idx += 1
            if branch_name:
                subquery += f" AND LOWER(cb.name) LIKE LOWER(${param_idx})"
                params.append(f"%{branch_name}%")
                param_idx += 1
            subquery = apply_company_filter(ctx, subquery, "ce")
            subquery += " ORDER BY ce.id, lh.created_at DESC"
            return subquery, params

        # AT_WORK employees
        if status in ['at_work', 'all']:
            subquery, params = build_location_subquery()
            query = f"""
                SELECT employee_name, branch_name, location_add_time, battery_percentage
                FROM ({subquery}) latest
                WHERE is_location_match = 1
            """
            rows = fetch_all(query, params) if params else fetch_all(query)

            if status == 'at_work':
                result["count"] = len(rows)
                result["branches"] = group_by_branch(rows)
            else:
                result["at_work_count"] = len(rows)

        # OUTSIDE employees
        if status in ['outside', 'all']:
            subquery, params = build_location_subquery()
            query = f"""
                SELECT employee_name, branch_name, address, city,
                       location_add_time, battery_percentage, activity_status
                FROM ({subquery}) latest
                WHERE is_location_match = 0 OR is_location_match IS NULL
            """
            rows = fetch_all(query, params) if params else fetch_all(query)

            if status == 'outside':
                result["count"] = len(rows)
                result["branches"] = group_by_branch(rows, include_location=True)
            else:
                result["outside_count"] = len(rows)

        # OFFLINE employees
        if status in ['offline', 'all']:
            params = []
            param_idx = 1
            query = """
                SELECT ce.employee_name, cb.name as branch_name
                FROM company_employee ce
                LEFT JOIN company c ON c.id = ce.company_id
                LEFT JOIN company_branch cb ON cb.id = ce.company_branch_id
                WHERE ce.is_deleted = '0' AND ce.employee_status = 3
                  AND ce.id NOT IN (
                      SELECT DISTINCT lh.company_employee_id
                      FROM company_employee_location_history lh
                      WHERE lh.location_add_date = CURRENT_DATE
                  )
            """
            if company_name:
                query += f" AND LOWER(c.name) LIKE LOWER(${param_idx})"
                params.append(f"%{company_name}%")
                param_idx += 1
            if branch_name:
                query += f" AND LOWER(cb.name) LIKE LOWER(${param_idx})"
                params.append(f"%{branch_name}%")
                param_idx += 1
            query = apply_company_filter(ctx, query, "ce")
            query += " ORDER BY cb.name, ce.employee_name"
            rows = fetch_all(query, params) if params else fetch_all(query)

            if status == 'offline':
                result["count"] = len(rows)
                branches = {}
                for row in rows:
                    branch = row.get("branch_name") or "Unknown"
                    if branch not in branches:
                        branches[branch] = []
                    branches[branch].append(row.get("employee_name"))
                result["branches"] = branches
                result["_note"] = "No location update today - app may not be running"
            else:
                result["offline_count"] = len(rows)

        return add_filters(result)
