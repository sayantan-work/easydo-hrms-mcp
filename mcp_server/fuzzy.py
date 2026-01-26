"""Fuzzy search utilities for MCP server."""
from rapidfuzz import fuzz, process
from typing import List, Tuple, Optional


def fuzzy_match(query: str, choices: List[str], threshold: int = 60, limit: int = 10) -> List[Tuple[str, float]]:
    """
    Find fuzzy matches for a query string against a list of choices.

    Args:
        query: The search query (potentially with typos)
        choices: List of strings to match against
        threshold: Minimum similarity score (0-100) to include in results
        limit: Maximum number of results to return

    Returns:
        List of (matched_string, score) tuples, sorted by score descending
    """
    if not query or not choices:
        return []

    # Use token_set_ratio for better handling of partial matches and word order
    results = process.extract(
        query,
        choices,
        scorer=fuzz.token_set_ratio,
        limit=limit
    )

    # Filter by threshold and return
    return [(match, score) for match, score, _ in results if score >= threshold]


def fuzzy_match_best(query: str, choices: List[str], threshold: int = 60) -> Optional[str]:
    """
    Find the best fuzzy match for a query.

    Args:
        query: The search query
        choices: List of strings to match against
        threshold: Minimum similarity score to accept

    Returns:
        Best matching string or None if no match above threshold
    """
    matches = fuzzy_match(query, choices, threshold=threshold, limit=1)
    return matches[0][0] if matches else None


def build_fuzzy_sql_pattern(query: str) -> str:
    """
    Build a SQL LIKE pattern that handles common typos.
    Converts query into a pattern with wildcards between characters.

    Example: "infospce" -> "%i%n%f%o%s%p%c%e%"
    """
    # Remove extra spaces and convert to lowercase
    query = query.strip().lower()

    # Create pattern with wildcards
    pattern = "%".join(query)
    return f"%{pattern}%"


def normalize_company_name(name: str) -> str:
    """
    Normalize company name for comparison.
    Removes common suffixes like PVT, LTD, PRIVATE, LIMITED, etc.
    """
    if not name:
        return ""

    name = name.lower().strip()

    # Remove common company suffixes
    suffixes = [
        'pvt. ltd.', 'pvt ltd', 'pvt.ltd.', 'pvt.ltd',
        'private limited', 'private ltd', 'private ltd.',
        'limited', 'ltd.', 'ltd',
        'llp', 'llc', 'inc.', 'inc', 'corp.', 'corp',
        'pvt', 'private'
    ]

    for suffix in suffixes:
        if name.endswith(suffix):
            name = name[:-len(suffix)].strip()

    # Remove extra punctuation
    name = name.rstrip('.')

    return name.strip()
