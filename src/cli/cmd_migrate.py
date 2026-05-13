"""Phase 11.2 -- ``autoapply migrate`` CLI.

A one-shot upgrade tool. Detects the small set of legacy artifacts left
behind by earlier revisions of Phase 10 and offers to clean them up:

1. **Stale ``managed_by: codex-cli`` credential breadcrumbs.** Early
   Phase 10 revisions persisted an OAuth-style record for the
   ``codex-cli`` subprocess provider; the current code treats the CLI
   as the source of auth truth and ignores any stored credential, so
   the breadcrumb is dead weight (and confuses the Settings UI).
2. **Subprocess-provider credentials with secrets.** Same root cause:
   a row for ``claude-cli`` or ``codex-cli`` carrying a non-empty
   ``secret`` dict was written by old code paths and is no longer
   honoured.
3. **Credential rows for provider ids the registry no longer knows.**
   E.g. ``codex-oauth`` which existed in 10.3 and was removed in 10.7.
4. **Legacy ``llm.provider`` scalar key in ``config/settings.yaml``.**
   ``primary_provider`` is the canonical key now; ``provider`` is kept
   purely as a read-time alias and can be dropped when ``primary_provider``
   is set and matches.
5. **Legacy scalar ``llm.fallback_provider`` key.** Phase 11.1 added
   the ordered list form ``llm.fallback_providers: [...]``. Migrate
   promotes the scalar into a single-element list so users get the new
   shape without losing their existing fallback.
6. **Stale credentials.** Any credential row with a ``last_test_error``
   recorded -- these may or may not still be broken, but flagging them
   gives the user a nudge to re-run ``autoapply provider test``.

Default behaviour is dry-run: print what we'd do, exit 0. Pass
``--apply`` to actually mutate the credential store and settings file.
JSON output via ``--json`` is stable enough to drive automation.
"""

from __future__ import annotations

import shutil
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import click

from src.cli.output import build_json_payload, emit_json
from src.providers import get_registry
from src.providers.store import CredentialStore

# Subprocess providers never legitimately carry a stored credential --
# their auth lives in the CLI ("claude login" / "codex login"). Any row
# we find with a non-empty ``secret`` for one of these ids is a leftover
# from old code paths and is fair game to delete.
_SUBPROCESS_PROVIDER_IDS = frozenset({"claude-cli", "codex-cli"})

# Issue codes are stable identifiers used by --json consumers / docs.
ISSUE_MANAGED_BY = "stale_managed_by_breadcrumb"
ISSUE_SUBPROCESS_SECRET = "subprocess_provider_with_secret"
ISSUE_UNKNOWN_PROVIDER = "credential_for_unknown_provider"
ISSUE_LEGACY_PROVIDER_KEY = "legacy_llm_provider_key"
ISSUE_LEGACY_FALLBACK_SCALAR = "legacy_fallback_provider_scalar"
ISSUE_STALE_CREDENTIAL = "credential_has_test_error"


@dataclass
class MigrationIssue:
    """One detected problem, with a human-readable description and a
    code stable enough to grep for / consume from JSON output.

    ``fix`` is a brief description of what ``--apply`` would do.
    ``severity`` is informational only (info / warn).
    """

    code: str
    target: str
    detail: str
    fix: str
    severity: str = "info"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class MigrationReport:
    issues: list[MigrationIssue] = field(default_factory=list)
    fixes_applied: list[str] = field(default_factory=list)
    backup_paths: list[str] = field(default_factory=list)
    started_at: str = ""
    finished_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "issues": [i.to_dict() for i in self.issues],
            "fixes_applied": list(self.fixes_applied),
            "backup_paths": list(self.backup_paths),
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "ok": True,
        }


# ---------------------------------------------------------------------------
# Detection
# ---------------------------------------------------------------------------


