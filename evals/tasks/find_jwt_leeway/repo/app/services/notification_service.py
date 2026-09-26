def notify(user, message):
    return f"[to {user.get('username', 'unknown')}] {message}"
