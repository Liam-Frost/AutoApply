"""Provider management use cases shared by CLI and Web.

These mirror the work done by ``src/cli/cmd_provider.py`` so the Web
UI can offer the same connect / disconnect / test / use workflow
through plain JSON HTTP rather than spawning the CLI. The shapes use
the same ``ok/error/error_code`` envelope as the rest of
``src/application/*`` use cases.
"""

from __future__ import annotations

from typing import Any

import yaml

from src.core.config import PROJECT_ROOT
from src.providers import get_registry
from src.providers.base import (
    AuthType,
    ProviderCredentials,
    ProviderError,
    ProviderTestResult,
    now_iso,
)

_SETTINGS_PATH = PROJECT_ROOT / "config" / "settings.yaml"


def _coerce_chain(raw: Any) -> list[str]:
    """Normalise the on-disk ``fallback_providers`` value to a list.

    ``get_llm_settings`` accepts three shapes -- ``["a", "b"]``,
    ``"a, b"``, and missing -- so any writer that mutates the chain
    must accept the same inputs. Without this, iterating the raw
    string yields one provider per *character* and we end up persisting
    a corrupted list back to settings.yaml.
    """
    if isinstance(raw, list):
        return [item for item in raw if isinstance(item, str) and item]
    if isinstance(raw, str):
        return [item.strip() for item in raw.split(",") if item.strip()]
    return []


# ---------------------------------------------------------------------------
# list
# ---------------------------------------------------------------------------


def list_providers() -> dict:
    """Return every registered provider's public view + current
    primary / fallback selection from settings.yaml."""
    try:
        registry = get_registry()
        providers = registry.public_view()
    except Exception as exc:  # noqa: BLE001 -- never break the settings page
        return {
            "ok": False,
            "error": f"Failed to load provider registry: {exc}",
            "error_code": "registry_unavailable",
            "providers": [],
        }
    settings = _load_settings()
    llm = settings.get("llm", {}) if isinstance(settings, dict) else {}
    return {
        "ok": True,
        "providers": providers,
        "primary_provider": llm.get("primary_provider") or llm.get("provider"),
        "fallback_provider": llm.get("fallback_provider"),
    }


# ---------------------------------------------------------------------------
# test
# ---------------------------------------------------------------------------


def test_provider_connection(provider_id: str) -> dict:
    registry = get_registry()
    provider = registry.maybe_get(provider_id)
    if provider is None:
        return {
            "ok": False,
            "error": f"Unknown provider {provider_id!r}.",
            "error_code": "unknown_provider",
            "provider_id": provider_id,
        }
    try:
        result = provider.test_connection()
    except Exception as exc:  # noqa: BLE001
        return {
            "ok": False,
            "error": f"Connection probe raised: {exc}",
            "error_code": "probe_raised",
            "provider_id": provider_id,
        }
    return {
        "ok": result.ok,
        "provider_id": provider_id,
        "result": result.to_dict(),
        "error": None if result.ok else result.detail,
        "error_code": None if result.ok else "probe_failed",
    }


# ---------------------------------------------------------------------------
# set-key
# ---------------------------------------------------------------------------


def connect_api_key_provider(
    provider_id: str,
    *,
    api_key: str,
    model: str | None = None,
    base_url: str | None = None,
) -> dict:
    registry = get_registry()
    provider = registry.maybe_get(provider_id)
    if provider is None:
        return {
            "ok": False,
            "error": f"Unknown provider {provider_id!r}.",
            "error_code": "unknown_provider",
        }
    if provider.auth_type is not AuthType.API_KEY:
        return {
            "ok": False,
            "error": (
                f"Provider {provider_id!r} uses auth_type "
                f"{provider.auth_type.value!r}, not 'api_key'."
            ),
            "error_code": "wrong_auth_type",
        }
    key = (api_key or "").strip()
    if not key:
        return {
            "ok": False,
            "error": "API key is empty.",
            "error_code": "empty_api_key",
        }

    metadata: dict[str, Any] = {}
    if model:
        metadata["model"] = model
    if base_url:
        metadata["base_url"] = base_url

    creds = ProviderCredentials(
        provider_id=provider_id,
        auth_type=AuthType.API_KEY,
        secret={"api_key": key},
        connected_at=now_iso(),
        metadata=metadata,
    )
    registry.store.set(creds)

    # Best-effort verification: run test_connection so the UI can show
    # whether the key actually works. A failure does NOT erase the
    # saved key (the user may have a transient network blip).
    try:
        probe = provider.test_connection()
    except Exception as exc:  # noqa: BLE001
        probe = ProviderTestResult(ok=False, detail=str(exc))

    if probe.ok:
        creds.verified_at = now_iso()
        creds.last_test_error = None
    else:
        creds.last_test_error = probe.detail
    registry.store.set(creds)

    return {
        "ok": probe.ok,
        "provider_id": provider_id,
        "test_result": probe.to_dict(),
        "verified": probe.ok,
        "message": "Connected and verified." if probe.ok else "Saved, but verification failed.",
        "error": None if probe.ok else probe.detail,
        "error_code": None if probe.ok else "probe_failed",
    }


