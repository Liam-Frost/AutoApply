"""Tenant context propagation across Celery boundaries (Phase 14.3).

A Celery task body must know which tenant it runs for so that:

* DB queries can be scoped (today: informational; Phase 18 enforces).
* Redis cache reads / writes land in the right namespace (Phase 18.4
  promotes this from informational to mandatory).
* Audit + trace rows carry the correct ``tenant_id``.

We thread the tenant via Celery task headers (the only Celery-native
mechanism that survives serialization without abusing the payload).
:class:`AutoApplyTask` reads the header at task start and pushes it
into a :class:`contextvars.ContextVar`; helpers throughout the codebase
read the ContextVar with :func:`current_tenant_id`.

The default value before Phase 18 is ``"default"``, matching the row
default written by Phase 13.9 / D026.
"""

from __future__ import annotations

from contextvars import ContextVar, Token

from src.core.models import TENANT_DEFAULT

_TENANT_HEADER = "x-autoapply-tenant"

_tenant_ctx: ContextVar[str] = ContextVar("autoapply_tenant_id", default=TENANT_DEFAULT)


def current_tenant_id() -> str:
    """Return the tenant id for the currently-executing call frame.

    Outside a task body this returns the process-default ``"default"``
    until Phase 18's auth middleware overrides it on web requests.
    """
    return _tenant_ctx.get()


def set_tenant_id(value: str) -> Token[str]:
    """Push a new tenant id onto the context stack; returns the token
    for :func:`reset_tenant_id`."""
    if not value:
        value = TENANT_DEFAULT
    return _tenant_ctx.set(value)


def reset_tenant_id(token: Token[str]) -> None:
    _tenant_ctx.reset(token)


def tenant_header_name() -> str:
    """Phase 14.3 base class reads / writes this exact header. Phase
    14.4 gate APIs and Phase 14.7 CLI must use the same constant."""
    return _TENANT_HEADER


__all__ = [
    "current_tenant_id",
    "reset_tenant_id",
    "set_tenant_id",
    "tenant_header_name",
]
