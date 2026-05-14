"""Phase 12 -- Namespace validation tests.

Codex review P2 regression: cache namespaces must reject anything
that could be a Redis ``SCAN`` glob metacharacter. Without this, a
caller passing ``namespace='*'`` would turn ``{version}:*:`` into
a glob that matches every key in the cache version.
"""

from __future__ import annotations

import pytest

from src.cache.base import (
    make_key,
    namespace_prefix,
    validate_namespace,
)


class TestValidateNamespace:
    @pytest.mark.parametrize(
        "ns",
        ["llm", "embedding", "response", "custom_ns", "ns-with-hyphen", "abc123"],
    )
    def test_accepts_identifiers(self, ns: str) -> None:
        assert validate_namespace(ns) == ns

    @pytest.mark.parametrize(
        "ns",
        [
            "*",
            "ll*",
            "?",
            "[abc]",
            "with space",
            "with:colon",
            "",
            "llm/sub",
            "llm.sub",
            "llm\\sub",
        ],
    )
    def test_rejects_glob_or_separator_chars(self, ns: str) -> None:
        with pytest.raises(ValueError):
            validate_namespace(ns)

    def test_rejects_non_string(self) -> None:
        with pytest.raises(ValueError):
            validate_namespace(None)  # type: ignore[arg-type]
        with pytest.raises(ValueError):
            validate_namespace(123)  # type: ignore[arg-type]


class TestMakeKeyValidates:
    def test_make_key_rejects_glob_namespace(self) -> None:
        with pytest.raises(ValueError):
            make_key("*", "anything")

    def test_namespace_prefix_rejects_glob_namespace(self) -> None:
        with pytest.raises(ValueError):
            namespace_prefix("*")
