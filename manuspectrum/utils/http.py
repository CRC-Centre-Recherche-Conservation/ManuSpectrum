"""Shared HTTP helpers for outbound requests from ManuSpectrum.

All project code that makes requests to external services should use the
User-Agent produced here so external hosts (IIIF servers, Biblissima, etc.)
see a single, identifiable client.
"""

from functools import lru_cache

import arches
from django.conf import settings as django_settings


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
