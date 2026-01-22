"""Role-Based Access Control helpers with multi-company support."""
from .auth import UserContext

# Role IDs for RBAC
ROLE_COMPANY_ADMIN = 1
ROLE_BRANCH_MANAGER = 2
ROLE_EMPLOYEE = 3

# Sensitive fields that should be hidden except for own profile or super admin
SENSITIVE_FIELDS = [
    "pan_number",
    "aadhar_card_number",
    "uan_number",
    "bank_account_number",
    "bank_ifsc_code",
    "personal_email",
    "emergency_contact_number",
]

HIDDEN_VALUE = "***HIDDEN***"


def _build_company_filter(company, prefix: str) -> str:
    """Build SQL filter clause for a single company based on role."""
    if company.role_id == ROLE_COMPANY_ADMIN:
        return f"{prefix}company_id = {company.company_id}"

    if company.role_id == ROLE_BRANCH_MANAGER:
        return (
            f"({prefix}company_id = {company.company_id} "
            f"AND {prefix}company_branch_id = {company.company_branch_id})"
        )

    # Employee (role 3) - own data only
    return f"{prefix}company_employee_id = {company.company_employee_id}"


def apply_company_filter(ctx: UserContext, base_query: str, table_alias: str = "") -> str:
    """
    Apply RBAC filter to query based on user role across ALL companies.

    For multi-company users, generates OR conditions for each company
    with appropriate RBAC per company role.

    Inserts the filter after WHERE clause but before GROUP BY/ORDER BY/LIMIT.
    """
    import re

    if ctx.is_super_admin:
        return base_query

    if not ctx.companies:
        return f"{base_query} AND 1=0"

    prefix = f"{table_alias}." if table_alias else ""
    company_filters = [_build_company_filter(comp, prefix) for comp in ctx.companies]

    if len(company_filters) == 1:
        filter_clause = company_filters[0]
    else:
        filter_clause = f"({' OR '.join(company_filters)})"

    # Find the position to insert the filter (before GROUP BY, ORDER BY, LIMIT, or end)
    # Case-insensitive search for these keywords
    insert_keywords = [r'\bGROUP\s+BY\b', r'\bORDER\s+BY\b', r'\bLIMIT\b', r'\bHAVING\b']

    insert_pos = len(base_query)
    for pattern in insert_keywords:
        match = re.search(pattern, base_query, re.IGNORECASE)
        if match and match.start() < insert_pos:
            insert_pos = match.start()

    # Insert the AND filter at the correct position
    before = base_query[:insert_pos].rstrip()
    after = base_query[insert_pos:]

    if after:
        return f"{before} AND {filter_clause} {after}"
    else:
        return f"{before} AND {filter_clause}"


def _is_own_employee_id(ctx: UserContext, employee_id: int) -> bool:
    """Check if the given employee ID belongs to the current user."""
    return employee_id in ctx.get_all_company_employee_ids()


def _has_manager_role(ctx: UserContext) -> bool:
    """Check if user has any manager role (admin or branch manager) in any company."""
    return any(c.role_id != ROLE_EMPLOYEE for c in ctx.companies)


def can_view_employee(ctx: UserContext, target_employee_id: int) -> bool:
    """Check if user can view a specific employee's data."""
    if ctx.is_super_admin:
        return True

    if _is_own_employee_id(ctx, target_employee_id):
        return True

    # Managers can view employees in their scope (filtered by company/branch in query)
    return _has_manager_role(ctx)


def can_view_sensitive_fields(ctx: UserContext, target_employee_id: int) -> bool:
    """Check if user can view sensitive fields for an employee."""
    if ctx.is_super_admin:
        return True

    return _is_own_employee_id(ctx, target_employee_id)


def filter_sensitive_fields(ctx: UserContext, data: dict, target_employee_id: int) -> dict:
    """Remove sensitive fields if user doesn't have permission."""
    if can_view_sensitive_fields(ctx, target_employee_id):
        return data

    filtered = data.copy()
    for field_name in SENSITIVE_FIELDS:
        if field_name in filtered:
            filtered[field_name] = HIDDEN_VALUE

    return filtered
