"""What can go wrong in a way the rest of the program acts on, and two small things about addresses."""

from __future__ import annotations

import re
from urllib.parse import urlparse

BUGS = (AttributeError, NameError, ImportError)


def tolerated(e: BaseException) -> None:
    """Called first in a handler that lets a failure pass ("the page is busy", "the control is not there yet"): what a
    page does may be let pass, a mistake in the program may not. A method the browser adapter does not have, a name
    that does not exist - these were swallowed by the same handlers, and showed up later as something else."""
    if isinstance(e, BUGS):
        raise e


class NeedsHuman(Exception):
    """Only the applicant can go on: a sign-in, a CAPTCHA, a second factor, a profile that is still empty."""

    def __init__(self, reason: str, *, kind: str = "login", url: str = "", waits_for: str = "") -> None:
        super().__init__(reason)
        self.reason, self.kind, self.url = reason, kind, url
        self.waits_for = waits_for      # the card that was made for it ("account:idp:google"): what the task waits for


class SiteDown(Exception):
    """The site itself is not answering (5xx, gateway error page, blank app shell). Not a sign-in problem: nothing is
    counted against the account and no one is asked to sign in."""


# what a browser says when an address gave no answer at all: the connection, not the page
UNREACHABLE = re.compile(r"net::ERR_(TIMED_OUT|CONNECTION_\w+|NAME_NOT_RESOLVED|EMPTY_RESPONSE|SSL_\w+|INTERNET_DISCONNECTED|NETWORK_\w+|ADDRESS_UNREACHABLE|PROXY_\w+|TUNNEL_\w+)"
                         r"|Page\.goto: Timeout \d+ms exceeded", re.I)


def unreachable(e: BaseException) -> bool:
    """Did this fail because the site (or the network on the way to it) gave no answer? That is "down for now" wherever
    it happens, and is tried again later. It says nothing about the form, the account, the password or the program, and
    nobody is asked to do anything."""
    return isinstance(e, SiteDown) or (not isinstance(e, NeedsHuman) and bool(UNREACHABLE.search(str(e))))


def host_is(host: str, domain: str) -> bool:
    """Is ``host`` that site or one of its subdomains? "jobs.ashbyhq.com" is ashbyhq.com; "notashbyhq.com" and
    "ashbyhq.com.evil.example" are not. Sites are told apart by this, never by looking for a name inside an address."""
    host, domain = (host or "").lower().split(":")[0].rstrip("."), domain.lower()
    return host == domain or host.endswith("." + domain)


def url_host(url: str) -> str:
    """The host of an address, lower case, without the port ('' when there is none)."""
    try:
        return (urlparse(url if "//" in (url or "") else f"https://{url}").hostname or "").lower()
    except ValueError:
        return ""
