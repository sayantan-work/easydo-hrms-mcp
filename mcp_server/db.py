"""Database connection via n8n webhook."""
import requests
from typing import Any

N8N_WEBHOOK_URL = "https://n8n.easydoochat.com/webhook/d6ff802e-055b-4ec9-8e6b-bf4f9cd8a5b7"


def execute_query(query: str, params: list = None) -> dict[str, Any]:
    """
    Execute SQL query via n8n webhook.

    Args:
        query: SQL SELECT/WITH query
        params: List of parameters for parameterized queries ($1, $2, etc.)

    Returns:
        dict with 'success', 'data' or 'error' keys
    """
    if params is None:
        params = []

    try:
        response = requests.post(
            N8N_WEBHOOK_URL,
            json={"query": query, "params": params},
            headers={"Content-Type": "application/json"},
            timeout=30
        )

        # Check for HTTP errors
        if response.status_code != 200:
            return {"success": False, "error": f"Database request failed with status {response.status_code}"}

        # Handle empty response as valid "no results" case
        if not response.text or response.text.strip() == "":
            return {"success": True, "data": []}

        try:
            return response.json()
        except ValueError as json_err:
            return {"success": False, "error": f"Invalid response from database: {response.text[:200]}"}

    except requests.RequestException as e:
        return {"success": False, "error": f"Database connection error: {str(e)}"}


def fetch_all(query: str, params: list = None) -> list[dict]:
    """Execute query and return list of rows."""
    result = execute_query(query, params)
    if result.get("success"):
        return result.get("data", [])
    raise Exception(result.get("error", "Unknown database error"))


def fetch_one(query: str, params: list = None) -> dict | None:
    """Execute query and return first row or None."""
    rows = fetch_all(query, params)
    return rows[0] if rows else None
