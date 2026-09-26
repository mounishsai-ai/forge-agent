from app.auth import validate_jwt_expiry
from app.sessions import validate_session_expiry


def handle_request(token, session):
    if not validate_jwt_expiry(token):
        return {"status": 401, "error": "token expired"}
    if not validate_session_expiry(session):
        return {"status": 401, "error": "session expired"}
    return {"status": 200}
