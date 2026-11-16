"""Secret storage.

Passwords, API keys and OAuth tokens are never written to SQLite, logs, run records, or LLM context.
Code that needs a secret calls ``get``; nothing returns a secret to an API response except the explicit
"reveal password" endpoint.

Where they are kept:

- the operating system's keyring (Windows Credential Manager, the macOS Keychain, the desktop's Secret Service),
  where there is one;
- otherwise - a server, a container: no desktop, so no keyring - one encrypted file, ``data/secrets.bin``. Its key is
  made from a master key that comes from ``AUTOAPPLY_MASTER_KEY``, from the file named in
  ``AUTOAPPLY_MASTER_KEY_FILE`` (a systemd credential, a Docker secret), or, when neither is given, from
  ``data/secrets.key``, which the program creates readable by the owner only.

The file is weaker than a keyring: whoever can read the master key can read the secrets. With the key beside the
data that is "whoever can read the data folder as you"; keep the key elsewhere to do better. ``describe()`` says which
store is in use, and the settings page and ``autoapply doctor`` show it.

Once ``data/secrets.bin`` exists it is the store on this computer, so the secrets are never split between two
places. ``AUTOAPPLY_SECRETS=keyring|file`` decides by hand.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import secrets as _secrets
import string
import threading
import time
from contextlib import contextmanager
from pathlib import Path

import keyring
from cryptography.fernet import Fernet, InvalidToken

SERVICE = os.environ.get("AUTOAPPLY_KEYRING_SERVICE", "autoapply")

# Well-known secret names
ANTHROPIC_KEY = "anthropic_api_key"
TELEGRAM_TOKEN = "telegram_bot_token"
CLAUDE_OAUTH_TOKEN = "claude_oauth_token"
GMAIL_TOKEN = "gmail_oauth_token"
GMAIL_CLIENT = "gmail_oauth_client"
SESSION_KEY = "session_encryption_key"


class Unavailable(RuntimeError):
    """The secrets cannot be read: the master key is missing or is not the one the file was written with."""


# --- the encrypted file ---------------------------------------------------------


class FileStore:
    """Every secret in one file, encrypted as a whole. Small (tens of entries), rewritten on each change."""

    def __init__(self, folder: Path):
        self.path, self.key_path = folder / "secrets.bin", folder / "secrets.key"
        self._lock = threading.Lock()
        self._seen: tuple[float, dict[str, str]] | None = None     # the file's time when it was read, and what it held

    def master(self, create: bool) -> tuple[str, str]:
        """The master key and where it came from."""
        if os.environ.get("AUTOAPPLY_MASTER_KEY"):
            return os.environ["AUTOAPPLY_MASTER_KEY"], "AUTOAPPLY_MASTER_KEY"
        named = os.environ.get("AUTOAPPLY_MASTER_KEY_FILE")
        if named:
            try:
                return Path(named).read_text(encoding="utf-8").strip(), named
            except OSError as e:
                raise Unavailable(f"the master key file {named} cannot be read: {e}") from e
        if not self.key_path.exists():
            if not create:
                raise Unavailable(f"{self.path.name} is there but its key ({self.key_path.name}) is not: give the master key it was written with")
            self.key_path.parent.mkdir(parents=True, exist_ok=True)
            _write_private(self.key_path, base64.urlsafe_b64encode(os.urandom(32)))
        return self.key_path.read_text(encoding="utf-8").strip(), str(self.key_path)

    def _fernet(self, salt: bytes, create: bool) -> Fernet:
        master, _ = self.master(create)
        if not master:
            raise Unavailable("the master key is empty")
        key = hashlib.scrypt(master.encode(), salt=salt, n=2**14, r=8, p=1, dklen=32)
        return Fernet(base64.urlsafe_b64encode(key))

    def _read(self) -> dict[str, str]:
        if not self.path.exists():
            return {}
        stamp = self.path.stat().st_mtime
        if self._seen is not None and self._seen[0] == stamp:
            return self._seen[1]
        try:
            box = json.loads(self.path.read_text(encoding="utf-8"))
            data = json.loads(self._fernet(base64.b64decode(box["salt"]), create=False).decrypt(box["data"].encode()))
        except InvalidToken as e:
            raise Unavailable("the master key is not the one the secrets were written with") from e
        except (ValueError, KeyError) as e:
            raise Unavailable(f"{self.path.name} is damaged: {e}") from e
        self._seen = (stamp, data)
        return data

    def _write(self, data: dict[str, str]) -> None:
        salt = os.urandom(16)
        box = {"v": 1, "salt": base64.b64encode(salt).decode(), "data": self._fernet(salt, create=True).encrypt(json.dumps(data).encode()).decode()}
        self.path.parent.mkdir(parents=True, exist_ok=True)
        _write_private(self.path, json.dumps(box).encode())
        self._seen = (self.path.stat().st_mtime, data)

    def get(self, name: str) -> str | None:
        with self._lock:
            return self._read().get(name)

    @contextmanager
    def _changing(self):
        """One writer at a time, across processes (the server and a command run beside it both change secrets): the
        file is read again inside the lock, so that what the other one wrote is kept, not written over."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._lock, open(self.path.with_name("secrets.lock"), "a+b") as lock:
            until = time.monotonic() + 30
            while True:
                try:
                    if os.name == "nt":
                        import msvcrt

                        lock.seek(0)
                        msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
                    else:
                        import fcntl

                        fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                    break
                except OSError:
                    if time.monotonic() > until:
                        raise Unavailable("another process has been changing the secrets for 30 seconds") from None
                    time.sleep(0.05)
            try:
                self._seen = None        # whatever was read before the lock may be stale
                yield
            finally:
                if os.name == "nt":
                    import msvcrt

                    lock.seek(0)
                    msvcrt.locking(lock.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    import fcntl

                    fcntl.flock(lock.fileno(), fcntl.LOCK_UN)

    def put(self, name: str, value: str) -> None:
        with self._changing():
            self._write({**self._read(), name: value})

    def delete(self, name: str) -> None:
        with self._changing():
            data = dict(self._read())
            if data.pop(name, None) is not None:
                self._write(data)


def _write_private(path: Path, data: bytes) -> None:
    """Write a file whole, readable by its owner only from the moment it exists."""
    tmp = path.with_name(f"{path.name}.{os.getpid()}.{threading.get_ident()}.tmp")       # its own: two writers never share one
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "wb") as f:
        f.write(data)
    os.replace(tmp, path)


