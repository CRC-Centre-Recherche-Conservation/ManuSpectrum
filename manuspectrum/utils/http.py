"""Shared HTTP helpers for outbound requests from ManuSpectrum.

All project code that makes requests to external services should use the
User-Agent produced here so external hosts (IIIF servers, Biblissima, etc.)
see a single, identifiable client.
"""

import ipaddress
import json
import socket
import threading
import time
from functools import lru_cache
from urllib.parse import urljoin, urlparse

import arches
import requests
from django.conf import settings as django_settings
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from manuspectrum.utils.contact import publishable_contact_email

# Public page an external operator should land on when they look us up: it
# carries the project description and the same contact address.
UA_INFO_PATH = "about/contact"


def _is_reachable_site(url):
    """True when *url* is worth advertising to a third party.

    Arches ships ``PUBLIC_SERVER_ADDRESS = "http://localhost:8000/"``; a prod
    deploy that never overrode it would otherwise tell every remote host to
    visit their own machine. Pure string/literal-IP inspection — no DNS, since
    this runs while building a header.
    """
    if not url:
        return False
    try:
        parsed = urlparse(url)
    except ValueError:
        return False
    host = (parsed.hostname or "").lower()
    if parsed.scheme not in _ALLOWED_URL_SCHEMES or not host:
        return False
    if host == "localhost" or host.endswith((".localhost", ".local", ".internal")):
        return False
    try:
        return _address_is_public(host)
    except ValueError:
        # Not an IP literal: a name is publishable if it is qualified.
        return "." in host


def _ua_contact_block():
    """The "(+<site>/about/contact; <email>)" suffix of the User-Agent, or "".

    Only emitted outside DEBUG. In development the public address is
    http://localhost:8000/ and the inbox is whatever the developer has in
    settings_local.py — publishing either to a remote host is noise at best.
    Placeholder addresses are dropped (a dead mailto is worse than none), and
    both halves are optional, so an unconfigured prod still gets a bare agent.
    """
    if getattr(django_settings, "DEBUG", False):
        return ""

    bits = []
    site = (getattr(django_settings, "PUBLIC_SERVER_ADDRESS", "") or "").strip()
    if _is_reachable_site(site):
        bits.append(f"+{site.rstrip('/')}/{UA_INFO_PATH}")
    email = publishable_contact_email().strip()
    if email:
        bits.append(email)
    if not bits:
        return ""
    # Collapse any whitespace: a CR/LF reaching a header value is injection.
    return "(" + " ".join("; ".join(bits).split()) + ")"


