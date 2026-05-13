"""Phase 11.2 -- ``autoapply migrate`` CLI.

Covers:
* Detection of each issue code (managed_by breadcrumb, subprocess-with-
  secret, unknown provider, stale credential, legacy `llm.provider`,
  legacy scalar `llm.fallback_provider`).
* Dry-run vs ``--apply``.
* JSON envelope shape.
* Backup file creation when mutating.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import yaml
from click.testing import CliRunner

from src.cli.cmd_migrate import (
    ISSUE_LEGACY_FALLBACK_SCALAR,
    ISSUE_LEGACY_PROVIDER_KEY,
    ISSUE_MANAGED_BY,
    ISSUE_STALE_CREDENTIAL,
    ISSUE_SUBPROCESS_SECRET,
    ISSUE_UNKNOWN_PROVIDER,
    detect_credential_issues,
    detect_settings_issues,
    migrate_cmd,
)
from src.providers.base import AuthType, ProviderCredentials
from src.providers.store import CredentialStore


def _write_credentials(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def _stale_cred(
    provider_id: str,
    *,
    secret: dict | None = None,
    managed_by: str | None = None,
    last_error: str | None = None,
) -> dict:
    metadata: dict = {}
    if managed_by:
        metadata["managed_by"] = managed_by
    return ProviderCredentials(
        provider_id=provider_id,
        auth_type=AuthType.API_KEY,
        secret=secret or {},
        connected_at="2026-04-01T00:00:00+00:00",
        last_test_error=last_error,
        metadata=metadata,
    ).to_dict()


class TestDetectCredentials:
    def test_managed_by_breadcrumb(self, tmp_path: Path) -> None:
        store = CredentialStore(path=tmp_path / "creds.json")
        _write_credentials(
            store.path,
            {"codex-cli": _stale_cred("codex-cli", managed_by="codex-cli")},
        )
        issues = detect_credential_issues(store, known_provider_ids={"codex-cli"})
        codes = [i.code for i in issues]
        assert ISSUE_MANAGED_BY in codes

    def test_subprocess_with_secret(self, tmp_path: Path) -> None:
        store = CredentialStore(path=tmp_path / "creds.json")
        _write_credentials(
            store.path,
            {
                "claude-cli": _stale_cred(
                    "claude-cli", secret={"api_key": "leftover"}
                )
            },
        )
        issues = detect_credential_issues(
            store, known_provider_ids={"claude-cli"}
        )
        codes = [i.code for i in issues]
        assert ISSUE_SUBPROCESS_SECRET in codes

    def test_unknown_provider(self, tmp_path: Path) -> None:
        store = CredentialStore(path=tmp_path / "creds.json")
        _write_credentials(
            store.path,
            {"codex-oauth": _stale_cred("codex-oauth", secret={"token": "x"})},
        )
        issues = detect_credential_issues(store, known_provider_ids={"openai"})
        assert any(i.code == ISSUE_UNKNOWN_PROVIDER for i in issues)

    def test_stale_credential_with_test_error(self, tmp_path: Path) -> None:
        store = CredentialStore(path=tmp_path / "creds.json")
        _write_credentials(
            store.path,
            {
                "openai": _stale_cred(
                    "openai",
                    secret={"api_key": "sk-xxx"},
                    last_error="401 invalid",
                )
            },
        )
        issues = detect_credential_issues(store, known_provider_ids={"openai"})
        codes = [i.code for i in issues]
        assert ISSUE_STALE_CREDENTIAL in codes

    def test_healthy_credential_emits_nothing(self, tmp_path: Path) -> None:
        store = CredentialStore(path=tmp_path / "creds.json")
        _write_credentials(
            store.path,
            {"openai": _stale_cred("openai", secret={"api_key": "sk-xxx"})},
        )
        issues = detect_credential_issues(store, known_provider_ids={"openai"})
        assert issues == []


class TestDetectSettings:
    def test_legacy_provider_alias(self) -> None:
        issues = detect_settings_issues(
            {
                "llm": {
                    "provider": "claude-cli",
                    "primary_provider": "claude-cli",
                }
            }
        )
        assert any(i.code == ISSUE_LEGACY_PROVIDER_KEY for i in issues)

    def test_provider_alias_with_mismatch_keeps_quiet(self) -> None:
        # If the two keys disagree something weirder is going on; we
        # leave it alone rather than silently overwriting either one.
        issues = detect_settings_issues(
            {
                "llm": {
                    "provider": "codex-cli",
                    "primary_provider": "claude-cli",
                }
            }
        )
        assert not any(i.code == ISSUE_LEGACY_PROVIDER_KEY for i in issues)

    def test_legacy_fallback_scalar(self) -> None:
        issues = detect_settings_issues(
            {
                "llm": {
                    "primary_provider": "claude-cli",
                    "fallback_provider": "codex-cli",
                }
            }
        )
        assert any(i.code == ISSUE_LEGACY_FALLBACK_SCALAR for i in issues)

    def test_already_using_list_form_is_clean(self) -> None:
        issues = detect_settings_issues(
            {
                "llm": {
                    "primary_provider": "claude-cli",
                    "fallback_providers": ["codex-cli"],
                }
            }
        )
        assert issues == []


class TestMigrateCommand:
    def _isolated_env(
        self, tmp_path: Path, *, settings: dict, credentials: dict
    ):
        """Patch the credential store path and the settings path so the
        command operates against a sandbox."""
        creds_path = tmp_path / "creds.json"
        _write_credentials(creds_path, credentials)
        settings_path = tmp_path / "settings.yaml"
        settings_path.write_text(yaml.safe_dump(settings), encoding="utf-8")

        # Patch the singleton registry's store and the settings paths.
        from src.providers import registry as registry_mod  # noqa: PLC0415

        registry_mod.reset_default_registry()
        registry = registry_mod.get_registry()
        registry._store = CredentialStore(path=creds_path)  # noqa: SLF001

        patches = [
            patch("src.cli.cmd_provider._SETTINGS_PATH", settings_path),
        ]
        return patches, creds_path, settings_path

    def test_dry_run_reports_without_mutating(self, tmp_path: Path) -> None:
        patches, creds_path, settings_path = self._isolated_env(
            tmp_path,
            settings={
                "llm": {
                    "primary_provider": "claude-cli",
                    "provider": "claude-cli",
                    "fallback_provider": "codex-cli",
                }
            },
            credentials={
                "codex-cli": _stale_cred("codex-cli", managed_by="codex-cli")
            },
        )
        for p in patches:
            p.start()
        try:
            result = CliRunner().invoke(migrate_cmd, [])
        finally:
            for p in patches:
                p.stop()

        assert result.exit_code == 0, result.output
        assert "Dry run" in result.output
        # Files unchanged
        creds_after = json.loads(creds_path.read_text(encoding="utf-8"))
        assert "codex-cli" in creds_after
        settings_after = yaml.safe_load(settings_path.read_text(encoding="utf-8"))
        assert settings_after["llm"]["provider"] == "claude-cli"

    def test_apply_mutates_and_backs_up(self, tmp_path: Path) -> None:
        patches, creds_path, settings_path = self._isolated_env(
            tmp_path,
            settings={
                "llm": {
                    "primary_provider": "claude-cli",
                    "provider": "claude-cli",
                    "fallback_provider": "codex-cli",
                }
            },
            credentials={
                "codex-cli": _stale_cred("codex-cli", managed_by="codex-cli"),
                "openai": _stale_cred(
                    "openai", secret={"api_key": "sk-xxx"}
                ),  # healthy -- untouched
            },
        )
        for p in patches:
            p.start()
        try:
            result = CliRunner().invoke(migrate_cmd, ["--apply"])
        finally:
            for p in patches:
                p.stop()

        assert result.exit_code == 0, result.output
        assert "Applied:" in result.output

        # codex-cli row deleted, openai row preserved
        creds_after = json.loads(creds_path.read_text(encoding="utf-8"))
        assert "codex-cli" not in creds_after
        assert "openai" in creds_after

        # legacy keys removed; fallback promoted to list form
        settings_after = yaml.safe_load(settings_path.read_text(encoding="utf-8"))
        llm = settings_after["llm"]
        assert "provider" not in llm
        assert "fallback_provider" not in llm
        assert llm["fallback_providers"] == ["codex-cli"]

        # Backups exist
        backups = list(tmp_path.glob("*.bak.*"))
        assert backups, "expected a backup file"

    def test_json_envelope(self, tmp_path: Path) -> None:
        patches, _creds_path, _settings_path = self._isolated_env(
            tmp_path,
            settings={"llm": {"primary_provider": "claude-cli"}},
            credentials={
                "codex-cli": _stale_cred("codex-cli", managed_by="codex-cli")
            },
        )
        for p in patches:
            p.start()
        try:
            result = CliRunner().invoke(migrate_cmd, ["--json"])
        finally:
            for p in patches:
                p.stop()

        assert result.exit_code == 0
        payload = json.loads(result.output)
        assert payload["command"] == "migrate"
        assert payload["ok"] is True
        assert "issues" in payload["data"]
        codes = [i["code"] for i in payload["data"]["issues"]]
        assert ISSUE_MANAGED_BY in codes

    def test_clean_environment_says_nothing_to_do(self, tmp_path: Path) -> None:
        patches, _creds_path, _settings_path = self._isolated_env(
            tmp_path,
            settings={
                "llm": {
                    "primary_provider": "claude-cli",
                    "fallback_providers": ["codex-cli"],
                }
            },
            credentials={},
        )
        for p in patches:
            p.start()
        try:
            result = CliRunner().invoke(migrate_cmd, [])
        finally:
            for p in patches:
                p.stop()

        assert result.exit_code == 0
        assert "Nothing to migrate" in result.output
