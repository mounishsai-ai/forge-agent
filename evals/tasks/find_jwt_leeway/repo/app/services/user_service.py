from app.users import get_display_name, check_password_expiry


def summarize_user(user):
    return {
        "name": get_display_name(user),
        "password_expired": check_password_expiry(user),
    }
