"""Authentication tools for MCP server."""
import json
import os
import uuid

import requests
from dotenv import load_dotenv

from ..auth import (
    get_user_context, SUPER_ADMIN_PHONE, normalize_phone,
    save_local_session_id, clear_local_session_id, get_local_session_id,
    set_request_session_id, get_request_session_id, clear_request_session_id,
    SESSION_DIR
)
from ..db import get_current_environment, set_current_environment
from ..supabase_client import session_store

load_dotenv()

# Constants
PENDING_LOGIN_FILE = os.path.join(SESSION_DIR, "pending_login.json")
VALID_ENVIRONMENTS = ("prod", "staging")

# Environment-specific API endpoints
API_BASES = {
    "prod": os.getenv("API_BASE_PROD", "https://api-prod.easydoochat.com"),
    "staging": os.getenv("API_BASE_STAGING", "https://api-staging.easydoochat.com"),
}

API_HEADERS = {
    "device_id": os.getenv("DEVICE_ID"),
    "device_type": os.getenv("DEVICE_TYPE"),
}

# Role definitions
ROLE_INFO = {
    1: {"name": "Company Admin", "level": "Authority Level 1", "access": "All branches in company"},
    2: {"name": "Branch Manager", "level": "Authority Level 2", "access": "Own branch only"},
    3: {"name": "Employee", "level": "Authority Level 3", "access": "Own data only"},
}


def get_api_url(endpoint: str) -> str:
    """Get API URL for current environment."""
    env = get_current_environment()
    base = API_BASES.get(env, API_BASES["prod"])
    return f"{base}{endpoint}"


def format_phone_number(phone: str) -> tuple[str, str | None]:
    """
    Clean and format phone number to international format.

    Returns:
        Tuple of (formatted_phone, error_message).
        If error_message is not None, the phone number is invalid.
    """
    phone = phone.strip().replace(" ", "").replace("-", "")

    if phone.startswith("+"):
        return phone, None

    if phone.startswith("91") and len(phone) == 12:
        return "+" + phone, None

    if len(phone) == 10:
        return "+91" + phone, None

    return phone, "Invalid phone number. Provide 10 digits or full number with country code (e.g., +9198XXXXXXXX)"


def save_pending_login(environment: str, device_type: str, session_id: str, phone: str) -> None:
    """Save pending login state to temp file."""
    os.makedirs(SESSION_DIR, exist_ok=True)
    with open(PENDING_LOGIN_FILE, "w") as f:
        json.dump({
            "environment": environment,
            "device_type": device_type,
            "session_id": session_id,
            "phone": phone
        }, f)


def load_pending_login() -> dict:
    """Load pending login state. Returns dict with defaults."""
    if not os.path.exists(PENDING_LOGIN_FILE):
        return {"environment": "prod", "device_type": "ios", "session_id": None, "phone": None}

    try:
        with open(PENDING_LOGIN_FILE, "r") as f:
            pending = json.load(f)
            return {
                "environment": pending.get("environment", "prod"),
                "device_type": pending.get("device_type", "ios"),
                "session_id": pending.get("session_id"),
                "phone": pending.get("phone")
            }
    except (json.JSONDecodeError, IOError):
        return {"environment": "prod", "device_type": "ios", "session_id": None, "phone": None}


def cleanup_pending_login() -> None:
    """Remove pending login temp file if it exists."""
    if os.path.exists(PENDING_LOGIN_FILE):
        os.remove(PENDING_LOGIN_FILE)


# Tool categorization rules: (category, match_function)
# Order matters - first match wins
TOOL_CATEGORY_RULES = [
    ("Authentication", lambda n: n in {
        "login", "verify_otp", "logout", "status", "whoami",
        "get_my_access", "get_my_companies", "list_tools",
    }),
    ("Employee", lambda n: "employee" in n or n in {
        "search_employee_directory", "get_document_verification_status",
    }),
    ("Attendance", lambda n: any(kw in n for kw in ("attendance", "punch", "present", "absent", "late"))),
    ("Leave", lambda n: "leave" in n),
    ("Salary", lambda n: "salary" in n or "payslip" in n),
    ("Team", lambda n: any(kw in n for kw in ("team", "manager", "org_chart"))),
    ("Organization", lambda n: any(kw in n for kw in (
        "company", "branch", "holiday", "announcement", "birthday", "joiner", "exit",
    ))),
    ("Policy", lambda n: "policy" in n or "statutory" in n),
    ("Reports", lambda n: any(kw in n for kw in (
        "summary", "utilization", "attrition", "expenditure", "headcount",
    ))),
    ("Tasks", lambda n: "task" in n),
    ("SQL", lambda n: "sql" in n or "table" in n),
    ("Location", lambda n: any(kw in n for kw in ("location", "at_work", "outside_work", "offline"))),
]


