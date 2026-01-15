"""Authentication and user context management with multi-company RBAC."""
import os
import json
from dataclasses import dataclass, field
from typing import Optional, List
from dotenv import load_dotenv
from .db import fetch_one, fetch_all

# Load environment variables
load_dotenv()

# Super admin user ID (bypasses all RBAC) - from .env
SUPER_ADMIN_USER_ID = int(os.getenv("SUPER_ADMIN_USER_ID", "0"))


@dataclass
class CompanyContext:
    """Context for a single company the user belongs to."""
    company_employee_id: int
    company_id: int
    company_name: str
    company_branch_id: int
    branch_name: str
    role_id: int  # 1=Authority Level 1, 2=Authority Level 2, 3=Authority Level 3
    designation: str = ""
    attendance_count: int = 0
    is_primary: bool = False

    @property
    def role_name(self) -> str:
        return {1: "Authority Level 1", 2: "Authority Level 2", 3: "Authority Level 3"}.get(self.role_id, "Unknown")


@dataclass
class UserContext:
    """User context with multi-company RBAC support."""
    user_id: int
    user_name: str
    companies: List[CompanyContext] = field(default_factory=list)

    @property
    def is_super_admin(self) -> bool:
        return self.user_id == SUPER_ADMIN_USER_ID

    @property
    def primary_company(self) -> Optional[CompanyContext]:
        """Get the primary company (most attendance records)."""
        for c in self.companies:
            if c.is_primary:
                return c
        return self.companies[0] if self.companies else None

    def get_company_context(self, company_id: int) -> Optional[CompanyContext]:
        """Get context for a specific company by ID."""
        for c in self.companies:
            if c.company_id == company_id:
                return c
        return None

    def get_company_by_name(self, company_name: str) -> Optional[CompanyContext]:
        """Get context for a specific company by name (case-insensitive partial match)."""
        company_name_lower = company_name.lower()
        for c in self.companies:
            if company_name_lower in c.company_name.lower():
                return c
        return None

    def get_all_company_employee_ids(self) -> list:
        """Get all company_employee_ids for this user."""
        return [c.company_employee_id for c in self.companies]

    # Convenience properties using primary company
    @property
    def company_employee_id(self) -> int:
        return self.primary_company.company_employee_id if self.primary_company else 0

    @property
    def company_id(self) -> int:
        return self.primary_company.company_id if self.primary_company else 0

    @property
    def company_branch_id(self) -> int:
        return self.primary_company.company_branch_id if self.primary_company else 0

    @property
    def role_id(self) -> int:
        return self.primary_company.role_id if self.primary_company else 3

    @property
    def is_company_admin(self) -> bool:
        return self.primary_company.role_id == 1 if self.primary_company else False

    @property
    def is_branch_manager(self) -> bool:
        return self.primary_company.role_id == 2 if self.primary_company else False

    @property
    def is_employee(self) -> bool:
        return self.primary_company.role_id == 3 if self.primary_company else True


def load_credentials() -> Optional[dict]:
    """Load credentials from ~/.easydo/credentials.json"""
    cred_file = os.path.expanduser("~/.easydo/credentials.json")
    if os.path.exists(cred_file):
        with open(cred_file, "r") as f:
            return json.load(f)
    return None


def get_user_context() -> Optional[UserContext]:
    """
    Get user context with all companies and their roles.
    Primary company = most attendance records.

    Note: Even super admins get their company associations populated
    so that "my" queries (get_my_salary, etc.) know which companies to query.
    Super admin RBAC bypass happens in apply_company_filter, not here.
    """
    creds = load_credentials()
    if not creds:
        return None

    user_id = creds.get("user_id")
    if not user_id:
        return None

    user_name = creds.get("user_name", "Unknown")

    # Query ALL company_employee records with attendance counts
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

    try:
        rows = fetch_all(query, [user_id])
        companies = []

        for i, row in enumerate(rows):
            att_count = row.get("attendance_count") or 0
            if isinstance(att_count, str):
                att_count = int(att_count)

            companies.append(CompanyContext(
                company_employee_id=row["company_employee_id"],
                company_id=row["company_id"],
                company_name=row.get("company_name", "Unknown"),
                company_branch_id=row.get("company_branch_id") or 0,
                branch_name=row.get("branch_name", "Unknown"),
                role_id=row.get("role_id") or 3,
                designation=row.get("designation") or "",
                attendance_count=att_count,
                is_primary=(i == 0)  # First row has highest attendance (ORDER BY DESC)
            ))

        return UserContext(user_id=user_id, user_name=user_name, companies=companies)

    except Exception:
        return UserContext(user_id=user_id, user_name=user_name, companies=[])


def require_auth(func):
    """Decorator to require authentication for tool functions."""
    def wrapper(*args, **kwargs):
        ctx = get_user_context()
        if not ctx:
            return {"error": "Not authenticated. Please run /sql-login first."}
        return func(ctx, *args, **kwargs)
    return wrapper
