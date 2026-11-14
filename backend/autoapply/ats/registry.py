"""Driver registry: URL -> JobRef -> driver."""

from __future__ import annotations

from urllib.parse import urlparse

from .base import Driver, JobRef


def drivers() -> dict[str, Driver]:
    from .ashby import AshbyDriver
    from .greenhouse import GreenhouseDriver
    from .pdportal import PDPortalDriver
    from .workday import WorkdayDriver

    return {d.ats: d for d in (GreenhouseDriver(), AshbyDriver(), WorkdayDriver(), PDPortalDriver())}  # type: ignore[misc]


# Hosts we recognise but have no driver for yet: handled by the generic agent path.
KNOWN_HOSTS = {
    "apply.workable.com": "workable",
    "oraclecloud.com": "oracle",
    "eightfold.ai": "eightfold",
    "smartrecruiters.com": "smartrecruiters",
    "lever.co": "lever",
    "icims.com": "icims",
}


def detect(url: str) -> JobRef | None:
    for d in drivers().values():
        ref = d.detect(url)
        if ref is not None:
            return ref
    host = urlparse(url).netloc.lower()
    for suffix, ats in KNOWN_HOSTS.items():
        if host.endswith(suffix):
            return JobRef(ats, host.split(".")[0], "", url, host)
    return JobRef("generic", host, "", url, host) if host else None


def get(ats: str) -> Driver | None:
    return drivers().get(ats)
