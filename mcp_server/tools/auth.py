"""Authentication tools for MCP server."""
import os
import json
import requests
from dotenv import load_dotenv

from ..auth import get_user_context
from ..db import get_current_environment

# Load environment variables from .env file
load_dotenv()

# Environment-specific API endpoints (from .env - required)
API_BASES = {
    "prod": os.getenv("API_BASE_PROD"),
    "staging": os.getenv("API_BASE_STAGING")
}

API_HEADERS = {
    "device_id": os.getenv("DEVICE_ID"),
    "device_type": os.getenv("DEVICE_TYPE")
}


def get_api_url(endpoint: str) -> str:
    """Get API URL for current environment."""
    env = get_current_environment()
    base = API_BASES.get(env, API_BASES["prod"])
    return f"{base}{endpoint}"


def register(mcp):
    """Register auth tools with MCP server."""

    @mcp.tool()
    def login(phone: str, environment: str = None) -> dict:
        """
        Start login with phone number. This will send an OTP to the phone.
        Phone format: with country code like +9198XXXXXXXX or just 10 digits like 98XXXXXXXX.
        After receiving OTP, call verify_otp(phone, otp) to complete login.

        environment: 'prod' or 'staging' - which server to connect to.
                    If not specified, returns action_required asking user to choose.

        To switch environments: User must logout() first, then login() with the new environment.
        """
        # Validate environment
        if environment and environment not in ["prod", "staging"]:
            return {"error": "Invalid environment. Use 'prod' or 'staging'."}

        if not environment:
            return {
                "action_required": "select_environment",
                "message": "Which environment do you want to connect to?",
                "options": ["prod", "staging"],
                "hint": "Call login again with environment='prod' or environment='staging'"
            }

        # Store selected environment temporarily (will be saved permanently on verify_otp)
        cred_dir = os.path.expanduser("~/.easydo")
        os.makedirs(cred_dir, exist_ok=True)
        temp_file = os.path.join(cred_dir, "pending_login.json")
        with open(temp_file, "w") as f:
            json.dump({"environment": environment}, f)

        # Clean and format phone number
        phone = phone.strip().replace(" ", "").replace("-", "")

        # Add +91 if not present
        if not phone.startswith("+"):
            if phone.startswith("91") and len(phone) == 12:
                phone = "+" + phone
            elif len(phone) == 10:
                phone = "+91" + phone
            else:
                return {"error": "Invalid phone number. Provide 10 digits or full number with country code (e.g., +9198XXXXXXXX)"}

        try:
            otp_url = get_api_url("/api/v2/user-otp-send")
            resp = requests.post(
                otp_url,
                headers=API_HEADERS,
                json={"fcm_token": "claude-mcp", "phone_no": phone},
                timeout=10
            )
            data = resp.json()

            if data.get("success"):
                # In dev mode, OTP is returned in response
                otp = data.get("otp")
                if otp:
                    return {
                        "success": True,
                        "message": f"OTP for {phone} is {otp}. Call verify_otp to complete login.",
                        "phone": phone,
                        "otp": otp,
                        "environment": environment
                    }
                else:
                    return {
                        "success": True,
                        "message": f"OTP sent to {phone}. Enter the OTP to complete login.",
                        "phone": phone,
                        "environment": environment
                    }
            else:
                return {"error": data.get("message", "Failed to send OTP")}
        except Exception as e:
            return {"error": f"Failed to send OTP: {str(e)}"}

    @mcp.tool()
    def verify_otp(phone: str, otp: str) -> dict:
        """
        Verify OTP and complete login. Call this after login(phone) sends the OTP.
        """
        # Clean and format phone number
        phone = phone.strip().replace(" ", "").replace("-", "")
        if not phone.startswith("+"):
            if phone.startswith("91") and len(phone) == 12:
                phone = "+" + phone
            elif len(phone) == 10:
                phone = "+91" + phone

        otp = otp.strip()

        # Get pending environment from temp file
        cred_dir = os.path.expanduser("~/.easydo")
        temp_file = os.path.join(cred_dir, "pending_login.json")
        environment = "prod"  # default
        if os.path.exists(temp_file):
            try:
                with open(temp_file, "r") as f:
                    pending = json.load(f)
                    environment = pending.get("environment", "prod")
            except (json.JSONDecodeError, IOError):
                pass

        try:
            # Use environment-specific API URL
            # Temporarily set environment for get_api_url to work
            temp_creds = {"environment": environment}
            with open(os.path.join(cred_dir, "credentials.json"), "w") as f:
                json.dump(temp_creds, f)

            verify_url = get_api_url("/api/v2/user-verify-otp")

            # Verify uses form data, not JSON
            resp = requests.post(
                verify_url,
                headers=API_HEADERS,
                data={"phone_no": phone, "fcm_token": "123456", "otp": otp},
                timeout=10
            )
            data = resp.json()

            if data.get("success"):
                user_data = data.get("data", {})

                # Save credentials with environment
                creds = {
                    "user_id": user_data.get("user_id"),
                    "user_name": user_data.get("user_name"),
                    "phone": phone,
                    "token": user_data.get("token"),
                    "token_expires_at": user_data.get("token_expires_at"),
                    "environment": environment
                }

                with open(os.path.join(cred_dir, "credentials.json"), "w") as f:
                    json.dump(creds, f, indent=2)

                # Clean up temp file
                if os.path.exists(temp_file):
                    os.remove(temp_file)

                return {
                    "success": True,
                    "message": f"Login successful! Welcome {creds['user_name']}. Connected to {environment.upper()}.",
                    "user_id": creds["user_id"],
                    "user_name": creds["user_name"],
                    "environment": environment
                }
            else:
                return {"error": data.get("message", "Invalid OTP")}
        except Exception as e:
            return {"error": f"Failed to verify OTP: {str(e)}"}

    @mcp.tool()
    def logout() -> dict:
        """Logout and clear saved credentials."""
        cred_file = os.path.expanduser("~/.easydo/credentials.json")
        if os.path.exists(cred_file):
            os.remove(cred_file)
            return {"success": True, "message": "Logged out successfully."}
        return {"success": True, "message": "Already logged out."}

    @mcp.tool()
    def status() -> dict:
        """Check if MCP is authenticated and ready to use."""
        cred_file = os.path.expanduser("~/.easydo/credentials.json")

        if not os.path.exists(cred_file):
            return {
                "authenticated": False,
                "status": "NOT_AUTHENTICATED",
                "message": "Not logged in. Use login(phone, environment) to authenticate.",
                "hint": "Example: login('98XXXXXXXX', 'prod') or login('98XXXXXXXX', 'staging')"
            }

        try:
            with open(cred_file, "r") as f:
                creds = json.load(f)

            if not creds.get("user_id"):
                return {
                    "authenticated": False,
                    "status": "INVALID_CREDENTIALS",
                    "message": "Credentials file exists but is invalid. Please login again."
                }

            env = creds.get("environment", "prod")
            return {
                "authenticated": True,
                "status": "READY",
                "user_id": creds.get("user_id"),
                "user_name": creds.get("user_name"),
                "environment": env,
                "message": f"Authenticated as {creds.get('user_name')} on {env.upper()}. Ready to use."
            }
        except (json.JSONDecodeError, IOError):
            return {
                "authenticated": False,
                "status": "CORRUPTED_CREDENTIALS",
                "message": "Credentials file is corrupted. Please login again."
            }

    @mcp.tool()
    def whoami() -> dict:
        """Check current login status and show user info."""
        ctx = get_user_context()
        if not ctx:
            return {"logged_in": False, "message": "Not logged in. Use login(phone) to login."}

        env = get_current_environment()

        if ctx.is_super_admin:
            return {
                "logged_in": True,
                "user_id": ctx.user_id,
                "user_name": ctx.user_name,
                "role": "Super Admin",
                "environment": env
            }

        return {
            "logged_in": True,
            "user_id": ctx.user_id,
            "user_name": ctx.user_name,
            "primary_company": ctx.primary_company.company_name if ctx.primary_company else None,
            "role_in_primary": ctx.primary_company.role_name if ctx.primary_company else None,
            "total_companies": len(ctx.companies),
            "environment": env
        }

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
                    "all_employees": True
                }
            }

        pc = ctx.primary_company
        if not pc:
            return {"error": "No company association found for your account."}

        if pc.role_id == 1:  # Company Admin
            return {
                "role": "Authority Level 1 (Company Admin)",
                "access_level": "Company-wide",
                "company": pc.company_name,
                "company_id": pc.company_id,
                "description": f"You can access ALL data within '{pc.company_name}' (all branches).",
                "sql_filter": f"company_id = {pc.company_id}",
                "can_access": {
                    "your_company": True,
                    "all_branches_in_company": True,
                    "all_employees_in_company": True,
                    "other_companies": False
                }
            }
        elif pc.role_id == 2:  # Branch Manager
            return {
                "role": "Authority Level 2 (Branch Manager)",
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
                    "other_companies": False
                }
            }
        else:  # Employee
            return {
                "role": "Authority Level 3 (Employee)",
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
                    "other_companies": False
                }
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
                "companies": []
            }

        # Map role_id to role info
        role_map = {
            1: {"name": "Company Admin", "access": "All branches in company"},
            2: {"name": "Branch Manager", "access": "Own branch only"},
            3: {"name": "Employee", "access": "Own data only"}
        }

        companies_list = []
        for comp in ctx.companies:
            role_info = role_map.get(comp.role_id, {"name": "Unknown", "access": "Unknown"})
            companies_list.append({
                "company_name": comp.company_name,
                "branch_name": comp.branch_name,
                "designation": comp.designation,
                "role_id": comp.role_id,
                "role_name": role_info["name"],
                "access_level": role_info["access"],
                "is_primary": comp.is_primary,
                "attendance_count": comp.attendance_count
            })

        return {
            "user_id": ctx.user_id,
            "user_name": ctx.user_name,
            "total_companies": len(ctx.companies),
            "primary_company": ctx.primary_company.company_name if ctx.primary_company else None,
            "companies": companies_list,
            "environment": get_current_environment()
        }

