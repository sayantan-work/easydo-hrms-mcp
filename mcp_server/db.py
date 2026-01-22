"""Database connection with toggle between direct PostgreSQL and n8n webhook."""
import json
import os
from typing import Any

import requests
from dotenv import load_dotenv

load_dotenv()

# Constants
CREDENTIALS_FILE = os.path.expanduser("~/.easydo/credentials.json")
DEFAULT_ENV = "prod"

# Database mode: "direct" or "n8n"
DB_MODE = os.getenv("DB_MODE", "n8n")

# n8n webhook URLs (used when DB_MODE=n8n)
WEBHOOKS = {
    "prod": os.getenv("N8N_WEBHOOK_PROD"),
    "staging": os.getenv("N8N_WEBHOOK_STAGING"),
}

# Direct connection settings (used when DB_MODE=direct)
DIRECT_DB = {
    "prod": {
        "host": os.getenv("DB_HOST_PROD", "localhost"),
        "port": int(os.getenv("DB_PORT_PROD", "5432")),
        "dbname": os.getenv("DB_NAME_PROD", "hrms"),
        "user": os.getenv("DB_USER_PROD", "postgres"),
        "password": os.getenv("DB_PASSWORD_PROD", ""),
    },
    "staging": {
        "host": os.getenv("DB_HOST_STAGING", "localhost"),
        "port": int(os.getenv("DB_PORT_STAGING", "5432")),
        "dbname": os.getenv("DB_NAME_STAGING", "hrms_staging"),
        "user": os.getenv("DB_USER_STAGING", "postgres"),
        "password": os.getenv("DB_PASSWORD_STAGING", ""),
    },
}

# Connection pool for direct mode
_connection_pool = {}


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


def _get_direct_connection():
    """Get or create a direct PostgreSQL connection for current environment."""
    env = get_current_environment()

    if env in _connection_pool:
        conn = _connection_pool[env]
        # Check if connection is still alive
        try:
            conn.cursor().execute("SELECT 1")
            return conn
        except Exception:
            # Connection dead, remove from pool
            try:
                conn.close()
            except Exception:
                pass
            del _connection_pool[env]

    # Create new connection
    try:
        import psycopg2
        from psycopg2.extras import RealDictCursor
    except ImportError:
        raise ImportError(
            "psycopg2 is required for direct DB mode. "
            "Install it with: pip install psycopg2-binary"
        )

    db_config = DIRECT_DB.get(env, DIRECT_DB[DEFAULT_ENV])
    conn = psycopg2.connect(
        host=db_config["host"],
        port=db_config["port"],
        dbname=db_config["dbname"],
        user=db_config["user"],
        password=db_config["password"],
        cursor_factory=RealDictCursor,
    )
    conn.autocommit = True
    _connection_pool[env] = conn
    return conn


def _make_error(message: str) -> dict[str, Any]:
    """Create a standardized error response."""
    return {"success": False, "error": message}


def _execute_via_n8n(query: str, params: list | None = None) -> dict[str, Any]:
    """Execute SQL query via n8n webhook."""
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


def _execute_direct(query: str, params: list | None = None) -> dict[str, Any]:
    """Execute SQL query directly via psycopg2."""
    try:
        conn = _get_direct_connection()
        cursor = conn.cursor()

        # Convert $1, $2 style params to %s style for psycopg2
        if params:
            import re
            converted_query = re.sub(r'\$(\d+)', '%s', query)
            cursor.execute(converted_query, params)
        else:
            cursor.execute(query)

        # Fetch results
        if cursor.description:
            rows = cursor.fetchall()
            # Convert RealDictRow to regular dict
            data = [dict(row) for row in rows]
            return {"success": True, "data": data}
        else:
            return {"success": True, "data": []}

    except Exception as e:
        return _make_error(f"Database error: {e}")


def execute_query(query: str, params: list | None = None) -> dict[str, Any]:
    """
    Execute SQL query via configured mode (direct or n8n).

    Args:
        query: SQL SELECT/WITH query
        params: List of parameters for parameterized queries ($1, $2, etc.)

    Returns:
        dict with 'success', 'data' or 'error' keys
    """
    if DB_MODE == "direct":
        return _execute_direct(query, params)
    else:
        return _execute_via_n8n(query, params)


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


def get_db_mode() -> str:
    """Get current database mode for debugging."""
    return DB_MODE
