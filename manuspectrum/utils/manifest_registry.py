"""The one rule that imports a remote IIIF manifest into ``iiif_manifests``.

Shared by the ``manifest`` datatype (``pre_tile_save``, which lets every
failure propagate so the tile save rolls back), the annotation receiver in
``signals.py`` and the ``register_manifests`` command (which go through
:func:`register_remote_manifest` and get a closed set of outcomes instead of
exceptions).

A row is keyed by the URL exactly as given. The Arches IIIF viewer stores that
URL in each annotation feature (``properties.manifest``) and offers the
registered rows by label in its selector.
"""

import hashlib
import uuid
from urllib.parse import urlparse, urlunparse

import requests
from django.core.cache import cache
from django.core.validators import URLValidator, ValidationError
from django.db import connection, transaction

from arches.app.models.models import IIIFManifest

from manuspectrum.iiif.sources import local_manifest_uuid
from manuspectrum.utils.budget import BudgetSpent
from manuspectrum.utils.http import (
    ResponseTooLargeError,
    UnsafeURLError,
    assert_url_is_safe,
    fetch_iiif_manifest,
)
from manuspectrum.views.explorer.values import rewrite_legacy_url

KNOWN = "known"
REGISTERED = "registered"
LOCAL = "local"

INVALID_URL = "invalid_url"
REJECTED = "rejected"
UNREACHABLE = "unreachable"
NOT_IIIF = "not_iiif"
CANVAS_MISMATCH = "canvas_mismatch"

FAILURE_MEMO_PREFIX = "manifest-register:failed"
FAILURE_MEMO_TTL = 3600

ADVISORY_LOCK_NAMESPACE = 0x4D534D46

# Cheap, network-free URL format gate; the host policy is the SSRF guard's.
_validate_url_format = URLValidator(schemes=["http", "https"])


def check_url_format(url):
    """Raise ``django.core.validators.ValidationError`` unless ``url`` is a well-formed http(s) URL."""
    _validate_url_format(url)


class FailParsingManifestIIIF(Exception):
    pass


class InvalidManifestURL(FailParsingManifestIIIF):
    """The string is not an http(s) URL."""


class CanvasMismatch(Exception):
    """The fetched manifest holds none of the expected image services."""


class ManifestRegistrationError(Exception):
    """A registration that did not store a row; ``reason`` is one of the failure outcomes."""

    def __init__(self, reason, detail=""):
        super().__init__(f"{reason}: {detail}" if detail else reason)
        self.reason = reason


def normalize_url(url):
    """Strip the fragment and the trailing slash of the path."""
    if not url:
        return url
    parsed = urlparse(url)
    return urlunparse(
        (
            parsed.scheme,
            parsed.netloc,
            parsed.path.rstrip("/"),
            parsed.params,
            parsed.query,
            "",
        )
    )


def local_row(url):
    """``(True, row or None)`` when ``url`` is a local manifest reference, else ``(False, None)``.

    The project's one local rule: ``iiif.sources.local_manifest_uuid`` applied
    after ``rewrite_legacy_url``. The row is looked up by globalid.
    """
    local = local_manifest_uuid(rewrite_legacy_url(url or ""))
    if local is None:
        return False, None
    try:
        return True, IIIFManifest.objects.filter(globalid=local).first()
    except (ValueError, ValidationError):
        return True, None


def is_iiif_manifest(manifest_json):
    if not isinstance(manifest_json, dict):
        raise FailParsingManifestIIIF("Manifest JSON is not a dict")

    context = manifest_json.get("@context")

    if context and "iiif.io/api/presentation/2/context.json" in context:
        if manifest_json.get("@type") == "sc:Manifest":
            return True
        raise FailParsingManifestIIIF("Missing or invalid @type for IIIF v2 manifest")

    if context and "iiif.io/api/presentation/3/context.json" in context:
        if manifest_json.get("type") == "Manifest":
            return True
        raise FailParsingManifestIIIF("Missing or invalid type for IIIF v3 manifest")

    raise FailParsingManifestIIIF("Not a recognized IIIF manifest (no valid @context)")


