from app.permissions import validate_permission_expiry


def enforce_permission_grant(grant):
    if not validate_permission_expiry(grant):
        raise PermissionError("permission grant expired")
