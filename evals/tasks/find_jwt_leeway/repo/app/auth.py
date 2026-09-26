"""JWT authentication helpers."""
import time

from app.utils.crypto_utils import decode_jwt

DEFAULT_LEEWAY_SECONDS = 30


def validate_jwt_expiry(token, leeway=None):
    """Check whether a JWT's `exp` claim is still valid.

    A grace period (`leeway`, in seconds) is applied to tolerate clock drift
    between services. If `leeway` is not given, DEFAULT_LEEWAY_SECONDS is used.
    """
    if leeway is None:
        leeway = DEFAULT_LEEWAY_SECONDS
    claims = decode_jwt(token)
    exp = claims.get("exp")
    if exp is None:
        raise ValueError("token has no exp claim")
    return time.time() <= exp + leeway


def get_claims(token):
    return decode_jwt(token)
