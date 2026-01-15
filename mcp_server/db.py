"""Database connection via n8n webhook."""
import os
import json
import requests
from typing import Any
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# Environment-specific webhook URLs (from .env)
WEBHOOKS = {
    "prod": os.getenv("N8N_WEBHOOK_PROD"),
    "staging": os.getenv("N8N_WEBHOOK_STAGING")
}

# Default environment
DEFAULT_ENV = "prod"


def get_current_environment() -> str:
    """Get the current environment from credentials file."""
    cred_file = os.path.expanduser("~/.easydo/credentials.json")
    if os.path.exists(cred_file):
        try:
            with open(cred_file, "r") as f:
                creds = json.load(f)
                return creds.get("environment", DEFAULT_ENV)
        except (json.JSONDecodeError, IOError):
            pass
    return DEFAULT_ENV


def get_webhook_url() -> str:
    """Get the webhook URL for current environment."""
    env = get_current_environment()
    return WEBHOOKS.get(env, WEBHOOKS[DEFAULT_ENV])


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
        webhook_url = get_webhook_url()
        response = requests.post(
            webhook_url,
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
