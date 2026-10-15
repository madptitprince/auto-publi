import os
import time
import base64
import hmac
import hashlib
import secrets
from fastapi import Request
from dotenv import load_dotenv

load_dotenv()

DEFAULT_USERNAME = "admin"
DEFAULT_PASSWORD = "muxa2002"
DEFAULT_SECRET = "bchef_bourges_auth_secret_key_2026_muxa"

COOKIE_NAME = "bchef_session"
SESSION_DURATION_DAYS = 7


def get_auth_config() -> tuple[str, str, str]:
    username = os.getenv("DASHBOARD_USERNAME", DEFAULT_USERNAME).strip()
    password = os.getenv("DASHBOARD_PASSWORD", DEFAULT_PASSWORD).strip()
    secret_key = os.getenv("DASHBOARD_SECRET_KEY", DEFAULT_SECRET).strip()
    return username, password, secret_key


def verify_credentials(user_input: str, pwd_input: str) -> bool:
    expected_user, expected_pwd, _ = get_auth_config()
    user_match = secrets.compare_digest(user_input.strip().encode("utf-8"), expected_user.encode("utf-8"))
    pwd_match = secrets.compare_digest(pwd_input.strip().encode("utf-8"), expected_pwd.encode("utf-8"))
    return user_match and pwd_match


def create_session_token(username: str) -> str:
    _, _, secret = get_auth_config()
    expires_at = int(time.time()) + (SESSION_DURATION_DAYS * 86400)
    payload = f"{username}:{expires_at}"
    signature = hmac.new(secret.encode("utf-8"), payload.encode("utf-8"), hashlib.sha256).hexdigest()
    raw_token = f"{payload}:{signature}"
    return base64.urlsafe_b64encode(raw_token.encode("utf-8")).decode("utf-8")


def verify_session_token(token: str | None) -> str | None:
    if not token:
        return None
    try:
        raw = base64.urlsafe_b64decode(token.encode("utf-8")).decode("utf-8")
        parts = raw.split(":")
        if len(parts) != 3:
            return None
        username, expires_str, signature = parts
        expires_at = int(expires_str)
        if time.time() > expires_at:
            return None

        expected_user, _, secret = get_auth_config()
        if not secrets.compare_digest(username.encode("utf-8"), expected_user.encode("utf-8")):
            return None

        payload = f"{username}:{expires_at}"
        expected_sig = hmac.new(secret.encode("utf-8"), payload.encode("utf-8"), hashlib.sha256).hexdigest()
        if secrets.compare_digest(signature.encode("utf-8"), expected_sig.encode("utf-8")):
            return username
        return None
    except Exception:
        return None


def verify_basic_auth(auth_header: str | None) -> str | None:
    if not auth_header or not auth_header.startswith("Basic "):
        return None
    try:
        b64_creds = auth_header.split(" ", 1)[1]
        decoded = base64.b64decode(b64_creds).decode("utf-8")
        if ":" not in decoded:
            return None
        u, p = decoded.split(":", 1)
        if verify_credentials(u, p):
            return u
        return None
    except Exception:
        return None


def get_authenticated_user(request: Request) -> str | None:
    # 1. Check Session Cookie
    cookie_token = request.cookies.get(COOKIE_NAME)
    user = verify_session_token(cookie_token)
    if user:
        return user

    # 2. Check Authorization Header (Basic Auth for API/cURL)
    auth_header = request.headers.get("Authorization")
    user = verify_basic_auth(auth_header)
    if user:
        return user

    return None