def detect_credential_issues(
    store: CredentialStore, known_provider_ids: set[str]
) -> list[MigrationIssue]:
    issues: list[MigrationIssue] = []
    try:
        creds = store.list_all()
    except Exception as exc:  # noqa: BLE001 -- surface as a single warning issue
        issues.append(
            MigrationIssue(
                code="credentials_unreadable",
                target=str(store.path),
                detail=f"Could not read credentials file: {exc}",
                fix="Inspect the file manually; migrate cannot proceed against it.",
                severity="warn",
            )
        )
        return issues

    for record in creds:
        meta = record.metadata or {}
        if meta.get("managed_by") == "codex-cli":
            issues.append(
                MigrationIssue(
                    code=ISSUE_MANAGED_BY,
                    target=record.provider_id,
                    detail=(
                        f"Provider {record.provider_id!r} has a "
                        "'managed_by: codex-cli' breadcrumb from an earlier "
                        "Phase 10 revision; the current code no longer reads it."
                    ),
                    fix=f"Delete the credential row for {record.provider_id!r}.",
                )
            )
            continue

        if record.provider_id in _SUBPROCESS_PROVIDER_IDS and record.secret:
            issues.append(
                MigrationIssue(
                    code=ISSUE_SUBPROCESS_SECRET,
                    target=record.provider_id,
                    detail=(
                        f"Subprocess provider {record.provider_id!r} has a "
                        "stored secret, but the new subprocess providers do "
                        "not consult the store -- the secret is dead weight."
                    ),
                    fix=f"Delete the credential row for {record.provider_id!r}.",
                )
            )
            continue

        if record.provider_id not in known_provider_ids:
            issues.append(
                MigrationIssue(
                    code=ISSUE_UNKNOWN_PROVIDER,
                    target=record.provider_id,
                    detail=(
                        f"Credential row exists for {record.provider_id!r} "
                        "but no provider with that id is registered today."
                    ),
                    fix=f"Delete the credential row for {record.provider_id!r}.",
                )
            )
            continue

        if record.last_test_error:
            issues.append(
                MigrationIssue(
                    code=ISSUE_STALE_CREDENTIAL,
                    target=record.provider_id,
                    detail=(
                        f"Provider {record.provider_id!r} has a recorded "
                        f"test failure: {record.last_test_error!r}"
                    ),
                    fix=(
                        f"Re-run `autoapply provider test {record.provider_id}` "
                        "or update the key via `autoapply provider set-key`."
                    ),
                    severity="warn",
                )
            )

    return issues


def detect_settings_issues(settings: dict[str, Any]) -> list[MigrationIssue]:
    issues: list[MigrationIssue] = []
    llm = settings.get("llm")
    if not isinstance(llm, dict):
        return issues

    provider = llm.get("provider")
    primary = llm.get("primary_provider")
    if provider and primary and provider == primary:
        issues.append(
            MigrationIssue(
                code=ISSUE_LEGACY_PROVIDER_KEY,
                target="llm.provider",
                detail=(
                    "`llm.provider` duplicates `llm.primary_provider` and is "
                    "only kept as a read-time alias. Dropping it simplifies "
                    "the config without changing behaviour."
                ),
                fix="Remove the `llm.provider` key from config/settings.yaml.",
            )
        )
    elif provider and not primary:
        # Pre-Phase-10 configs only carried `llm.provider`. Promote it
        # so the runtime stops falling back to the legacy alias.
        issues.append(
            MigrationIssue(
                code=ISSUE_LEGACY_PROVIDER_KEY,
                target="llm.provider",
                detail=(
                    f"Config has only the legacy `llm.provider: {provider!r}` "
                    "key. The current code prefers `llm.primary_provider` "
                    "and only falls back to the alias for read."
                ),
                fix=(
                    f"Set `llm.primary_provider: {provider}` and drop "
                    "`llm.provider` from config/settings.yaml."
                ),
            )
        )

    fallback = llm.get("fallback_provider")
    fallback_list = llm.get("fallback_providers")
    if fallback and not fallback_list:
        issues.append(
            MigrationIssue(
                code=ISSUE_LEGACY_FALLBACK_SCALAR,
                target="llm.fallback_provider",
                detail=(
                    "`llm.fallback_provider` (scalar) is the pre-11.1 form. "
                    "Phase 11.1 added `llm.fallback_providers: [...]` for "
                    "ordered chains; promoting the scalar is loss-free."
                ),
                fix=(
                    "Replace `llm.fallback_provider: X` with "
                    "`llm.fallback_providers: [X]`."
                ),
            )
        )

    return issues


# ---------------------------------------------------------------------------
# Fixes
# ---------------------------------------------------------------------------


def apply_credential_fix(
    store: CredentialStore, issue: MigrationIssue
) -> str | None:
    if issue.code in (
        ISSUE_MANAGED_BY,
        ISSUE_SUBPROCESS_SECRET,
        ISSUE_UNKNOWN_PROVIDER,
    ):
        deleted = store.delete(issue.target)
        if deleted:
            return f"deleted credential row for {issue.target!r}"
    # Stale-credential issues are informational only; we never auto-delete
    # a key the user might still want -- they may have a transient outage.
    return None


