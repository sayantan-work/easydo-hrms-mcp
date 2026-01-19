"""Database connection via n8n webhook."""
import json
import os
from typing import Any

import requests
from dotenv import load_dotenv

load_dotenv()

# Constants
CREDENTIALS_FILE = os.path.expanduser("~/.easydo/credentials.json")
DEFAULT_ENV = "prod"
WEBHOOKS = {
    "prod": os.getenv("N8N_WEBHOOK_PROD"),
    "staging": os.getenv("N8N_WEBHOOK_STAGING"),
}


def _load_credentials() -> dict | None:
    """Load credentials from file, returning None on any error."""
    if not os.path.exists(CREDENTIALS_FILE):
        return None
    try:
        with open(CREDENTIALS_FILE, "r") as f:
            return json.load(f)
    except (ValueError, IOError):
        return None


def get_current_environment() -> str:
    """Get the current environment from credentials file."""
    creds = _load_credentials()
    if creds:
        return creds.get("environment", DEFAULT_ENV)
    return DEFAULT_ENV


def get_webhook_url() -> str:
    """Get the webhook URL for current environment."""
    env = get_current_environment()
    return WEBHOOKS.get(env) or WEBHOOKS[DEFAULT_ENV]


def _make_error(message: str) -> dict[str, Any]:
    """Create a standardized error response."""
    return {"success": False, "error": message}


def execute_query(query: str, params: list | None = None) -> dict[str, Any]:
    """
    Execute SQL query via n8n webhook.

    Args:
        query: SQL SELECT/WITH query
        params: List of parameters for parameterized queries ($1, $2, etc.)

    Returns:
        dict with 'success', 'data' or 'error' keys
    """
    try:
        response = requests.post(
            get_webhook_url(),
            json={"query": query, "params": params or []},
            headers={"Content-Type": "application/json"},
            timeout=30,
        )
    except requests.RequestException as e:
        return _make_error(f"Database connection error: {e}")

    if response.status_code != 200:
        return _make_error(f"Database request failed with status {response.status_code}")

    if not response.text.strip():
        return {"success": True, "data": []}

    try:
        return response.json()
    except ValueError:
        return _make_error(f"Invalid response from database: {response.text[:200]}")


def fetch_all(query: str, params: list | None = None) -> list[dict]:
    """Execute query and return list of rows, raising on error."""
    result = execute_query(query, params)
    if result.get("success"):
        return result.get("data", [])
    raise Exception(result.get("error", "Unknown database error"))


def fetch_one(query: str, params: list | None = None) -> dict | None:
    """Execute query and return first row or None."""
    rows = fetch_all(query, params)
    return rows[0] if rows else None