@lru_cache(maxsize=1)
def get_user_agent():
    """Return the ManuSpectrum User-Agent string.

    Format: "<APP_NAME>/<APP_VERSION> Arches/<arches_version>", plus
    "(+<site_url>/about/contact; <contact_email>)" in production so an
    operator seeing our traffic can identify and reach us (issue #29).
    Falls back gracefully when app/arches versions are missing.
    """
    app_name = getattr(django_settings, "APP_NAME", "Arches")
    app_version = getattr(django_settings, "APP_VERSION", "")
    arches_version = getattr(arches, "__version__", "")
    parts = [f"{app_name}/{app_version}" if app_version else app_name]
    if arches_version:
        parts.append(f"Arches/{arches_version}")
    contact = _ua_contact_block()
    if contact:
        parts.append(contact)
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

    Either the scheme/host/port is malformed or disallowed, DNS resolution
    fails, or the host resolves to a non-public address (loopback / private /
    link-local / reserved — including the cloud-metadata endpoint
    169.254.169.254).
    """


class ResponseTooLargeError(Exception):
    """Raised when an outbound response exceeds the byte budget.

    Counted on the DECOMPRESSED stream, so a small gzip answering with
    gigabytes of zeroes is refused at the cap rather than in swap.
    """


_ALLOWED_URL_SCHEMES = ("http", "https")

# An outbound fetch targets a web service, and every IIIF provider the project
# talks to serves on a default port. Anything else is a scan of the host's
# other services (Redis 6379, Elasticsearch 9200, a database) wearing an http
# URL, so the guard refuses it outright.
_ALLOWED_PORTS = frozenset({80, 443})


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


def _canonical_url(url):
    """The URL exactly as ``requests`` will put it on the wire.

    ``urllib.parse`` and ``urllib3`` disagree about where an authority ends
    when the string holds a backslash: ``urlparse`` reads
    ``http://169.254.169.254\\@example.com/`` as host ``example.com`` while
    ``requests`` connects to ``169.254.169.254``. Checking one host and
    connecting to another is the whole bug class, so the guard validates — and
    :func:`safe_fetch` sends — what ``requests`` prepares. A URL requests
    itself refuses (no host, malformed port) never becomes a fetch either.
    """
    prepared = requests.PreparedRequest()
    try:
        prepared.prepare_url(url, None)
    except Exception as exc:
        raise UnsafeURLError(f"Malformed URL {url!r}") from exc
    return prepared.url


def assert_url_is_safe(url, *, allow_private=None):
    """Validate an outbound URL against SSRF before fetching it.

    Checks the scheme is http(s), the host is present and the port is a web
    port, then resolves the host and rejects the URL if *any* resolved address
    is non-public. Returns the parsed CANONICAL URL on success (the form
    :func:`_canonical_url` produces, which is the one a fetch must send);
    raises ``UnsafeURLError`` otherwise.

    ``allow_private`` defaults to ``settings.SSRF_ALLOW_PRIVATE`` (False). A
    developer running a IIIF server on localhost sets it in
    ``settings_local.py``; it is deliberately NOT derived from ``DEBUG``, so
    turning on the debug toolbar cannot also open the guard.

    NOTE: the resolved addresses are checked at call time, but the connection
    is not pinned to a checked IP, so this is not a complete defence against
    DNS-rebinding (re-resolution at connect time). Pinning the resolved IP on
    the connection is a documented follow-up hardening.
    """
    if allow_private is None:
        allow_private = bool(getattr(django_settings, "SSRF_ALLOW_PRIVATE", False))

    parsed = urlparse(url)
    if parsed.scheme not in _ALLOWED_URL_SCHEMES:
        raise UnsafeURLError(f"Disallowed URL scheme: {parsed.scheme!r}")

    parsed = urlparse(_canonical_url(url))
    host = parsed.hostname
    if not host:
        raise UnsafeURLError("URL has no host")

    if allow_private:
        return parsed

    try:
        port = parsed.port or (443 if parsed.scheme == "https" else 80)
    except ValueError as exc:
        # urlparse defers the port syntax check to attribute access.
        raise UnsafeURLError(f"Malformed port in {url!r}") from exc
    if port not in _ALLOWED_PORTS:
        raise UnsafeURLError(f"Disallowed port {port} for host {host!r}")

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

    A host matches a configured suffix when it equals it or ends with
    ".<suffix>", so gallica.bnf.fr and any *.bnf.fr subdomain share the single
    "bnf.fr" bucket (and its stricter interval).

    Any other host is bucketed under ITS OWN hostname with the "default"
    interval — NOT a shared "default" bucket — so throttling one host never
    serialises requests to unrelated hosts (a bulk import spanning e-codices,
    DigiVatLib, Bodleian… runs each host's throttle independently instead of
    globally at one-request-per-second). The per-host bucket dicts grow by
    distinct host, which is naturally bounded by the handful of IIIF providers
    a batch touches.
    """
    host = (host or "").lower()
    limits = _rate_limits()
    for suffix, interval in limits.items():
        if suffix == "default":
            continue
        if host == suffix or host.endswith("." + suffix):
            return suffix, interval
    return host or "default", limits.get("default", 0)


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


# ---------------------------------------------------------------------------
# The single outbound fetch path
# ---------------------------------------------------------------------------

# A IIIF manifest for a fully digitised codex runs to a few MB; a thumbnail is
# smaller still. The cap is what an answer may weigh before it is treated as an
# attack on this host's memory rather than as data.
_DEFAULT_MAX_BYTES = 25 * 1024 * 1024
_READ_CHUNK = 64 * 1024

# Manifests come from providers that build them on the fly (Gallica, e-codices),
# so the read half of the budget stays generous where the connect half is the
# project-wide SSRF_TIMEOUT.
_MANIFEST_READ_TIMEOUT = 45


class FetchedResponse:
    """A fully-read, size-capped answer to :func:`safe_fetch`.

    Exposes the slice of the ``requests.Response`` API the project uses. It is
    a shim rather than a real ``Response`` with its private ``_content`` filled
    in: the body is already in memory and the socket is released, so nothing
    can read past the cap after the fact — an invariant a full ``Response``
    would let a caller undo. Add a member here when a caller needs one.
    """

    __slots__ = ("url", "status_code", "headers", "content")

    def __init__(self, url, status_code, headers, content):
        self.url = url
        self.status_code = status_code
        self.headers = headers
        self.content = content

    @property
    def ok(self):
        return self.status_code < 400

    def raise_for_status(self):
        if 400 <= self.status_code < 600:
            raise requests.HTTPError(
                f"{self.status_code} for url: {self.url}", response=self
            )

    def json(self):
        return json.loads(self.content)


