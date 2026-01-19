"""Attendance tools for MCP server."""
import calendar
from datetime import datetime, timedelta, timezone
from ..auth import get_user_context
from ..db import fetch_all, fetch_one
from ..rbac import apply_company_filter


def register(mcp):
    """Register attendance tools with MCP server."""

    @mcp.tool()
    def get_time(timezone_name: str = "IST") -> dict:
        """
        Get current time. Defaults to IST (Indian Standard Time).
        Supported: IST, UTC, EST, PST, GMT, or offset like +05:30, -08:00
        """
        now_utc = datetime.now(timezone.utc)

        # Timezone offsets
        tz_offsets = {
            "IST": timedelta(hours=5, minutes=30),
            "UTC": timedelta(hours=0),
            "GMT": timedelta(hours=0),
            "EST": timedelta(hours=-5),
            "PST": timedelta(hours=-8),
            "CST": timedelta(hours=-6),
            "MST": timedelta(hours=-7),
        }

        tz_upper = timezone_name.upper().strip()

        if tz_upper in tz_offsets:
            offset = tz_offsets[tz_upper]
        elif timezone_name.startswith(("+", "-")):
            # Parse offset like +05:30 or -08:00
            try:
                sign = 1 if timezone_name[0] == "+" else -1
                parts = timezone_name[1:].split(":")
                hours = int(parts[0])
                minutes = int(parts[1]) if len(parts) > 1 else 0
                offset = timedelta(hours=sign * hours, minutes=sign * minutes)
            except:
                return {"error": f"Invalid timezone format: {timezone_name}. Use IST, UTC, or +05:30 format."}
        else:
            return {"error": f"Unknown timezone: {timezone_name}. Use IST, UTC, EST, PST, or +05:30 format."}

        local_time = now_utc + offset

        return {
            "timezone": timezone_name.upper() if timezone_name.upper() in tz_offsets else timezone_name,
            "datetime": local_time.strftime("%Y-%m-%d %H:%M:%S"),
            "date": local_time.strftime("%Y-%m-%d"),
            "time": local_time.strftime("%H:%M:%S"),
            "day": local_time.strftime("%A"),
            "timestamp": int(now_utc.timestamp()),
            "utc": now_utc.strftime("%Y-%m-%d %H:%M:%S")
        }

    @mcp.tool()
    def get_punch_history(employee_name: str = None, date: str = None, company_name: str = None) -> dict:
        """
        Get detailed punch in/out history for an employee.
        Date format: YYYY-MM-DD (defaults to today).
        Shows all punches with locations, timestamps, and calculates total worked hours.
        """
        ctx = get_user_context()
        if not ctx:
            return {"error": "Not authenticated. Please login first."}

        if not date:
            date = datetime.now().strftime("%Y-%m-%d")

        # Resolve employee
        if employee_name:
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
                return {"error": f"Employee '{employee_name}' not found"}
            if len(emp_rows) > 1 and not company_name:
                return {
                    "error": "Multiple employees found. Specify company_name.",
                    "matches": [{"name": r["employee_name"], "company": r["company_name"]} for r in emp_rows]
                }

            target_emp_id = emp_rows[0]["id"]
            target_name = emp_rows[0]["employee_name"]
            target_company = emp_rows[0]["company_name"]
            target_branch = emp_rows[0]["branch_name"]
        else:
            pc = ctx.primary_company
            if not pc:
                return {"error": "No company association found."}
            target_emp_id = pc.company_employee_id
            target_name = ctx.user_name
            target_company = pc.company_name
            target_branch = pc.branch_name

        # Get all punch records for the day
        query = """
            SELECT ca.check_in_time, ca.check_out_time,
                   ca.address as check_in_address, ca.check_out_address,
                   ca.check_in_location_name, ca.check_out_location_name,
                   ca.is_late, ca.is_half_day, ca.is_auto_check_out,
                   ca.total_minutes, ca.notes
            FROM company_attendance ca
            WHERE ca.company_employee_id = $1 AND ca.date = $2
            ORDER BY ca.check_in_time ASC
        """
        rows = fetch_all(query, [target_emp_id, date])

        if not rows:
            return {
                "employee_name": target_name,
                "date": date,
                "status": "No punch records found",
                "punches": []
            }

        # Process punch records
        punches = []
        total_worked_minutes = 0
        first_check_in = None
        last_check_out = None

        # IST offset for display
        ist_offset = timedelta(hours=5, minutes=30)

        for row in rows:
            check_in_ts = row.get("check_in_time")
            check_out_ts = row.get("check_out_time")

            # Convert to int if string
            if check_in_ts and isinstance(check_in_ts, str):
                check_in_ts = int(check_in_ts)
            if check_out_ts and isinstance(check_out_ts, str):
                check_out_ts = int(check_out_ts)

            # Convert timestamps to readable time (IST)
            check_in_str = None
            check_out_str = None

            if check_in_ts:
                check_in_dt = datetime.fromtimestamp(check_in_ts / 1000, tz=timezone.utc) + ist_offset
                check_in_str = check_in_dt.strftime("%I:%M %p")
                if first_check_in is None:
                    first_check_in = check_in_dt

            if check_out_ts:
                check_out_dt = datetime.fromtimestamp(check_out_ts / 1000, tz=timezone.utc) + ist_offset
                check_out_str = check_out_dt.strftime("%I:%M %p")
                last_check_out = check_out_dt

            # Calculate duration for this punch
            duration_mins = row.get("total_minutes") or 0
            total_worked_minutes += duration_mins

            punches.append({
                "check_in": check_in_str,
                "check_in_location": row.get("check_in_location_name") or row.get("check_in_address"),
                "check_out": check_out_str,
                "check_out_location": row.get("check_out_location_name") or row.get("check_out_address"),
                "duration_mins": round(duration_mins, 1),
                "is_late": row.get("is_late") == 1,
                "is_half_day": row.get("is_half_day") == 1,
                "auto_checkout": row.get("is_auto_check_out") == 1,
                "notes": row.get("notes")
            })

        # Calculate hours and minutes
        total_hours = int(total_worked_minutes // 60)
        remaining_mins = int(total_worked_minutes % 60)

        # Check if still checked in (no checkout on last punch)
        # Handle None, empty string, 0, "0" as no checkout
        last_checkout = rows[-1].get("check_out_time") if rows else None
        still_checked_in = not last_checkout or last_checkout == "0" or last_checkout == 0

        # If still checked in, calculate time till now
        current_session_mins = 0
        if still_checked_in and rows[-1].get("check_in_time"):
            now_utc = datetime.now(timezone.utc)
            last_check_in_ts = rows[-1]["check_in_time"]
            if isinstance(last_check_in_ts, str):
                last_check_in_ts = int(last_check_in_ts)
            last_check_in = datetime.fromtimestamp(last_check_in_ts / 1000, tz=timezone.utc)
            current_session_mins = (now_utc - last_check_in).total_seconds() / 60
            total_with_current = total_worked_minutes + current_session_mins
            total_hours_with_current = int(total_with_current // 60)
            remaining_mins_with_current = int(total_with_current % 60)

        result = {
            "employee_name": target_name,
            "company": target_company,
            "branch": target_branch,
            "date": date,
            "first_check_in": first_check_in.strftime("%I:%M %p") if first_check_in else None,
            "last_check_out": last_check_out.strftime("%I:%M %p") if last_check_out else None,
            "status": "Checked In" if still_checked_in else "Checked Out",
            "total_punches": len(punches),
            "punches": punches,
            "total_worked": f"{total_hours}h {remaining_mins}m"
        }

        if still_checked_in:
            result["current_session"] = f"{int(current_session_mins // 60)}h {int(current_session_mins % 60)}m"
            result["total_with_current"] = f"{total_hours_with_current}h {remaining_mins_with_current}m"
            result["_note"] = "Still checked in. 'total_with_current' includes ongoing session."

        return result

    @mcp.tool()
    def get_attendance(employee_name: str = None, month: str = None, company_name: str = None, detailed: bool = False) -> dict:
        """
        Get monthly attendance summary for an employee.
        If employee_name is not provided, returns your own attendance.
        Month format: YYYY-MM (defaults to current month).
        Set detailed=True to include day-by-day breakdown with check-in/out times.
        """
        ctx = get_user_context()
        if not ctx:
            return {"error": "Not authenticated. Please login first."}

        if not month:
            month = datetime.now().strftime("%Y-%m")

        # Validate month format
        try:
            year, mon = map(int, month.split('-'))
            if mon < 1 or mon > 12:
                return {"error": f"Invalid month: {month}. Use YYYY-MM format."}
        except:
            return {"error": f"Invalid month format: {month}. Use YYYY-MM format."}

        # Resolve employee
        if employee_name:
            emp_query = """
                SELECT ce.id, ce.employee_name, ce.working_day as emp_working_day,
                       ce.date_of_joining,
                       c.name as company_name, cb.name as branch_name,
                       cb.id as branch_id, cb.working_day as branch_working_day
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
            target_branch_id = emp_rows[0]["branch_id"]
            working_day_config = emp_rows[0].get("emp_working_day") or emp_rows[0].get("branch_working_day")
            doj_raw = emp_rows[0].get("date_of_joining")
        else:
            pc = ctx.primary_company
            if not pc:
                return {"error": "No company association found."}
            target_emp_id = pc.company_employee_id
            target_name = ctx.user_name
            target_company = pc.company_name
            target_branch = pc.branch_name
            target_branch_id = pc.company_branch_id

            # Get working day config and DOJ for self
            config_query = """
                SELECT ce.working_day as emp_working_day, cb.working_day as branch_working_day,
                       ce.date_of_joining
                FROM company_employee ce
                LEFT JOIN company_branch cb ON cb.id = ce.company_branch_id
                WHERE ce.id = $1
            """
            config_row = fetch_one(config_query, [target_emp_id])
            working_day_config = config_row.get("emp_working_day") or config_row.get("branch_working_day") if config_row else None
            doj_raw = config_row.get("date_of_joining") if config_row else None

        # Parse DOJ
        doj_date = None
        if doj_raw:
            if isinstance(doj_raw, str):
                doj_date = datetime.strptime(doj_raw.split('T')[0], "%Y-%m-%d").date()
            elif hasattr(doj_raw, 'date'):
                doj_date = doj_raw.date() if hasattr(doj_raw, 'date') else doj_raw
            elif hasattr(doj_raw, 'year'):
                from datetime import date
                doj_date = date(doj_raw.year, doj_raw.month, doj_raw.day)

        # Parse working days config
        day_map = {'mon': 0, 'tue': 1, 'wed': 2, 'thu': 3, 'fri': 4, 'sat': 5, 'sun': 6}
        reverse_day_map = {0: 'Monday', 1: 'Tuesday', 2: 'Wednesday', 3: 'Thursday', 4: 'Friday', 5: 'Saturday', 6: 'Sunday'}

        if working_day_config:
            working_days_set = set()
            for d in working_day_config.split(','):
                d_lower = d.strip().lower()
                if d_lower in day_map:
                    working_days_set.add(day_map[d_lower])
        else:
            working_days_set = {0, 1, 2, 3, 4}  # Default Mon-Fri

        # Get holidays for the month
        holiday_query = """
            SELECT date, name FROM company_holiday
            WHERE company_branch_id = $1 AND TO_CHAR(date, 'YYYY-MM') = $2
        """
        holiday_rows = fetch_all(holiday_query, [target_branch_id, month])
        holidays = {}
        if holiday_rows:
            for hr in holiday_rows:
                hdate = hr.get('date')
                if hdate:
                    if isinstance(hdate, str):
                        date_part = hdate.split('T')[0]
                        day_num = int(date_part.split('-')[2])
                    elif hasattr(hdate, 'day'):
                        day_num = hdate.day
                    else:
                        continue
                    holidays[day_num] = hr.get('name', 'Holiday')

        # Get attendance records from company_attendance (aggregated by day)
        attendance_query = """
            SELECT date,
                   MAX(CASE WHEN is_late = 1 THEN 1 ELSE 0 END) as is_late,
                   MAX(CASE WHEN is_half_day = 1 THEN 1 ELSE 0 END) as is_half_day,
                   SUM(COALESCE(total_minutes, 0)) as total_minutes,
                   MIN(check_in_time) as first_check_in,
                   MAX(CASE WHEN check_out_time IS NOT NULL AND check_out_time != 0
                       THEN check_out_time ELSE NULL END) as last_check_out,
                   (SELECT ca2.check_in_location_name FROM company_attendance ca2
                    WHERE ca2.company_employee_id = ca.company_employee_id AND ca2.date = ca.date
                    ORDER BY ca2.check_in_time ASC LIMIT 1) as check_in_location_name
            FROM company_attendance ca
            WHERE ca.company_employee_id = $1 AND TO_CHAR(ca.date, 'YYYY-MM') = $2
            GROUP BY ca.company_employee_id, ca.date
            ORDER BY date
        """
        attendance_rows = fetch_all(attendance_query, [target_emp_id, month])

        # Build attendance lookup by day
        attendance_by_day = {}
        for ar in attendance_rows:
            adate = ar.get('date')
            if adate:
                if isinstance(adate, str):
                    date_part = adate.split('T')[0]
                    day_num = int(date_part.split('-')[2])
                elif hasattr(adate, 'day'):
                    day_num = adate.day
                else:
                    continue
                # Map to expected field names
                ar['check_in_time'] = ar.get('first_check_in')
                ar['check_out_time'] = ar.get('last_check_out')
                ar['is_present'] = 1
                attendance_by_day[day_num] = ar

        # Get approved leaves for the month
        leave_query = """
            SELECT start_date, end_date, title as leave_type
            FROM company_approval
            WHERE company_employee_id = $1
              AND media_type = 'LEAVE_APPROVAL'
              AND UPPER(status) = 'APPROVED'
              AND (TO_CHAR(start_date, 'YYYY-MM') = $2 OR TO_CHAR(end_date, 'YYYY-MM') = $2)
        """
        leave_rows = fetch_all(leave_query, [target_emp_id, month])

        # Build leave days lookup
        leave_days = {}
        for lr in leave_rows:
            start = lr.get('start_date')
            end = lr.get('end_date')
            leave_type = lr.get('leave_type', 'Leave')
            if start:
                if isinstance(start, str):
                    start = datetime.strptime(start.split('T')[0], "%Y-%m-%d")
                if end:
                    if isinstance(end, str):
                        end = datetime.strptime(end.split('T')[0], "%Y-%m-%d")
                else:
                    end = start
                current = start
                while current <= end:
                    if current.year == year and current.month == mon:
                        leave_days[current.day] = leave_type
                    current += timedelta(days=1)

        # Build day-by-day attendance list
        today = datetime.now()
        if year == today.year and mon == today.month:
            last_day = today.day
        else:
            last_day = calendar.monthrange(year, mon)[1]

        days = []
        summary = {
            "total_days": last_day,
            "working_days": 0,
            "present": 0,
            "absent": 0,
            "late": 0,
            "half_day": 0,
            "leave": 0,
            "holiday": 0,
            "week_off": 0,
            "before_doj": 0
        }

        ist_offset = timedelta(hours=5, minutes=30)

        for day in range(1, last_day + 1):
            weekday = calendar.weekday(year, mon, day)
            day_name = reverse_day_map[weekday]
            date_str = f"{year}-{mon:02d}-{day:02d}"

            day_info = {
                "date": date_str,
                "day": day_name,
                "status": None,
                "check_in": None,
                "check_out": None,
                "hours_worked": None,
                "is_late": False,
                "is_half_day": False,
                "location": None,
                "note": None
            }

            # Check if date is before DOJ - skip these days
            from datetime import date
            current_date = date(year, mon, day)
            if doj_date and current_date < doj_date:
                day_info["status"] = "before_doj"
                day_info["note"] = "Before date of joining"
                summary["before_doj"] += 1
                days.append(day_info)
                continue

            # Determine status
            if day in holidays:
                day_info["status"] = "holiday"
                day_info["note"] = holidays[day]
                summary["holiday"] += 1
            elif weekday not in working_days_set:
                day_info["status"] = "week_off"
                summary["week_off"] += 1
            elif day in leave_days:
                day_info["status"] = "leave"
                day_info["note"] = leave_days[day]
                summary["leave"] += 1
                summary["working_days"] += 1
            elif day in attendance_by_day:
                ar = attendance_by_day[day]
                day_info["status"] = "present"
                day_info["is_late"] = ar.get("is_late") == 1
                day_info["is_half_day"] = ar.get("is_half_day") == 1
                day_info["location"] = ar.get("check_in_location_name")

                # Convert timestamps
                check_in_ts = ar.get("check_in_time")
                check_out_ts = ar.get("check_out_time")

                if check_in_ts and check_in_ts != "0" and check_in_ts != 0:
                    if isinstance(check_in_ts, str):
                        check_in_ts = int(check_in_ts)
                    check_in_dt = datetime.fromtimestamp(check_in_ts / 1000, tz=timezone.utc) + ist_offset
                    day_info["check_in"] = check_in_dt.strftime("%I:%M %p")

                if check_out_ts and check_out_ts != 0 and check_out_ts != "0":
                    if isinstance(check_out_ts, str):
                        check_out_ts = int(check_out_ts)
                    check_out_dt = datetime.fromtimestamp(check_out_ts / 1000, tz=timezone.utc) + ist_offset
                    day_info["check_out"] = check_out_dt.strftime("%I:%M %p")

                total_mins = ar.get("total_minutes") or 0

                # For today, check if still working and add ongoing session time
                is_today = (year == today.year and mon == today.month and day == today.day)
                if is_today:
                    # Get the last punch to check if still checked in
                    last_punch_query = """
                        SELECT check_in_time, check_out_time
                        FROM company_attendance
                        WHERE company_employee_id = $1 AND date = $2
                        ORDER BY check_in_time DESC LIMIT 1
                    """
                    last_punch = fetch_one(last_punch_query, [target_emp_id, date_str])
                    if last_punch:
                        last_checkout = last_punch.get("check_out_time")
                        if not last_checkout or last_checkout == 0 or last_checkout == "0":
                            # Still checked in - calculate ongoing session
                            last_checkin_ts = last_punch.get("check_in_time")
                            if last_checkin_ts:
                                if isinstance(last_checkin_ts, str):
                                    last_checkin_ts = int(last_checkin_ts)
                                now_utc = datetime.now(timezone.utc)
                                last_checkin_dt = datetime.fromtimestamp(last_checkin_ts / 1000, tz=timezone.utc)
                                ongoing_mins = (now_utc - last_checkin_dt).total_seconds() / 60
                                total_mins += ongoing_mins
                                day_info["check_out"] = "(working)"

                hours = int(total_mins // 60)
                mins = int(total_mins % 60)
                day_info["hours_worked"] = f"{hours}h {mins}m"

                summary["present"] += 1
                summary["working_days"] += 1
                if day_info["is_late"]:
                    summary["late"] += 1
                if day_info["is_half_day"]:
                    summary["half_day"] += 1
            else:
                day_info["status"] = "absent"
                summary["absent"] += 1
                summary["working_days"] += 1

            days.append(day_info)

        # Calculate attendance percentage
        if summary["working_days"] > 0:
            summary["attendance_percentage"] = round(
                (summary["present"] / summary["working_days"]) * 100, 1
            )
        else:
            summary["attendance_percentage"] = 0

        result = {
            "employee_name": target_name,
            "company_name": target_company,
            "branch_name": target_branch,
            "month": month,
            "date_of_joining": str(doj_date) if doj_date else None,
            "summary": summary
        }

        if detailed:
            result["days"] = days

        return result

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
        Excludes employees on approved leave, holidays, and non-working days.
        """
        ctx = get_user_context()
        if not ctx:
            return {"error": "Not authenticated. Please login first."}

        if not date:
            date = datetime.now().strftime("%Y-%m-%d")

        # Parse date to get day of week
        try:
            date_obj = datetime.strptime(date, "%Y-%m-%d")
            # Python weekday: 0=Monday, 6=Sunday
            # Map to day abbreviations
            day_map = {0: 'mon', 1: 'tue', 2: 'wed', 3: 'thu', 4: 'fri', 5: 'sat', 6: 'sun'}
            day_abbr = day_map[date_obj.weekday()]
        except ValueError:
            return {"error": f"Invalid date format: {date}. Use YYYY-MM-DD."}

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
              AND ce.company_branch_id NOT IN (
                  SELECT ch.company_branch_id
                  FROM company_holiday ch
                  WHERE ch.date = $1
              )
              AND (
                  cb.working_day IS NULL
                  OR cb.working_day = ''
                  OR LOWER(cb.working_day) LIKE $2
              )
        """
        params = [date, f"%{day_abbr}%"]
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
        query += " ORDER BY ce.employee_name"

        rows = fetch_all(query, params)

        result = {
            "date": date,
            "day": date_obj.strftime("%A"),
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
            "_note": "Excludes: approved leave, holidays, non-working days"
        }

        if company_name:
            result["company_filter"] = company_name
        if branch_name:
            result["branch_filter"] = branch_name

        return result
