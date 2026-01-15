"""Location tracking tools for MCP server."""
from datetime import datetime
from ..auth import get_user_context
from ..db import fetch_all, fetch_one
from ..rbac import apply_company_filter


def register(mcp):
    """Register location tracking tools with MCP server."""

    @mcp.tool()
    def get_employee_location(employee_name: str = None, company_name: str = None) -> dict:
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

        if employee_name:
            query += f" AND LOWER(ce.employee_name) LIKE LOWER(${param_idx})"
            params.append(f"%{employee_name}%")
            param_idx += 1
        elif ctx.primary_company:
            query += f" AND ce.id = ${param_idx}"
            params.append(ctx.primary_company.company_employee_id)
            param_idx += 1

        if company_name:
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
    def get_location_history(employee_name: str, date: str = None, company_name: str = None) -> dict:
        """
        Get location trail/history for an employee on a specific date.
        Date format: YYYY-MM-DD (defaults to today).
        """
        ctx = get_user_context()
        if not ctx:
            return {"error": "Not authenticated. Please login first."}

        if not date:
            date = datetime.now().strftime("%Y-%m-%d")

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
    def who_is_at_work(company_name: str = None, branch_name: str = None) -> dict:
        """
        Get list of employees who are currently at their designated work location.
        Based on today's latest location update.
        """
        ctx = get_user_context()
        if not ctx:
            return {"error": "Not authenticated. Please login first."}

        # First get latest location per employee, then filter for at_work
        query = """
            SELECT employee_name, branch_name, location_add_time, battery_percentage
            FROM (
                SELECT DISTINCT ON (ce.id)
                       ce.id, ce.employee_name, cb.name as branch_name,
                       lh.location_add_time, lh.battery_percentage,
                       lh.is_location_match, c.name as company_name
                FROM company_employee_location_history lh
                JOIN company_employee ce ON ce.id = lh.company_employee_id
                LEFT JOIN company c ON c.id = ce.company_id
                LEFT JOIN company_branch cb ON cb.id = ce.company_branch_id
                WHERE ce.is_deleted = '0' AND ce.employee_status = 3
                  AND lh.location_add_date = CURRENT_DATE
                ORDER BY ce.id, lh.created_at DESC
            ) latest
            WHERE is_location_match = 1
        """
        params = []
        param_idx = 1

        # Filters need to be in the subquery - rebuild query with filters
        subquery = """
            SELECT DISTINCT ON (ce.id)
                   ce.id, ce.employee_name, cb.name as branch_name,
                   lh.location_add_time, lh.battery_percentage,
                   lh.is_location_match
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

        query = f"""
            SELECT employee_name, branch_name, location_add_time, battery_percentage
            FROM ({subquery}) latest
            WHERE is_location_match = 1
        """

        rows = fetch_all(query, params) if params else fetch_all(query)

        # Group by branch
        branches = {}
        for row in rows:
            branch = row.get("branch_name") or "Unknown"
            if branch not in branches:
                branches[branch] = []
            branches[branch].append({
                "name": row.get("employee_name"),
                "last_update": row.get("location_add_time"),
                "battery": row.get("battery_percentage")
            })

        result = {
            "date": datetime.now().strftime("%Y-%m-%d"),
            "count": len(rows),
            "branches": branches
        }

        if company_name:
            result["company_filter"] = company_name
        if branch_name:
            result["branch_filter"] = branch_name

        return result

    @mcp.tool()
    def who_is_outside_work(company_name: str = None, branch_name: str = None) -> dict:
        """
        Get list of employees who are currently outside their designated work location.
        Includes field staff, remote workers, or employees in transit.
        """
        ctx = get_user_context()
        if not ctx:
            return {"error": "Not authenticated. Please login first."}

        # First get latest location per employee, then filter for outside work
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

        query = f"""
            SELECT employee_name, branch_name, address, city,
                   location_add_time, battery_percentage, activity_status
            FROM ({subquery}) latest
            WHERE is_location_match = 0 OR is_location_match IS NULL
        """

        rows = fetch_all(query, params) if params else fetch_all(query)

        # Group by branch
        branches = {}
        for row in rows:
            branch = row.get("branch_name") or "Unknown"
            if branch not in branches:
                branches[branch] = []
            branches[branch].append({
                "name": row.get("employee_name"),
                "location": row.get("address") or row.get("city") or "Unknown",
                "last_update": row.get("location_add_time"),
                "activity": row.get("activity_status"),
                "battery": row.get("battery_percentage")
            })

        result = {
            "date": datetime.now().strftime("%Y-%m-%d"),
            "count": len(rows),
            "branches": branches
        }

        if company_name:
            result["company_filter"] = company_name
        if branch_name:
            result["branch_filter"] = branch_name

        return result

    @mcp.tool()
    def who_is_offline(company_name: str = None, branch_name: str = None) -> dict:
        """
        Get list of employees with no location update today.
        Could indicate app not running, phone off, or no network.
        """
        ctx = get_user_context()
        if not ctx:
            return {"error": "Not authenticated. Please login first."}

        # Get employees who have NO location record today
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
        query += " ORDER BY cb.name, ce.employee_name"

        rows = fetch_all(query, params) if params else fetch_all(query)

        # Group by branch
        branches = {}
        for row in rows:
            branch = row.get("branch_name") or "Unknown"
            if branch not in branches:
                branches[branch] = []
            branches[branch].append(row.get("employee_name"))

        result = {
            "date": datetime.now().strftime("%Y-%m-%d"),
            "count": len(rows),
            "branches": branches,
            "_note": "No location update today - app may not be running"
        }

        if company_name:
            result["company_filter"] = company_name
        if branch_name:
            result["branch_filter"] = branch_name

        return result