def _get_registered_tools(mcp) -> list[dict] | dict:
    """Extract registered tools from MCP server."""
    try:
        if not hasattr(mcp, "_tool_manager"):
            return []

        tool_manager = mcp._tool_manager

        if hasattr(tool_manager, "_tools"):
            return [
                {"name": name, "description": getattr(tool, "description", None) or "No description"}
                for name, tool in tool_manager._tools.items()
            ]

        if hasattr(tool_manager, "list_tools"):
            return [
                {
                    "name": getattr(tool, "name", "unknown"),
                    "description": getattr(tool, "description", None) or "No description",
                }
                for tool in tool_manager.list_tools()
            ]

        return []
    except Exception as e:
        return {"error": f"Failed to list tools: {str(e)}"}


def _categorize_tools(tools_list: list[dict]) -> dict[str, list[dict]]:
    """Categorize tools by name patterns."""
    categories = {
        "Authentication": [],
        "Employee": [],
        "Attendance": [],
        "Leave": [],
        "Salary": [],
        "Team": [],
        "Organization": [],
        "Policy": [],
        "Reports": [],
        "Tasks": [],
        "SQL": [],
        "Location": [],
        "Other": [],
    }

    for tool in tools_list:
        name = tool["name"]
        category = "Other"

        for cat_name, match_fn in TOOL_CATEGORY_RULES:
            if match_fn(name):
                category = cat_name
                break

        categories[category].append(tool)

    return {k: v for k, v in categories.items() if v}