# --- which store ----------------------------------------------------------------

_store: FileStore | None = None
_chosen: str | None = None


def _folder() -> Path:
    from . import config

    return config.DATA


def keyring_usable() -> bool:
    """Is there a keyring that answers? A server has none; a desktop's may be locked or not running."""
    try:
        if type(keyring.get_keyring()).__module__.startswith("keyring.backends.fail"):
            return False
        keyring.get_password(SERVICE, "__probe__")
        return True
    except Exception:  # noqa: BLE001 - whatever the backend raises, it means "not usable"
        return False


def backend() -> str:
    """"keyring" or "file". Decided once for the process."""
    global _chosen
    if _chosen is None:
        forced = (os.environ.get("AUTOAPPLY_SECRETS") or "").lower()
        if forced in ("keyring", "file"):
            _chosen = forced
        elif (_folder() / "secrets.bin").exists():
            _chosen = "file"
        else:
            _chosen = "keyring" if keyring_usable() else "file"
    return _chosen


def reset() -> None:
    """Forget the decision (tests, and after the data folder changed)."""
    global _chosen, _store
    _chosen, _store = None, None


def _file() -> FileStore:
    global _store
    if _store is None or _store.path.parent != _folder():
        _store = FileStore(_folder())
    return _store


def describe() -> dict[str, str]:
    """Which store is in use, for the settings page and the doctor. No secret, no key."""
    if backend() == "keyring":
        return {"backend": "keyring", "detail": type(keyring.get_keyring()).__name__}
    try:
        source = _file().master(create=False)[1] if _file().path.exists() or os.environ.get("AUTOAPPLY_MASTER_KEY") or os.environ.get("AUTOAPPLY_MASTER_KEY_FILE") else str(_file().key_path)
    except Unavailable as e:
        return {"backend": "file", "detail": str(e), "problem": "key"}
    beside = source == str(_file().key_path)
    return {"backend": "file", "detail": source, "key": "beside" if beside else "elsewhere"}


def get(name: str) -> str | None:
    if backend() == "file":
        return _file().get(name)
    return keyring.get_password(SERVICE, name)


def put(name: str, value: str) -> None:
    if backend() == "file":
        return _file().put(name, value)
    keyring.set_password(SERVICE, name, value)


def delete(name: str) -> None:
    if backend() == "file":
        return _file().delete(name)
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
