"""Session-based authentication for multi-user support."""
import os
from typing import Optional

from dotenv import load_dotenv

from .db import fetch_all
from .auth import UserContext, CompanyContext, normalize_phone
from .sessions import Session, get_session

load_dotenv()

SUPER_ADMIN_PHONE = os.getenv("SUPER_ADMIN_PHONE", "").strip()


def get_user_context_for_session(session: Session) -> Optional[UserContext]:
    """
    Get user context for a specific session.
    Similar to get_user_context() but uses session data instead of global credentials.
    """
    if not session or not session.is_authenticated:
        return None

    user_id = session.user_id
    user_name = session.user_name
    phone = session.phone

    # Check if super admin by phone
    is_super = SUPER_ADMIN_PHONE and phone and normalize_phone(phone) == normalize_phone(SUPER_ADMIN_PHONE)

    # If no user_id but is super admin, return context with no companies
    if not user_id:
        if is_super:
            return UserContext(user_id=0, user_name=user_name or "Super Admin", phone=phone, companies=[])
        return None

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
                is_primary=(i == 0)
            ))

        return UserContext(user_id=user_id, user_name=user_name, phone=phone, companies=companies)

    except Exception:
        return UserContext(user_id=user_id, user_name=user_name, phone=phone, companies=[])


def get_user_context_by_session_id(session_id: str) -> Optional[UserContext]:
    """Get user context using session ID."""
    session = get_session(session_id)
    if not session:
        return None
    return get_user_context_for_session(session)
