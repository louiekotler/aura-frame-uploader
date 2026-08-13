"""Authentication against api.pushd.com, with the token kept in the keyring.

Only the auth token is persisted, never the password. The token appears to be
long-lived; when it stops working the tool asks for a fresh login rather than
holding the password to renew silently.
"""

import getpass
import json

import keyring
import requests

from .errors import ApiError, NotLoggedIn

BASE_URL = "https://api.pushd.com/v5"
KEYRING_SERVICE = "aura-upload"
KEYRING_KEY = "session"

# Mirrors the payload the Aura iOS client sends; the API rejects logins that
# omit these fields.
APP_IDENTIFIER = "com.pushd.Framelord"
DEVICE_ID = "aura-frame-uploader"


def login(email: str, password: str | None = None) -> dict:
    password = password or getpass.getpass(f"Aura password for {email}: ")
    payload = {
        "identifier_for_vendor": DEVICE_ID,
        "client_device_id": DEVICE_ID,
        "app_identifier": APP_IDENTIFIER,
        "locale": "en",
        "user": {"email": email, "password": password},
    }
    r = requests.post(f"{BASE_URL}/login.json", json=payload, timeout=30)
    if r.status_code != 200:
        raise ApiError("Login failed — check the email and password.", r.status_code)

    body = r.json()
    result = body.get("result") or {}
    user = result.get("current_user") or {}
    if not user.get("auth_token"):
        raise ApiError(f"Login response had no auth token: {str(body)[:300]}")

    session = {
        "user_id": user["id"],
        "auth_token": user["auth_token"],
        "email": email,
        "name": user.get("name"),
    }
    keyring.set_password(KEYRING_SERVICE, KEYRING_KEY, json.dumps(session))
    return session


def load_session() -> dict:
    raw = keyring.get_password(KEYRING_SERVICE, KEYRING_KEY)
    if not raw:
        raise NotLoggedIn("Not logged in. Run `aura-upload login --email you@example.com`.")
    return json.loads(raw)


def logout() -> bool:
    try:
        keyring.delete_password(KEYRING_SERVICE, KEYRING_KEY)
        return True
    except keyring.errors.PasswordDeleteError:
        return False
