"""Permission grants can themselves expire, independent of the user's JWT."""
import time

PERMISSION_LEEWAY_SECONDS = 15


def validate_permission_expiry(grant, leeway=PERMISSION_LEEWAY_SECONDS):
    expires_at = grant.get("expires_at")
    if expires_at is None:
        return True
    return time.time() <= expires_at + leeway


def has_permission(user, perm):
    return perm in user.get("permissions", [])
