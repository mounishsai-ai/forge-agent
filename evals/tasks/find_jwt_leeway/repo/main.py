import time

from app.api.routes import handle_request
from app.utils.crypto_utils import encode_jwt


def main():
    token = encode_jwt({"exp": time.time() + 3600, "sub": "demo"})
    session = {"expires_at": time.time() + 3600}
    print(handle_request(token, session))


if __name__ == "__main__":
    main()
