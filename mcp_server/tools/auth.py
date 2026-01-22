"""Authentication tools for MCP server."""
import json
import os

import requests
from dotenv import load_dotenv

from ..auth import get_user_context, SUPER_ADMIN_PHONE, normalize_phone
from ..db import get_current_environment

load_dotenv()

# Constants
CREDENTIALS_DIR = os.path.expanduser("~/.easydo")
CREDENTIALS_FILE = os.path.join(CREDENTIALS_DIR, "credentials.json")
PENDING_LOGIN_FILE = os.path.join(CREDENTIALS_DIR, "pending_login.json")
VALID_ENVIRONMENTS = ("prod", "staging")

# Environment-specific API endpoints
API_BASES = {
    "prod": os.getenv("API_BASE_PROD"),
    "staging": os.getenv("API_BASE_STAGING"),
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


def save_pending_login(environment: str, device_type: str) -> None:
    """Save pending login state to temp file."""
    os.makedirs(CREDENTIALS_DIR, exist_ok=True)
    with open(PENDING_LOGIN_FILE, "w") as f:
        json.dump({"environment": environment, "device_type": device_type}, f)


def load_pending_login() -> tuple[str, str]:
    """Load pending login state. Returns (environment, device_type) with defaults."""
    if not os.path.exists(PENDING_LOGIN_FILE):
        return "prod", "ios"

    try:
        with open(PENDING_LOGIN_FILE, "r") as f:
            pending = json.load(f)
            return pending.get("environment", "prod"), pending.get("device_type", "ios")
    except (json.JSONDecodeError, IOError):
        return "prod", "ios"


def save_credentials(creds: dict) -> None:
    """Save credentials to file."""
    os.makedirs(CREDENTIALS_DIR, exist_ok=True)
    with open(CREDENTIALS_FILE, "w") as f:
        json.dump(creds, f, indent=2)


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

        phone, error = format_phone_number(phone)
        if error:
            return {"error": error}

        # Check if super admin - bypass OTP
        if SUPER_ADMIN_PHONE and normalize_phone(phone) == normalize_phone(SUPER_ADMIN_PHONE):
            # Temporarily set environment so DB queries work
            save_credentials({"environment": environment})

            # Try to fetch actual user record from DB
            from ..db import fetch_one
            user_data = None
            try:
                # Phone stored as contact_number (without country code) or with +91 prefix
                phone_digits = normalize_phone(phone)  # Last 10 digits
                user_data = fetch_one(
                    "SELECT id, user_name FROM users WHERE contact_number = $1 OR contact_number = $2 LIMIT 1",
                    [phone_digits, phone]
                )
            except Exception:
                pass  # DB lookup failed, use defaults

            creds = {
                "user_id": user_data.get("id") if user_data else None,
                "user_name": user_data.get("user_name", "Super Admin") if user_data else "Super Admin",
                "phone": phone,
                "token": None,
                "token_expires_at": None,
                "environment": environment,
            }
            save_credentials(creds)
            cleanup_pending_login()

            return {
                "success": True,
                "message": f"Super Admin login successful! Connected to {environment.upper()}. No OTP required.",
                "user_id": creds["user_id"],
                "user_name": creds["user_name"],
                "environment": environment,
                "is_super_admin": True,
            }

        save_pending_login(environment, device_type)

        try:
            resp = requests.post(
                get_api_url("/api/v2/user-otp-send"),
                headers={**API_HEADERS, "device_type": device_type},
                json={"fcm_token": "dgtewtwet", "phone_no": phone, "is_development": 1},
                timeout=10,
            )
            data = resp.json()
        except Exception as e:
            return {"error": f"Failed to send OTP: {str(e)}"}

        if not data.get("success"):
            return {"error": data.get("message", "Failed to send OTP")}

        result = {
            "success": True,
            "phone": phone,
            "environment": environment,
        }

        otp = data.get("otp")
        if otp:
            result["message"] = f"OTP for {phone} is {otp}. Call verify_otp to complete login."
            result["otp"] = otp
        else:
            result["message"] = f"OTP sent to {phone}. Enter the OTP to complete login."

        return result

    @mcp.tool()
    def verify_otp(phone: str, otp: str) -> dict:
        """
        Verify OTP and complete login. Call this after login(phone) sends the OTP.
        """
        phone, _ = format_phone_number(phone)
        otp = otp.strip()

        environment, device_type = load_pending_login()

        # Temporarily set environment so get_api_url works correctly
        save_credentials({"environment": environment})

        try:
            resp = requests.post(
                get_api_url("/api/v2/user-verify-otp"),
                headers={**API_HEADERS, "device_type": device_type},
                data={"phone_no": phone, "fcm_token": "dgtewtwet", "otp": otp},
                timeout=10,
            )
            data = resp.json()
        except Exception as e:
            return {"error": f"Failed to verify OTP: {str(e)}"}

        if not data.get("success"):
            return {"error": data.get("message", "Invalid OTP")}

        user_data = data.get("data", {})
        creds = {
            "user_id": user_data.get("user_id"),
            "user_name": user_data.get("user_name"),
            "phone": phone,
            "token": user_data.get("token"),
            "token_expires_at": user_data.get("token_expires_at"),
            "environment": environment,
        }

        save_credentials(creds)
        cleanup_pending_login()

        return {
            "success": True,
            "message": f"Login successful! Welcome {creds['user_name']}. Connected to {environment.upper()}.",
            "user_id": creds["user_id"],
            "user_name": creds["user_name"],
            "environment": environment,
        }

    @mcp.tool()
    def logout() -> dict:
        """Logout and clear saved credentials."""
        if os.path.exists(CREDENTIALS_FILE):
            os.remove(CREDENTIALS_FILE)
            return {"success": True, "message": "Logged out successfully."}
        return {"success": True, "message": "Already logged out."}

    @mcp.tool()
    def status() -> dict:
        """Check if MCP is authenticated and ready to use."""
        if not os.path.exists(CREDENTIALS_FILE):
            return {
                "authenticated": False,
                "status": "NOT_AUTHENTICATED",
                "message": "Not logged in. Use login(phone, environment) to authenticate.",
                "hint": "Example: login('98XXXXXXXX', 'prod') or login('98XXXXXXXX', 'staging')",
            }

        try:
            with open(CREDENTIALS_FILE, "r") as f:
                creds = json.load(f)
        except (json.JSONDecodeError, IOError):
            return {
                "authenticated": False,
                "status": "CORRUPTED_CREDENTIALS",
                "message": "Credentials file is corrupted. Please login again.",
            }

        if not creds.get("user_id"):
            return {
                "authenticated": False,
                "status": "INVALID_CREDENTIALS",
                "message": "Credentials file exists but is invalid. Please login again.",
            }

        env = creds.get("environment", "prod")
        return {
            "authenticated": True,
            "status": "READY",
            "user_id": creds.get("user_id"),
            "user_name": creds.get("user_name"),
            "environment": env,
            "message": f"Authenticated as {creds.get('user_name')} on {env.upper()}. Ready to use.",
        }

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