def _ssrf_timeout():
    return getattr(django_settings, "SSRF_TIMEOUT", 10)


def _max_bytes(explicit=None):
    if explicit is not None:
        return explicit
    return getattr(django_settings, "SSRF_MAX_RESPONSE_BYTES", _DEFAULT_MAX_BYTES)


def _read_capped(response, max_bytes):
    """Read at most *max_bytes* of a streamed response, decompressed.

    ``iter_content`` decodes the transfer encoding as it goes, so the count is
    of bytes that would land in memory — the size a decompression bomb inflates
    to, not the size it was sent as. Stacked codings ("gzip, gzip") are refused
    outright: they are the shape of the urllib3 1.x decompression CVEs that
    Arches' pin leaves unfixed, and no IIIF server emits them.
    """
    codings = [
        c.strip()
        for c in response.headers.get("Content-Encoding", "").split(",")
        if c.strip()
    ]
    if len(codings) > 1:
        raise ResponseTooLargeError(
            f"Stacked content encodings {codings} from {response.url}"
        )

    declared = response.headers.get("Content-Length")
    try:
        declared_length = int(declared) if declared else None
    except ValueError:
        declared_length = None
    if declared_length is not None and declared_length > max_bytes:
        raise ResponseTooLargeError(
            f"{response.url} declares {declared_length} bytes (cap {max_bytes})"
        )

    chunks = []
    total = 0
    for chunk in response.iter_content(_READ_CHUNK):
        total += len(chunk)
        if total > max_bytes:
            raise ResponseTooLargeError(
                f"{response.url} exceeded the {max_bytes} byte cap"
            )
        chunks.append(chunk)
    return b"".join(chunks)


def safe_fetch(
    url,
    *,
    session=None,
    headers=None,
    timeout=None,
    max_bytes=None,
    allow_private=None,
    throttle=True,
):
    """GET *url* under every outbound-fetch rule the project applies.

    The SSRF guard runs on the URL and again on each redirect target, which is
    why redirects are never handed to ``requests`` (``allow_redirects=False``):
    a 302 to 169.254.169.254 is the classic way past a check made only on the
    URL a user typed. At most ``settings.SSRF_MAX_REDIRECTS`` hops are
    followed. The body is streamed and capped (see :func:`_read_capped`).

    ``throttle=False`` skips the per-host rate limit, for a caller that bounds
    its own outbound rate (the Biblissima proxy holds a concurrency semaphore
    for the whole call).

    Raises ``UnsafeURLError`` for a rejected URL or redirect chain,
    ``ResponseTooLargeError`` past the cap, and whatever ``requests`` raises
    for a transport failure.
    """
    session = session or get_iiif_session()
    if timeout is None:
        timeout = (_ssrf_timeout(), _ssrf_timeout())
    cap = _max_bytes(max_bytes)
    hops = getattr(django_settings, "SSRF_MAX_REDIRECTS", 5)

    target = url
    for _ in range(hops + 1):
        # The guard hands back the canonical form; sending anything else would
        # reopen the parser gap it just closed.
        target = assert_url_is_safe(target, allow_private=allow_private).geturl()
        if throttle:
            throttle_for_host(target)
        response = session.get(
            target,
            headers=headers,
            timeout=timeout,
            allow_redirects=False,
            stream=True,
        )
        location = response.headers.get("Location") if response.is_redirect else None
        if not location:
            try:
                body = _read_capped(response, cap)
            finally:
                response.close()
            return FetchedResponse(target, response.status_code, response.headers, body)
        response.close()
        target = urljoin(target, location)
    raise UnsafeURLError(f"More than {hops} redirects from {url}")


def fetch_iiif_manifest(url, *, session=None, timeout=None, allow_private=None):
    """Throttled, guarded GET of an external IIIF manifest.

    Thin alias for :func:`safe_fetch` with the manifest read budget; kept as a
    name because the manifest datatype and the IIIF tools read as callers of a
    IIIF operation, not of a generic fetch.
    """
    if timeout is None:
        timeout = (_ssrf_timeout(), _MANIFEST_READ_TIMEOUT)
    return safe_fetch(
        url,
        session=session,
        timeout=timeout,
        allow_private=allow_private,
    )
