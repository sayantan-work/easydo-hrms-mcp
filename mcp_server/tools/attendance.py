"""Attendance tools for MCP server."""
import calendar
from datetime import datetime, timedelta, timezone, date
from ..auth import get_user_context
from ..db import fetch_all, fetch_one
from ..rbac import apply_company_filter


# Constants
IST_OFFSET = timedelta(hours=5, minutes=30)
TIMEZONE_OFFSETS = {
    "IST": timedelta(hours=5, minutes=30),
    "UTC": timedelta(hours=0),
    "GMT": timedelta(hours=0),
    "EST": timedelta(hours=-5),
    "PST": timedelta(hours=-8),
    "CST": timedelta(hours=-6),
    "MST": timedelta(hours=-7),
}
WEEKDAY_MAP = {0: 'Monday', 1: 'Tuesday', 2: 'Wednesday', 3: 'Thursday', 4: 'Friday', 5: 'Saturday', 6: 'Sunday'}
DAY_ABBR_MAP = {'mon': 0, 'tue': 1, 'wed': 2, 'thu': 3, 'fri': 4, 'sat': 5, 'sun': 6}
DAY_ABBR_REVERSE = {0: 'mon', 1: 'tue', 2: 'wed', 3: 'thu', 4: 'fri', 5: 'sat', 6: 'sun'}
DEFAULT_WORKING_DAYS = {0, 1, 2, 3, 4}  # Mon-Fri


def _require_auth():
    """Get user context or return error dict."""
    ctx = get_user_context()
    if not ctx:
        return None, {"error": "Not authenticated. Please login first."}
    return ctx, None


def _today_str() -> str:
    """Get today's date as YYYY-MM-DD string."""
    return datetime.now().strftime("%Y-%m-%d")


def _current_month_str() -> str:
    """Get current month as YYYY-MM string."""
    return datetime.now().strftime("%Y-%m")