# ---------------------------------------------------------------------------
# disconnect
# ---------------------------------------------------------------------------


def disconnect_provider(provider_id: str) -> dict:
    """Forget the saved credential AND scrub settings.yaml if needed.

    Without the settings.yaml scrub the user could disconnect their
    primary API-key provider, leaving ``primary_provider: openai`` in
    config; the next ``generate_text`` call would crash with
    "Unsupported LLM provider" because the registry would no longer
    consider it configured. So when the disconnected provider is the
    current primary or fallback in settings.yaml, we also clear that
    reference and return ``reset_routing=True`` so the UI can surface
    a "pick a new primary" hint.
    """
    registry = get_registry()
    provider = registry.maybe_get(provider_id)
    if provider is None:
        return {
            "ok": False,
            "error": f"Unknown provider {provider_id!r}.",
            "error_code": "unknown_provider",
        }
    try:
        provider.disconnect()
    except ProviderError as exc:
        return {
            "ok": False,
            "error": str(exc),
            "error_code": "disconnect_failed",
        }

    reset_routing = False
    settings = _load_settings()
    llm = settings.get("llm", {}) if isinstance(settings, dict) else {}

    # Build the canonical chain once. ``fallback_providers`` may be a
    # list OR a comma-separated string OR missing -- ``_coerce_chain``
    # handles all three. We only fall back to the legacy scalar when
    # the list is absent/empty, mirroring ``get_llm_settings`` which
    # treats the list as authoritative and ignores a stale scalar.
    # Otherwise disconnect cleanup could re-promote a fallback the
    # runtime was already ignoring.
    raw_chain = _coerce_chain(llm.get("fallback_providers"))
    if not raw_chain:
        scalar = llm.get("fallback_provider")
        if isinstance(scalar, str) and scalar:
            raw_chain = [scalar]
    # De-dupe while preserving order.
    seen: set[str] = set()
    existing_chain: list[str] = []
    for entry in raw_chain:
        if entry not in seen:
            existing_chain.append(entry)
            seen.add(entry)

    if llm.get("primary_provider") == provider_id or llm.get("provider") == provider_id:
        # Walk the full chain looking for the first still-configured
        # entry that isn't the one being disconnected. Any remaining
        # entries stay in the chain as deeper fallbacks.
        promoted: str | None = None
        for cand in existing_chain:
            if (
                cand != provider_id
                and registry.maybe_get(cand) is not None
                and registry.get(cand).is_configured()
            ):
                promoted = cand
                break
        llm["primary_provider"] = promoted or ""
        llm["provider"] = promoted or ""
        new_chain = [
            f for f in existing_chain if f != provider_id and f != promoted
        ]
        llm["fallback_providers"] = new_chain
        llm["fallback_provider"] = new_chain[0] if new_chain else None
        # Only force ``allow_fallback`` off when the chain is empty.
        # If the user had explicitly disabled fallback with a chain
        # still present, respect that -- don't silently re-enable
        # fallback routing as a side-effect of disconnect cleanup.
        if not new_chain:
            llm["allow_fallback"] = False
        reset_routing = True
    elif provider_id in existing_chain:
        # Only the fallback chain was affected -- primary stays put.
        # Drop the disconnected provider from both shapes; promote the
        # next entry into the scalar slot so we don't lose deeper
        # fallbacks the user configured.
        new_chain = [f for f in existing_chain if f != provider_id]
        llm["fallback_providers"] = new_chain
        llm["fallback_provider"] = new_chain[0] if new_chain else None
        if not new_chain:
            llm["allow_fallback"] = False
        reset_routing = True

    if reset_routing:
        settings["llm"] = llm
        _save_settings(settings)

    message = f"Disconnected {provider_id}."
    if reset_routing and not llm.get("primary_provider"):
        message += " Pick a new primary in the LLM routing section."
    elif reset_routing:
        message += f" Promoted '{llm['primary_provider']}' to primary."
    return {
        "ok": True,
        "provider_id": provider_id,
        "reset_routing": reset_routing,
        "primary_provider": llm.get("primary_provider") or None,
        "fallback_provider": llm.get("fallback_provider"),
        "message": message,
    }


