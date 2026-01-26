"""Session management for multi-user support."""
import uuid
import time
from dataclasses import dataclass, field
from typing import Dict, Optional
from threading import Lock


@dataclass
class Session:
    """User session with credentials and context."""
    session_id: str
    phone: str = ""
    user_id: Optional[int] = None
    user_name: str = ""
    token: str = ""
    environment: str = "prod"  # prod or staging
    created_at: float = field(default_factory=time.time)
    last_activity: float = field(default_factory=time.time)
    is_authenticated: bool = False
    otp_pending: bool = False

    def update_activity(self):
        """Update last activity timestamp."""
        self.last_activity = time.time()

    def is_expired(self, timeout_seconds: int = 3600) -> bool:
        """Check if session has expired (default 1 hour)."""
        return time.time() - self.last_activity > timeout_seconds

    def to_dict(self) -> dict:
        """Convert to dictionary for JSON serialization."""
        return {
            "session_id": self.session_id,
            "phone": self.phone[-4:].rjust(len(self.phone), '*') if self.phone else "",
            "user_id": self.user_id,
            "user_name": self.user_name,
            "environment": self.environment,
            "is_authenticated": self.is_authenticated,
            "created_at": self.created_at,
            "last_activity": self.last_activity
        }


class SessionManager:
    """Thread-safe session manager for multi-user support."""

    def __init__(self, session_timeout: int = 3600):
        self._sessions: Dict[str, Session] = {}
        self._lock = Lock()
        self._session_timeout = session_timeout  # seconds

    def create_session(self, phone: str = "", environment: str = "prod") -> Session:
        """Create a new session."""
        session_id = f"sess_{uuid.uuid4().hex[:16]}"
        session = Session(
            session_id=session_id,
            phone=phone,
            environment=environment
        )
        with self._lock:
            self._sessions[session_id] = session
        return session

    def get_session(self, session_id: str) -> Optional[Session]:
        """Get session by ID, returns None if expired or not found."""
        with self._lock:
            session = self._sessions.get(session_id)
            if session:
                if session.is_expired(self._session_timeout):
                    del self._sessions[session_id]
                    return None
                session.update_activity()
                return session
        return None

    def update_session(self, session_id: str, **kwargs) -> Optional[Session]:
        """Update session attributes."""
        with self._lock:
            session = self._sessions.get(session_id)
            if session:
                for key, value in kwargs.items():
                    if hasattr(session, key):
                        setattr(session, key, value)
                session.update_activity()
                return session
        return None

    def delete_session(self, session_id: str) -> bool:
        """Delete a session (logout)."""
        with self._lock:
            if session_id in self._sessions:
                del self._sessions[session_id]
                return True
        return False

    def cleanup_expired(self) -> int:
        """Remove all expired sessions. Returns count of removed sessions."""
        removed = 0
        with self._lock:
            expired_ids = [
                sid for sid, session in self._sessions.items()
                if session.is_expired(self._session_timeout)
            ]
            for sid in expired_ids:
                del self._sessions[sid]
                removed += 1
        return removed

    def get_active_count(self) -> int:
        """Get count of active (non-expired) sessions."""
        with self._lock:
            return sum(
                1 for session in self._sessions.values()
                if not session.is_expired(self._session_timeout)
            )

    def list_sessions(self) -> list:
        """List all active sessions (for admin/debugging)."""
        with self._lock:
            return [
                session.to_dict()
                for session in self._sessions.values()
                if not session.is_expired(self._session_timeout)
            ]


# Global session manager instance
session_manager = SessionManager()


def get_session(session_id: str) -> Optional[Session]:
    """Get session by ID (convenience function)."""
    return session_manager.get_session(session_id)


def create_session(phone: str = "", environment: str = "prod") -> Session:
    """Create new session (convenience function)."""
    return session_manager.create_session(phone, environment)


def delete_session(session_id: str) -> bool:
    """Delete session (convenience function)."""
    return session_manager.delete_session(session_id)
