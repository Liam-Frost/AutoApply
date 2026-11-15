import importlib
import sys
from pathlib import Path

import keyring
import pytest
from keyring.backend import KeyringBackend

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
sys.path.insert(0, str(Path(__file__).resolve().parent))


class MemoryKeyring(KeyringBackend):
    priority = 1

    def __init__(self):
        self.store = {}

    def get_password(self, service, username):
        return self.store.get((service, username))

    def set_password(self, service, username, password):
        self.store[(service, username)] = password

    def delete_password(self, service, username):
        self.store.pop((service, username), None)


@pytest.fixture()
def app_env(tmp_path, monkeypatch):
    """Isolated data dir, knowledge dir, in-memory keyring, fresh SQLite."""
    monkeypatch.setenv("AUTOAPPLY_DATA", str(tmp_path / "data"))
    monkeypatch.setenv("AUTOAPPLY_KNOWLEDGE", str(tmp_path / "knowledge"))
    keyring.set_keyring(MemoryKeyring())
    from autoapply import config, db

    importlib.reload(config)
    db.reset_engine()
    from autoapply import knowledge

    knowledge.DOCS = {"profile": config.PROFILE_MD, "scoring": config.SCORING_MD, "stories": config.STORIES_MD}
    db.init_db()
    # The coded drivers are tested as what they are - tools. In the program every site is read by the agent ("*");
    # a test that is about that says so itself.
    db.set_setting("agent.reads", [])
    # Tests never reach a real model: anything not stubbed by a test behaves as "no credentials".
    from autoapply import llm, llm_sdk

    def no_model(*a, **k):
        raise llm.LLMUnavailable("no model in tests")

    monkeypatch.setattr(llm_sdk, "call", lambda *a, **k: (_ for _ in ()).throw(llm_sdk.SDKError("no model in tests", unavailable=True)))
    monkeypatch.setattr(llm, "_create", no_model)
    monkeypatch.setitem(sys.modules, "openai_codex", None)  # the ChatGPT runtime may be installed and signed in on this machine
    from autoapply import persona

    for k, v in persona.LEGACY.items():
        if k != "persona":
            db.set_setting(k, v)
    yield tmp_path
    db.reset_engine()
