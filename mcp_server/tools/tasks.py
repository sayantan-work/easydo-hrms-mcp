"""Task management tools for MCP server."""
from datetime import datetime
from ..auth import get_user_context
from ..db import fetch_all, fetch_one
from ..rbac import apply_company_filter


def _get_current_month() -> str:
    """Get current month in YYYY-MM format."""
    return datetime.now().strftime("%Y-%m")


def _resolve_company_branch(ctx, company_name: str = None, branch_name: str = None) -> tuple:
    """
    Resolve company and branch IDs from names.
    Returns (company_id, branch_id, error_message)
    """
    company_id = None
    branch_id = None

    if company_name:
        comp = ctx.get_company_by_name(company_name)
        if not comp and not ctx.is_super_admin:
            return None, None, f"Company '{company_name}' not found or not accessible"
        if comp:
            company_id = comp.company_id

    if branch_name:
        query = "SELECT id, name FROM company_branch WHERE LOWER(name) LIKE LOWER($1)"
        params = [f"%{branch_name}%"]
        if company_id:
            query += " AND company_id = $2"
            params.append(company_id)

        branches = fetch_all(query, params)
        if not branches:
            return None, None, f"Branch '{branch_name}' not found"
        if len(branches) > 1:
            return None, None, f"Multiple branches found: {[b['name'] for b in branches]}"
        branch_id = branches[0]["id"]

    return company_id, branch_id, None


def _resolve_employee_user_id(ctx, employee_name: str) -> tuple:
    """
    Resolve employee name to user_id.
    Returns (user_id, employee_name, error_message)
    """
    query = """
        SELECT ce.user_id, ce.employee_name
        FROM company_employee ce
        WHERE LOWER(ce.employee_name) LIKE LOWER($1) AND ce.is_deleted = '0'
    """
    query = apply_company_filter(ctx, query, "ce")
    rows = fetch_all(query, [f"%{employee_name}%"])

    if not rows:
        return None, None, f"Employee '{employee_name}' not found"
    if len(rows) > 1:
        names = list(set(r["employee_name"] for r in rows))
        if len(names) > 1:
            return None, None, f"Multiple employees found: {names[:5]}"

    return rows[0]["user_id"], rows[0]["employee_name"], None


