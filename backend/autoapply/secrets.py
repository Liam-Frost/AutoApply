"""Secret storage.

Passwords, API keys and OAuth tokens live in the OS keyring (Windows Credential
Manager). They are never written to SQLite, logs, run records, or LLM context.
Code that needs a secret calls ``get``; nothing returns a secret to an API
response except the explicit "reveal password" endpoint.
"""

from __future__ import annotations

import base64
import json
import os
import secrets as _secrets
import string

import keyring
from cryptography.fernet import Fernet

SERVICE = os.environ.get("AUTOAPPLY_KEYRING_SERVICE", "autoapply")

# Well-known secret names
ANTHROPIC_KEY = "anthropic_api_key"
TELEGRAM_TOKEN = "telegram_bot_token"
CLAUDE_OAUTH_TOKEN = "claude_oauth_token"
GMAIL_TOKEN = "gmail_oauth_token"
GMAIL_CLIENT = "gmail_oauth_client"
SESSION_KEY = "session_encryption_key"


def get(name: str) -> str | None:
    return keyring.get_password(SERVICE, name)


def put(name: str, value: str) -> None:
    keyring.set_password(SERVICE, name, value)


def delete(name: str) -> None:
    try:
        keyring.delete_password(SERVICE, name)
    except keyring.errors.PasswordDeleteError:
        pass


def has(name: str) -> bool:
    return get(name) is not None


# --- account passwords ---------------------------------------------------------


def _acct(tenant_key: str) -> str:
    return f"account:{tenant_key}"


def get_password(tenant_key: str) -> str | None:
    return get(_acct(tenant_key))


def put_password(tenant_key: str, password: str) -> None:
    put(_acct(tenant_key), password)


def delete_password(tenant_key: str) -> None:
    delete(_acct(tenant_key))


def generate_password(
    length: int = 20,
    *,
    upper: bool = True,
    lower: bool = True,
    digits: bool = True,
    symbols: str = "!@#$%^&*",
) -> str:
    """Random password that satisfies a driver-declared policy."""
    pools = []
    if upper:
        pools.append(string.ascii_uppercase)
    if lower:
        pools.append(string.ascii_lowercase)
    if digits:
        pools.append(string.digits)
    if symbols:
        pools.append(symbols)
    chars = [_secrets.choice(p) for p in pools]
    alphabet = "".join(pools)
    chars += [_secrets.choice(alphabet) for _ in range(max(0, length - len(chars)))]
    _secrets.SystemRandom().shuffle(chars)
    return "".join(chars)


# --- encryption of browser storage states --------------------------------------


def _fernet() -> Fernet:
    key = get(SESSION_KEY)
    if key is None:
        key = Fernet.generate_key().decode()
        put(SESSION_KEY, key)
    return Fernet(key.encode())


def encrypt_json(obj: object) -> bytes:
    return _fernet().encrypt(json.dumps(obj).encode())


def decrypt_json(blob: bytes) -> object:
    return json.loads(_fernet().decrypt(blob).decode())


def redact(text: str, *values: str | None) -> str:
    """Remove secret values from a string before it is logged."""
    for v in values:
        if v:
            text = text.replace(v, "•••")
            text = text.replace(base64.b64encode(v.encode()).decode(), "•••")
    return text
