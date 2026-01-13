"""Authentication tools for MCP server."""
import os
import json
import requests

from ..auth import get_user_context

# API endpoints
OTP_REQUEST_URL = "https://api-prod.easydoochat.com/api/v2/user-otp-send"
OTP_VERIFY_URL = "https://api-prod.easydoochat.com/api/v2/user-verify-otp"
API_HEADERS = {
    "device_id": "123456",
    "device_type": "ios"
}


def register(mcp):
    """Register auth tools with MCP server."""

    @mcp.tool()
    def login(phone: str) -> dict:
        """
        Start login with phone number. This will send an OTP to the phone.
        Phone format: with country code like +919163991280 or just 10 digits like 9163991280.
        After receiving OTP, call verify_otp(phone, otp) to complete login.
        """
        # Clean and format phone number
        phone = phone.strip().replace(" ", "").replace("-", "")

        # Add +91 if not present
        if not phone.startswith("+"):
            if phone.startswith("91") and len(phone) == 12:
                phone = "+" + phone
            elif len(phone) == 10:
                phone = "+91" + phone
            else:
                return {"error": "Invalid phone number. Provide 10 digits or full number with country code (e.g., +919163991280)"}

        try:
            resp = requests.post(
                OTP_REQUEST_URL,
                headers=API_HEADERS,
                json={"fcm_token": "claude-mcp", "phone_no": phone, "is_development": 1},
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
                        "otp": otp
                    }
                else:
                    return {
                        "success": True,
                        "message": f"OTP sent to {phone}. Enter the OTP to complete login.",
                        "phone": phone
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

        try:
            # Verify uses form data, not JSON
            resp = requests.post(
                OTP_VERIFY_URL,
                headers=API_HEADERS,
                data={"phone_no": phone, "fcm_token": "123456", "otp": otp},
                timeout=10
            )
            data = resp.json()

            if data.get("success"):
                user_data = data.get("data", {})

                # Save credentials
                cred_dir = os.path.expanduser("~/.easydo")
                os.makedirs(cred_dir, exist_ok=True)

                creds = {
                    "user_id": user_data.get("user_id"),
                    "user_name": user_data.get("user_name"),
                    "phone": phone,
                    "token": user_data.get("token"),
                    "token_expires_at": user_data.get("token_expires_at")
                }

                with open(os.path.join(cred_dir, "credentials.json"), "w") as f:
                    json.dump(creds, f, indent=2)

                return {
                    "success": True,
                    "message": f"Login successful! Welcome {creds['user_name']}.",
                    "user_id": creds["user_id"],
                    "user_name": creds["user_name"]
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
    def whoami() -> dict:
        """Check current login status and show user info."""
        ctx = get_user_context()
        if not ctx:
            return {"logged_in": False, "message": "Not logged in. Use login(phone) to login."}

        if ctx.is_super_admin:
            return {
                "logged_in": True,
                "user_id": ctx.user_id,
                "user_name": ctx.user_name,
                "role": "Super Admin"
            }

        return {
            "logged_in": True,
            "user_id": ctx.user_id,
            "user_name": ctx.user_name,
            "primary_company": ctx.primary_company.company_name if ctx.primary_company else None,
            "role_in_primary": ctx.primary_company.role_name if ctx.primary_company else None,
            "total_companies": len(ctx.companies)
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

        if ctx.is_super_admin:
            return {
                "role": "Super Admin",
                "access_level": "Full Access",
                "description": "You have unrestricted access to ALL data across ALL companies and branches.",
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