def register(mcp):
    """Register auth tools with MCP server."""

    @mcp.tool()
    def login(phone: str, environment: str = None, device_type: str = "ios") -> dict:
        """
        Start login with phone number. This will send an OTP to the phone.
        Phone format: with country code like +9198XXXXXXXX or just 10 digits like 98XXXXXXXX.
        After receiving OTP, call verify_otp(phone, otp) to complete login.

        environment: 'prod' or 'staging' - which server to connect to.
                    If not specified, returns action_required asking user to choose.

        device_type: Device type to send with the request. Defaults to 'ios'.
                    Can be any string (e.g., 'ios', 'android', 'web', etc.)

        To switch environments: User must logout() first, then login() with the new environment.
        """
        if environment and environment not in VALID_ENVIRONMENTS:
            return {"error": "Invalid environment. Use 'prod' or 'staging'."}

        if not environment:
            return {
                "action_required": "select_environment",
                "message": "Which environment do you want to connect to?",
                "options": list(VALID_ENVIRONMENTS),
                "hint": "Call login again with environment='prod' or environment='staging'",
            }

        phone_formatted, error = format_phone_number(phone)
        if error:
            return {"error": error}

        phone_digits = normalize_phone(phone_formatted)

        # Auto-logout previous user if any (CLI only supports one user at a time)
        existing_local_session = get_local_session_id()
        if existing_local_session:
            session_store.delete(existing_local_session)  # Mark as inactive
            clear_local_session_id()

        # Check if this is super admin phone (for messaging only, still needs OTP)
        is_super_admin_phone = SUPER_ADMIN_PHONE and phone_digits == normalize_phone(SUPER_ADMIN_PHONE)

        # All users go through OTP flow (super admin included - they need token too)
        # We'll create/reuse session after OTP verification since we don't have user_id yet
        # Create a new pending session for OTP flow
        session_id = f"sess_{uuid.uuid4().hex[:16]}"

        # Create pending session in Supabase
        session_store.create(
            session_id=session_id,
            phone=phone_digits,
            environment=environment,
            mode="cli",
            is_authenticated=False,
            otp_pending=True
        )

        # Save pending login state locally
        save_pending_login(environment, device_type, session_id, phone_formatted)

        # Set environment for API URL
        set_current_environment(environment)

        try:
            resp = requests.post(
                get_api_url("/api/v2/user-otp-send"),
                headers={**API_HEADERS, "device_type": device_type},
                json={"fcm_token": "dgtewtwet", "phone_no": phone_formatted, "is_development": 1},
                timeout=10,
            )
            data = resp.json()
        except Exception as e:
            # Cleanup session on failure
            session_store.delete(session_id)
            return {"error": f"Failed to send OTP: {str(e)}"}

        if not data.get("success"):
            # Cleanup session on failure
            session_store.delete(session_id)
            return {"error": data.get("message", "Failed to send OTP")}

        result = {
            "success": True,
            "session_id": session_id,
            "phone": phone_formatted,
            "environment": environment,
        }

        otp = data.get("otp")
        if otp:
            result["message"] = f"OTP for {phone_formatted} is {otp}. Call verify_otp to complete login."
            result["otp"] = otp
        else:
            result["message"] = f"OTP sent to {phone_formatted}. Enter the OTP to complete login."

        return result

    @mcp.tool()
    def verify_otp(phone: str, otp: str) -> dict:
        """
        Verify OTP and complete login. Call this after login(phone) sends the OTP.
        """
        phone_formatted, _ = format_phone_number(phone)
        otp = otp.strip()

        # Load pending login state
        pending = load_pending_login()
        environment = pending["environment"]
        device_type = pending["device_type"]
        session_id = pending["session_id"]

        if not session_id:
            return {"error": "No pending login found. Please call login() first."}

        # Set environment for API URL
        set_current_environment(environment)

        try:
            resp = requests.post(
                get_api_url("/api/v2/user-verify-otp"),
                headers={**API_HEADERS, "device_type": device_type},
                json={"phone_no": phone_formatted, "fcm_token": "dgtewtwet", "otp": otp},
                timeout=10,
            )
            data = resp.json()
        except Exception as e:
            return {"error": f"Failed to verify OTP: {str(e)}"}

        if not data.get("success"):
            return {"error": data.get("message", "Invalid OTP")}

        user_data = data.get("data", {})
        user_id = user_data.get("user_id") or user_data.get("id")
        user_name = user_data.get("user_name", "")

        # Fetch company/RBAC data from HRMS DB
        from ..db import fetch_all
        companies_data = []
        primary_company_id = None
        primary_branch_id = None
        role_id = None

        try:
            query = """
                SELECT
                    ce.id as company_employee_id,
                    ce.company_id,
                    c.name as company_name,
                    ce.company_branch_id,
                    cb.name as branch_name,
                    ce.company_role_id as role_id,
                    ce.designation,
                    COALESCE(att.cnt, 0) as attendance_count
                FROM company_employee ce
                LEFT JOIN company c ON c.id = ce.company_id
                LEFT JOIN company_branch cb ON cb.id = ce.company_branch_id
                LEFT JOIN (
                    SELECT company_employee_id, COUNT(*) as cnt
                    FROM company_attendance
                    GROUP BY company_employee_id
                ) att ON att.company_employee_id = ce.id
                WHERE ce.user_id = $1 AND ce.is_deleted = '0'
                ORDER BY attendance_count DESC
            """
            rows = fetch_all(query, [user_id])

            for i, row in enumerate(rows):
                is_primary = (i == 0)  # First row has highest attendance
                companies_data.append({
                    "company_employee_id": row["company_employee_id"],
                    "company_id": row["company_id"],
                    "company_name": row.get("company_name", "Unknown"),
                    "company_branch_id": row.get("company_branch_id"),
                    "branch_name": row.get("branch_name", "Unknown"),
                    "role_id": row.get("role_id") or 3,
                    "designation": row.get("designation") or "",
                    "is_primary": is_primary,
                })
                if is_primary:
                    primary_company_id = row["company_id"]
                    primary_branch_id = row.get("company_branch_id")
                    role_id = row.get("role_id") or 3
        except Exception as e:
            print(f"[verify_otp] Failed to fetch companies: {e}")

        phone_digits = normalize_phone(phone_formatted)

        # Check if this is super admin (RBAC bypass, but still needs OTP for token)
        is_super_admin = SUPER_ADMIN_PHONE and phone_digits == normalize_phone(SUPER_ADMIN_PHONE)

        session_data = {
            "phone": phone_digits,
            "user_id": user_id,
            "user_name": user_name,
            "token": user_data.get("token"),
            "companies": companies_data,
            "primary_company_id": primary_company_id,
            "primary_branch_id": primary_branch_id,
            "role_id": role_id,
            "is_super_admin": is_super_admin,
        }

        # Check for existing session to reuse
        existing_session = session_store.find_by_user_mode(user_id, "cli") if user_id else None
        reused = False

        if existing_session and existing_session["session_id"] != session_id:
            # Found a different existing session - reactivate it
            final_session_id = existing_session["session_id"]
            session_store.reactivate(final_session_id, **session_data)
            # Delete the pending session we created during login
            session_store.delete(session_id)
            reused = True
        else:
            # Use the pending session (either no existing or same session)
            final_session_id = session_id
            session_store.update(
                session_id,
                is_authenticated=True,
                otp_pending=False,
                **session_data
            )

        # Save session_id locally for CLI
        save_local_session_id(final_session_id)
        cleanup_pending_login()

        return {
            "success": True,
            "message": f"Login successful! Welcome {user_name}. Connected to {environment.upper()}.",
            "session_id": final_session_id,
            "user_id": user_id,
            "user_name": user_name,
            "phone": phone_digits,
            "environment": environment,
            "is_super_admin": is_super_admin,
            "companies": companies_data,
            "primary_company_id": primary_company_id,
            "primary_branch_id": primary_branch_id,
            "role_id": role_id,
            "session_reused": reused,
        }

    @mcp.tool()
    def logout() -> dict:
        """Logout and clear saved credentials."""
        # Get current session_id from local file
        session_id = get_local_session_id()

        if session_id:
            # Delete from Supabase
            session_store.delete(session_id)

        # Clear local session file
        clear_local_session_id()
        cleanup_pending_login()

        return {"success": True, "message": "Logged out successfully."}

    @mcp.tool()
    def whoami() -> dict:
        """Check current login status and show user info."""
        ctx = get_user_context()
        if not ctx:
            return {"logged_in": False, "message": "Not logged in. Use login(phone) to login."}

        env = get_current_environment()
        result = {
            "logged_in": True,
            "user_id": ctx.user_id,
            "user_name": ctx.user_name,
            "environment": env,
        }

        if ctx.is_super_admin:
            result["role"] = "Super Admin"
        else:
            pc = ctx.primary_company
            result["primary_company"] = pc.company_name if pc else None
            result["role_in_primary"] = pc.role_name if pc else None
            result["total_companies"] = len(ctx.companies)

        return result

    @mcp.tool()
    def get_my_access() -> dict:
        """
        Check your RBAC access level and what data you can query.
        Use this to understand why a query might return no results.
        """
        ctx = get_user_context()
        if not ctx:
            return {"error": "Not authenticated. Please login first."}

        env = get_current_environment()

        if ctx.is_super_admin:
            return {
                "role": "Super Admin",
                "access_level": "Full Access",
                "environment": env,
                "description": f"You have unrestricted access to ALL data across ALL companies and branches on {env.upper()}.",
                "sql_filter": "None (no RBAC filter applied)",
                "can_access": {
                    "all_companies": True,
                    "all_branches": True,
                    "all_employees": True,
                },
            }

        pc = ctx.primary_company
        if not pc:
            return {"error": "No company association found for your account."}

        role_info = ROLE_INFO.get(pc.role_id, ROLE_INFO[3])

        if pc.role_id == 1:
            return {
                "role": f"{role_info['level']} ({role_info['name']})",
                "access_level": "Company-wide",
                "company": pc.company_name,
                "company_id": pc.company_id,
                "description": f"You can access ALL data within '{pc.company_name}' (all branches).",
                "sql_filter": f"company_id = {pc.company_id}",
                "can_access": {
                    "your_company": True,
                    "all_branches_in_company": True,
                    "all_employees_in_company": True,
                    "other_companies": False,
                },
            }

        if pc.role_id == 2:
            return {
                "role": f"{role_info['level']} ({role_info['name']})",
                "access_level": "Branch-only",
                "company": pc.company_name,
                "company_id": pc.company_id,
                "branch": pc.branch_name,
                "branch_id": pc.company_branch_id,
                "description": f"You can access data only within '{pc.branch_name}' branch of '{pc.company_name}'.",
                "sql_filter": f"company_id = {pc.company_id} AND company_branch_id = {pc.company_branch_id}",
                "can_access": {
                    "your_branch": True,
                    "other_branches": False,
                    "employees_in_your_branch": True,
                    "employees_in_other_branches": False,
                    "other_companies": False,
                },
            }

        # Default: Employee (role_id == 3)
        return {
            "role": f"{role_info['level']} ({role_info['name']})",
            "access_level": "Self-only",
            "company": pc.company_name,
            "branch": pc.branch_name,
            "employee_id": pc.company_employee_id,
            "description": "You can only access your own data.",
            "sql_filter": f"company_employee_id = {pc.company_employee_id}",
            "can_access": {
                "your_own_data": True,
                "other_employees": False,
                "other_branches": False,
                "other_companies": False,
            },
        }

    @mcp.tool()
    def list_tools() -> dict:
        """
        List all available tools in this MCP server with their descriptions.
        Use this to discover what capabilities are available.
        """
        tools_list = _get_registered_tools(mcp)
        if isinstance(tools_list, dict) and "error" in tools_list:
            return tools_list

        categories = _categorize_tools(tools_list)

        return {
            "total_tools": len(tools_list),
            "categories": categories,
            "hint": "Use any tool by calling it with the required parameters. Most tools accept optional company_name and branch_name filters.",
        }

    @mcp.tool()
    def get_my_companies() -> dict:
        """
        List all companies you belong to with your role in each.
        Shows designation, branch, and access level per company.
        """
        ctx = get_user_context()
        if not ctx:
            return {"error": "Not authenticated. Please login first."}

        if ctx.is_super_admin:
            return {
                "user_id": ctx.user_id,
                "user_name": ctx.user_name,
                "role": "Super Admin",
                "access": "Full access to ALL companies",
                "companies": [],
            }

        companies_list = []
        for comp in ctx.companies:
            role_info = ROLE_INFO.get(comp.role_id, {"name": "Unknown", "access": "Unknown"})
            companies_list.append({
                "company_name": comp.company_name,
                "branch_name": comp.branch_name,
                "designation": comp.designation,
                "role_id": comp.role_id,
                "role_name": role_info["name"],
                "access_level": role_info["access"],
                "is_primary": comp.is_primary,
                "attendance_count": comp.attendance_count,
            })

        return {
            "user_id": ctx.user_id,
            "user_name": ctx.user_name,
            "total_companies": len(ctx.companies),
            "primary_company": ctx.primary_company.company_name if ctx.primary_company else None,
            "companies": companies_list,
            "environment": get_current_environment(),
        }

    # =========================================================================
    # INTERNAL TOOLS (API mode only - filtered from agent's tool list)
    # =========================================================================

    @mcp.tool()
    def set_request_context(user_id: int, environment: str = "prod") -> dict:
        """
        [INTERNAL - API use only, not exposed to agent]
        Set user context directly from user_id without OTP flow.
        Used by API layer to authenticate requests with pre-validated user_id.

        Args:
            user_id: The user ID to set context for (must exist in HRMS DB)
            environment: 'prod' or 'staging' - which database to use

        Returns:
            dict with success status and user info, or error if user not found
        """
        if environment not in VALID_ENVIRONMENTS:
            return {"error": f"Invalid environment. Use one of: {VALID_ENVIRONMENTS}"}

        # Set environment for DB queries
        set_current_environment(environment)

        # Import here to avoid circular imports
        from ..db import fetch_all, fetch_one

        # First, validate user exists in users table
        try:
            user_query = """
                SELECT id, user_name, contact_number
                FROM users
                WHERE id = $1 AND (is_delete IS NULL OR is_delete = '0' OR is_delete = 0)
            """
            user_row = fetch_one(user_query, [user_id])
            if not user_row:
                return {"error": f"User with id {user_id} not found in {environment} database"}

            user_name = user_row.get("user_name", "Unknown")
            phone = user_row.get("contact_number", "")
        except Exception as e:
            return {"error": f"Failed to fetch user: {str(e)}"}

        # Fetch company/RBAC data from HRMS DB (same query as verify_otp)
        companies_data = []
        primary_company_id = None
        primary_branch_id = None
        role_id = None

        try:
            query = """
                SELECT
                    ce.id as company_employee_id,
                    ce.company_id,
                    c.name as company_name,
                    ce.company_branch_id,
                    cb.name as branch_name,
                    ce.company_role_id as role_id,
                    ce.designation,
                    COALESCE(att.cnt, 0) as attendance_count
                FROM company_employee ce
                LEFT JOIN company c ON c.id = ce.company_id
                LEFT JOIN company_branch cb ON cb.id = ce.company_branch_id
                LEFT JOIN (
                    SELECT company_employee_id, COUNT(*) as cnt
                    FROM company_attendance
                    GROUP BY company_employee_id
                ) att ON att.company_employee_id = ce.id
                WHERE ce.user_id = $1 AND ce.is_deleted = '0'
                ORDER BY attendance_count DESC
            """
            rows = fetch_all(query, [user_id])

            for i, row in enumerate(rows):
                is_primary = (i == 0)  # First row has highest attendance
                companies_data.append({
                    "company_employee_id": row["company_employee_id"],
                    "company_id": row["company_id"],
                    "company_name": row.get("company_name", "Unknown"),
                    "company_branch_id": row.get("company_branch_id"),
                    "branch_name": row.get("branch_name", "Unknown"),
                    "role_id": row.get("role_id") or 3,
                    "designation": row.get("designation") or "",
                    "is_primary": is_primary,
                })
                if is_primary:
                    primary_company_id = row["company_id"]
                    primary_branch_id = row.get("company_branch_id")
                    role_id = row.get("role_id") or 3
        except Exception as e:
            return {"error": f"Failed to fetch company data: {str(e)}"}

        # Check if no company associations found
        if not companies_data:
            return {"error": f"User {user_id} has no active company associations"}

        phone_digits = normalize_phone(phone) if phone else ""

        # Check if this is super admin (RBAC bypass)
        is_super_admin = SUPER_ADMIN_PHONE and phone_digits and phone_digits == normalize_phone(SUPER_ADMIN_PHONE)

        # Create a request-scoped session in Supabase
        session_id = f"req_{uuid.uuid4().hex[:16]}"

        session_data = {
            "phone": phone_digits,
            "user_id": user_id,
            "user_name": user_name,
            "token": None,  # No token in API mode
            "companies": companies_data,
            "primary_company_id": primary_company_id,
            "primary_branch_id": primary_branch_id,
            "role_id": role_id,
            "is_super_admin": is_super_admin,
        }

        # Create session in Supabase
        session_store.create(
            session_id=session_id,
            phone=phone_digits,
            environment=environment,
            mode="api",  # Mark as API mode
            is_authenticated=True,
            otp_pending=False,
            **session_data
        )

        # Set the request-scoped session ID so get_user_context() can find it
        set_request_session_id(session_id)

        return {
            "success": True,
            "session_id": session_id,
            "user_id": user_id,
            "user_name": user_name,
            "environment": environment,
            "is_super_admin": is_super_admin,
            "companies": companies_data,
            "primary_company_id": primary_company_id,
            "role_id": role_id,
        }

    @mcp.tool()
    def clear_context() -> dict:
        """
        [INTERNAL - API use only, not exposed to agent]
        Clear the current request context. Called after request processing.
        Deletes the temporary session from Supabase and clears local state.
        """
        session_id = get_request_session_id()

        if session_id:
            # Delete from Supabase
            session_store.delete(session_id)
            # Clear local request-scoped session
            clear_request_session_id()
            return {"success": True, "message": "Context cleared", "session_id": session_id}

        return {"success": True, "message": "No active context to clear"}