def apply_settings_fixes(
    settings: dict[str, Any], issues: list[MigrationIssue]
) -> list[str]:
    applied: list[str] = []
    llm = settings.get("llm")
    if not isinstance(llm, dict):
        return applied

    for issue in issues:
        if issue.code == ISSUE_LEGACY_PROVIDER_KEY:
            legacy = llm.get("provider")
            primary = llm.get("primary_provider")
            if legacy and not primary:
                # Orphan case: only `llm.provider` exists. Promote it
                # to `primary_provider` then drop the alias.
                llm["primary_provider"] = legacy
                llm.pop("provider", None)
                applied.append(
                    f"promoted legacy `llm.provider: {legacy}` to "
                    "`llm.primary_provider` and dropped the alias"
                )
            elif legacy and primary == legacy:
                llm.pop("provider", None)
                applied.append("dropped `llm.provider` (alias of `primary_provider`)")
        if issue.code == ISSUE_LEGACY_FALLBACK_SCALAR:
            scalar = llm.pop("fallback_provider", None)
            if scalar:
                llm["fallback_providers"] = [scalar]
                applied.append(
                    "promoted `llm.fallback_provider` scalar to "
                    "`llm.fallback_providers: [...]`"
                )
    return applied


def backup_file(path: Path) -> Path:
    """Snapshot a file before mutating it.

    Returns the backup path; the caller surfaces it to the user so a
    manual revert is one ``mv`` away. Naming uses an ISO-style suffix
    so multiple migrate runs don't collide.
    """
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    backup = path.with_suffix(path.suffix + f".bak.{stamp}")
    shutil.copy2(path, backup)
    return backup


# ---------------------------------------------------------------------------
# CLI surface
# ---------------------------------------------------------------------------


@click.command("migrate")
@click.option(
    "--apply",
    "apply",
    is_flag=True,
    help="Perform the fixes. Without this flag, migrate is a dry run.",
)
@click.option("--json", "as_json", is_flag=True, help="Emit JSON instead of text.")
def migrate_cmd(apply: bool, as_json: bool) -> None:
    """One-shot upgrade tool for legacy credential and settings artifacts."""
    started = datetime.now(UTC).isoformat()

    # Importing inside the function keeps `autoapply --help` cheap; we
    # only touch the credential store / settings file when this command
    # actually fires.
    from src.cli.cmd_provider import _load_settings, _save_settings  # noqa: PLC0415

    registry = get_registry()
    store = registry.store
    known_ids = set(registry.ids())

    cred_issues = detect_credential_issues(store, known_ids)
    settings = _load_settings()
    settings_issues = detect_settings_issues(settings)
    all_issues = cred_issues + settings_issues

    report = MigrationReport(issues=all_issues, started_at=started)

    if apply and all_issues:
        # Back up before any mutation so the user has an escape hatch.
        if any(i.target.startswith("llm.") for i in settings_issues):
            settings_path = Path(_settings_path())
            if settings_path.exists():
                report.backup_paths.append(str(backup_file(settings_path)))
        if any(
            i.code
            in (
                ISSUE_MANAGED_BY,
                ISSUE_SUBPROCESS_SECRET,
                ISSUE_UNKNOWN_PROVIDER,
            )
            for i in cred_issues
        ) and store.path.exists():
            report.backup_paths.append(str(backup_file(store.path)))

        for issue in cred_issues:
            applied = apply_credential_fix(store, issue)
            if applied:
                report.fixes_applied.append(applied)

        applied_settings = apply_settings_fixes(settings, settings_issues)
        report.fixes_applied.extend(applied_settings)
        if applied_settings:
            _save_settings(settings)

    report.finished_at = datetime.now(UTC).isoformat()

    if as_json:
        emit_json(build_json_payload(command="migrate", data=report.to_dict()))
        return

    if not all_issues:
        click.echo("No legacy artifacts found. Nothing to migrate.")
        return

    click.echo(f"Found {len(all_issues)} legacy artifact(s):")
    for issue in all_issues:
        marker = "!" if issue.severity == "warn" else "*"
        click.echo(f"  {marker} [{issue.code}] {issue.target}")
        click.echo(f"      {issue.detail}")
        click.echo(f"      fix: {issue.fix}")

    if not apply:
        click.echo()
        click.echo("Dry run -- re-run with `--apply` to perform these fixes.")
        return

    if report.fixes_applied:
        click.echo()
        click.echo("Applied:")
        for line in report.fixes_applied:
            click.echo(f"  - {line}")
    if report.backup_paths:
        click.echo()
        click.echo("Backups:")
        for path in report.backup_paths:
            click.echo(f"  - {path}")


def _settings_path() -> str:
    """Re-export the settings path so tests can patch it.

    The CLI command imports ``_load_settings`` / ``_save_settings``
    from ``cmd_provider``, which already knows the path; this indirection
    is only used for the backup snapshot.
    """
    from src.cli.cmd_provider import _SETTINGS_PATH  # noqa: PLC0415

    return str(_SETTINGS_PATH)
