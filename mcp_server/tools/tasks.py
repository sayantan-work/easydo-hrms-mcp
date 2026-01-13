"""Task management tools for MCP server."""
from datetime import datetime
from ..auth import get_user_context
from ..db import fetch_all, fetch_one
from ..rbac import apply_company_filter


def register(mcp):
    """Register task tools with MCP server."""

    @mcp.tool()
    def get_tasks(employee_name: str = None, status: str = None) -> dict:
        """
        Get tasks assigned to or created by an employee.
        If employee_name is not provided, returns your own tasks.
        Status filter: 'all', 'pending', 'completed', 'overdue' (defaults to 'all').
        """
        ctx = get_user_context()
        if not ctx:
            return {"error": "Not authenticated. Please login first."}

        if not status:
            status = "all"

        if employee_name:
            # Search for the employee
            emp_query = """
                SELECT ce.user_id, ce.employee_name, c.name as company_name
                FROM company_employee ce
                JOIN company c ON c.id = ce.company_id
                WHERE LOWER(ce.employee_name) LIKE LOWER($1) AND ce.is_deleted = '0'
            """
            emp_query = apply_company_filter(ctx, emp_query, "ce")
            emp_rows = fetch_all(emp_query, [f"%{employee_name}%"])

            if not emp_rows:
                return {"error": f"Employee '{employee_name}' not found or not accessible"}
            if len(emp_rows) > 1:
                return {
                    "error": "Multiple employees found. Please be more specific.",
                    "matches": [{"name": r["employee_name"], "company": r["company_name"]} for r in emp_rows]
                }

            target_user_id = emp_rows[0]["user_id"]
            target_name = emp_rows[0]["employee_name"]
        else:
            # Default to self
            target_user_id = ctx.user_id
            target_name = ctx.user_name

        query = """
            SELECT tm.id, tm.title, tm.instructions, tm.start_date, tm.end_date,
                   tm.is_completed, tm.completed_date, tm.created_date
            FROM task_management tm
            WHERE (tm.created_by = $1 OR tm.to_user_ids LIKE $2)
              AND tm.is_active = 'Y'
              AND (tm.is_delete IS NULL OR tm.is_delete = '0')
            ORDER BY tm.end_date ASC
        """
        rows = fetch_all(query, [target_user_id, f"%{target_user_id}%"])

        now = datetime.now()
        tasks = []
        for r in rows:
            end_date = r.get("end_date")
            is_completed = r.get("is_completed") == 1
            is_overdue = False

            if end_date and not is_completed:
                if isinstance(end_date, str):
                    try:
                        end_dt = datetime.fromisoformat(end_date.replace("Z", "+00:00"))
                        is_overdue = end_dt < now
                    except:
                        pass
                else:
                    is_overdue = end_date < now

            task_status = "completed" if is_completed else ("overdue" if is_overdue else "pending")

            # Filter by status
            if status != "all" and task_status != status:
                continue

            tasks.append({
                "id": r.get("id"),
                "title": r.get("title"),
                "instructions": r.get("instructions"),
                "start_date": str(r.get("start_date")),
                "end_date": str(r.get("end_date")),
                "status": task_status,
                "completed_date": str(r.get("completed_date")) if r.get("completed_date") else None
            })

        # Summary
        total = len(tasks)
        completed = len([t for t in tasks if t["status"] == "completed"])
        pending = len([t for t in tasks if t["status"] == "pending"])
        overdue = len([t for t in tasks if t["status"] == "overdue"])

        return {
            "employee_name": target_name,
            "filter": status,
            "summary": {
                "total": total,
                "completed": completed,
                "pending": pending,
                "overdue": overdue
            },
            "tasks": tasks,
            "_note": "Overdue = end_date has passed and task is not completed."
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
                   tm.created_by, u.name as created_by_name
            FROM task_management tm
            LEFT JOIN users u ON u.id = tm.created_by
            WHERE tm.is_active = 'Y'
              AND (tm.is_delete IS NULL OR tm.is_delete = '0')
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
                    "start_date": str(r.get("start_date")),
                    "due_date": str(r.get("end_date")),
                    "created_by": r.get("created_by_name"),
                    "days_overdue": (datetime.now() - r.get("end_date")).days if r.get("end_date") else None
                }
                for r in rows
            ],
            "_note": "Tasks where end_date < current date and is_completed = 0"
        }