def _format_duration(minutes: float) -> str:
    """Format minutes as 'Xh Ym' string."""
    hours = int(minutes // 60)
    mins = int(minutes % 60)
    return f"{hours}h {mins}m"


def _timestamp_to_ist_time(ts) -> str | None:
    """Convert millisecond timestamp to IST time string (HH:MM AM/PM)."""
    if not ts or ts == 0 or ts == "0":
        return None
    if isinstance(ts, str):
        ts = int(ts)
    dt = datetime.fromtimestamp(ts / 1000, tz=timezone.utc) + IST_OFFSET
    return dt.strftime("%I:%M %p")


def _timestamp_to_datetime(ts) -> datetime | None:
    """Convert millisecond timestamp to datetime (UTC+IST offset)."""
    if not ts or ts == 0 or ts == "0":
        return None
    if isinstance(ts, str):
        ts = int(ts)
    return datetime.fromtimestamp(ts / 1000, tz=timezone.utc) + IST_OFFSET


def _parse_date(date_raw) -> date | None:
    """Parse various date formats to date object."""
    if not date_raw:
        return None
    if isinstance(date_raw, str):
        return datetime.strptime(date_raw.split('T')[0], "%Y-%m-%d").date()
    if hasattr(date_raw, 'date') and callable(date_raw.date):
        return date_raw.date()
    if hasattr(date_raw, 'year'):
        return date(date_raw.year, date_raw.month, date_raw.day)
    return None


def _extract_day_from_date(date_raw) -> int | None:
    """Extract day number from various date formats."""
    if not date_raw:
        return None
    if isinstance(date_raw, str):
        date_part = date_raw.split('T')[0]
        return int(date_part.split('-')[2])
    if hasattr(date_raw, 'day'):
        return date_raw.day
    return None


def _parse_working_days(config: str | None) -> set:
    """Parse working days config string to set of weekday integers."""
    if not config:
        return DEFAULT_WORKING_DAYS
    working_days = set()
    for d in config.split(','):
        d_lower = d.strip().lower()
        if d_lower in DAY_ABBR_MAP:
            working_days.add(DAY_ABBR_MAP[d_lower])
    return working_days if working_days else DEFAULT_WORKING_DAYS


def _resolve_employee(ctx, employee_name: str = None, company_name: str = None):
    """
    Resolve employee by name or default to self.
    Returns (emp_id, emp_name, company_name, branch_name, branch_id, error).
    """
    if employee_name:
        query = """
            SELECT ce.id, ce.employee_name, c.name as company_name,
                   cb.name as branch_name, cb.id as branch_id
            FROM company_employee ce
            JOIN company c ON c.id = ce.company_id
            LEFT JOIN company_branch cb ON cb.id = ce.company_branch_id
            WHERE LOWER(ce.employee_name) LIKE LOWER($1) AND ce.is_deleted = '0'
        """
        params = [f"%{employee_name}%"]
        if company_name:
            query += " AND LOWER(c.name) LIKE LOWER($2)"
            params.append(f"%{company_name}%")

        query = apply_company_filter(ctx, query, "ce")
        rows = fetch_all(query, params)

        if not rows:
            return None, None, None, None, None, {"error": f"Employee '{employee_name}' not found"}
        if len(rows) > 1 and not company_name:
            return None, None, None, None, None, {
                "error": "Multiple employees found. Specify company_name.",
                "matches": [{"name": r["employee_name"], "company": r["company_name"]} for r in rows]
            }

        row = rows[0]
        return row["id"], row["employee_name"], row["company_name"], row["branch_name"], row.get("branch_id"), None

    # Default to self
    pc = ctx.primary_company
    if not pc:
        return None, None, None, None, None, {"error": "No company association found."}
    return pc.company_employee_id, ctx.user_name, pc.company_name, pc.branch_name, pc.company_branch_id, None


def _build_filtered_query(base_query: str, ctx, params: list, param_idx: int,
                          company_name: str = None, branch_name: str = None,
                          employee_alias: str = "ce"):
    """Build query with company/branch filters and RBAC. Returns (query, params)."""
    if company_name:
        base_query += f" AND LOWER(c.name) LIKE LOWER(${param_idx})"
        params.append(f"%{company_name}%")
        param_idx += 1

    if branch_name:
        base_query += f" AND LOWER(cb.name) LIKE LOWER(${param_idx})"
        params.append(f"%{branch_name}%")

    return apply_company_filter(ctx, base_query, employee_alias), params


def _add_filters_to_result(result: dict, company_name: str = None, branch_name: str = None) -> dict:
    """Add filter info to result dict if filters were applied."""
    if company_name:
        result["company_filter"] = company_name
    if branch_name:
        result["branch_filter"] = branch_name
    return result


def _parse_timezone_offset(tz_name: str) -> timedelta | dict:
    """Parse timezone name or offset string. Returns timedelta or error dict."""
    tz_upper = tz_name.upper().strip()

    if tz_upper in TIMEZONE_OFFSETS:
        return TIMEZONE_OFFSETS[tz_upper]

    if tz_name.startswith(("+", "-")):
        try:
            sign = 1 if tz_name[0] == "+" else -1
            parts = tz_name[1:].split(":")
            hours = int(parts[0])
            minutes = int(parts[1]) if len(parts) > 1 else 0
            return timedelta(hours=sign * hours, minutes=sign * minutes)
        except (ValueError, IndexError):
            return {"error": f"Invalid timezone format: {tz_name}. Use IST, UTC, or +05:30 format."}

    return {"error": f"Unknown timezone: {tz_name}. Use IST, UTC, EST, PST, or +05:30 format."}


def register(mcp):
    """Register attendance tools with MCP server."""

    @mcp.tool()
    def get_time(timezone_name: str = "IST") -> dict:
        """
        Get current time. Defaults to IST (Indian Standard Time).
        Supported: IST, UTC, EST, PST, GMT, or offset like +05:30, -08:00
        """
        now_utc = datetime.now(timezone.utc)
        offset = _parse_timezone_offset(timezone_name)

        if isinstance(offset, dict):
            return offset

        local_time = now_utc + offset
        display_tz = timezone_name.upper() if timezone_name.upper() in TIMEZONE_OFFSETS else timezone_name

        return {
            "timezone": display_tz,
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
        ctx, err = _require_auth()
        if err:
            return err

        if not date:
            date = _today_str()

        emp_id, emp_name, comp_name, branch_name, _, error = _resolve_employee(ctx, employee_name, company_name)
        if error:
            return error

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
        rows = fetch_all(query, [emp_id, date])

        if not rows:
            return {
                "employee_name": emp_name,
                "date": date,
                "status": "No punch records found",
                "punches": []
            }

        punches = []
        total_worked_minutes = 0
        first_check_in = None
        last_check_out = None

        for row in rows:
            check_in_dt = _timestamp_to_datetime(row.get("check_in_time"))
            check_out_dt = _timestamp_to_datetime(row.get("check_out_time"))

            if check_in_dt and first_check_in is None:
                first_check_in = check_in_dt
            if check_out_dt:
                last_check_out = check_out_dt

            duration_mins = row.get("total_minutes") or 0
            total_worked_minutes += duration_mins

            punches.append({
                "check_in": check_in_dt.strftime("%I:%M %p") if check_in_dt else None,
                "check_in_location": row.get("check_in_location_name") or row.get("check_in_address"),
                "check_out": check_out_dt.strftime("%I:%M %p") if check_out_dt else None,
                "check_out_location": row.get("check_out_location_name") or row.get("check_out_address"),
                "duration_mins": round(duration_mins, 1),
                "is_late": row.get("is_late") == 1,
                "is_half_day": row.get("is_half_day") == 1,
                "auto_checkout": row.get("is_auto_check_out") == 1,
                "notes": row.get("notes")
            })

        # Check if still checked in
        last_checkout_raw = rows[-1].get("check_out_time")
        still_checked_in = not last_checkout_raw or last_checkout_raw == "0" or last_checkout_raw == 0

        result = {
            "employee_name": emp_name,
            "company": comp_name,
            "branch": branch_name,
            "date": date,
            "first_check_in": first_check_in.strftime("%I:%M %p") if first_check_in else None,
            "last_check_out": last_check_out.strftime("%I:%M %p") if last_check_out else None,
            "status": "Checked In" if still_checked_in else "Checked Out",
            "total_punches": len(punches),
            "punches": punches,
            "total_worked": _format_duration(total_worked_minutes)
        }

        # Add ongoing session info if still checked in
        if still_checked_in:
            last_check_in_ts = rows[-1].get("check_in_time")
            if last_check_in_ts:
                if isinstance(last_check_in_ts, str):
                    last_check_in_ts = int(last_check_in_ts)
                now_utc = datetime.now(timezone.utc)
                last_check_in = datetime.fromtimestamp(last_check_in_ts / 1000, tz=timezone.utc)
                current_session_mins = (now_utc - last_check_in).total_seconds() / 60
                total_with_current = total_worked_minutes + current_session_mins

                result["current_session"] = _format_duration(current_session_mins)
                result["total_with_current"] = _format_duration(total_with_current)
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
        ctx, err = _require_auth()
        if err:
            return err

        if not month:
            month = _current_month_str()

        # Validate month format
        try:
            year, mon = map(int, month.split('-'))
            if mon < 1 or mon > 12:
                return {"error": f"Invalid month: {month}. Use YYYY-MM format."}
        except (ValueError, AttributeError):
            return {"error": f"Invalid month format: {month}. Use YYYY-MM format."}

        # Resolve employee with extended info
        emp_id, emp_name, comp_name, branch_name, branch_id, error = _resolve_employee(ctx, employee_name, company_name)
        if error:
            return error

        # Get working day config and DOJ
        config_query = """
            SELECT ce.working_day as emp_working_day, cb.working_day as branch_working_day,
                   ce.date_of_joining
            FROM company_employee ce
            LEFT JOIN company_branch cb ON cb.id = ce.company_branch_id
            WHERE ce.id = $1
        """
        config_row = fetch_one(config_query, [emp_id])
        working_day_config = None
        doj_raw = None
        if config_row:
            working_day_config = config_row.get("emp_working_day") or config_row.get("branch_working_day")
            doj_raw = config_row.get("date_of_joining")

        doj_date = _parse_date(doj_raw)
        working_days_set = _parse_working_days(working_day_config)

        # Get holidays for the month
        holiday_query = """
            SELECT date, name FROM company_holiday
            WHERE company_branch_id = $1 AND TO_CHAR(date, 'YYYY-MM') = $2
        """
        holiday_rows = fetch_all(holiday_query, [branch_id, month])
        holidays = {}
        for hr in holiday_rows:
            day_num = _extract_day_from_date(hr.get('date'))
            if day_num:
                holidays[day_num] = hr.get('name', 'Holiday')

        # Get attendance records (aggregated by day)
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
        attendance_rows = fetch_all(attendance_query, [emp_id, month])

        # Build attendance lookup by day
        attendance_by_day = {}
        for ar in attendance_rows:
            day_num = _extract_day_from_date(ar.get('date'))
            if day_num:
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
        leave_rows = fetch_all(leave_query, [emp_id, month])

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

        # Determine last day of the month to process
        today = datetime.now()
        if year == today.year and mon == today.month:
            last_day = today.day
        else:
            last_day = calendar.monthrange(year, mon)[1]

        # Build day-by-day attendance
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

        for day in range(1, last_day + 1):
            weekday = calendar.weekday(year, mon, day)
            day_name = WEEKDAY_MAP[weekday]
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

            current_date = date(year, mon, day)

            # Check if before DOJ
            if doj_date and current_date < doj_date:
                day_info["status"] = "before_doj"
                day_info["note"] = "Before date of joining"
                summary["before_doj"] += 1
                days.append(day_info)
                continue

            # Determine day status
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

                day_info["check_in"] = _timestamp_to_ist_time(ar.get("check_in_time"))
                day_info["check_out"] = _timestamp_to_ist_time(ar.get("check_out_time"))

                total_mins = ar.get("total_minutes") or 0

                # For today, add ongoing session time if still checked in
                is_today = (year == today.year and mon == today.month and day == today.day)
                if is_today:
                    last_punch_query = """
                        SELECT check_in_time, check_out_time
                        FROM company_attendance
                        WHERE company_employee_id = $1 AND date = $2
                        ORDER BY check_in_time DESC LIMIT 1
                    """
                    last_punch = fetch_one(last_punch_query, [emp_id, date_str])
                    if last_punch:
                        last_checkout = last_punch.get("check_out_time")
                        if not last_checkout or last_checkout == 0 or last_checkout == "0":
                            last_checkin_ts = last_punch.get("check_in_time")
                            if last_checkin_ts:
                                if isinstance(last_checkin_ts, str):
                                    last_checkin_ts = int(last_checkin_ts)
                                now_utc = datetime.now(timezone.utc)
                                last_checkin_dt = datetime.fromtimestamp(last_checkin_ts / 1000, tz=timezone.utc)
                                ongoing_mins = (now_utc - last_checkin_dt).total_seconds() / 60
                                total_mins += ongoing_mins
                                day_info["check_out"] = "(working)"

                day_info["hours_worked"] = _format_duration(total_mins)

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
            "employee_name": emp_name,
            "company_name": comp_name,
            "branch_name": branch_name,
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
        ctx, err = _require_auth()
        if err:
            return err

        today = _today_str()

        base_select = """
            SELECT ce.employee_name, ce.designation, cd.name as department_name,
                   cb.name as branch_name, c.name as company_name,
                   TO_TIMESTAMP(ca.check_in_time / 1000) as check_in_time
        """
        base_from = """
            FROM company_attendance ca
            JOIN company_employee ce ON ce.id = ca.company_employee_id
            JOIN company c ON c.id = ce.company_id
            LEFT JOIN company_branch cb ON cb.id = ce.company_branch_id
            LEFT JOIN company_department cd ON cd.id = ce.company_role_id
            WHERE ce.is_deleted = '0' AND ca.date = $1
        """

        late_query = base_select + base_from + " AND ca.is_late = 1"
        half_day_query = base_select + ", TO_TIMESTAMP(ca.check_out_time / 1000) as check_out_time" + base_from + " AND ca.is_half_day = 1"

        params = [today]
        param_idx = 2

        late_query, params = _build_filtered_query(late_query, ctx, params, param_idx, company_name, branch_name)
        late_query += " ORDER BY ca.check_in_time DESC"

        # Reset params for half_day query
        params_hd = [today]
        half_day_query, params_hd = _build_filtered_query(half_day_query, ctx, params_hd, param_idx, company_name, branch_name)
        half_day_query += " ORDER BY ca.check_in_time DESC"

        late_rows = fetch_all(late_query, params)
        half_day_rows = fetch_all(half_day_query, params_hd)

        result = {
            "date": today,
            "late_count": len(late_rows),
            "half_day_count": len(half_day_rows),
            "late_employees": late_rows,
            "half_day_employees": half_day_rows
        }

        return _add_filters_to_result(result, company_name, branch_name)

    @mcp.tool()
    def get_present_employees(date: str = None, company_name: str = None, branch_name: str = None) -> dict:
        """
        Get employees who are present (checked in) on a specific date.
        Date format: YYYY-MM-DD (defaults to today).
        Use company_name and/or branch_name to filter.
        """
        ctx, err = _require_auth()
        if err:
            return err

        if not date:
            date = _today_str()

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
        query, params = _build_filtered_query(query, ctx, params, 2, company_name, branch_name)
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

        return _add_filters_to_result(result, company_name, branch_name)

    @mcp.tool()
    def get_absent_employees(date: str = None, company_name: str = None, branch_name: str = None) -> dict:
        """
        Get employees who were absent on a specific date.
        Date format: YYYY-MM-DD (defaults to today).
        Excludes employees on approved leave, holidays, and non-working days.
        """
        ctx, err = _require_auth()
        if err:
            return err

        if not date:
            date = _today_str()

        try:
            date_obj = datetime.strptime(date, "%Y-%m-%d")
            day_abbr = DAY_ABBR_REVERSE[date_obj.weekday()]
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
        query, params = _build_filtered_query(query, ctx, params, 3, company_name, branch_name)
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

        return _add_filters_to_result(result, company_name, branch_name)
