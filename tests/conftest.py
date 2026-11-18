import importlib
import os
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
    # an application's status is written through lifecycle.move: in the tests, the program's own code doing otherwise stops the run
    monkeypatch.setenv("AUTOAPPLY_STRICT_STATUS", "1")
    keyring.set_keyring(MemoryKeyring())
    from autoapply import secrets as _secret_store

    _secret_store.reset()        # the store is chosen anew for every test's data folder
    from autoapply import config, db

    importlib.reload(config)
    db.reset_engine()
    from autoapply import knowledge

    knowledge.DOCS = {"profile": config.PROFILE_MD, "scoring": config.SCORING_MD, "stories": config.STORIES_MD}
    db.init_db()
    # The tests are about the program with an applicant in it: what reads the profile - scoring a posting, answering a
    # form - waits while there is none. A test that is about the empty profile empties it itself (test_profile_init.py).
    config.PROFILE_MD.parent.mkdir(parents=True, exist_ok=True)
    config.PROFILE_MD.write_text(knowledge.EMPTY_PROFILE.replace("## Identity & contact\n\n", "## Identity & contact\n\n- Name: Test Applicant\n\n", 1), encoding="utf-8", newline="\n")
    # The coded drivers are tested as what they are - tools. In the program every site is read by the agent ("*");
    # a test that is about that says so itself.
    db.set_setting("agent.reads", [])
    # Tests never show a window and never wait for a person. A run that hands the form to the applicant does so in a
    # visible window and waits up to twenty minutes; a test that gets there without saying what the applicant does would
    # sit on the screen of whoever runs the tests. So: every window is hidden, and that wait fails at once unless the
    # test replaces it.
    from autoapply import browser, executor

    from autoapply import access

    monkeypatch.setattr(access, "enforced", lambda: False)      # the tests are about the program behind the login; test_access.py turns it on
    real_open = browser.open_page
    monkeypatch.setattr(browser, "real_open_page", real_open, raising=False)      # for the tests that are about windows
    # AUTOAPPLY_TEST_BROWSER=nodriver: every page the program opens in a test is opened in the ordinary browser instead
    # of the automated one. Whatever the program does to a form has to work in both - a site's work is done in the
    # browser its sign-in lives in (browser_policy) - so the whole suite is the contract for the adapter.
    if os.environ.get("AUTOAPPLY_TEST_BROWSER") == "nodriver":
        from autoapply import browser_policy

        from contextvars import ContextVar

        db.set_setting("browser.nodriver_enabled", True)
        monkeypatch.setenv("AUTOAPPLY_ORDINARY_HIDDEN", "1")       # hundreds of pages: not hundreds of windows on the screen
        monkeypatch.setattr(browser_policy, "_override", ContextVar("browser_backend", default="nodriver"))
    monkeypatch.setattr(browser, "open_page", lambda tenant_key=None, *, headless=True, downloads=None, **kwargs: real_open(tenant_key, headless=True, downloads=downloads, **kwargs))

    def nobody_is_there(*a, **k):
        raise AssertionError("this run handed the form to the applicant, and the test does not say what the applicant does")

    if not hasattr(executor, "wait_for_the_applicant"):      # the real thing, for the tests that are about it
        executor.wait_for_the_applicant = executor._wait_for_manual_submit
    monkeypatch.setattr(executor, "_wait_for_manual_submit", nobody_is_there)
    # ("Look for the confirmation e-mail in five minutes" used to be a timer that went off in whichever test was running
    # five minutes later, and was switched off here. It is a row in the test's own queue now, gone with the test.)
    from autoapply import tasks

    tasks.enqueue_later_for_real = tasks.enqueue_later      # the name older tests know it by
    # Tests never reach a real model: anything not stubbed by a test behaves as "no credentials".
    from autoapply import llm, llm_sdk

    def no_model(*a, **k):
        raise llm.LLMUnavailable("no model in tests")

    monkeypatch.setattr(llm_sdk, "real_call", llm_sdk.call, raising=False)      # for the tests that are about the call itself (with the SDK replaced)
    monkeypatch.setattr(llm_sdk, "call", lambda *a, **k: (_ for _ in ()).throw(llm_sdk.SDKError("no model in tests", unavailable=True)))
    monkeypatch.setattr(llm, "_create", no_model)
    monkeypatch.setitem(sys.modules, "openai_codex", None)  # the ChatGPT runtime may be installed and signed in on this machine
    from autoapply import persona

    for k, v in persona.LEGACY.items():
        if k != "persona":
            db.set_setting(k, v)
    yield tmp_path
    db.reset_engine()
