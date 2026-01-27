"""Supabase client for session management."""
import os
from datetime import datetime, timedelta, timezone
from typing import Optional
from dotenv import load_dotenv

load_dotenv()

SUPABASE_URL = os.getenv("SUPABASE_URL", "")
SUPABASE_KEY = os.getenv("SUPABASE_SERVICE_KEY", "")

_client = None


def get_supabase():
    """Get Supabase client singleton."""
    global _client
    if _client is None:
        if not SUPABASE_URL or not SUPABASE_KEY:
            raise ValueError("SUPABASE_URL and SUPABASE_SERVICE_KEY must be set in .env")
        from supabase import create_client
        _client = create_client(SUPABASE_URL, SUPABASE_KEY)
    return _client


class SessionStore:
    """Supabase-backed session storage for MCP."""

    TABLE = "api_sessions"

    def create(self, session_id: str, phone: str, environment: str = "prod",
               mode: str = "cli", **kwargs) -> Optional[dict]:
        """Create a new session in Supabase."""
        try:
            client = get_supabase()
            data = {
                "session_id": session_id,
                "phone": phone,
                "environment": environment,
                "mode": mode,
                "active": True,
                "is_authenticated": False,
                "otp_pending": True,
                **kwargs
            }
            result = client.table(self.TABLE).insert(data).execute()
            return result.data[0] if result.data else None
        except Exception as e:
            print(f"[SessionStore] Create error: {e}")
            return None

    def get(self, session_id: str) -> Optional[dict]:
        """Get session by ID. Returns None if expired, inactive, or not found."""
        try:
            client = get_supabase()
            now = datetime.now(timezone.utc)
            result = client.table(self.TABLE) \
                .select("*") \
                .eq("session_id", session_id) \
                .eq("active", True) \
                .gte("expires_at", now.isoformat()) \
                .execute()

            if result.data:
                # Update last_activity
                client.table(self.TABLE) \
                    .update({"last_activity": now.isoformat()}) \
                    .eq("session_id", session_id) \
                    .execute()
                return result.data[0]
            return None
        except Exception as e:
            print(f"[SessionStore] Get error: {e}")
            return None

    def update(self, session_id: str, **kwargs) -> Optional[dict]:
        """Update session fields."""
        try:
            client = get_supabase()
            kwargs["last_activity"] = datetime.now(timezone.utc).isoformat()
            result = client.table(self.TABLE) \
                .update(kwargs) \
                .eq("session_id", session_id) \
                .execute()
            return result.data[0] if result.data else None
        except Exception as e:
            print(f"[SessionStore] Update error: {e}")
            return None

    def delete(self, session_id: str) -> bool:
        """Soft delete - mark session as inactive."""
        try:
            client = get_supabase()
            now = datetime.now(timezone.utc).isoformat()
            client.table(self.TABLE) \
                .update({"active": False, "logged_out_at": now}) \
                .eq("session_id", session_id) \
                .execute()
            return True
        except Exception as e:
            print(f"[SessionStore] Delete error: {e}")
            return False

    def find_by_user_mode(self, user_id: int, mode: str) -> Optional[dict]:
        """Find existing session for user+mode combination."""
        try:
            client = get_supabase()
            result = client.table(self.TABLE) \
                .select("*") \
                .eq("user_id", user_id) \
                .eq("mode", mode) \
                .order("created_at", desc=True) \
                .limit(1) \
                .execute()
            return result.data[0] if result.data else None
        except Exception as e:
            print(f"[SessionStore] FindByUserMode error: {e}")
            return None

    def reactivate(self, session_id: str, **kwargs) -> Optional[dict]:
        """Reactivate an inactive session."""
        try:
            client = get_supabase()
            now = datetime.now(timezone.utc)
            update_data = {
                "active": True,
                "is_authenticated": True,
                "otp_pending": False,
                "logged_out_at": None,
                "last_activity": now.isoformat(),
                "expires_at": (now + timedelta(hours=1)).isoformat(),
                **kwargs
            }
            result = client.table(self.TABLE) \
                .update(update_data) \
                .eq("session_id", session_id) \
                .execute()
            return result.data[0] if result.data else None
        except Exception as e:
            print(f"[SessionStore] Reactivate error: {e}")
            return None

    def get_by_mode(self, mode: str, limit: int = 10) -> list:
        """Get sessions by mode (cli/client)."""
        try:
            client = get_supabase()
            result = client.table(self.TABLE) \
                .select("*") \
                .eq("mode", mode) \
                .gte("expires_at", "now()") \
                .order("last_activity", desc=True) \
                .limit(limit) \
                .execute()
            return result.data or []
        except Exception as e:
            print(f"[SessionStore] GetByMode error: {e}")
            return []


# Singleton instance
session_store = SessionStore()
