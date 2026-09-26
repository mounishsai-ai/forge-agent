"""User management operations with input validation."""


def create_user(name, age, email):
    if not name:
        raise ValueError("name is required")
    if not isinstance(age, int) or age < 0 or age > 150:
        raise ValueError("age must be an integer between 0 and 150")
    if "@" not in email:
        raise ValueError("email must contain '@'")
    return {"name": name, "age": age, "email": email, "action": "created"}


def update_user(name, age, email):
    if not name:
        raise ValueError("name is required")
    if not isinstance(age, int) or age < 0 or age > 150:
        raise ValueError("age must be an integer between 0 and 150")
    if "@" not in email:
        raise ValueError("email must contain '@'")
    return {"name": name, "age": age, "email": email, "action": "updated"}


def register_user(name, age, email):
    if not name:
        raise ValueError("name is required")
    if not isinstance(age, int) or age < 0 or age > 150:
        raise ValueError("age must be an integer between 0 and 150")
    if "@" not in email:
        raise ValueError("email must contain '@'")
    return {"name": name, "age": age, "email": email, "action": "registered"}