def register(mcp):
    """Register task tools with MCP server."""

    @mcp.tool()
    def get_tasks(
        company_name: str = None,
        branch_name: str = None,
        month: str = None,
        status: str = None,
        created_by: str = None,
        assigned_to: str = None
    ) -> dict:
        """
        Get tasks with filters for company, branch, month, status, and people.

        Parameters:
        - company_name: Filter by company (default: user's primary company)
        - branch_name: Filter by branch
        - month: Format YYYY-MM (default: current month)
        - status: 'pending', 'completed', 'overdue', 'all' (default: 'all')
        - created_by: Filter by creator's name
        - assigned_to: Filter by assignee's name

        Returns tasks with creator and assignee information.
        """
        ctx = get_user_context()
        if not ctx:
            return {"error": "Not authenticated. Please login first."}

        # Defaults
        if not month:
            month = _get_current_month()
        if not status:
            status = "all"

        # Parse month
        try:
            year, mon = month.split("-")
            start_date = f"{year}-{mon}-01"
            # Calculate end date (first day of next month)
            next_mon = int(mon) + 1
            next_year = int(year)
            if next_mon > 12:
                next_mon = 1
                next_year += 1
            end_date = f"{next_year}-{next_mon:02d}-01"
        except ValueError:
            return {"error": "Invalid month format. Use YYYY-MM (e.g., 2025-12)"}

        # Resolve company/branch
        company_id, branch_id, error = _resolve_company_branch(ctx, company_name, branch_name)
        if error:
            return {"error": error}

        # Resolve created_by user_id
        created_by_user_id = None
        created_by_resolved = None
        if created_by:
            created_by_user_id, created_by_resolved, error = _resolve_employee_user_id(ctx, created_by)
            if error:
                return {"error": error}

        # Resolve assigned_to user_id
        assigned_to_user_id = None
        assigned_to_resolved = None
        if assigned_to:
            assigned_to_user_id, assigned_to_resolved, error = _resolve_employee_user_id(ctx, assigned_to)
            if error:
                return {"error": error}

        # Build main query
        query = """
            SELECT DISTINCT
                tm.id,
                tm.title,
                tm.instructions,
                tm.start_date,
                tm.end_date,
                tm.is_completed,
                tm.completed_date,
                tm.created_by,
                ce_creator.employee_name as creator_name
            FROM task_management tm
            LEFT JOIN company_employee ce_creator
                ON ce_creator.user_id = tm.created_by AND ce_creator.is_deleted = '0'
            LEFT JOIN task_transaction tt ON tt.task_id = tm.id
            WHERE tm.start_date >= $1 AND tm.start_date < $2
              AND (tm.is_delete IS NULL OR tm.is_delete = 'N' OR tm.is_delete = '0')
        """
        params = [start_date, end_date]
        param_idx = 3

        # Add company filter
        if company_id:
            query += f" AND tm.company_id = ${param_idx}"
            params.append(company_id)
            param_idx += 1

        # Add branch filter
        if branch_id:
            query += f" AND tm.company_branch_id = ${param_idx}"
            params.append(branch_id)
            param_idx += 1

        # Add created_by filter
        if created_by_user_id:
            query += f" AND tm.created_by = ${param_idx}"
            params.append(created_by_user_id)
            param_idx += 1

        # Add assigned_to filter
        if assigned_to_user_id:
            query += f" AND tt.user_id = ${param_idx}"
            params.append(assigned_to_user_id)
            param_idx += 1

        query += " ORDER BY tm.start_date DESC"

        # Apply RBAC filter
        query = apply_company_filter(ctx, query, "tm")

        try:
            rows = fetch_all(query, params)
        except Exception as e:
            return {"error": f"Query failed: {str(e)}"}

        # Get task IDs for fetching assignees
        task_ids = [r["id"] for r in rows]

        # Fetch assignees for all tasks in one query
        assignees_map = {}
        if task_ids:
            placeholders = ", ".join([f"${i+1}" for i in range(len(task_ids))])
            assignee_query = f"""
                SELECT tt.task_id, tt.user_id, tt.status as assignment_status,
                       ce.employee_name
                FROM task_transaction tt
                LEFT JOIN company_employee ce
                    ON ce.user_id = tt.user_id AND ce.is_deleted = '0'
                WHERE tt.task_id IN ({placeholders})
                  AND (tt.is_delete IS NULL OR tt.is_delete = 'N' OR tt.is_delete = '0')
            """
            assignee_rows = fetch_all(assignee_query, task_ids)

            for ar in assignee_rows:
                tid = ar["task_id"]
                if tid not in assignees_map:
                    assignees_map[tid] = []
                assignees_map[tid].append({
                    "name": ar.get("employee_name") or f"User {ar['user_id']}",
                    "status": ar.get("assignment_status")
                })

        # Process results
        now = datetime.now()
        tasks = []

        for r in rows:
            end_dt = r.get("end_date")
            is_completed = r.get("is_completed") == 1
            is_overdue = False

            if end_dt and not is_completed:
                if isinstance(end_dt, datetime):
                    is_overdue = end_dt < now
                elif isinstance(end_dt, str):
                    try:
                        end_dt_parsed = datetime.fromisoformat(end_dt.replace("Z", "+00:00"))
                        is_overdue = end_dt_parsed.replace(tzinfo=None) < now
                    except:
                        pass

            task_status = "completed" if is_completed else ("overdue" if is_overdue else "pending")

            # Filter by status
            if status != "all" and task_status != status:
                continue

            task_id = r["id"]
            assignees = assignees_map.get(task_id, [])

            tasks.append({
                "id": task_id,
                "title": r.get("title"),
                "instructions": r.get("instructions"),
                "start_date": str(r.get("start_date"))[:10] if r.get("start_date") else None,
                "end_date": str(r.get("end_date"))[:10] if r.get("end_date") else None,
                "status": task_status,
                "created_by": r.get("creator_name") or f"User {r.get('created_by')}",
                "assigned_to": [a["name"] for a in assignees] if assignees else ["Self"],
                "assignee_status": [a["status"] for a in assignees] if assignees else [],
                "completed_date": str(r.get("completed_date"))[:10] if r.get("completed_date") else None
            })

        # Summary
        total = len(tasks)
        completed_count = len([t for t in tasks if t["status"] == "completed"])
        pending_count = len([t for t in tasks if t["status"] == "pending"])
        overdue_count = len([t for t in tasks if t["status"] == "overdue"])

        return {
            "month": month,
            "filters": {
                "company": company_name or "all accessible",
                "branch": branch_name,
                "status": status,
                "created_by": created_by_resolved,
                "assigned_to": assigned_to_resolved
            },
            "summary": {
                "total": total,
                "completed": completed_count,
                "pending": pending_count,
                "overdue": overdue_count
            },
            "tasks": tasks
        }

    @mcp.tool()
    def get_overdue_tasks() -> dict:
        """
        Get all overdue tasks across your accessible scope.
        Shows tasks past due date that are not completed.
        """
        ctx = get_user_context()
        if not ctx:
            return {"error": "Not authenticated. Please login first."}

        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        query = """
            SELECT tm.id, tm.title, tm.instructions, tm.start_date, tm.end_date,
                   tm.created_by, ce.employee_name as created_by_name
            FROM task_management tm
            LEFT JOIN company_employee ce ON ce.user_id = tm.created_by AND ce.is_deleted = '0'
            WHERE tm.is_active = 'Y'
              AND (tm.is_delete IS NULL OR tm.is_delete = 'N' OR tm.is_delete = '0')
              AND (tm.is_completed IS NULL OR tm.is_completed = 0)
              AND tm.end_date < $1
            ORDER BY tm.end_date ASC
        """
        query = apply_company_filter(ctx, query, "tm")
        rows = fetch_all(query, [now])

        return {
            "count": len(rows),
            "overdue_tasks": [
                {
                    "id": r.get("id"),
                    "title": r.get("title"),
                    "instructions": r.get("instructions"),
                    "start_date": str(r.get("start_date"))[:10] if r.get("start_date") else None,
                    "due_date": str(r.get("end_date"))[:10] if r.get("end_date") else None,
                    "created_by": r.get("created_by_name") or f"User {r.get('created_by')}",
                    "days_overdue": (datetime.now() - r.get("end_date")).days if r.get("end_date") else None
                }
                for r in rows
            ],
            "_note": "Tasks where end_date < current date and is_completed = 0"
        }
