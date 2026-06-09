"""Shared HTTP helpers for outbound requests from ManuSpectrum.

All project code that makes requests to external services should use the
User-Agent produced here so external hosts (IIIF servers, Biblissima, etc.)
see a single, identifiable client.
"""

import ipaddress
import socket
import threading
import time
from functools import lru_cache
from urllib.parse import urlparse

import arches
import requests
from django.conf import settings as django_settings
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry


@lru_cache(maxsize=1)
def get_user_agent():
    """Return the ManuSpectrum User-Agent string.

    Format: "<APP_NAME>/<APP_VERSION> Arches/<arches_version>".
    Falls back gracefully when app/arches versions are missing.
    """
    app_name = getattr(django_settings, "APP_NAME", "Arches")
    app_version = getattr(django_settings, "APP_VERSION", "")
    arches_version = getattr(arches, "__version__", "")
    parts = [f"{app_name}/{app_version}" if app_version else app_name]
    if arches_version:
        parts.append(f"Arches/{arches_version}")
    return " ".join(parts)


@lru_cache(maxsize=1)
def get_json_request_headers():
    """Standard headers for outbound JSON/JSON-LD requests (e.g. IIIF manifests)."""
    return {
        "User-Agent": get_user_agent(),
        "Accept": "application/ld+json, application/json",
    }


# ---------------------------------------------------------------------------
# SSRF guard for outbound fetches of user/scraper-supplied URLs
# ---------------------------------------------------------------------------


class UnsafeURLError(Exception):
    """Raised when an outbound URL is rejected by the SSRF guard.

    Either the scheme/host is malformed, DNS resolution fails, or the host
    resolves to a non-public address (loopback / private / link-local /
    reserved — including the cloud-metadata endpoint 169.254.169.254).
    """


_ALLOWED_URL_SCHEMES = ("http", "https")


def _address_is_public(ip_str):
    """True only for globally-routable unicast addresses.

    ``ipaddress.is_global`` is False for loopback, private (RFC-1918),
    carrier-grade NAT, link-local (incl. the cloud-metadata
    169.254.169.254), reserved, multicast and unspecified ranges — i.e.
    exactly the targets an SSRF probe would aim for. IPv4-mapped IPv6
    addresses (``::ffff:127.0.0.1``) are unwrapped first so they can't be
    used to smuggle an internal v4 target past the check.
    """
    ip = ipaddress.ip_address(ip_str)
    mapped = getattr(ip, "ipv4_mapped", None)
    if mapped is not None:
        ip = mapped
    return ip.is_global and not ip.is_multicast


def assert_url_is_safe(url, *, allow_private=None):
    """Validate an outbound URL against SSRF before fetching it.

    Checks the scheme is http(s) and the host is present, then resolves the
    host and rejects the URL if *any* resolved address is non-public.

    ``allow_private`` defaults to ``settings.DEBUG``: in development we keep
    the historical behaviour of allowing localhost / private IIIF servers
    (mirroring ``_URL_REGEX_DEV``); in production (``DEBUG=False``) the guard
    is enforced. Returns the parsed URL on success; raises ``UnsafeURLError``
    otherwise.

    NOTE: the resolved addresses are checked at call time, but the connection
    is not pinned to a checked IP, so this is not a complete defence against
    DNS-rebinding (re-resolution at connect time). Pinning the resolved IP on
    the connection is a documented follow-up hardening.
    """
    if allow_private is None:
        allow_private = bool(getattr(django_settings, "DEBUG", False))

    parsed = urlparse(url)
    if parsed.scheme not in _ALLOWED_URL_SCHEMES:
        raise UnsafeURLError(f"Disallowed URL scheme: {parsed.scheme!r}")
    host = parsed.hostname
    if not host:
        raise UnsafeURLError("URL has no host")

    if allow_private:
        return parsed

    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    try:
        infos = socket.getaddrinfo(host, port, proto=socket.IPPROTO_TCP)
    except socket.gaierror as exc:
        raise UnsafeURLError(f"DNS resolution failed for {host!r}") from exc

    resolved = {info[4][0] for info in infos}
    if not resolved:
        raise UnsafeURLError(f"No addresses resolved for {host!r}")
    for ip_str in resolved:
        if not _address_is_public(ip_str):
            raise UnsafeURLError(f"{host!r} resolves to non-public address {ip_str}")
    return parsed