def extract_label(manifest_json):
    if not manifest_json:
        return None
    label = manifest_json.get("label")
    if isinstance(label, dict):
        val = label.get("en") or label.get("none") or next(iter(label.values()), None)
        return val[0] if isinstance(val, list) and val else val
    if isinstance(label, list) and label:
        return label[0].get("@value") if isinstance(label[0], dict) else label[0]
    return str(label) if label else None


def extract_description(manifest_json):
    if not manifest_json:
        return None
    desc = manifest_json.get("description") or manifest_json.get("summary")
    if isinstance(desc, dict):
        val = desc.get("en") or desc.get("none") or next(iter(desc.values()), None)
        return val[0] if isinstance(val, list) and val else val
    if isinstance(desc, list) and desc:
        return desc[0].get("@value") if isinstance(desc[0], dict) else desc[0]
    return str(desc) if desc else None


def _service_id(service):
    if isinstance(service, list):
        return [sid for item in service for sid in _service_id(item)]
    if isinstance(service, dict):
        sid = service.get("@id") or service.get("id")
        return [sid] if isinstance(sid, str) else []
    return []


def image_services(manifest_json):
    """Image service ids of a v2 or v3 manifest, trailing slash stripped."""
    found = set()

    def dicts(value):
        return (
            [v for v in value if isinstance(v, dict)] if isinstance(value, list) else []
        )

    for sequence in dicts(manifest_json.get("sequences")):
        for canvas in dicts(sequence.get("canvases")):
            for image in dicts(canvas.get("images")):
                resource = image.get("resource")
                if isinstance(resource, dict):
                    found.update(_service_id(resource.get("service")))
    for canvas in dicts(manifest_json.get("items")):
        for page in dicts(canvas.get("items")):
            for annotation in dicts(page.get("items")):
                body = annotation.get("body")
                for item in body if isinstance(body, list) else [body]:
                    if isinstance(item, dict):
                        found.update(_service_id(item.get("service")))
    return {sid.rstrip("/") for sid in found}


def _known_variants(url):
    """The URL as given, its normalized form, and that form with a trailing slash."""
    normalized = normalize_url(url)
    return [url, normalized, f"{normalized}/"]


def _find_known(url):
    return IIIFManifest.objects.filter(url__in=_known_variants(url)).first()


def find_registered(url):
    """``(row or None, outcome or None)`` from the database alone: ``local``, ``known`` or nothing."""
    is_local, row = local_row(url)
    if is_local:
        return row, LOCAL
    row = _find_known(url)
    return (row, KNOWN) if row else (None, None)


def fetch_manifest_json(url):
    """Guarded fetch of ``url``: format gate, SSRF guard, throttled GET, IIIF check.

    Raises the underlying exceptions unchanged (``InvalidManifestURL``,
    ``UnsafeURLError``, ``requests`` errors, ``FailParsingManifestIIIF``).
    """
    try:
        check_url_format(url)
    except ValidationError as exc:
        raise InvalidManifestURL(f"Not a valid manifest URL: {url}") from exc
    assert_url_is_safe(url)
    resp = fetch_iiif_manifest(url)
    resp.raise_for_status()
    manifest_json = resp.json()
    is_iiif_manifest(manifest_json)
    return manifest_json


def store_manifest(url, manifest_json):
    """Create the row for ``url`` unless a concurrent call did; return ``(row, created)``.

    A transaction-scoped advisory lock on the normalized URL serialises
    registrations of one URL, and existence is re-checked under it. The lock
    lives until the outermost commit (on the datatype path, after the rest of
    ``Tile.save``), so two saves registering the same two URLs in opposite
    orders can deadlock and PostgreSQL fails one of them.
    """
    with transaction.atomic():
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT pg_advisory_xact_lock(%s, hashtext(%s))",
                [ADVISORY_LOCK_NAMESPACE, normalize_url(url)],
            )
        existing = _find_known(url)
        if existing:
            return existing, False
        row = IIIFManifest.objects.create(
            globalid=uuid.uuid4(),
            url=url,
            label=extract_label(manifest_json) or "IIIF Manifest",
            description=extract_description(manifest_json) or "",
            manifest=manifest_json,
        )
        return row, True


