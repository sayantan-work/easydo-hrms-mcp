"""Role-Based Access Control helpers with multi-company support."""
from .auth import UserContext

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


def apply_company_filter(ctx: UserContext, base_query: str, table_alias: str = "") -> str:
    """
    Apply RBAC filter to query based on user role across ALL companies.

    For multi-company users, generates OR conditions for each company
    with appropriate RBAC per company role.
    """
    if ctx.is_super_admin:
        return base_query

    prefix = f"{table_alias}." if table_alias else ""

    if not ctx.companies:
        # No companies - return impossible condition
        return f"{base_query} AND 1=0"

    # Build filter for each company based on role
    company_filters = []
    for comp in ctx.companies:
        if comp.role_id == 1:  # Company Admin - all branches
            company_filters.append(f"{prefix}company_id = {comp.company_id}")
        elif comp.role_id == 2:  # Branch Manager - own branch only
            company_filters.append(
                f"({prefix}company_id = {comp.company_id} AND {prefix}company_branch_id = {comp.company_branch_id})"
            )
        else:  # Employee (role 3) - own data only
            company_filters.append(f"{prefix}company_employee_id = {comp.company_employee_id}")

    # Combine with OR
    if len(company_filters) == 1:
        return f"{base_query} AND {company_filters[0]}"
    else:
        combined = " OR ".join(company_filters)
        return f"{base_query} AND ({combined})"


def get_company_employee_ids(ctx: UserContext) -> list:
    """Get all company_employee_ids for the user."""
    return [c.company_employee_id for c in ctx.companies]


def can_view_employee(ctx: UserContext, target_employee_id: int) -> bool:
    """Check if user can view a specific employee's data."""
    if ctx.is_super_admin:
        return True

    # Check if target is one of user's own employee IDs
    if target_employee_id in get_company_employee_ids(ctx):
        return True

    # For managers, they can view if employee is in their scope
    # This will be filtered by company/branch in query
    return not all(c.role_id == 3 for c in ctx.companies)


def can_view_sensitive_fields(ctx: UserContext, target_employee_id: int) -> bool:
    """Check if user can view sensitive fields for an employee."""
    if ctx.is_super_admin:
        return True

    # Can only view own sensitive data
    return target_employee_id in get_company_employee_ids(ctx)


def filter_sensitive_fields(ctx: UserContext, data: dict, target_employee_id: int) -> dict:
    """Remove sensitive fields if user doesn't have permission."""
    if can_view_sensitive_fields(ctx, target_employee_id):
        return data

    filtered = data.copy()
    for field in SENSITIVE_FIELDS:
        if field in filtered:
            filtered[field] = "***HIDDEN***"

    return filtered
