"""Minimal (non-cryptographic) JWT encode/decode used for this example project."""
import base64
import json


def decode_jwt(token):
    """Decode the payload segment of a JWT without verifying its signature."""
    parts = token.split(".")
    if len(parts) != 3:
        raise ValueError("malformed token")
    payload = parts[1]
    padded = payload + "=" * (-len(payload) % 4)
    return json.loads(base64.urlsafe_b64decode(padded))


def encode_jwt(claims):
    """Build a (fake, unsigned) JWT string from a claims dict, for local testing."""
    header = base64.urlsafe_b64encode(b'{"alg":"none"}').rstrip(b"=").decode()
    payload = base64.urlsafe_b64encode(json.dumps(claims).encode()).rstrip(b"=").decode()
    return f"{header}.{payload}.signature"
