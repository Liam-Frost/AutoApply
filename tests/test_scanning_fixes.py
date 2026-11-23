"""Two code scanning findings (2026-11-23).

#199: the first sentence of an application's latest event was cut with a pattern that backtracked over long runs of
spaces after a full stop. It is now one pass - with exactly the old rule, checked against the old pattern.

#198: an OpenAI-compatible service's address is the applicant's to choose (a service on their own network is the
point), so the request itself stays; the address is checked, and the saved key is only ever sent to the address it was
saved for.
"""
from __future__ import annotations

import random
import re
import time

import pytest

OLD = re.compile(r"(?<=[。！？!?])|(?<=\.)\s+(?=[^\Wa-z0-9_])|\n")


def old_first(text: str) -> str:
    return OLD.split(text.strip(), maxsplit=1)[0].strip()


def test_the_first_sentence_is_what_the_old_pattern_gave():
    from autoapply.applications import first_sentence

    cases = ["Labs Inc. is not two.", "Done. Next one", "Sent. 2 more", "第一句。第二句", "Wait! What", "a.\nB", "a. \n b",
             "a.   b", "ends with a stop.  ", "École. Été", "x. É", "x. é", "x._y", "x. 1", "x. ١", "", "   ", "one line"]
    rng = random.Random(7)
    alphabet = [".", " ", "  ", "\n", "A", "a", "1", "。", "é", "É", "中", "!", "_", "\t"]
    cases += ["".join(rng.choice(alphabet) for _ in range(rng.randint(0, 24))) for _ in range(5000)]
    for c in cases:
        assert first_sentence(c) == old_first(c), repr(c)


def test_the_first_sentence_of_a_long_run_of_spaces_takes_no_time():
    from autoapply.applications import first_sentence

    hostile = ("x." + " " * 20000 + "y") * 5
    t = time.perf_counter()
    first_sentence(hostile)
    assert time.perf_counter() - t < 0.5


def test_a_service_address_is_checked():
    from autoapply import llm_openai

    assert llm_openai.endpoint("https://api.openai.com/v1/") == "https://api.openai.com/v1"
    assert llm_openai.endpoint(" http://localhost:11434/v1 ") == "http://localhost:11434/v1"      # (one's own network: the point)
    for bad in ("", "ftp://example.com/v1", "javascript:alert(1)", "http://user:pw@example.com/v1", "https://example.com/v1?x=1",
                "https://example.com/v1#a", "http:///v1", "example.com/v1"):
        with pytest.raises(llm_openai.Unavailable):
            llm_openai.endpoint(bad)


def test_the_saved_key_goes_only_to_the_address_it_was_saved_for(app_env, monkeypatch):
    from fastapi import HTTPException

    from autoapply import db, llm_openai, secrets
    from autoapply.api import main

    db.set_setting("llm.providers", {"custom": {"base_url": "http://localhost:11434/v1", "model": "m"}})
    monkeypatch.setattr(secrets, "get", lambda name: "saved-key" if name == "llm_key_custom" else None)
    seen = []

    class Stub:
        def __init__(self, base, key, **k):
            seen.append((llm_openai.endpoint(base), key))

        def models(self):
            return ["m"]

    monkeypatch.setattr(llm_openai, "Client", Stub)
    assert main.llm_provider_models("custom", {})["models"] == ["m"]                                              # the saved address: its key
    assert main.llm_provider_models("custom", {"base_url": "http://localhost:11434/v1/"})["models"] == ["m"]       # the same address written another way
    with pytest.raises(HTTPException) as e:
        main.llm_provider_models("custom", {"base_url": "https://elsewhere.example/v1"})                            # another address, no key typed
    assert e.value.status_code == 400
    assert main.llm_provider_models("custom", {"base_url": "https://elsewhere.example/v1", "api_key": "typed"})["models"] == ["m"]
    assert seen == [("http://localhost:11434/v1", "saved-key"), ("http://localhost:11434/v1", "saved-key"), ("https://elsewhere.example/v1", "typed")]
    # a preset service with nothing saved: its own address takes the saved key; another address does not
    db.set_setting("llm.providers", {})
    monkeypatch.setattr(secrets, "get", lambda name: "openai-key")
    seen.clear()
    main.llm_provider_models("openai", {})
    with pytest.raises(HTTPException):
        main.llm_provider_models("openai", {"base_url": "https://proxy.example/v1"})
    assert seen == [("https://api.openai.com/v1", "openai-key")]