def import_manifest(url, *, expected_service=None):
    """Fetch and store ``url``; return ``(row, created)``, raising the raw exceptions.

    With ``expected_service`` the manifest must hold that image service id
    (trailing slash ignored), else ``CanvasMismatch`` and nothing is stored.
    """
    manifest_json = fetch_manifest_json(url)
    if expected_service is not None:
        if expected_service.rstrip("/") not in image_services(manifest_json):
            raise CanvasMismatch(url)
    return store_manifest(url, manifest_json)


def _memo_key(url):
    return f"{FAILURE_MEMO_PREFIX}:{hashlib.sha256(url.encode()).hexdigest()}"


def _reason_of(exc):
    if isinstance(exc, InvalidManifestURL):
        return INVALID_URL
    if isinstance(exc, CanvasMismatch):
        return CANVAS_MISMATCH
    if isinstance(exc, (FailParsingManifestIIIF, ValueError)):
        return NOT_IIIF
    if isinstance(exc, (UnsafeURLError, ResponseTooLargeError)):
        return REJECTED
    if isinstance(exc, requests.HTTPError):
        status = getattr(exc.response, "status_code", None) or 0
        return REJECTED if 400 <= status < 500 else UNREACHABLE
    if isinstance(exc, (requests.RequestException, BudgetSpent)):
        return UNREACHABLE
    return None


def register_remote_manifest(url, *, expected_service=None, use_memo=True):
    """Register the manifest at ``url``; return ``(row, outcome)``.

    Outcomes: ``known`` (a row holds the URL, or its normalized form),
    ``registered``, ``local`` (a local reference per ``local_row``, never fetched; the
    row or None). Anything else raises ``ManifestRegistrationError`` whose reason is
    ``invalid_url``, ``rejected`` (SSRF guard, HTTP 4xx), ``unreachable``
    (network, timeout, 5xx), ``not_iiif`` or ``canvas_mismatch``. With
    ``use_memo`` a URL that failed for any of these reasons is not fetched
    again for an hour; without it nothing is read or stored in the memo. A
    spent request budget is the caller's, not the URL's: it is not memoised.
    Does not catch exceptions it cannot name.
    """
    row, outcome = find_registered(url)
    if outcome:
        return row, outcome
    if use_memo:
        memoised = cache.get(_memo_key(url))
        if memoised:
            raise ManifestRegistrationError(memoised, "recent failure")
    try:
        row, created = import_manifest(url, expected_service=expected_service)
    except Exception as exc:
        reason = _reason_of(exc)
        if reason is None:
            raise
        if use_memo and not isinstance(exc, BudgetSpent):
            cache.add(_memo_key(url), reason, FAILURE_MEMO_TTL)
        raise ManifestRegistrationError(reason, type(exc).__name__) from exc
    return row, REGISTERED if created else KNOWN


def feature_manifest(feature):
    """``(manifest URL, canvas id or None)`` of an annotation feature naming an http(s) manifest, else None."""
    properties = feature.get("properties") if isinstance(feature, dict) else None
    if not isinstance(properties, dict):
        return None
    manifest = properties.get("manifest")
    if not isinstance(manifest, str) or not manifest.startswith(
        ("http://", "https://")
    ):
        return None
    canvas = properties.get("canvas")
    return manifest, canvas if isinstance(canvas, str) else None


def annotation_manifests(data):
    """``{node id: {manifest URL: [canvas ids]}}`` of the http(s) manifests named by the FeatureCollections of tile ``data``.

    The one rule for which manifests an annotation names; canvas ids are kept
    in the order first seen, once each.
    """
    found = {}
    for nodeid, value in (data or {}).items():
        if not isinstance(value, dict) or value.get("type") != "FeatureCollection":
            continue
        for feature in value.get("features") or []:
            named = feature_manifest(feature)
            if named is None:
                continue
            url, canvas = named
            canvases = found.setdefault(nodeid, {}).setdefault(url, [])
            if canvas and canvas not in canvases:
                canvases.append(canvas)
    return found