# ---------------------------------------------------------------------------
# use
# ---------------------------------------------------------------------------


def use_provider_as_primary(
    provider_id: str, *, fallback_provider: str | None = None
) -> dict:
    """Set ``provider_id`` as the primary LLM in settings.yaml.

    ``fallback_provider`` is a three-state value matching the CLI:

      * ``None`` — preserve the current fallback (do not touch it).
      * ``""`` or ``"none"`` — explicitly clear the fallback.
      * any other string — set as fallback (must be registered).
    """
    registry = get_registry()
    if registry.maybe_get(provider_id) is None:
        return {
            "ok": False,
            "error": f"Unknown provider {provider_id!r}.",
            "error_code": "unknown_provider",
        }
    if (
        fallback_provider is not None
        and fallback_provider not in ("", "none")
        and registry.maybe_get(fallback_provider) is None
    ):
        return {
            "ok": False,
            "error": f"Unknown fallback provider {fallback_provider!r}.",
            "error_code": "unknown_provider",
        }

    settings = _load_settings()
    llm = settings.setdefault("llm", {})
    llm["primary_provider"] = provider_id
    llm["provider"] = provider_id  # legacy alias

    # Phase 11.1: when the caller writes a fallback, keep the list form
    # in sync with the scalar so generate_text() never routes through
    # a stale list this writer failed to update. When the caller passes
    # ``fallback_provider=None`` ("preserve current") we leave BOTH the
    # scalar and the list alone -- collapsing the list to one entry
    # would silently drop chains a user configured directly in
    # settings.yaml.
    if fallback_provider in ("", "none"):
        llm["fallback_provider"] = None
        llm["fallback_providers"] = []
        llm["allow_fallback"] = False
    elif fallback_provider is not None:
        llm["fallback_provider"] = fallback_provider
        llm["fallback_providers"] = [fallback_provider]
        llm["allow_fallback"] = True

    # Self-heal: if the newly-promoted primary is also in the existing
    # fallback chain, remove just that entry from both shapes. Deeper
    # fallbacks the user configured (e.g. ``[codex-cli, openai]`` while
    # promoting ``codex-cli``) must survive -- the previous version
    # cleared the whole chain and silently disabled fallback.
    # ``_coerce_chain`` is required because ``fallback_providers`` may
    # be the comma-separated string shape that ``get_llm_settings``
    # accepts; iterating the raw string would walk characters and
    # corrupt the saved list.
    chain_now = _coerce_chain(llm.get("fallback_providers"))
    healed = False
    if llm.get("fallback_provider") == provider_id:
        llm["fallback_provider"] = None
        healed = True
    if provider_id in chain_now:
        chain_now = [f for f in chain_now if f != provider_id]
        llm["fallback_providers"] = chain_now
        healed = True
    if healed:
        if chain_now:
            # Always mirror the scalar onto the list head so the saved
            # config matches what ``get_llm_settings`` (list-first)
            # will read back. Without this, a config with a stale
            # scalar + good list ends up persisting two disagreeing
            # shapes after we prune the list. ``allow_fallback`` is
            # left untouched here: the caller's explicit fallback path
            # above already set it when needed, and self-heal must
            # preserve a user's ``allow_fallback: false`` choice.
            llm["fallback_provider"] = chain_now[0]
        else:
            llm["fallback_provider"] = None
            llm["fallback_providers"] = []
            llm["allow_fallback"] = False

    _save_settings(settings)

    return {
        "ok": True,
        "primary_provider": provider_id,
        "fallback_provider": llm.get("fallback_provider"),
        "message": f"Primary provider set to {provider_id}.",
    }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _load_settings() -> dict[str, Any]:
    if not _SETTINGS_PATH.exists():
        return {}
    with _SETTINGS_PATH.open("r", encoding="utf-8") as fh:
        data = yaml.safe_load(fh) or {}
    return data if isinstance(data, dict) else {}


def _save_settings(data: dict[str, Any]) -> None:
    _SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
    with _SETTINGS_PATH.open("w", encoding="utf-8") as fh:
        yaml.safe_dump(data, fh, sort_keys=False, default_flow_style=False)
