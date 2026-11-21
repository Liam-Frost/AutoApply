"""Carrying a sign-in from one computer to another.

Some sign-ins cannot be done on a server at all: a passkey lives on the device in your hand, and some sites will
only sign you in on a computer they have seen before. So: sign in where it works - AutoApply on your own computer -
and carry the saved sign-in over. On that computer the site's saved session is written to a file, encrypted with a
passphrase you choose; on the server the file and the passphrase put it in place.

The file holds what a browser holds after signing in (cookies and local storage for that one site, and the sign-in
provider's if it was "Sign in with ..."): whoever has the file and the passphrase is signed in as you there. It is
never written anywhere by the program - it is handed to the browser as a download - and the passphrase is not kept.

A site may tie a sign-in to where it was made; a carried session can then be refused, and the next run says so the
way it always does when a sign-in has run out.
"""

from __future__ import annotations

from .say import say as T

import base64
import hashlib
import json
import os
from typing import Any

from cryptography.fernet import Fernet, InvalidToken

from . import browser

KIND = "autoapply-session"
MIN_PASSPHRASE = 8


class Refused(ValueError):
    """The file or the passphrase is not what it should be. The message is for the person."""


def _fernet(passphrase: str, salt: bytes) -> Fernet:
    return Fernet(base64.urlsafe_b64encode(hashlib.scrypt(passphrase.encode(), salt=salt, n=2**14, r=8, p=1, dklen=32)))


def _check(passphrase: str) -> None:
    if len(passphrase or "") < MIN_PASSPHRASE:
        raise Refused(T("server.transfer.thePassphraseNeedsAt", p0=MIN_PASSPHRASE))


def export(tenant_key: str, passphrase: str, *, host: str = "") -> bytes:
    """The saved sign-in of one site, as an encrypted file's content."""
    _check(passphrase)
    state = browser.load_state(tenant_key)
    if not state or not state.get("cookies"):
        raise Refused(T("server.transfer.noSignInIs"))
    salt = os.urandom(16)
    box = {"kind": KIND, "v": 1, "tenant": tenant_key, "host": host, "salt": base64.b64encode(salt).decode(),
           "data": _fernet(passphrase, salt).encrypt(json.dumps(state).encode()).decode()}
    return json.dumps(box).encode()


def read(blob: bytes, passphrase: str) -> dict[str, Any]:
    """What a file holds: {"tenant", "host", "state"}. Nothing is saved."""
    try:
        box = json.loads(blob.decode("utf-8"))
        if box.get("kind") != KIND or box.get("v") != 1:
            raise ValueError
        salt, data, tenant = base64.b64decode(box["salt"]), str(box["data"]).encode(), str(box["tenant"])
    except (ValueError, KeyError, UnicodeDecodeError, TypeError):
        raise Refused(T("server.transfer.thisIsNotA")) from None
    try:
        state = json.loads(_fernet(passphrase or "", salt).decrypt(data))
    except InvalidToken:
        raise Refused(T("server.transfer.thePassphraseIsWrong")) from None
    if not isinstance(state, dict) or not isinstance(state.get("cookies"), list):
        raise Refused(T("server.transfer.whatTheFileHolds"))
    return {"tenant": tenant, "host": str(box.get("host") or ""), "state": state}


def put(blob: bytes, passphrase: str) -> dict[str, str]:
    """Put a carried sign-in in place on this computer. Returns which site it was for."""
    from . import auth

    got = read(blob, passphrase)
    tenant = got["tenant"]
    browser.replace_state(tenant, got["state"])
    if not tenant.startswith("idp:"):            # a sign-in provider's session is not a site account
        auth.upsert_account(tenant, host=got["host"], status="ok", created_by="takeover")
    return {"tenant": tenant, "host": got["host"]}
