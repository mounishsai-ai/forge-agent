"""Server-side web session (cookie) handling, distinct from JWT auth."""
import time

SESSION_LEEWAY_SECONDS = 60


def validate_session_expiry(session, leeway=SESSION_LEEWAY_SECONDS):
    """Check whether a server-side session dict is still valid."""
    expires_at = session.get("expires_at")
    if expires_at is None:
        return False
    return time.time() <= expires_at + leeway


def touch_session(session):
    session["last_seen"] = time.time()
    return session