# ---------------------------------------------------------------------------
# Per-host outbound rate limiting (avoid IP blocks, esp. Gallica/BnF)
# ---------------------------------------------------------------------------

# Minimum seconds between outbound requests to a host, keyed by host suffix;
# "default" applies to everything else. BnF/Gallica publish no manifest-fetch
# limit and IP-block "abusive" use at their discretion; community tooling
# converges on ~1 request / 3 s as the safe ceiling. Override per environment
# via settings.MANIFEST_FETCH_RATE_LIMITS (e.g. {} disables throttling).
_DEFAULT_RATE_LIMITS = {"bnf.fr": 3.0, "default": 1.0}

_host_rate_locks = {}
_host_rate_last = {}
_host_rate_guard = threading.Lock()


def _rate_limits():
    return getattr(django_settings, "MANIFEST_FETCH_RATE_LIMITS", _DEFAULT_RATE_LIMITS)


def _rate_key_and_interval(host):
    """Return (bucket_key, min_interval_seconds) for a hostname.

    A host matches a suffix when it equals it or ends with ".<suffix>", so
    gallica.bnf.fr and any *.bnf.fr subdomain share the single "bnf.fr" bucket.
    """
    host = (host or "").lower()
    limits = _rate_limits()
    for suffix, interval in limits.items():
        if suffix == "default":
            continue
        if host == suffix or host.endswith("." + suffix):
            return suffix, interval
    return "default", limits.get("default", 0)


def throttle_for_host(url):
    """Block until the per-host minimum interval has elapsed before a request.

    Enforces e.g. 1 request / 3 s for *.bnf.fr so a bulk import does not trip
    Gallica/BnF's (undocumented, discretionary) abuse blocking. No-op when the
    resolved interval is 0 (e.g. ``MANIFEST_FETCH_RATE_LIMITS={}`` in tests).
    Uses a per-host lock so a wait on one host does not block another.
    """
    key, interval = _rate_key_and_interval(urlparse(url).hostname)
    if not interval or interval <= 0:
        return
    with _host_rate_guard:
        lock = _host_rate_locks.setdefault(key, threading.Lock())
    with lock:
        wait = _host_rate_last.get(key, 0.0) + interval - time.monotonic()
        if wait > 0:
            time.sleep(wait)
        _host_rate_last[key] = time.monotonic()


# ---------------------------------------------------------------------------
# Resilient session for IIIF manifest fetches
# ---------------------------------------------------------------------------

_iiif_session = None
_iiif_session_guard = threading.Lock()


def _build_iiif_session():
    session = requests.Session()
    # Carries our User-Agent (get_user_agent) + JSON-LD Accept on every request.
    session.headers.update(get_json_request_headers())
    retry = Retry(
        total=3,
        connect=2,
        read=2,
        status=3,
        backoff_factor=1.5,
        status_forcelist=(429, 502, 503, 504),
        allowed_methods=frozenset(["GET", "HEAD"]),
        respect_retry_after_header=True,
        raise_on_status=False,
    )
    adapter = HTTPAdapter(max_retries=retry)
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    return session


def get_iiif_session():
    """Process-wide ``requests.Session`` with retry/backoff for IIIF fetches.

    Retries transient upstream failures (429/502/503/504) with exponential
    backoff and honours ``Retry-After``. Carries our User-Agent and JSON-LD
    Accept headers on every request.
    """
    global _iiif_session
    if _iiif_session is None:
        with _iiif_session_guard:
            if _iiif_session is None:
                _iiif_session = _build_iiif_session()
    return _iiif_session


def fetch_iiif_manifest(url, *, timeout=(10, 45)):
    """Throttled GET of an external IIIF manifest via the resilient session.

    Applies the per-host rate limit (``throttle_for_host``) and forces
    ``allow_redirects=False`` — a security invariant, since following redirects
    is a classic SSRF bypass. The caller must run the SSRF address check
    (``assert_url_is_safe``) before calling this.
    """
    throttle_for_host(url)
    return get_iiif_session().get(url, timeout=timeout, allow_redirects=False)
