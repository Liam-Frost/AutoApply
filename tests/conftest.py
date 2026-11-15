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
    # Tests never show a window and never wait for a person. A run that hands the form to the applicant does so in a
    # visible window and waits up to twenty minutes; a test that gets there without saying what the applicant does would
    # sit on the screen of whoever runs the tests. So: every window is hidden, and that wait fails at once unless the
    # test replaces it.
    from autoapply import browser, executor

    real_open = browser.open_page
    monkeypatch.setattr(browser, "open_page", lambda tenant_key=None, *, headless=True, downloads=None: real_open(tenant_key, headless=True, downloads=downloads))

    def nobody_is_there(*a, **k):
        raise AssertionError("this run handed the form to the applicant, and the test does not say what the applicant does")

    if not hasattr(executor, "wait_for_the_applicant"):      # the real thing, for the tests that are about it
        executor.wait_for_the_applicant = executor._wait_for_manual_submit
    monkeypatch.setattr(executor, "_wait_for_manual_submit", nobody_is_there)
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
