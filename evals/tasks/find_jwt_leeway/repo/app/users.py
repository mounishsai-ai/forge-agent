"""User account helpers."""

PASSWORD_MAX_AGE_DAYS = 90


def check_password_expiry(user):
    """Return True if the user's password is older than PASSWORD_MAX_AGE_DAYS."""
    age_days = user.get("password_age_days", 0)
    return age_days > PASSWORD_MAX_AGE_DAYS


def get_display_name(user):
    return user.get("full_name") or user.get("username", "unknown")
