"""Where secrets are kept: the system's keyring where there is one, an encrypted file where there is none."""

from __future__ import annotations

import keyring
import pytest
from keyring.backends.fail import Keyring as NoKeyring

from autoapply import config, secrets


@pytest.fixture
def server(app_env, monkeypatch):
    """A computer without a keyring: a server, a container."""
    keyring.set_keyring(NoKeyring())
    for name in ("AUTOAPPLY_SECRETS", "AUTOAPPLY_MASTER_KEY", "AUTOAPPLY_MASTER_KEY_FILE"):
        monkeypatch.delenv(name, raising=False)
    secrets.reset()
    yield
    secrets.reset()


def test_with_a_keyring_nothing_is_written_to_the_data_folder(app_env):
    secrets.put("k", "v")
    assert secrets.backend() == "keyring" and secrets.get("k") == "v"
    assert not (config.DATA / "secrets.bin").exists()


def test_without_a_keyring_the_secrets_go_into_an_encrypted_file(server):
    assert secrets.backend() == "file"
    secrets.put(secrets.ANTHROPIC_KEY, "sk-very-secret")
    secrets.put_password("workday:acme", "hunter2")
    assert secrets.get(secrets.ANTHROPIC_KEY) == "sk-very-secret" and secrets.get_password("workday:acme") == "hunter2"
    raw = (config.DATA / "secrets.bin").read_bytes()
    assert b"sk-very-secret" not in raw and b"hunter2" not in raw and b"anthropic" not in raw     # names are secret too
    secrets.delete(secrets.ANTHROPIC_KEY)
    assert secrets.get(secrets.ANTHROPIC_KEY) is None and secrets.has("account:workday:acme")
    assert secrets.describe() == {"backend": "file", "detail": str(config.DATA / "secrets.key"), "key": "beside"}
    # sessions are encrypted with a key that is itself one of the secrets
    assert secrets.decrypt_json(secrets.encrypt_json({"cookies": [1]})) == {"cookies": [1]}


def test_another_process_sees_what_was_written(server):
    secrets.put("k", "one")
    other = secrets.FileStore(config.DATA)
    assert other.get("k") == "one"
    other.put("k", "two")
    import os

    os.utime(config.DATA / "secrets.bin", (1, 1))        # a change the first process did not make
    assert secrets.get("k") == "two"


def test_a_master_key_given_from_outside_is_used_and_no_key_is_left_beside_the_data(server, monkeypatch, tmp_path):
    monkeypatch.setenv("AUTOAPPLY_MASTER_KEY", "correct horse battery staple")
    secrets.put("k", "v")
    assert not (config.DATA / "secrets.key").exists()
    assert secrets.describe()["key"] == "elsewhere"
    monkeypatch.setenv("AUTOAPPLY_MASTER_KEY", "something else")
    secrets.reset()
    with pytest.raises(secrets.Unavailable):
        secrets.get("k")
    monkeypatch.delenv("AUTOAPPLY_MASTER_KEY")
    keyfile = tmp_path / "credential"
    keyfile.write_text("correct horse battery staple\n", encoding="utf-8")
    monkeypatch.setenv("AUTOAPPLY_MASTER_KEY_FILE", str(keyfile))
    secrets.reset()
    assert secrets.get("k") == "v"


def test_once_the_file_exists_it_stays_the_store_even_if_a_keyring_appears(server):
    secrets.put("k", "v")
    from conftest import MemoryKeyring

    keyring.set_keyring(MemoryKeyring())
    secrets.reset()
    assert secrets.backend() == "file" and secrets.get("k") == "v"


def test_a_file_whose_key_is_gone_says_so_instead_of_starting_empty(server):
    secrets.put("k", "v")
    (config.DATA / "secrets.key").unlink()
    secrets.reset()
    with pytest.raises(secrets.Unavailable):
        secrets.get("k")
    assert secrets.describe()["problem"] == "key"
