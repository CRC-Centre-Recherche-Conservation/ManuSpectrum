"""Biblissima connector: HTTP proxy + Arches write path.

Shared module — not workflow-specific. Any feature that needs Biblissima
data (imports, enrichments, search suggestions, future connectors…) should
go through the views here rather than calling the portal / Wikibase / IIIF
endpoints directly, so that concurrency limits, caching, and user-agent /
language headers stay consistent for the whole server.

Two surface areas:

- **Read-only proxy views** (``BiblissimaSuggestView``, ``BiblissimaEntityView``,
  ``BiblissimaSearchView``, ``BiblissimaSearchManuscriptsView``,
  ``BiblissimaManuscriptIlluminationsView``, ``BiblissimaIlluminationDetailView``,
  …) — HTTP facades over the Biblissima portal, Wikibase, and IIIF manifests.
  Never write to the Arches DB. Safe to call from any frontend or service.

- **Write path** (``BiblissimaCreateResourceView``, ``BiblissimaAddAltNameView``)
  — create or annotate Arches resources from Biblissima-derived data. The
  ``Import Biblissima`` workflow plugin is the primary consumer today,
  but the endpoints are generic: they take a ``resourceType`` + payload
  and don't assume a specific UI flow.

Outbound HTTP all goes through ``_build_biblissima_session()`` +
``_bib_request()``, which share a module-level concurrency semaphore and
force ``Accept-Language: fr`` so that scraped portal field labels
(``Type :``, ``Lieu de fabrication :``, …) always match our French field
map regardless of the end-user's browser locale.

## Attention points for devs

- **HTML parsing**: use ``lxml.html`` + XPath (see
  ``BiblissimaIlluminationDetailView``). Regex is only used for URL-level
  string transformations on already-extracted values, never to find
  content inside HTML.
- **Caching**: every scraping view is wrapped with ``@cache_page(3600)``.
  Code changes to any parser are **invisible** until the cache expires or
  is flushed::

      redis-cli --scan --pattern "*biblissima*" | xargs -r redis-cli DEL
      redis-cli --scan --pattern "*views.decorators.cache*" | xargs -r redis-cli DEL

- **Type resolution**: ``_resolve_biblissima_type`` returns
  ``(valueid, is_fallback)``. ``is_fallback=True`` only when **no** input
  term matched the mapping at all — an explicit ``"Enluminure"`` matches
  and returns ``is_fallback=False`` even though it happens to share the
  same valueid as the generic default. Callers that want to flag items
  needing user review must check the flag, not compare valueids.
"""

import logging
import re
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from html import unescape

import requests
from lxml import html as lxml_html
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from django.core.cache import cache
from django.http import JsonResponse
from django.utils.decorators import method_decorator
from django.utils.translation import gettext as _
from django.views import View
from django.views.decorators.cache import cache_page, never_cache

from arches.app.models.models import ResourceInstance
from arches.app.models.models import Value  # used in _concept_valueid
from arches.app.models.tile import Tile

from manuspectrum.utils.dates import (
    CENTURY_MAPPING,
    parse_century,
    parse_historical_date,
)
from manuspectrum.utils.http import get_user_agent

logger = logging.getLogger(__name__)

BIBLISSIMA_WIKIBASE = "https://data.biblissima.fr/w/api.php"
BIBLISSIMA_IIIF_MANIFEST = "https://portail.biblissima.fr/iiif/manifest"

REQUEST_TIMEOUT = 10
# The Biblissima IIIF manifest and portal HTML endpoints can be slow when
# aggregating descriptor-based manifests or when the portal is under load.
IIIF_REQUEST_TIMEOUT = 45
PORTAL_REQUEST_TIMEOUT = 30


def _build_biblissima_session():
    """Requests session with retry/backoff on transient upstream failures.

    The Retry adapter honors Retry-After headers by default
    (respect_retry_after_header=True), so upstream explicit backoff requests
    on 429/503 are respected transparently.

    ``Accept-Language: fr`` is forced on every outbound request: the portal
    URLs themselves are already locked to ``/fr/`` paths, but this header
    ensures that any content negotiation (on Biblissima side or on an
    intermediate proxy / CDN) still serves us the French page — our
    scrape field map (``"Type :"``, ``"Lieu de fabrication :"``, …) only
    matches French labels. Whatever locale the end-user's browser runs in
    is irrelevant, only what *this server* sends to Biblissima counts.
    """
    session = requests.Session()
    session.headers.update(
        {
            "User-Agent": get_user_agent(),
            "Accept-Language": "fr-FR,fr;q=0.9",
        }
    )
    retry = Retry(
        total=3,
        connect=2,
        read=2,
        status=3,
        backoff_factor=1.5,
        status_forcelist=(429, 502, 503, 504),
        allowed_methods=frozenset(["GET", "HEAD"]),
        raise_on_status=False,
    )
    adapter = HTTPAdapter(max_retries=retry)
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    return session


# ---------------------------------------------------------------------------
# Concurrency control & monitoring for outbound Biblissima calls
# ---------------------------------------------------------------------------

# Module-level semaphore bounds how many concurrent HTTP calls to Biblissima
# can run across the whole Django process, regardless of how many users hit
# the proxy at the same time. Sized to stay a good API citizen.
_BIBLISSIMA_CONCURRENCY_LIMIT = 12
_biblissima_semaphore = threading.BoundedSemaphore(_BIBLISSIMA_CONCURRENCY_LIMIT)

# Cache keys and TTLs for Biblissima data in the Django cache backend.
_BIBLISSIMA_CACHE_TTL = 24 * 60 * 60  # 24 hours
_BIBLISSIMA_ENTITY_CACHE_KEY = "biblissima:wikibase:entity:{qid}"
_BIBLISSIMA_MANUSCRIPT_CACHE_KEY = "biblissima:wikibase:manuscript:{ark_hash}"

# Lightweight counters for observing upstream health via /api/biblissima/stats.
_biblissima_stats = {
    "requests_total": 0,
    "requests_in_flight": 0,
    "responses_429": 0,
    "responses_5xx": 0,
    "errors_total": 0,
    "cache_hits": 0,
    "cache_misses": 0,
}
_biblissima_stats_lock = threading.Lock()


def _incr_stat(key, delta=1):
    with _biblissima_stats_lock:
        _biblissima_stats[key] = _biblissima_stats.get(key, 0) + delta


@contextmanager
def _biblissima_slot():
    """Acquire one concurrency slot for an outbound Biblissima call."""
    _biblissima_semaphore.acquire()
    _incr_stat("requests_in_flight", 1)
    try:
        yield
    finally:
        _incr_stat("requests_in_flight", -1)
        _biblissima_semaphore.release()


def _bib_request(session, url, **kwargs):
    """Wrapper around session.get bounding concurrency and recording metrics.

    The session's HTTPAdapter already handles Retry-After and transient 5xx/429
    retries with backoff, so this wrapper only counts the final response that
    reaches the caller. Retries inside the adapter are invisible here by design
    (otherwise we'd double-count them).
    """
    with _biblissima_slot():
        _incr_stat("requests_total", 1)
        try:
            resp = session.get(url, **kwargs)
        except Exception:
            _incr_stat("errors_total", 1)
            raise
    status = resp.status_code
    if status == 429:
        _incr_stat("responses_429", 1)
    elif 500 <= status < 600:
        _incr_stat("responses_5xx", 1)
    return resp


def _biblissima_upstream_error(exc, context):
    """Map a requests exception to a JSON error response with a user-facing message."""
    if isinstance(exc, requests.exceptions.Timeout):
        logger.warning("%s timed out", context)
        return JsonResponse(
            {
                "error": "timeout",
                "message": _(
                    "The Biblissima portal did not respond in time. Please try again in a moment."
                ),
            },
            status=504,
        )
    if isinstance(exc, requests.exceptions.ConnectionError):
        logger.warning("%s connection error", context)
        return JsonResponse(
            {
                "error": "connection_error",
                "message": _(
                    "Unable to reach the Biblissima portal. Check your connection and try again."
                ),
            },
            status=502,
        )
    if isinstance(exc, requests.exceptions.HTTPError):
        status = exc.response.status_code if exc.response is not None else 502
        logger.warning("%s HTTP error %s", context, status)
        return JsonResponse(
            {
                "error": "upstream_error",
                "status": status,
                "message": _(
                    "The Biblissima portal returned an error (%(status)s). Please try again in a moment."
                )
                % {"status": status},
            },
            status=502,
        )
    if isinstance(exc, ValueError):
        logger.exception("%s returned invalid JSON", context)
        return JsonResponse(
            {
                "error": "invalid_response",
                "message": _("Invalid response from the Biblissima portal."),
            },
            status=502,
        )
    logger.exception("%s failed", context)
    return JsonResponse(
        {
            "error": "unknown_error",
            "message": _("Unknown error while querying Biblissima."),
        },
        status=502,
    )


# Wikibase property IDs
P2 = "P2"  # nature de l'élément
P129 = "P129"  # identifiant Portail Biblissima
P194 = "P194"  # collection (institution)
P195 = "P195"  # cote (shelfmark)
P196 = "P196"  # manifeste IIIF
P197 = "P197"  # numérisation URL
P198 = "P198"  # identifiant BnF Archives et Manuscrits (AeM)
P270 = "P270"  # identifiant Mandragore
P354 = "P354"  # auteur
P201 = "P201"  # localisation (place)
P169 = "P169"  # partie de (parent institution)
P123 = "P123"  # identifiant Geonames

# Arches graph UUIDs
DOCUMENT_GRAPH_ID = "0c8226c1-11a9-4c48-9601-a7a0c6f2df6b"
COMPONENT_GRAPH_ID = "d47595b4-f8a6-419c-8f33-b388206280c4"
PROJECT_GRAPH_ID = "87a4319d-3ca5-43f6-88cc-a7379fba67f6"
PLACE_GRAPH_ID = "3f2b036a-b65d-474d-b692-0b21903655c5"
PERSON_GRAPH_ID = "5bf45c85-84cd-4a76-b64a-3ffe86eea1b8"
GROUP_GRAPH_ID = "4f447dca-dbb3-48d0-bc90-3f2935db8b8c"

# --- Document nodegroups & nodes ---
DOC_NAME_NG = "3e132cfd-7038-11ef-8753-0575b5bada34"
DOC_NAME_LABEL = "3e132d00-7038-11ef-8753-0575b5bada34"
DOC_NAME_LANGUAGE = "3e132cff-7038-11ef-8753-0575b5bada34"
DOC_NAME_TYPE = "3e132d01-7038-11ef-8753-0575b5bada34"

DOC_IDENTIFIER_NG = "413fd755-7038-11ef-8753-0575b5bada34"
DOC_IDENTIFIER_VALUE = "413fd757-7038-11ef-8753-0575b5bada34"
DOC_IDENTIFIER_SOURCE = "413fd758-7038-11ef-8753-0575b5bada34"
DOC_IDENTIFIER_TYPE = "413fd759-7038-11ef-8753-0575b5bada34"

DOC_TYPE_NG = "9d757c50-7041-11ef-8753-0575b5bada34"
DOC_TYPE_NODE = "9d757c50-7041-11ef-8753-0575b5bada34"

DOC_STATEMENT_NG = "44a2e1a3-7038-11ef-8753-0575b5bada34"
DOC_STATEMENT_CONTENT = "44a2e1a7-7038-11ef-8753-0575b5bada34"
DOC_STATEMENT_LANGUAGE = "44a2e1aa-7038-11ef-8753-0575b5bada34"
DOC_STATEMENT_SOURCE = "44a2e1ad-7038-11ef-8753-0575b5bada34"
DOC_STATEMENT_TYPE = "44a2e1ac-7038-11ef-8753-0575b5bada34"

DOC_FACSIMILES_NG = "76cb5191-e4e4-4fd4-8d1d-f040292290b4"
DOC_FACSIMILES_NODE = "76cb5191-e4e4-4fd4-8d1d-f040292290b4"

DOC_LOCATION_NG = "a53152c8-703e-11ef-8753-0575b5bada34"
DOC_LOCATION_NODE = "a53152c8-703e-11ef-8753-0575b5bada34"
DOC_LOCATION_LITERAL = "c764ad5c-d1b6-11ef-8532-495867ec2258"

DOC_OWNER_NG = "ce94a73c-703e-11ef-8753-0575b5bada34"
DOC_OWNER_NODE = "ce94a73c-703e-11ef-8753-0575b5bada34"

DOC_PRODUCTION_NG = "fb5d903b-7052-11ef-8753-0575b5bada34"
DOC_PROD_ACTORS = "fb5d904d-7052-11ef-8753-0575b5bada34"
DOC_PROD_MOTIVATED = "fb5d904a-7052-11ef-8753-0575b5bada34"
DOC_PROD_PLACE = "fb5d904f-7052-11ef-8753-0575b5bada34"
DOC_PROD_INFLUENCES = "fb5d9045-7052-11ef-8753-0575b5bada34"
DOC_PROD_DATE_START = "fb5d9050-7052-11ef-8753-0575b5bada34"
DOC_PROD_DATE_END = "fb5d904c-7052-11ef-8753-0575b5bada34"
DOC_PROD_TIME_TYPE = "fb5d9042-7052-11ef-8753-0575b5bada34"
DOC_PROD_CULTURAL = "5b462970-edfe-11ef-9a8f-89acc4447d22"
DOC_PROD_TECHNIQUES = "2577f662-d1b0-11ef-8532-495867ec2258"

DOC_PERIOD_NG = "ee5666f5-edf3-11ef-9a8f-89acc4447d22"
DOC_PERIOD_ABSOLUTE = "ee5666fc-edf3-11ef-9a8f-89acc4447d22"
DOC_PERIOD_PRODUCTION = "ee5666f5-edf3-11ef-9a8f-89acc4447d22"

DOC_DIMENSION_NG = "dd725542-7039-11ef-8753-0575b5bada34"
DOC_DIMENSION_TYPE = "66351560-703d-11ef-8753-0575b5bada34"
DOC_DIMENSION_UNIT = "f0f2f252-7039-11ef-8753-0575b5bada34"
DOC_DIMENSION_VALUE = "1dc76d80-703a-11ef-8753-0575b5bada34"

DOC_COMPOSED_NG = "e3bfe85e-703b-11ef-8753-0575b5bada34"
DOC_COMPOSED_TYPE = "7153adc2-704f-11ef-8753-0575b5bada34"
DOC_COMPOSED_UNIT = "7153adc3-704f-11ef-8753-0575b5bada34"
DOC_COMPOSED_VALUE = "7153adc1-704f-11ef-8753-0575b5bada34"

DOC_PART_OF_NG = "e4166b5c-d1b1-11ef-8532-495867ec2258"
DOC_PART_OF_NODE = "e4166b5c-d1b1-11ef-8532-495867ec2258"

# Project studied objects
PROJECT_STUDIED_OBJECTS_NG = "a8fb3c9e-bbc4-11ef-bd5f-ed806b645d76"
PROJECT_STUDIED_OBJECTS_NODE = "a8fb3c9e-bbc4-11ef-bd5f-ed806b645d76"

# --- Component nodegroups & nodes ---
COMP_TYPE_NG = "0474f0de-711e-11ef-be19-21cc18cdd2a8"
COMP_TYPE_NODE = "0474f0de-711e-11ef-be19-21cc18cdd2a8"

COMP_PARENT_DOC_NG = "26524186-710d-11ef-be19-21cc18cdd2a8"
COMP_PARENT_DOC_NODE = "e0bd205a-711b-11ef-be19-21cc18cdd2a8"

COMP_ICONOGRAPHIC_NG = "56018940-ee09-11ef-9a8f-89acc4447d22"
COMP_ICONOGRAPHIC_NODE = "56018940-ee09-11ef-9a8f-89acc4447d22"

COMP_NAME_NG = "96e53203-710b-11ef-be19-21cc18cdd2a8"
COMP_NAME_LABEL = "96e53206-710b-11ef-be19-21cc18cdd2a8"
COMP_NAME_LANGUAGE = "96e53205-710b-11ef-be19-21cc18cdd2a8"
COMP_NAME_TYPE = "96e53207-710b-11ef-be19-21cc18cdd2a8"

COMP_CONTEXT_NG = "96ef1746-711e-11ef-be19-21cc18cdd2a8"
COMP_CONTEXT_NODE = "96ef1746-711e-11ef-be19-21cc18cdd2a8"

COMP_IDENTIFIER_NG = "a9c93cbb-710b-11ef-be19-21cc18cdd2a8"
COMP_IDENTIFIER_VALUE = "a9c93cbd-710b-11ef-be19-21cc18cdd2a8"
COMP_IDENTIFIER_SOURCE = "a9c93cbe-710b-11ef-be19-21cc18cdd2a8"
COMP_IDENTIFIER_TYPE = "a9c93cbf-710b-11ef-be19-21cc18cdd2a8"

COMP_STATEMENT_NG = "b6dfa2e1-710b-11ef-be19-21cc18cdd2a8"
COMP_STATEMENT_CONTENT = "b6dfa2e5-710b-11ef-be19-21cc18cdd2a8"
COMP_STATEMENT_LANGUAGE = "b6dfa2e8-710b-11ef-be19-21cc18cdd2a8"
COMP_STATEMENT_SOURCE = "b6dfa2eb-710b-11ef-be19-21cc18cdd2a8"
COMP_STATEMENT_TYPE = "b6dfa2ea-710b-11ef-be19-21cc18cdd2a8"

COMP_PRODUCTION_NG = "c31205b9-71b4-11ef-bb52-6361ac5a97ee"
COMP_PROD_ACTORS = "c31205cb-71b4-11ef-bb52-6361ac5a97ee"
COMP_PROD_MOTIVATED = "c31205c8-71b4-11ef-bb52-6361ac5a97ee"
COMP_PROD_PLACE = "c31205cd-71b4-11ef-bb52-6361ac5a97ee"
COMP_PROD_INFLUENCES = "c31205c3-71b4-11ef-bb52-6361ac5a97ee"
COMP_PROD_DATE_START = "c31205ce-71b4-11ef-bb52-6361ac5a97ee"
COMP_PROD_DATE_END = "c31205ca-71b4-11ef-bb52-6361ac5a97ee"
COMP_PROD_TIME_TYPE = "c31205c0-71b4-11ef-bb52-6361ac5a97ee"

COMP_PERIOD_NG = "e67686af-edf2-11ef-9a8f-89acc4447d22"
COMP_PERIOD_ABSOLUTE = "e67686b6-edf2-11ef-9a8f-89acc4447d22"
COMP_PERIOD_PRODUCTION = "e67686af-edf2-11ef-9a8f-89acc4447d22"

COMP_LOCATION_DOC_NG = "fa5cc926-e889-11ef-9bfc-0debd0685137"
COMP_LOCATION_DOC_NODE = "fa5cc926-e889-11ef-9bfc-0debd0685137"
COMP_LOCATION_APPELLATION = "f0dcdbf0-e88b-11ef-9bfc-0debd0685137"

# --- Place nodegroups & nodes ---
PLACE_NAME_NG = "e4513853-7024-11ef-8753-0575b5bada34"
PLACE_NAME_LABEL = "e4513856-7024-11ef-8753-0575b5bada34"
PLACE_NAME_LANGUAGE = "e4513855-7024-11ef-8753-0575b5bada34"
PLACE_NAME_TYPE = "e4513857-7024-11ef-8753-0575b5bada34"

PLACE_IDENTIFIER_NG = "e7bf9151-7024-11ef-8753-0575b5bada34"
PLACE_IDENTIFIER_VALUE = "e7bf9153-7024-11ef-8753-0575b5bada34"
PLACE_IDENTIFIER_SOURCE = "e7bf9154-7024-11ef-8753-0575b5bada34"
PLACE_IDENTIFIER_TYPE = "e7bf9155-7024-11ef-8753-0575b5bada34"

# --- Group nodegroups & nodes ---
GROUP_NAME_NG = "e69cbd41-7018-11ef-8753-0575b5bada34"
GROUP_NAME_LABEL = "e69cbd44-7018-11ef-8753-0575b5bada34"
GROUP_NAME_LANGUAGE = "e69cbd43-7018-11ef-8753-0575b5bada34"
GROUP_NAME_TYPE = "e69cbd45-7018-11ef-8753-0575b5bada34"

GROUP_IDENTIFIER_NG = "eda9eee7-7018-11ef-8753-0575b5bada34"
GROUP_IDENTIFIER_VALUE = "eda9eee9-7018-11ef-8753-0575b5bada34"
GROUP_IDENTIFIER_SOURCE = "eda9eeea-7018-11ef-8753-0575b5bada34"
GROUP_IDENTIFIER_TYPE = "eda9eeeb-7018-11ef-8753-0575b5bada34"

GROUP_MEMBER_OF_NG = "86e02cce-7019-11ef-8753-0575b5bada34"
GROUP_MEMBER_OF_NODE = "86e02cce-7019-11ef-8753-0575b5bada34"

GROUP_LOCATION_NG = "636b1b3e-ae2e-11ef-8dd2-3b6c98a10134"
GROUP_LOCATION_NODE = "636b1b3e-ae2e-11ef-8dd2-3b6c98a10134"

# --- Person nodegroups & nodes ---
PERSON_NAME_NG = "8e97f1a7-701c-11ef-8753-0575b5bada34"
PERSON_NAME_LABEL = "8e97f1aa-701c-11ef-8753-0575b5bada34"
PERSON_NAME_LANGUAGE = "8e97f1a9-701c-11ef-8753-0575b5bada34"
PERSON_NAME_TYPE = "8e97f1ab-701c-11ef-8753-0575b5bada34"

PERSON_IDENTIFIER_NG = "943a2c65-701c-11ef-8753-0575b5bada34"
PERSON_IDENTIFIER_VALUE = "943a2c67-701c-11ef-8753-0575b5bada34"
PERSON_IDENTIFIER_SOURCE = "943a2c68-701c-11ef-8753-0575b5bada34"
PERSON_IDENTIFIER_TYPE = "943a2c69-701c-11ef-8753-0575b5bada34"

# Dependency nodegroup lookup by graph ID
DEP_NAME_CONFIG = {
    PLACE_GRAPH_ID: {
        "ng": PLACE_NAME_NG,
        "label": PLACE_NAME_LABEL,
        "language": PLACE_NAME_LANGUAGE,
        "type": PLACE_NAME_TYPE,
    },
    GROUP_GRAPH_ID: {
        "ng": GROUP_NAME_NG,
        "label": GROUP_NAME_LABEL,
        "language": GROUP_NAME_LANGUAGE,
        "type": GROUP_NAME_TYPE,
    },
    PERSON_GRAPH_ID: {
        "ng": PERSON_NAME_NG,
        "label": PERSON_NAME_LABEL,
        "language": PERSON_NAME_LANGUAGE,
        "type": PERSON_NAME_TYPE,
    },
}

# --- Concept defaults ---
CONCEPT_ALTERNATE_TITLES = "7cca3482-44b5-42ea-a1d7-120cd732b350"
CONCEPT_FRENCH = "a1d82c77-ebd6-4215-ab85-2c0b6a68a0e8"
CONCEPT_PREFERRED_TERMS = "5f400d39-3b6b-4b8a-939b-4e49787c7444"
CONCEPT_PERSISTENT_ID = "5b292232-52ac-4e71-ba6c-fe4dd6ff02fa"
CONCEPT_RECORD_ID = "e10752d3-d8fa-47cb-92f9-dd7277dfc97a"
CONCEPT_SOURCE_BIBLISSIMA = "39124989-dfb1-4e2a-9d1a-4bff0827ed71"
CONCEPT_SOURCE_MANDRAGORE = "3b78627a-c751-43df-b427-73e1dd11ec38"
CONCEPT_TYPE_BNF_ID = "bd1fa4c5-c7e7-45d2-b58c-e5f54a1da34d"
CONCEPT_DESCRIPTION = "9a51d30b-48e8-4f94-9344-cd2bb1d4b33a"
CONCEPT_IDENTIFICATION = (
    "d2a8104a-312a-4f1d-acb7-3ecb1335e2fc"  # Statement type for "Texte" (which work)
)
CONCEPT_INSCRIPTIONS = (
    "9076a3e5-06f5-4ed7-91e4-985914c7178b"  # Statement type for "Rubrique"
)
CONCEPT_MANUSCRIT = "56c61151-3bc5-45b4-957e-3cccde26abe7"
CONCEPT_DECOR = "c19f3196-d1e9-4f08-9917-4d627e61e153"
CONCEPT_SHELF_MARKS = "2cbf15b4-aa04-4b5b-bf4a-2594bbeb72ca"
CONCEPT_MEDIEVAL = "f8101404-1570-35cf-ac70-1a18a84072ca"

# Century mapping: "13e siècle" → concept UUID
# CENTURY_MAPPING + _CENTURY_RE + parse_century now live in
# ``manuspectrum.utils.dates`` (imported above) so other connectors and
# importers can share the same vocabulary → valueid mapping.

RELATIONSHIP_CONCEPT = "ac41d9be-79db-4256-b368-2f4559cfbe55"

_ARK_RE = re.compile(r"ark:/43093/(\w+)")


def _parse_html_fragment(text):
    """Parse an HTML fragment with lxml, tolerant of mixed text/markup.

    ``fragment_fromstring(create_parent=...)`` accepts text-only input,
    multiple top-level tags, and ill-formed-but-real HTML — all things a
    bare ``fromstring`` rejects. Returns ``None`` if parsing fails.
    """
    try:
        return lxml_html.fragment_fromstring(text, create_parent="div")
    except Exception:
        return None


def _strip_html(text):
    """Remove HTML tags and unescape entities from a (possibly HTML) value.

    Uses lxml on actual fragments so attributes containing ``>`` or other
    HTML-y content don't break the strip. Lists are processed recursively.
    """
    if not text:
        return text
    if isinstance(text, list):
        return [_strip_html(t) for t in text]
    s = str(text)
    if "<" not in s:
        return unescape(s)
    frag = _parse_html_fragment(s)
    if frag is None:
        return unescape(s)
    return " ".join(frag.text_content().split())


def _extract_ark(html_value):
    """Extract ARK identifier from an HTML link."""
    if not html_value:
        return None
    text = html_value if isinstance(html_value, str) else str(html_value)
    match = _ARK_RE.search(text)
    return f"ark:/43093/{match.group(1)}" if match else None


def _extract_href(html_value):
    """Extract the first href URL from an HTML fragment."""
    if not html_value:
        return None
    s = html_value if isinstance(html_value, str) else str(html_value)
    if "href" not in s:
        return None
    frag = _parse_html_fragment(s)
    if frag is None:
        return None
    for a in frag.iter("a"):
        href = a.get("href")
        if href:
            return href
    return None


def _extract_entity_props(qid, raw_entity):
    """Extract relevant properties from a raw Wikibase entity dict."""
    claims = raw_entity.get("claims", {})

    def _get_string(prop):
        claim_list = claims.get(prop, [])
        if claim_list:
            val = claim_list[0].get("mainsnak", {}).get("datavalue", {}).get("value")
            if isinstance(val, str):
                return val
        return None

    def _get_entity_id(prop):
        claim_list = claims.get(prop, [])
        if claim_list:
            val = (
                claim_list[0].get("mainsnak", {}).get("datavalue", {}).get("value", {})
            )
            if isinstance(val, dict):
                return val.get("id")
        return None

    labels = raw_entity.get("labels", {})
    label = labels.get("fr", {}).get("value") or labels.get("en", {}).get("value") or ""

    return {
        "biblissimaQid": qid,
        "label": label,
        "portalHash": _get_string(P129),
        "manifestUrl": _get_string(P196),
        "digitizationUrl": _get_string(P197),
        "shelfmark": _get_string(P195),
        "collection": _get_entity_id(P194),
        "author": _get_entity_id(P354),
        "mandragoreId": _get_string(P270),
        "aemId": _get_string(P198),
        # P2 = "nature de l'élément" (manuscrit / imprimé / etc.). The QID is
        # extracted here; the human-readable label is filled in later by
        # _enrich_canvases (batch fetch) or by BiblissimaEntityView (single
        # synchronous fetch). Left as None at this stage so callers know the
        # field needs resolution before being used as a mapping key.
        "documentNatureQid": _get_entity_id(P2),
        "documentNatureLabel": None,
    }


def _get_wikibase_entity(qid, session=None):
    """Fetch a single Wikibase entity and extract relevant properties.

    Results are cached in the Django cache for 24h keyed by QID, so repeated
    lookups across requests hit the cache instead of Biblissima.
    """
    cache_key = _BIBLISSIMA_ENTITY_CACHE_KEY.format(qid=qid)
    cached = cache.get(cache_key)
    if cached is not None:
        _incr_stat("cache_hits", 1)
        return cached
    _incr_stat("cache_misses", 1)

    s = session or _build_biblissima_session()
    try:
        resp = _bib_request(
            s,
            BIBLISSIMA_WIKIBASE,
            params={
                "action": "wbgetentities",
                "ids": qid,
                "format": "json",
                "languages": "fr|en",
            },
            timeout=REQUEST_TIMEOUT,
        )
        resp.raise_for_status()
        raw = resp.json().get("entities", {}).get(qid, {})
    except Exception:
        logger.warning("Failed to fetch Wikibase entity %s", qid)
        return None

    result = _extract_entity_props(qid, raw)
    if result:
        cache.set(cache_key, result, _BIBLISSIMA_CACHE_TTL)
    return result


def _batch_get_wikibase_entities(qids, session=None):
    """Fetch multiple Wikibase entities in a single API call (max 50 per batch).

    Entities already present in the Django cache are returned without hitting
    the network; only uncached QIDs are batched into ``wbgetentities`` calls.
    Freshly fetched entities are written back to the cache for 24h.
    """
    if not qids:
        return {}

    results = {}
    uncached = []
    for qid in qids:
        cached = cache.get(_BIBLISSIMA_ENTITY_CACHE_KEY.format(qid=qid))
        if cached is not None:
            results[qid] = cached
            _incr_stat("cache_hits", 1)
        else:
            uncached.append(qid)
            _incr_stat("cache_misses", 1)

    if not uncached:
        return results

    s = session or _build_biblissima_session()
    # wbgetentities supports up to 50 IDs per call
    for i in range(0, len(uncached), 50):
        batch = uncached[i : i + 50]
        try:
            resp = _bib_request(
                s,
                BIBLISSIMA_WIKIBASE,
                params={
                    "action": "wbgetentities",
                    "ids": "|".join(batch),
                    "format": "json",
                    "languages": "fr|en",
                },
                timeout=REQUEST_TIMEOUT * 2,
            )
            resp.raise_for_status()
            entities = resp.json().get("entities", {})
            for qid in batch:
                raw = entities.get(qid, {})
                if raw and "missing" not in raw:
                    entity = _extract_entity_props(qid, raw)
                    if entity:
                        results[qid] = entity
                        cache.set(
                            _BIBLISSIMA_ENTITY_CACHE_KEY.format(qid=qid),
                            entity,
                            _BIBLISSIMA_CACHE_TTL,
                        )
        except Exception:
            logger.warning("Batch fetch failed for %s", batch)
    return results


def _resolve_collection(collection_qid, session=None):
    """Resolve a Biblissima collection entity into owner + location data.

    Follows the chain: collection → P201 (localisation) → place with Geonames ID
                        collection → P169 (partie de) → parent institution
    Returns dict with ownerLabel, ownerQid, locationLabel, locationQid, geonamesId.
    """
    if not collection_qid:
        return {}

    coll = _get_wikibase_entity(collection_qid, session=session)
    if not coll:
        return {}

    result = {
        "ownerLabel": coll.get("label", ""),
        "ownerQid": collection_qid,
    }

    s = session or requests
    coll_claims = {}
    try:
        resp = s.get(
            BIBLISSIMA_WIKIBASE,
            params={
                "action": "wbgetentities",
                "ids": collection_qid,
                "format": "json",
                "languages": "fr|en",
                "props": "claims",
            },
            timeout=REQUEST_TIMEOUT,
        )
        resp.raise_for_status()
        entity = resp.json().get("entities", {}).get(collection_qid, {})
        coll_claims = entity.get("claims", {})
    except Exception:
        logger.warning("Failed to fetch collection claims for %s", collection_qid)
        return result

    # P201 = localisation (place)
    loc_claims = coll_claims.get(P201, [])
    if loc_claims:
        loc_qid = (
            loc_claims[0]
            .get("mainsnak", {})
            .get("datavalue", {})
            .get("value", {})
            .get("id")
        )
        if loc_qid:
            loc_entity = _get_wikibase_entity(loc_qid, session=session)
            if loc_entity:
                result["locationLabel"] = loc_entity.get("label", "")
                result["locationQid"] = loc_qid

                # Get Geonames ID from the place entity
                try:
                    loc_resp = s.get(
                        BIBLISSIMA_WIKIBASE,
                        params={
                            "action": "wbgetentities",
                            "ids": loc_qid,
                            "format": "json",
                            "props": "claims",
                        },
                        timeout=REQUEST_TIMEOUT,
                    )
                    loc_resp.raise_for_status()
                    loc_data = loc_resp.json().get("entities", {}).get(loc_qid, {})
                    geo_claims = loc_data.get("claims", {}).get(P123, [])
                    if geo_claims:
                        geo_val = (
                            geo_claims[0]
                            .get("mainsnak", {})
                            .get("datavalue", {})
                            .get("value")
                        )
                        if geo_val:
                            result["geonamesId"] = str(geo_val)
                except Exception:
                    pass

    # P169 = partie de (parent institution) — for the top-level owner
    parent_claims = coll_claims.get(P169, [])
    if parent_claims:
        parent_qid = (
            parent_claims[0]
            .get("mainsnak", {})
            .get("datavalue", {})
            .get("value", {})
            .get("id")
        )
        if parent_qid:
            parent_entity = _get_wikibase_entity(parent_qid, session=session)
            if parent_entity:
                result["parentInstitutionLabel"] = parent_entity.get("label", "")
                result["parentInstitutionQid"] = parent_qid

    return result


def _parse_iiif_canvases(manifest_json):
    """Parse IIIF v2 manifest and extract canvas data."""
    results = []
    sequences = manifest_json.get("sequences", [])
    if not sequences:
        return results

    canvases = sequences[0].get("canvases", [])
    for canvas in canvases:
        metadata = {}
        for m in canvas.get("metadata", []):
            metadata[m.get("label", "")] = m.get("value")

        # Extract image service URL — ``service`` may be a dict or a list
        # of dicts depending on the provider (Gallica returns a dict,
        # e-codices/DigiVatLib/Bodleian sometimes return a list).
        image_url = None
        images = canvas.get("images", [])
        if images:
            resource = images[0].get("resource") or {}
            service = resource.get("service") or {}
            if isinstance(service, list):
                service = service[0] if service else {}
            if isinstance(service, dict):
                image_url = service.get("@id") or ""

        # Extract thumbnail. Fall back to deriving one from the IIIF Image
        # API when the manifest doesn't ship a ``thumbnail`` field — true
        # for several non-Gallica providers.
        thumbnail = None
        thumb_obj = canvas.get("thumbnail")
        if isinstance(thumb_obj, dict):
            thumbnail = thumb_obj.get("@id")
        elif isinstance(thumb_obj, str):
            thumbnail = thumb_obj
        if not thumbnail and image_url:
            thumbnail = _iiif_thumbnail_from_service(image_url)

        # Extract ARK identifiers
        portal_link = metadata.get("Sur le portail Biblissima", "")
        item_ark = _extract_ark(portal_link)
        portal_url = _extract_href(portal_link)

        manuscript_link = metadata.get("Manuscrit", "")
        manuscript_ark = _extract_ark(manuscript_link)
        manuscript_label = _strip_html(manuscript_link)
        if isinstance(manuscript_label, str):
            manuscript_label = manuscript_label.strip()

        # Extract descriptors
        descriptors_raw = metadata.get("Descripteurs", [])
        if isinstance(descriptors_raw, str):
            descriptors_raw = [descriptors_raw]
        descriptors = [_strip_html(d) for d in descriptors_raw]

        # Location
        location_raw = metadata.get("Lieu de fabrication", "")
        if isinstance(location_raw, list):
            location = ", ".join(_strip_html(location_raw))
        else:
            location = _strip_html(location_raw)

        # Resolve Component type from descriptors / canvas label.
        # The first descriptor is usually the iconographic type (e.g.
        # "Miniature", "Lettrine ornée") — fall through to the label if
        # nothing matches, which will default to "Enluminure".
        canvas_label = _strip_html(canvas.get("label", "")) or ""
        first_desc = descriptors[0] if descriptors else ""
        type_valueid, type_is_fallback = _resolve_biblissima_type(
            descriptor=first_desc, type_field=canvas_label
        )

        results.append(
            {
                "canvasId": canvas.get("@id", ""),
                "arkId": item_ark,
                "label": canvas_label,
                "thumbnail": thumbnail,
                "imageUrl": image_url,
                "manuscript": manuscript_label,
                "manuscriptArk": manuscript_ark,
                "folio": metadata.get("Feuillet / page", ""),
                "legend": _strip_html(metadata.get("Légende", "")),
                "date": metadata.get("Date", ""),
                "location": location,
                "descriptors": descriptors,
                "portalUrl": portal_url,
                "typeValueId": type_valueid,
                "typeLabel": _biblissima_type_label(type_valueid),
                "typeIsFallback": type_is_fallback,
                # Derive ifdataHash from the portal ARK so that step 3
                # enrichment can fetch the individual page and fill in
                # the fields that only the portal scrape surfaces (text,
                # rubric, descriptors, mandragore, canvas dims…).
                "ifdataHash": (
                    re.search(r"(ifdata\w+)", item_ark or "").group(1)
                    if item_ark and "ifdata" in (item_ark or "")
                    else ""
                ),
                # Fields expected by the frontend template (populated during enrichment)
                "shelfmark": "",
                "collectionLabel": "",
                "manifestUrl": "",
                "authorLabel": "",
                "authorQid": "",
                "biblissimaQid": "",
                "mandragoreId": "",
                "digitizationUrl": "",
                "locationLabel": "",
                "locationQid": "",
                "geonamesId": "",
                "parentInstitutionLabel": "",
                "parentInstitutionQid": "",
            }
        )
    return results


class BiblissimaSuggestView(View):
    """Proxy for Biblissima Wikibase entity search (autocomplete).

    Combines prefix match (wbsearchentities) and full-text search
    (CirrusSearch) for flexible matching regardless of word order.
    """

    # Wikibase type QIDs for filtering
    TYPE_FILTERS = {
        "manuscript": "Q32810",
        "descriptor": "Q304387",
    }

    @method_decorator(cache_page(1800))
    def get(self, request):
        query = request.GET.get("q", "").strip()
        if len(query) < 2:
            return JsonResponse({"results": []})

        lang = request.GET.get("lang", "fr")
        limit = int(request.GET.get("limit", 10))
        type_filter = request.GET.get("type", "")  # "manuscript" or "descriptor"
        type_qid = self.TYPE_FILTERS.get(type_filter, "")
        seen_ids = set()
        results = []

        session = _build_biblissima_session()

        # 1. Prefix match (fast, good for exact starts)
        # wbsearchentities doesn't support type filtering, so we fetch more
        # and filter by checking P2 claims afterwards
        try:
            fetch_limit = limit * 3 if type_qid else limit
            resp = _bib_request(
                session,
                BIBLISSIMA_WIKIBASE,
                params={
                    "action": "wbsearchentities",
                    "search": query,
                    "language": lang,
                    "format": "json",
                    "limit": fetch_limit,
                },
                timeout=REQUEST_TIMEOUT,
            )
            resp.raise_for_status()
            prefix_items = resp.json().get("search", [])

            if type_qid and prefix_items:
                # Batch fetch P2 claims to filter by type
                batch_ids = [item["id"] for item in prefix_items]
                type_resp = _bib_request(
                    session,
                    BIBLISSIMA_WIKIBASE,
                    params={
                        "action": "wbgetentities",
                        "ids": "|".join(batch_ids),
                        "format": "json",
                        "props": "claims",
                    },
                    timeout=REQUEST_TIMEOUT,
                )
                type_resp.raise_for_status()
                entities = type_resp.json().get("entities", {})
                valid_ids = set()
                for qid, entity in entities.items():
                    for claim in entity.get("claims", {}).get(P2, []):
                        val = (
                            claim.get("mainsnak", {})
                            .get("datavalue", {})
                            .get("value", {})
                        )
                        if isinstance(val, dict) and val.get("id") == type_qid:
                            valid_ids.add(qid)
                            break

                for item in prefix_items:
                    if item["id"] in valid_ids and item["id"] not in seen_ids:
                        seen_ids.add(item["id"])
                        results.append(
                            {
                                "id": item["id"],
                                "label": item.get("label", ""),
                                "description": item.get("description", ""),
                            }
                        )
                        if len(results) >= limit:
                            break
            else:
                for item in prefix_items:
                    if item["id"] not in seen_ids:
                        seen_ids.add(item["id"])
                        results.append(
                            {
                                "id": item["id"],
                                "label": item.get("label", ""),
                                "description": item.get("description", ""),
                            }
                        )
        except Exception:
            logger.warning("wbsearchentities failed for query=%s", query)

        # 2. Full-text search (flexible word order, partial matches)
        # CirrusSearch supports haswbstatement for native type filtering
        if len(results) < limit:
            try:
                srsearch = query
                if type_qid:
                    srsearch = f"{query} haswbstatement:P2={type_qid}"

                resp = _bib_request(
                    session,
                    BIBLISSIMA_WIKIBASE,
                    params={
                        "action": "query",
                        "list": "search",
                        "srsearch": srsearch,
                        "srnamespace": 120,
                        "format": "json",
                        "srlimit": limit,
                    },
                    timeout=REQUEST_TIMEOUT,
                )
                resp.raise_for_status()
                search_results = resp.json().get("query", {}).get("search", [])
                qids_to_fetch = [
                    r["title"].replace("Item:", "")
                    for r in search_results
                    if r["title"].replace("Item:", "") not in seen_ids
                ]

                # Batch fetch labels for full-text results
                if qids_to_fetch:
                    resp = _bib_request(
                        session,
                        BIBLISSIMA_WIKIBASE,
                        params={
                            "action": "wbgetentities",
                            "ids": "|".join(qids_to_fetch[: limit - len(results)]),
                            "format": "json",
                            "languages": f"{lang}|en",
                            "props": "labels|descriptions",
                        },
                        timeout=REQUEST_TIMEOUT,
                    )
                    resp.raise_for_status()
                    entities = resp.json().get("entities", {})
                    for qid in qids_to_fetch:
                        if len(results) >= limit:
                            break
                        entity = entities.get(qid, {})
                        labels = entity.get("labels", {})
                        label = (
                            labels.get(lang, {}).get("value")
                            or labels.get("en", {}).get("value")
                            or ""
                        )
                        descs = entity.get("descriptions", {})
                        desc = (
                            descs.get(lang, {}).get("value")
                            or descs.get("en", {}).get("value")
                            or ""
                        )
                        if label:
                            seen_ids.add(qid)
                            results.append(
                                {"id": qid, "label": label, "description": desc}
                            )
            except Exception:
                logger.warning("CirrusSearch failed for query=%s", query)

        session.close()
        return JsonResponse({"results": results})


class BiblissimaEntityView(View):
    """Proxy for fetching a single Wikibase entity with extracted properties."""

    @method_decorator(cache_page(1800))
    def get(self, request, qid):
        entity = _get_wikibase_entity(qid)
        if entity is None:
            return JsonResponse({"error": "Entity not found"}, status=404)

        # Resolve P2 nature label and pre-compute Document Type valueid
        # (helper is idempotent and used by SearchManuscriptsView too).
        _attach_document_type(entity)

        # If author is a QID, resolve its label
        if entity.get("author"):
            author_entity = _get_wikibase_entity(entity["author"])
            if author_entity:
                entity["authorLabel"] = author_entity["label"]
                entity["authorQid"] = entity["author"]

        # If collection is a QID, resolve full collection data (owner + location)
        if entity.get("collection"):
            coll_data = _resolve_collection(entity["collection"])
            entity["collectionLabel"] = coll_data.get("ownerLabel", "")
            entity["collectionQid"] = entity["collection"]
            entity["locationLabel"] = coll_data.get("locationLabel", "")
            entity["locationQid"] = coll_data.get("locationQid", "")
            entity["geonamesId"] = coll_data.get("geonamesId", "")
            entity["parentInstitutionLabel"] = coll_data.get(
                "parentInstitutionLabel", ""
            )
            entity["parentInstitutionQid"] = coll_data.get("parentInstitutionQid", "")

        return JsonResponse(entity)


class BiblissimaSearchManuscriptsView(View):
    """Search manuscripts on Biblissima with full batch enrichment.

    Replaces the N+1 pattern (suggest + N entity calls) with:
    1. Suggest (2 API calls: prefix + fulltext)
    2. Batch entity fetch (1 call for all QIDs)
    3. Batch author resolution (1 call for unique author QIDs)
    4. Deduplicated collection resolution
    5. Parallel portal date scraping
    """

    TYPE_FILTERS = BiblissimaSuggestView.TYPE_FILTERS

    @method_decorator(cache_page(1800))
    def get(self, request):
        query = request.GET.get("q", "").strip()
        if len(query) < 3:
            return JsonResponse({"results": []})

        limit = max(1, int(request.GET.get("limit", 50)))
        session = _build_biblissima_session()

        # --- Step 1: Suggest (reuse SuggestView logic inline) ---
        type_qid = self.TYPE_FILTERS.get("manuscript", "")
        seen_ids = set()
        suggest_results = []

        # Prefix search
        try:
            fetch_limit = limit * 3
            resp = _bib_request(
                session,
                BIBLISSIMA_WIKIBASE,
                params={
                    "action": "wbsearchentities",
                    "search": query,
                    "language": "fr",
                    "format": "json",
                    "limit": fetch_limit,
                },
                timeout=REQUEST_TIMEOUT,
            )
            resp.raise_for_status()
            prefix_items = resp.json().get("search", [])

            if prefix_items:
                batch_ids = [item["id"] for item in prefix_items]
                type_resp = _bib_request(
                    session,
                    BIBLISSIMA_WIKIBASE,
                    params={
                        "action": "wbgetentities",
                        "ids": "|".join(batch_ids),
                        "format": "json",
                        "props": "claims",
                    },
                    timeout=REQUEST_TIMEOUT,
                )
                type_resp.raise_for_status()
                entities = type_resp.json().get("entities", {})
                for item in prefix_items:
                    qid = item["id"]
                    for claim in entities.get(qid, {}).get("claims", {}).get(P2, []):
                        val = (
                            claim.get("mainsnak", {})
                            .get("datavalue", {})
                            .get("value", {})
                        )
                        if isinstance(val, dict) and val.get("id") == type_qid:
                            if qid not in seen_ids:
                                seen_ids.add(qid)
                                suggest_results.append(qid)
                            break
                    if len(suggest_results) >= limit:
                        break
        except Exception:
            logger.warning("Manuscript search prefix failed for: %s", query)

        # Fulltext search
        if len(suggest_results) < limit:
            try:
                srsearch = f"{query} haswbstatement:P2={type_qid}"
                resp = _bib_request(
                    session,
                    BIBLISSIMA_WIKIBASE,
                    params={
                        "action": "query",
                        "list": "search",
                        "srsearch": srsearch,
                        "srnamespace": 120,
                        "format": "json",
                        "srlimit": limit,
                    },
                    timeout=REQUEST_TIMEOUT,
                )
                resp.raise_for_status()
                for r in resp.json().get("query", {}).get("search", []):
                    qid = r["title"].replace("Item:", "")
                    if qid not in seen_ids:
                        seen_ids.add(qid)
                        suggest_results.append(qid)
                        if len(suggest_results) >= limit:
                            break
            except Exception:
                logger.warning("Manuscript search fulltext failed for: %s", query)

        if not suggest_results:
            session.close()
            return JsonResponse({"total": 0, "results": []})

        # --- Step 2: Batch entity fetch (1 call instead of N) ---
        entities = _batch_get_wikibase_entities(suggest_results, session=session)

        # --- Step 3: Batch author resolution (1 call for unique authors) ---
        author_qids = list({e["author"] for e in entities.values() if e.get("author")})
        authors = _batch_get_wikibase_entities(author_qids, session=session)

        # --- Step 4: Deduplicated collection resolution ---
        collection_qids = list(
            {e["collection"] for e in entities.values() if e.get("collection")}
        )
        collections = {}
        for coll_qid in collection_qids:
            collections[coll_qid] = _resolve_collection(coll_qid, session=session)

        session.close()

        # --- Assemble results ---
        results = []
        for qid in suggest_results:
            e = entities.get(qid)
            if not e:
                continue

            # Author
            author_qid = e.get("author")
            if author_qid and author_qid in authors:
                e["authorLabel"] = authors[author_qid].get("label", "")
                e["authorQid"] = author_qid

            # Collection
            coll_qid = e.get("collection")
            if coll_qid and coll_qid in collections:
                coll = collections[coll_qid]
                e["collectionLabel"] = coll.get("ownerLabel", "")
                e["locationLabel"] = coll.get("locationLabel", "")
                e["locationQid"] = coll.get("locationQid", "")
                e["geonamesId"] = coll.get("geonamesId", "")
                e["parentInstitutionLabel"] = coll.get("parentInstitutionLabel", "")
                e["parentInstitutionQid"] = coll.get("parentInstitutionQid", "")

            # Document Type — resolve P2 nature → label → Arches valueid
            # (idempotent; cached lookup on _get_wikibase_entity).
            _attach_document_type(e)

            results.append(e)

        return JsonResponse({"total": len(results), "results": results})


# Canvas labels from Biblissima IIIF descriptor manifests look like
# "Lettre ornée (Paris, Arsenal, 12 f.3)". The text inside parens carries
# the full manuscript context (institution + shelfmark) — much more
# distinctive than the bare ``manuscript`` field which is often just the
# shelfmark fragment ("12"). Extracting it gives the manuscript-resolution
# query a fighting chance against generic shelfmarks.
_CANVAS_MS_CONTEXT_RE = re.compile(r"\(([^)]+)\)")
_CANVAS_FOLIO_TAIL_RE = re.compile(r"\s+ff?\.\S+\s*$")


def _extract_ms_search_query(canvas):
    """Build a Wikibase-friendly search string for a canvas's parent
    manuscript. Tries the ``( …institution, shelfmark f.X )`` parenthetical
    in the canvas label first (strips the trailing folio), falls back to
    the raw ``manuscript`` field which works for distinctive shelfmarks
    like "Anglais 32" but fails on generic numerics like "12" / "579".
    """
    label = canvas.get("label") or ""
    m = _CANVAS_MS_CONTEXT_RE.search(label)
    if m:
        ctx = _CANVAS_FOLIO_TAIL_RE.sub("", m.group(1).strip())
        if ctx:
            return ctx
    return canvas.get("manuscript", "") or ""


def _enrich_canvases(canvases, session=None):
    """Enrich a list of canvases with Wikibase manuscript data in place.

    Uses the 3-phase batch strategy:
      - Phase 1: deduplicate manuscriptArk across the given canvases
      - Phase 2: cache lookup, parallel wbsearchentities for uncached
                 manuscripts, batch wbgetentities for candidate and author
                 entities. Newly resolved manuscripts are persisted to cache.
      - Phase 3: copy resolved fields onto every canvas in place.

    Only the manuscripts referenced by the given canvases are resolved, which
    makes it cheap to call on a page slice rather than on the whole result set.
    """
    if not canvases:
        return

    owned_session = session is None
    if owned_session:
        session = _build_biblissima_session()

    try:
        # Phase 1: collect unique manuscripts. The "name" we keep here is the
        # query string used to look up the manuscript in Wikibase later — we
        # extract the institution+shelfmark context from the canvas label
        # (e.g. "Paris, Arsenal, 12") rather than the bare ``manuscript``
        # field which is often just the shelfmark fragment.
        unique_manuscripts = {}
        for canvas in canvases:
            ms_ark = canvas.get("manuscriptArk")
            if not ms_ark:
                continue
            ark_hash = ms_ark.replace("ark:/43093/", "")
            if ark_hash and ark_hash not in unique_manuscripts:
                unique_manuscripts[ark_hash] = _extract_ms_search_query(canvas)

        resolved_manuscripts = {}
        to_resolve = {}

        # Phase 2a: Django cache lookup per manuscript
        for ark_hash, ms_name in unique_manuscripts.items():
            cached = cache.get(
                _BIBLISSIMA_MANUSCRIPT_CACHE_KEY.format(ark_hash=ark_hash)
            )
            if cached is not None:
                resolved_manuscripts[ark_hash] = cached
                _incr_stat("cache_hits", 1)
            else:
                to_resolve[ark_hash] = ms_name
                _incr_stat("cache_misses", 1)

        # Phase 2b: parallel CirrusSearch fulltext lookup for uncached
        # manuscripts. We use ``action=query&list=search`` rather than
        # ``wbsearchentities`` because the latter only matches against
        # labels/aliases as a prefix and silently returns garbage for the
        # bare-shelfmark labels that the IIIF manifest provides ("12",
        # "579"). The richer ``ms_name`` extracted from the canvas label
        # (e.g. "Paris, Arsenal, 12") is distinctive enough that fulltext
        # search returns the correct entity in the top results, and the
        # Phase 2d ``portalHash == ark_hash`` filter rejects any false
        # positive — so reconciliation is done without scraping.
        def _search_candidates(item):
            ark_hash, ms_name = item
            if not ms_name:
                return ark_hash, []
            try:
                resp = _bib_request(
                    session,
                    BIBLISSIMA_WIKIBASE,
                    params={
                        "action": "query",
                        "list": "search",
                        "srsearch": ms_name,
                        "srnamespace": 120,
                        "format": "json",
                        "srlimit": 5,
                    },
                    timeout=REQUEST_TIMEOUT,
                )
                resp.raise_for_status()
                hits = resp.json().get("query", {}).get("search", [])
                qids = []
                for hit in hits:
                    title = hit.get("title", "")
                    qid = title.split(":")[-1] if ":" in title else title
                    if qid:
                        qids.append(qid)
                return ark_hash, qids
            except Exception:
                logger.warning("CirrusSearch failed for %s", ms_name)
                return ark_hash, []

        candidates_by_ark_hash = {}
        if to_resolve:
            max_workers = min(6, len(to_resolve))
            with ThreadPoolExecutor(max_workers=max_workers) as executor:
                for ark_hash, candidate_qids in executor.map(
                    _search_candidates, to_resolve.items()
                ):
                    candidates_by_ark_hash[ark_hash] = candidate_qids

        # Phase 2c: batch-fetch all candidate entities in one go
        all_candidate_qids = list(
            {qid for qids in candidates_by_ark_hash.values() for qid in qids}
        )
        entities_by_qid = _batch_get_wikibase_entities(
            all_candidate_qids, session=session
        )

        # Phase 2d: match each manuscript to its QID via portalHash, and
        # collect both author and nature (P2) QIDs for the batch fetch.
        author_qids = set()
        nature_qids = set()
        for ark_hash, candidate_qids in candidates_by_ark_hash.items():
            ms_data = {}
            for qid in candidate_qids:
                entity = entities_by_qid.get(qid)
                if entity and entity.get("portalHash") == ark_hash:
                    ms_data = dict(entity)
                    if ms_data.get("author"):
                        author_qids.add(ms_data["author"])
                    if ms_data.get("documentNatureQid"):
                        nature_qids.add(ms_data["documentNatureQid"])
                    break
            resolved_manuscripts[ark_hash] = ms_data

        # Phase 2e: batch-fetch authors and natures together (single round-trip).
        # Cached natures (which is most of them — Biblissima only uses ~5
        # distinct nature concepts) hit the Django cache and don't go to
        # Biblissima at all.
        secondary_qids = list(author_qids | nature_qids)
        secondaries_by_qid = (
            _batch_get_wikibase_entities(secondary_qids, session=session)
            if secondary_qids
            else {}
        )

        # Phase 2f: attach author and nature labels, pre-resolve the Arches
        # Document-Type valueid once per manuscript, and persist newly-resolved
        # manuscripts to cache so subsequent enrichments are zero-cost. Doing
        # the type resolution here (vs. per-canvas in phase 3) avoids calling
        # the resolver N times for an N-page manuscript with identical nature
        # label across canvases.
        for ark_hash in to_resolve:
            ms_data = resolved_manuscripts.get(ark_hash, {})
            if ms_data:
                author_qid = ms_data.get("author")
                if author_qid and author_qid in secondaries_by_qid:
                    author = secondaries_by_qid[author_qid]
                    ms_data["authorLabel"] = author.get("label", "")
                    ms_data["authorQid"] = author_qid
                nature_qid = ms_data.get("documentNatureQid")
                if nature_qid and nature_qid in secondaries_by_qid:
                    nature = secondaries_by_qid[nature_qid]
                    ms_data["documentNatureLabel"] = nature.get("label", "") or None
                type_valueid, type_is_fallback = _resolve_biblissima_document_type(
                    ms_data.get("documentNatureLabel")
                )
                ms_data["documentTypeValueId"] = type_valueid
                ms_data["documentTypeIsFallback"] = type_is_fallback
            cache.set(
                _BIBLISSIMA_MANUSCRIPT_CACHE_KEY.format(ark_hash=ark_hash),
                ms_data,
                _BIBLISSIMA_CACHE_TTL,
            )

        # Phase 2g: resolve collection chains (location + parent institution)
        # for each unique collection QID, so downstream consumers get
        # collectionLabel / locationLabel / parentInstitutionLabel.
        collection_data = {}
        collection_qids = {
            ms.get("collection")
            for ms in resolved_manuscripts.values()
            if ms.get("collection")
        }
        for coll_qid in collection_qids:
            try:
                collection_data[coll_qid] = _resolve_collection(
                    coll_qid, session=session
                )
            except Exception:
                logger.warning("Collection resolution failed for %s", coll_qid)

        # Phase 3: decorate every canvas from the resolved manuscript map.
        # All manuscript-level fields that downstream consumers need (dep
        # resolution for Places/Groups, identifier creation, etc.) must be
        # copied here — _illuminationToResult in the search-step JS reads
        # entityData.* for the manuscript scrape path, but the IIIF
        # descriptor search path gets its data entirely from this enrichment.
        for canvas in canvases:
            ms_ark = canvas.get("manuscriptArk")
            if not ms_ark:
                continue
            ark_hash = ms_ark.replace("ark:/43093/", "")
            ms_data = resolved_manuscripts.get(ark_hash) or {}
            # Prefer the full Wikibase entity label (e.g. "Paris. Bibliothèque
            # de l'Arsenal, 12") over the raw IIIF metadata value, which is
            # often just the shelfmark fragment ("12") for Arsenal/BnF
            # manifests where Biblissima only inlines the shelfmark text in
            # the <a>Manuscrit</a> link.
            if ms_data.get("label"):
                canvas["manuscript"] = ms_data["label"]
            canvas["manifestUrl"] = ms_data.get("manifestUrl")
            canvas["authorLabel"] = ms_data.get("authorLabel")
            canvas["authorQid"] = ms_data.get("authorQid")
            canvas["biblissimaQid"] = ms_data.get("biblissimaQid")
            canvas["shelfmark"] = ms_data.get("shelfmark")
            canvas["mandragoreId"] = ms_data.get("mandragoreId")
            # Institution / location chain from the collection resolution.
            coll_qid = ms_data.get("collection")
            coll = collection_data.get(coll_qid) or {} if coll_qid else {}
            canvas["collectionLabel"] = coll.get("ownerLabel", "")
            canvas["collectionQid"] = coll.get("ownerQid", "")
            canvas["locationLabel"] = coll.get("locationLabel", "")
            canvas["locationQid"] = coll.get("locationQid", "")
            canvas["geonamesId"] = coll.get("geonamesId", "")
            canvas["parentInstitutionLabel"] = coll.get("parentInstitutionLabel", "")
            canvas["parentInstitutionQid"] = coll.get("parentInstitutionQid", "")
            # Document Type — pre-resolved once in phase 2f for fresh manuscripts;
            # for cache-hit manuscripts that pre-date this change we resolve here
            # as a one-time fallback. Falls back to MANUSCRIT with
            # is_fallback=True if the nature label is missing or unknown.
            canvas["documentNatureLabel"] = ms_data.get("documentNatureLabel")
            if "documentTypeValueId" in ms_data:
                canvas["documentTypeValueId"] = ms_data["documentTypeValueId"]
                canvas["documentTypeIsFallback"] = ms_data["documentTypeIsFallback"]
            else:
                type_valueid, type_is_fallback = _resolve_biblissima_document_type(
                    ms_data.get("documentNatureLabel")
                )
                canvas["documentTypeValueId"] = type_valueid
                canvas["documentTypeIsFallback"] = type_is_fallback
    finally:
        if owned_session:
            session.close()


def _normalize_descriptors(descriptors):
    """Normalize a raw descriptors query string to the canonical desc-prefixed list."""
    hash_list = [h.strip() for h in descriptors.split(",") if h.strip()]
    known_prefixes = ("pdata", "mdata", "oedata", "cdata", "ldata", "ifdata")
    normalized = []
    for h in hash_list:
        if h.startswith("desc"):
            normalized.append(h)
            continue
        base = h
        for prefix in known_prefixes:
            if h.startswith(prefix):
                base = h[len(prefix) :]
                break
        normalized.append(f"desc{base}")
    return normalized


def _fetch_biblissima_canvases(desc_hashes, session):
    """Fetch the IIIF manifest from Biblissima and parse its canvases.

    Goes through ``_bib_request`` so the outbound call honors the concurrency
    semaphore and is counted in the stats counters like every other Biblissima
    call. The session already carries the shared User-Agent header.
    """
    headers = {"Accept": "application/ld+json, application/json"}
    if len(desc_hashes) == 1:
        url = f"{BIBLISSIMA_IIIF_MANIFEST}/ark:/43093/{desc_hashes[0]}"
        resp = _bib_request(session, url, headers=headers, timeout=IIIF_REQUEST_TIMEOUT)
    else:
        descriptor_parts = ",".join(f"AND|{h}" for h in desc_hashes)
        resp = _bib_request(
            session,
            BIBLISSIMA_IIIF_MANIFEST,
            params={"descriptors": descriptor_parts},
            headers=headers,
            timeout=IIIF_REQUEST_TIMEOUT,
        )
    resp.raise_for_status()
    return _parse_iiif_canvases(resp.json())


# Raw parsed canvases are cached server-side under this key to avoid
# refetching the (big, slow) IIIF manifest for every paginated request.
_BIBLISSIMA_RAW_SEARCH_CACHE_KEY = "biblissima:search:raw:{descriptors_key}"
_BIBLISSIMA_RAW_SEARCH_TTL = 3600  # 1h

_DEFAULT_SEARCH_PAGE_SIZE = 50
_MAX_SEARCH_PAGE_SIZE = 200


class BiblissimaSearchView(View):
    """Search Biblissima via IIIF manifest by iconographic descriptors.

    Paginated to enable progressive loading: the frontend fetches page 1 first
    (incurs the one-time IIIF manifest fetch), then continues with pages 2..N
    in the background while the user is already interacting with page 1.

    Raw parsed canvases are cached server-side for 1h under the normalized
    descriptor key, so paginated follow-up requests skip the IIIF fetch and
    only enrich the requested slice.
    """

    @method_decorator(cache_page(3600))
    def get(self, request):
        descriptors = request.GET.get("descriptors", "").strip()
        if not descriptors:
            return JsonResponse({"error": "descriptors parameter required"}, status=400)

        try:
            page = max(1, int(request.GET.get("page", 1)))
        except ValueError:
            page = 1
        try:
            page_size = int(request.GET.get("page_size", _DEFAULT_SEARCH_PAGE_SIZE))
        except ValueError:
            page_size = _DEFAULT_SEARCH_PAGE_SIZE
        page_size = max(1, min(page_size, _MAX_SEARCH_PAGE_SIZE))

        desc_hashes = _normalize_descriptors(descriptors)
        if not desc_hashes:
            return JsonResponse({"error": "descriptors parameter required"}, status=400)

        descriptors_key = ",".join(sorted(desc_hashes))
        raw_cache_key = _BIBLISSIMA_RAW_SEARCH_CACHE_KEY.format(
            descriptors_key=descriptors_key
        )

        session = _build_biblissima_session()
        try:
            all_canvases = cache.get(raw_cache_key)
            if all_canvases is None:
                try:
                    all_canvases = _fetch_biblissima_canvases(desc_hashes, session)
                except Exception as exc:
                    return _biblissima_upstream_error(exc, "Biblissima IIIF search")
                cache.set(raw_cache_key, all_canvases, _BIBLISSIMA_RAW_SEARCH_TTL)

            total = len(all_canvases)
            total_pages = max(1, (total + page_size - 1) // page_size) if total else 0

            start = (page - 1) * page_size
            end = start + page_size
            page_canvases = all_canvases[start:end]

            # Enrich in place on the slice we're about to return.
            _enrich_canvases(page_canvases, session=session)
        finally:
            session.close()

        return JsonResponse(
            {
                "total": total,
                "page": page,
                "page_size": page_size,
                "total_pages": total_pages,
                "results": page_canvases,
            }
        )


class BiblissimaCheckDuplicatesView(View):
    """Find potential duplicate resources in Arches using flexible matching.

    For each item, runs multiple search strategies and returns ranked suggestions.
    The user decides whether a match is a true duplicate or not.
    """

    def post(self, request):
        import json

        try:
            body = json.loads(request.body)
        except (json.JSONDecodeError, ValueError):
            return JsonResponse({"error": "Invalid JSON"}, status=400)

        items = body.get("items", [])
        graph_id = body.get("graphId", DOCUMENT_GRAPH_ID)

        if not items:
            return JsonResponse({"results": []})

        from arches.app.search.search_engine_factory import SearchEngineInstance

        se = SearchEngineInstance
        results = []

        for idx, item in enumerate(items):
            ark_id = item.get("arkId", "")
            label = item.get("label", "")
            shelfmark = item.get("shelfmark", "")
            qid = item.get("biblissimaQid", "")

            suggestions = []
            seen_ids = set()

            # Strategy 1: Search by identifiers in tiles
            # Build all possible search tokens from Biblissima data
            search_tokens = set()
            if ark_id:
                search_tokens.add(ark_id)
                # Hash without ark: prefix
                ark_hash = ark_id.replace("ark:/43093/", "")
                if ark_hash != ark_id:
                    search_tokens.add(ark_hash)
            if qid:
                search_tokens.add(qid)
                # Also match full URL form used in Arches identifiers
                search_tokens.add(f"https://data.biblissima.fr/entity/{qid}")

            portal_hash = item.get("portalHash", "")
            if portal_hash:
                search_tokens.add(portal_hash)
                search_tokens.add(f"ark:/43093/{portal_hash}")

            manifest_url = item.get("manifestUrl", "")
            if manifest_url:
                search_tokens.add(manifest_url)

            if search_tokens:
                id_ng = (
                    DOC_IDENTIFIER_NG
                    if graph_id == DOCUMENT_GRAPH_ID
                    else COMP_IDENTIFIER_NG
                )
                id_node = (
                    DOC_IDENTIFIER_VALUE
                    if graph_id == DOCUMENT_GRAPH_ID
                    else COMP_IDENTIFIER_VALUE
                )
                try:
                    matching_tiles = Tile.objects.filter(
                        nodegroup_id=id_ng,
                        resourceinstance__graph_id=graph_id,
                    )
                    for tile in matching_tiles:
                        raw_value = tile.data.get(id_node, "")
                        # Handle i18n dict format
                        if isinstance(raw_value, dict):
                            tile_value = ""
                            for lang in ("en", "fr", "de", "es", "it"):
                                v = raw_value.get(lang, {})
                                if isinstance(v, dict) and v.get("value"):
                                    tile_value = v["value"].strip()
                                    break
                        else:
                            tile_value = str(raw_value).strip() if raw_value else ""

                        if not tile_value:
                            continue

                        # Check if tile value matches any search token
                        # or if any search token is contained in the tile value
                        matched = False
                        for token in search_tokens:
                            if (
                                token == tile_value
                                or token in tile_value
                                or tile_value in token
                            ):
                                matched = True
                                break

                        if matched:
                            rid = str(tile.resourceinstance_id)
                            if rid not in seen_ids:
                                seen_ids.add(rid)
                                dn = self._get_resource_name(rid)
                                suggestions.append(
                                    {
                                        "resourceId": rid,
                                        "displayname": dn,
                                        "matchType": "identifier",
                                        "matchValue": tile_value,
                                        "confidence": "high",
                                    }
                                )
                except Exception:
                    logger.warning("Tile identifier search failed for item %d", idx)

            # Strategies 2 and 3 are skipped only for Components. Components
            # share the parent manuscript's shelfmark, and their displayname
            # embeds that shelfmark too — so an ES match on either field
            # returns sibling-illumination false positives (e.g. "Aggée et
            # Dieu" f.328v matching "Abdias prophétisant" f.323v just because
            # both belong to BnF Latin 40). For Components, only the ARK
            # ifdata identifier (strategy 1) is unique per illumination.
            # Documents AND non-graph dependencies (Place / Person / Group,
            # resolved separately via the dependency-resolution flow) all
            # need label-based ES matching.
            if graph_id != COMPONENT_GRAPH_ID:
                # Strategy 2: ES search by shelfmark (nested strings.string field)
                if shelfmark:
                    self._es_string_search(
                        se, graph_id, shelfmark, "shelfmark", seen_ids, suggestions
                    )

                # Strategy 3: ES search by label/displayname
                if label and len(suggestions) < 3:
                    self._es_string_search(
                        se, graph_id, label, "displayname", seen_ids, suggestions
                    )

            results.append(
                {
                    "index": idx,
                    "key": ark_id or label,
                    "suggestions": suggestions[:5],
                }
            )

        return JsonResponse({"results": results})

    @staticmethod
    def _get_resource_name(resource_id):
        """Get the display name for a resource."""
        try:
            ri = ResourceInstance.objects.get(resourceinstanceid=resource_id)
            return str(ri.name) if ri.name else str(ri)
        except ResourceInstance.DoesNotExist:
            return ""

    @staticmethod
    def _extract_es_displayname(hit):
        """Extract display name from an ES hit."""
        dn = hit.get("_source", {}).get("displayname", [])
        if isinstance(dn, list) and dn:
            return dn[0].get("value", "") if isinstance(dn[0], dict) else str(dn[0])
        if isinstance(dn, str):
            return dn
        return ""

    def _es_string_search(
        self, se, graph_id, search_term, match_type, seen_ids, suggestions
    ):
        """Search ES using nested strings.string field (analyzed text)."""
        try:
            query = {
                "query": {
                    "bool": {
                        "must": [
                            {"term": {"graph_id": graph_id}},
                            {
                                "nested": {
                                    "path": "strings",
                                    "query": {
                                        "bool": {
                                            "should": [
                                                {
                                                    "match_phrase": {
                                                        "strings.string": {
                                                            "query": search_term,
                                                            "boost": 3,
                                                        }
                                                    }
                                                },
                                                {
                                                    "match": {
                                                        "strings.string": {
                                                            "query": search_term,
                                                            "operator": "and",
                                                        }
                                                    }
                                                },
                                            ],
                                            "minimum_should_match": 1,
                                        }
                                    },
                                }
                            },
                        ],
                    }
                },
                "_source": ["displayname"],
                "size": 3,
            }
            es_results = se.search(index="resources", body=query)
            for hit in es_results.get("hits", {}).get("hits", []):
                rid = hit["_id"]
                if rid not in seen_ids:
                    score = hit.get("_score", 0)
                    seen_ids.add(rid)
                    suggestions.append(
                        {
                            "resourceId": rid,
                            "displayname": self._extract_es_displayname(hit),
                            "matchType": match_type,
                            "matchValue": search_term,
                            "confidence": (
                                "high"
                                if score > 8
                                else "medium" if score > 3 else "low"
                            ),
                        }
                    )
        except Exception:
            logger.debug("ES %s search no results for: %s", match_type, search_term)


BIBLISSIMA_PORTAL = "https://portail.biblissima.fr/fr/ark:/43093"
BIBLISSIMA_PORTAL_EN = "https://portail.biblissima.fr/en/ark:/43093"


# Map Biblissima illumination type/typologie/descriptor strings to Arches Type of Component valueids.
# Keys are lowercase. Matching is done with startswith() to handle variants like "initiale ornée (1)".
BIBLISSIMA_TYPE_MAPPING = {
    "initiale ornée": "31158e76-817a-447d-a40c-3963731296a8",  # lettrine/initial
    "initiale filigranée": "31158e76-817a-447d-a40c-3963731296a8",  # lettrine/initial
    "initiale historiée": "31158e76-817a-447d-a40c-3963731296a8",  # lettrine/initial
    "initiale animée": "31158e76-817a-447d-a40c-3963731296a8",  # lettrine/initial
    "initiale zoomorphe": "31158e76-817a-447d-a40c-3963731296a8",  # lettrine/initial
    "initiale anthropomorphe": "31158e76-817a-447d-a40c-3963731296a8",
    "initiale de couleur": "31158e76-817a-447d-a40c-3963731296a8",
    "initiale": "31158e76-817a-447d-a40c-3963731296a8",
    "lettrine": "31158e76-817a-447d-a40c-3963731296a8",
    "lettre ornée": "2f5df709-4f32-40b4-8858-d0d54ba25d61",  # decorated letter
    "lettre cadelée": "2f5df709-4f32-40b4-8858-d0d54ba25d61",
    "lettre or": "2f5df709-4f32-40b4-8858-d0d54ba25d61",
    "miniature": "63bc98e3-57de-48fc-a656-8d6f9a9acf40",  # miniature
    "page décorée": "4063b4aa-c50b-4101-947c-d8094eed6e25",  # Decoration
    "décor": "4063b4aa-c50b-4101-947c-d8094eed6e25",
    "bordure": "4063b4aa-c50b-4101-947c-d8094eed6e25",
    "bandeau": "4063b4aa-c50b-4101-947c-d8094eed6e25",
    "encadrement": "4063b4aa-c50b-4101-947c-d8094eed6e25",
    "frontispice": "0805a584-1395-48df-8e84-4ae4b25cdeae",  # frontispiece
    "vignette": "29167061-2645-4d86-8f30-9206c1f83297",  # vignette
    "photographie": "85e458af-0292-4ecb-84b9-5715071d45e1",  # photography
    "filigrane": "c3168cc7-23d3-4ddb-9eac-38383b852f5a",  # watermark
    "planche": "36a20d43-f316-4d0f-bf58-ec8a2cb71d0a",  # board
    "enluminure": "3ecd8040-7c4b-4b1d-88f7-379297358f66",  # illumination (default)
}

# Default fallback when no type mapping matches
BIBLISSIMA_TYPE_DEFAULT = "3ecd8040-7c4b-4b1d-88f7-379297358f66"  # illumination

# Human-readable labels for each target valueid. Used by the import workflow
# so the per-item type badge can show a real concept name (e.g. "Enluminure")
# instead of a generic "default" string. Labels are in French to match the
# underlying concept collection.
BIBLISSIMA_TYPE_VALUEID_LABELS = {
    "31158e76-817a-447d-a40c-3963731296a8": "Lettrine",
    "2f5df709-4f32-40b4-8858-d0d54ba25d61": "Lettre ornée",
    "63bc98e3-57de-48fc-a656-8d6f9a9acf40": "Miniature",
    "4063b4aa-c50b-4101-947c-d8094eed6e25": "Décor",
    "0805a584-1395-48df-8e84-4ae4b25cdeae": "Frontispice",
    "29167061-2645-4d86-8f30-9206c1f83297": "Vignette",
    "85e458af-0292-4ecb-84b9-5715071d45e1": "Photographie",
    "c3168cc7-23d3-4ddb-9eac-38383b852f5a": "Filigrane",
    "36a20d43-f316-4d0f-bf58-ec8a2cb71d0a": "Planche",
    "3ecd8040-7c4b-4b1d-88f7-379297358f66": "Enluminure",
}


# ----------------------------------------------------------------------------
# Document Type mapping — Biblissima 'nature de l'élément' (P2 label) →
# Arches Document Type valueid. Sample of 1500 random Biblissima items shows
# ~96% are some flavour of 'manuscrit' and ~7.5% are 'imprimé'; the remainder
# is <1% (estampe, …) for which AGORHA has no direct equivalent — those fall
# through to the default and the UI shows a "needs review" badge so the
# analyst can correct the type inline.
# Mapping is keyed by lowercase canonical label, not QID, for two reasons:
#   • robust if Biblissima reorganises entities under different QIDs
#   • mirrors _resolve_biblissima_type (Component) which also keys on labels
# ----------------------------------------------------------------------------
VALUEID_MANUSCRIT = "30931466-b4e0-4527-ac93-b7290e80084c"
VALUEID_TEXTE_IMPRIME = "feff36de-e9d0-4723-b00b-142dc19df8ed"

BIBLISSIMA_DOCUMENT_NATURE_MAP = {
    "manuscrit": VALUEID_MANUSCRIT,
    "manuscrits en plusieurs volumes": VALUEID_MANUSCRIT,
    "unité codicologique": VALUEID_MANUSCRIT,
    "imprimé": VALUEID_TEXTE_IMPRIME,
    "texte imprimé": VALUEID_TEXTE_IMPRIME,
}

DOCUMENT_NATURE_DEFAULT = VALUEID_MANUSCRIT  # 96% Biblissima is manuscrit

# Human-readable labels for the resolved valueids — used by the badge UI
# (mirrors BIBLISSIMA_TYPE_VALUEID_LABELS for Components).
BIBLISSIMA_DOCUMENT_TYPE_VALUEID_LABELS = {
    VALUEID_MANUSCRIT: "Manuscrit",
    VALUEID_TEXTE_IMPRIME: "Texte imprimé",
}


def _resolve_biblissima_document_type(nature_label):
    """Map Biblissima 'nature de l'élément' label → Arches Document Type valueid.

    Returns (valueid, is_fallback). is_fallback=True signals the UI to flag
    the value as "needs review" (same convention as Component types).
    """
    if nature_label:
        # Exact-match (vs. startswith for Components): nature labels are canonical
        # and have no variant suffixes. Switch to startswith if that ever changes.
        normalized = nature_label.strip().lower()
        if normalized in BIBLISSIMA_DOCUMENT_NATURE_MAP:
            return BIBLISSIMA_DOCUMENT_NATURE_MAP[normalized], False
        logger.warning(
            "Unknown Biblissima document nature: %r — falling back",
            nature_label,
        )
    return DOCUMENT_NATURE_DEFAULT, True


def _attach_document_type(entity, session=None):
    """Resolve P2 nature label and attach Document Type valueid in place.

    Idempotent: safe to call on an entity that already has the fields. Used
    by both BiblissimaEntityView and BiblissimaSearchManuscriptsView so the
    two flows return the same payload shape to the frontend. The label
    lookup is a single cached call (24h TTL on _get_wikibase_entity).
    """
    if entity is None:
        return
    nature_qid = entity.get("documentNatureQid")
    nature_label = entity.get("documentNatureLabel")
    if nature_qid and not nature_label:
        nature_entity = _get_wikibase_entity(nature_qid, session=session)
        if nature_entity:
            nature_label = nature_entity.get("label") or None
            entity["documentNatureLabel"] = nature_label
    type_valueid, type_is_fallback = _resolve_biblissima_document_type(nature_label)
    entity["documentTypeValueId"] = type_valueid
    entity["documentTypeIsFallback"] = type_is_fallback


def _biblissima_type_label(valueid):
    """Return the display label for a resolved Component type valueid."""
    return BIBLISSIMA_TYPE_VALUEID_LABELS.get(valueid, "")


def _resolve_biblissima_type(typologie="", descriptor="", type_field=""):
    """Resolve a Biblissima illumination to an Arches Type of Component valueid.

    Priority: typologie > descriptor > type_field > default.
    Uses startswith matching for variants (e.g. "initiale ornée (1)").

    Returns ``(valueid, is_fallback)``. ``is_fallback`` is True only when no
    input term matched the mapping at all — distinct from the case where an
    input explicitly says "Enluminure" (which matches the mapping even
    though it happens to share the same valueid as the generic default).
    """
    for term in (typologie, descriptor, type_field):
        if not term:
            continue
        normalized = term.lower().strip()
        # Remove trailing numbering like "(1)", "(2)"
        normalized = re.sub(r"\s*\(\d+\)\s*$", "", normalized)
        # Try exact match first
        if normalized in BIBLISSIMA_TYPE_MAPPING:
            return BIBLISSIMA_TYPE_MAPPING[normalized], False
        # Try startswith match
        for key, valueid in BIBLISSIMA_TYPE_MAPPING.items():
            if normalized.startswith(key):
                return valueid, False
    return BIBLISSIMA_TYPE_DEFAULT, True


def _parse_manuscript_illuminations(html):
    """Parse a Biblissima portal manuscript page and return the illumination list.

    HTML structure (section#illuminations):

        <ul class="list-inline-block-container">
            <li>
                <span class="fa fa-picture-o" ...></span>  <!-- optional icon -->
                <a href=".../ark:/43093/ifdataXXX">Full label with manuscript…</a>
            </li>
            …
        </ul>

    We iterate over every ``<a>`` link pointing at an ``ifdata`` ARK and
    detect the presence of a sibling ``.fa-picture-o`` icon inside the same
    ``<li>`` to flag whether a digitization is available. Dedupes by
    ifdata hash in case the same illumination is rendered twice.
    """
    tree = lxml_html.fromstring(html)
    results = []
    seen_hashes = set()

    for a in tree.xpath('.//a[contains(@href, "/ark:/43093/ifdata")]'):
        href = a.get("href", "")
        m = re.search(r"(ifdata\w+)", href)
        if not m:
            continue
        ifdata_hash = m.group(1)
        if ifdata_hash in seen_hashes:
            continue
        seen_hashes.add(ifdata_hash)

        label = " ".join(a.text_content().split()).strip()

        desc_match = re.match(r"^([^(]+)", label)
        descriptor = desc_match.group(1).strip() if desc_match else label

        folio_match = re.search(r"\bf\.?\s*(\d+\w*)\)?$", label)
        folio = folio_match.group(1) if folio_match else ""

        # "Has image" → look for a `fa-picture-o` icon in the enclosing <li>
        # (or up to 3 ancestors if the portal nests things deeper in future).
        has_image = False
        parent = a.getparent()
        for _ in range(3):
            if parent is None:
                break
            if parent.xpath('.//*[contains(@class, "fa-picture-o")]'):
                has_image = True
                break
            parent = parent.getparent()

        type_valueid, type_is_fallback = _resolve_biblissima_type(descriptor=descriptor)

        results.append(
            {
                "ifdataHash": ifdata_hash,
                "arkId": f"ark:/43093/{ifdata_hash}",
                "label": label,
                "descriptor": descriptor,
                "folio": folio,
                "hasImage": has_image,
                "portalUrl": f"{BIBLISSIMA_PORTAL}/{ifdata_hash}",
                "typeValueId": type_valueid,
                "typeLabel": _biblissima_type_label(type_valueid),
                "typeIsFallback": type_is_fallback,
            }
        )
    return results


# Raw parsed illumination lists are cached server-side under this key to
# avoid re-scraping the (slow) portal HTML page on every paginated request.
_BIBLISSIMA_RAW_ILLUMINATIONS_CACHE_KEY = "biblissima:illuminations:raw:{portal_hash}"
_BIBLISSIMA_RAW_ILLUMINATIONS_TTL = 3600  # 1h

_DEFAULT_ILLUMINATIONS_PAGE_SIZE = 20
_MAX_ILLUMINATIONS_PAGE_SIZE = 200


class BiblissimaManuscriptIlluminationsView(View):
    """Scrape Biblissima portal page for a manuscript to list its illuminations.

    Paginated like BiblissimaSearchView so the frontend can render the first
    page quickly and stream the rest in the background with a progress bar.
    Raw parsed illuminations are cached for 1h under the manuscript portal
    hash so follow-up page requests skip the (slow) HTML scrape.
    """

    @method_decorator(cache_page(3600))
    def get(self, request):
        portal_hash = request.GET.get("portalHash", "").strip()
        if not portal_hash:
            return JsonResponse({"error": "portalHash required"}, status=400)

        try:
            page = max(1, int(request.GET.get("page", 1)))
        except ValueError:
            page = 1
        try:
            page_size = int(
                request.GET.get("page_size", _DEFAULT_ILLUMINATIONS_PAGE_SIZE)
            )
        except ValueError:
            page_size = _DEFAULT_ILLUMINATIONS_PAGE_SIZE
        page_size = max(1, min(page_size, _MAX_ILLUMINATIONS_PAGE_SIZE))

        raw_cache_key = _BIBLISSIMA_RAW_ILLUMINATIONS_CACHE_KEY.format(
            portal_hash=portal_hash
        )
        all_illuminations = cache.get(raw_cache_key)

        if all_illuminations is None:
            session = _build_biblissima_session()
            try:
                try:
                    resp = _bib_request(
                        session,
                        f"{BIBLISSIMA_PORTAL}/{portal_hash}",
                        timeout=PORTAL_REQUEST_TIMEOUT,
                    )
                    resp.raise_for_status()
                    html = resp.text
                except Exception as exc:
                    return _biblissima_upstream_error(
                        exc, f"Biblissima portal fetch ({portal_hash})"
                    )
            finally:
                session.close()

            all_illuminations = _parse_manuscript_illuminations(html)
            cache.set(
                raw_cache_key, all_illuminations, _BIBLISSIMA_RAW_ILLUMINATIONS_TTL
            )

        total = len(all_illuminations)
        total_pages = max(1, (total + page_size - 1) // page_size) if total else 0

        start = (page - 1) * page_size
        end = start + page_size
        page_illuminations = all_illuminations[start:end]

        return JsonResponse(
            {
                "total": total,
                "page": page,
                "page_size": page_size,
                "total_pages": total_pages,
                "results": page_illuminations,
            }
        )


def _fetch_canvas_dimensions(manifest_url, folio, session):
    """Fetch a source IIIF manifest and return the target canvas info.

    Canvas matching is done by **folio** — Biblissima portal pages expose
    the folio label (e.g. ``"323v"``) and IIIF manifests carry it in
    ``canvas.label``, so this join works for any IIIF-conformant provider
    (Gallica, e-codices, DigiVatLib, Bodleian, Morgan, …) without
    per-provider special casing. First canvas is used as a last-resort
    fallback so the Location annotation still lands on *some* page rather
    than failing silently.

    Also extracts the image service URL from
    ``canvas.images[0].resource.service`` and derives a provider-agnostic
    thumbnail URL via the IIIF Image API pattern
    (``/full/200,/0/default.jpg``).

    Cached under ``(manifest_url, folio)``.

    Returns::

        {
            "canvasId": str,
            "canvasWidth": int,
            "canvasHeight": int,
            "thumbnailUrl": str,   # empty if the canvas has no image service
        }

    or ``{}`` on any failure.
    """
    if not manifest_url:
        return {}
    cache_key = f"biblissima:manifest-canvas:{manifest_url}:{folio or ''}"
    cached = cache.get(cache_key)
    if cached is not None:
        return cached

    try:
        resp = _bib_request(
            session,
            manifest_url,
            headers={"Accept": "application/ld+json, application/json"},
            timeout=IIIF_REQUEST_TIMEOUT,
        )
        resp.raise_for_status()
        manifest = resp.json()
    except Exception as exc:
        logger.warning("Biblissima manifest fetch failed for %s: %s", manifest_url, exc)
        return {}

    folio_norm = (folio or "").strip().lstrip("f.").strip().lower()

    target = None
    for seq in manifest.get("sequences", []):
        for canvas in seq.get("canvases", []) or []:
            if not folio_norm:
                continue
            raw_label = canvas.get("label", "") or ""
            if isinstance(raw_label, list):
                raw_label = " ".join(str(x) for x in raw_label)
            if folio_norm in str(raw_label).lower():
                target = canvas
                break
        if target:
            break

    if target is None:
        seqs = manifest.get("sequences") or []
        if seqs:
            canvases = seqs[0].get("canvases") or []
            if canvases:
                target = canvases[0]
                logger.info(
                    "Biblissima canvas match fallback to first canvas for "
                    "manifest=%s folio=%r",
                    manifest_url,
                    folio,
                )
    if target is None:
        logger.warning("Biblissima manifest has no canvases: %s", manifest_url)
        return {}

    # Derive the image service URL from the first image on this canvas.
    service_id = ""
    for img in target.get("images", []) or []:
        resource = img.get("resource") or {}
        service = resource.get("service") or {}
        if isinstance(service, list):
            service = service[0] if service else {}
        if isinstance(service, dict):
            service_id = service.get("@id") or ""
            if service_id:
                break

    result = {
        "canvasId": target.get("@id", ""),
        "canvasWidth": int(target.get("width") or 0),
        "canvasHeight": int(target.get("height") or 0),
        "thumbnailUrl": _iiif_thumbnail_from_service(service_id),
        # The Image Service URL is what Arches' annotation viewer
        # expects in the `canvas` property of a GeoJSON feature — NOT
        # the Presentation API canvas @id. The viewer uses it to build
        # IIIF Image API tile requests for the Leaflet layer.
        "imageServiceUrl": service_id,
    }
    cache.set(cache_key, result, 3600)
    return result


def _iiif_thumbnail_from_service(service_id, width=200):
    """Build a provider-agnostic IIIF Image API thumbnail URL.

    Works against any IIIF Image API 2.x / 3.x compliant service: Gallica,
    e-codices, DigiVatLib, Bodleian, Morgan, … — they all answer to
    ``{service_id}/full/{w},/0/default.jpg``.
    """
    if not service_id:
        return ""
    return f"{service_id.rstrip('/')}/full/{width},/0/default.jpg"


class BiblissimaIlluminationDetailView(View):
    """Scrape a single illumination page from the Biblissima portal.

    Uses lxml.html + CSS selectors to walk the portal's stable DOM:

        <section id="presentation">
            <h1>Full name with manuscript info</h1>
            <ul class="description">
                <li><strong>Type :</strong><span>enluminure</span></li>
                <li><strong>Feuillet / page :</strong><span>323v</span></li>
                <li><strong>Descripteurs :</strong>
                    <span><a href="…/desc…">prophète</a>, …</span></li>
                <li><strong>Manuscrit :</strong>
                    <span><a href="…/mdata…">Paris. BnF…</a></span></li>
                …
            </ul>
        </section>

    Provider-agnostic by design: the source IIIF manifest URL is read
    from the ``data-manifest`` attribute on the ``.numerisation-iiif``
    link (Biblissima exposes this regardless of the origin provider —
    Gallica, e-codices, DigiVatLib, …), and ``_fetch_canvas_dimensions``
    derives the canvas dimensions + a IIIF-Image-API thumbnail without any
    per-provider special casing.
    """

    # Portal <strong> label → normalized result key. Exact-match only,
    # so there's no more risk of "Type" accidentally swallowing
    # "Typologie". Both French and English labels are listed — the same
    # parser runs against /fr/ and /en/ variants of the portal page.
    _FIELD_MAP = {
        # French labels (from /fr/ ark:/... pages)
        "Type": "type",
        "Feuillet / page": "folio",
        "Typologie": "typologie",
        "Technique": "technique",
        "Date de fabrication": "date",
        "Manuscrit": "manuscript",
        "Texte": "text",
        "Rubrique": "rubric",
        "Lieu de fabrication": "location",
        # English labels (from /en/ ark:/... pages) — same internal keys
        "Folio / page": "folio",
        "Date of Origin": "date",
        "Manuscript": "manuscript",
        "Text": "text",
        "Rubric": "rubric",
        "Place of Origin": "location",
    }

    def _parse_page(self, html):
        """Extract structured fields from a single portal HTML document.

        Returns a plain dict of scraped values. Language-agnostic: runs on
        either the ``/fr/`` or ``/en/`` variant of an illumination page —
        the same DOM structure, only the <strong> field labels differ
        (handled by ``_FIELD_MAP``).
        """
        tree = lxml_html.fromstring(html)
        page = {}

        # h1 inside the presentation section (full name with manuscript
        # + folio tail). Biblissima doesn't translate the title, so the
        # FR and EN versions return the same string here.
        h1 = tree.xpath('.//section[@id="presentation"]//h1')
        if h1:
            title = " ".join(h1[0].text_content().split()).strip()
            if title:
                page["pageTitle"] = title
                page["label"] = title

        # Presentation field list.
        for li in tree.xpath('.//section[@id="presentation"]//li'):
            strong_el = li.xpath(".//strong")
            if not strong_el:
                continue
            strong_text = strong_el[0].text_content()
            label_text = strong_text.replace(":", "").strip()
            key = self._FIELD_MAP.get(label_text)
            if key is None:
                continue
            span = li.xpath(".//span")
            if span:
                value = " ".join(span[0].text_content().split()).strip()
            else:
                full = li.text_content()
                value = full.replace(strong_text, "", 1)
                value = " ".join(value.split()).strip(" :")
            if value:
                page[key] = value

        # Iconographic descriptor links — scoped to the presentation
        # section so we don't pick up stray `desc` ARKs elsewhere.
        descriptor_links = []
        seen_uris = set()
        for a in tree.xpath(
            './/section[@id="presentation"]' '//a[contains(@href, "/ark:/43093/desc")]'
        ):
            uri = (a.get("href") or "").strip()
            if not uri or uri in seen_uris:
                continue
            seen_uris.add(uri)
            label = " ".join(a.text_content().split()).strip()
            descriptor_links.append({"label": label, "uri": uri})
        if descriptor_links:
            page["descriptorLinks"] = descriptor_links

        # Parent manuscript ARK — first <a> pointing at an mdata ARK.
        for a in tree.xpath('.//a[contains(@href, "/ark:/43093/mdata")]'):
            m = re.search(r"(mdata\w+)", a.get("href", ""))
            if m:
                page["manuscriptHash"] = m.group(1)
                page["manuscriptArk"] = f"ark:/43093/{m.group(1)}"
                break

        # Mandragore cross-reference.
        for a in tree.xpath('.//a[contains(@href, "mandragore.bnf.fr")]'):
            m = re.search(r"mandragore\.bnf\.fr/ark:/12148/(\w+)", a.get("href", ""))
            if m:
                page["mandragoreArk"] = f"ark:/12148/{m.group(1)}"
                break

        # Source IIIF manifest — clean URL via ``data-manifest`` on the
        # IIIF drag-and-drop link, with fallback on the companion
        # ``<input id="iiifUrl">``.
        for a in tree.xpath(
            './/div[contains(@class, "numerisation-iiif")]//a[@data-manifest]'
        ):
            mu = (a.get("data-manifest") or "").strip()
            if mu:
                page["manifestUrl"] = mu
                break
        if "manifestUrl" not in page:
            for inp in tree.xpath('.//input[@id="iiifUrl"]'):
                mu = (inp.get("value") or "").strip()
                if mu:
                    page["manifestUrl"] = mu
                    break

        return page

    @method_decorator(cache_page(3600))
    def get(self, request, ifdata_hash):
        """Fetch the /fr/ and /en/ portal pages in sequence, merge, enrich.

        Biblissima only translates a handful of fields between the two
        locale variants (notably ``Date de fabrication`` → ``Date of
        Origin`` — English dates feed straight into ``edtf`` without
        custom French-idiom handling). Everything else (titles,
        descriptors, place names, etc.) is the same French content on
        both pages, so we prefer the French values for them.

        The /en/ fetch is best-effort: if it fails the French-only
        result is returned and date parsing may degrade for century
        idioms, but the create step still works.
        """
        session = _build_biblissima_session()
        try:
            try:
                fr_resp = _bib_request(
                    session,
                    f"{BIBLISSIMA_PORTAL}/{ifdata_hash}",
                    timeout=PORTAL_REQUEST_TIMEOUT,
                )
                fr_resp.raise_for_status()
            except Exception as exc:
                return _biblissima_upstream_error(
                    exc, f"Biblissima illumination fetch ({ifdata_hash})"
                )

            fr_page = self._parse_page(fr_resp.text)

            # /en/ page — best effort, but loud on failure: when it does
            # fail we lose the date parsing path (edtf doesn't understand
            # French century idioms), so the operator should know.
            en_page = {}
            try:
                en_resp = _bib_request(
                    session,
                    f"{BIBLISSIMA_PORTAL_EN}/{ifdata_hash}",
                    timeout=PORTAL_REQUEST_TIMEOUT,
                )
                if en_resp.ok:
                    en_page = self._parse_page(en_resp.text)
                else:
                    logger.warning(
                        "Biblissima /en/ fetch returned %s for %s — date "
                        "parsing will fall back to French and likely fail",
                        en_resp.status_code,
                        ifdata_hash,
                    )
            except Exception as exc:
                logger.warning(
                    "Biblissima /en/ fetch raised for %s: %s — date "
                    "parsing will fall back to French and likely fail",
                    ifdata_hash,
                    exc,
                )

            # Merge: start from the French scrape, then prefer the English
            # value only for fields Biblissima actually translates. Date is
            # the one that matters — the edtf parser handles English
            # natural language ("13th century") natively.
            result = dict(fr_page)
            result["ifdataHash"] = ifdata_hash
            result["arkId"] = f"ark:/43093/{ifdata_hash}"
            result["portalUrl"] = f"{BIBLISSIMA_PORTAL}/{ifdata_hash}"
            if en_page.get("date"):
                result["date"] = en_page["date"]

            # Resolve the Component type: typologie > descriptor from label
            # > raw Type field > default.
            typologie = result.get("typologie", "")
            descriptor = ""
            if result.get("label"):
                desc_match = re.match(r"^([^(]+)", result["label"])
                if desc_match:
                    descriptor = desc_match.group(1).strip()
            type_field = result.get("type", "")
            type_valueid, type_is_fallback = _resolve_biblissima_type(
                typologie, descriptor, type_field
            )
            result["typeValueId"] = type_valueid
            result["typeLabel"] = _biblissima_type_label(type_valueid)
            result["typeIsFallback"] = type_is_fallback

            # Parse the date string (English preferred, French fallback)
            # into ISO bounds + century concept list so the create step
            # doesn't have to redo the work. ``centuryConcept`` is a list
            # because cross-century ranges (e.g. ``1290-1310``) cover more
            # than one period concept.
            if result.get("date"):
                start_iso, end_iso, centuries = parse_historical_date(result["date"])
                if start_iso:
                    result["dateStart"] = start_iso
                if end_iso:
                    result["dateEnd"] = end_iso
                if centuries:
                    result["centuryConcept"] = centuries

            # Canvas dimensions + thumbnail via one cached manifest fetch.
            if result.get("manifestUrl"):
                canvas_info = _fetch_canvas_dimensions(
                    result["manifestUrl"], result.get("folio", ""), session
                )
                if canvas_info:
                    result.update(canvas_info)

            return JsonResponse(result)
        finally:
            session.close()


class BiblissimaCreateResourceView(View):
    """Create one Arches resource per POST — the only write-path view.

    Expected body::

        {
            "resourceType": "Document" | "Component" | "Place" | "Group" | "Person",
            "transactionId": <uuid | null>,
            "biblissimaData": { ... ko.toJS(item) ... },
            "dependencies": {
                "parentDocument":   <uuid>,      // Component only, required
                "project":          <uuid>,      // optional
                "productionPlace":  <uuid>,      // Component → Production.Place
                "currentLocation":  <uuid>,      // Document → currentLocation
                "currentOwner":     [<uuid>],    // Document → Owner
                "productionActors": [<uuid>]
            },
            "conceptMappings": { "type": <valueid> }
        }

    Dispatch:

    - ``Place | Group | Person`` → ``_create_dependency_resource`` (lightweight
      name + optional ``memberOf`` / ``location``). Called recursively by
      the frontend cascade, so parent deps are always created first.
    - ``Document`` → ``_create_document_tiles``.
    - ``Component`` → ``_create_component_tiles``.

    Tile writes run inside a single ``transaction.atomic()``. ES indexing is
    deferred until after the DB transaction commits — a rollback therefore
    leaves no orphan ES docs.
    """

    # Graph ID mapping for all supported resource types
    GRAPH_IDS = {
        "Document": DOCUMENT_GRAPH_ID,
        "Component": COMPONENT_GRAPH_ID,
        "Place": PLACE_GRAPH_ID,
        "Group": GROUP_GRAPH_ID,
        "Person": PERSON_GRAPH_ID,
    }

    def post(self, request):
        import json

        try:
            body = json.loads(request.body)
        except (json.JSONDecodeError, ValueError):
            return JsonResponse({"error": "Invalid JSON body"}, status=400)

        resource_type = body.get("resourceType", "Document")
        transaction_id = body.get("transactionId")
        bbma_data = body.get("biblissimaData", {})
        dependencies = body.get("dependencies", {})
        concept_mappings = body.get("conceptMappings", {})

        graph_id = self.GRAPH_IDS.get(resource_type)
        if not graph_id:
            return JsonResponse(
                {"error": f"Unknown resourceType: {resource_type}"}, status=400
            )

        # Dependency types (Place/Group/Person): lightweight creation with just a name
        if resource_type in ("Place", "Group", "Person"):
            return self._create_dependency_resource(graph_id, resource_type, bbma_data)

        try:
            resource_id, created_deps = self._create_resource(
                graph_id=graph_id,
                resource_type=resource_type,
                transaction_id=transaction_id,
                bbma_data=bbma_data,
                dependencies=dependencies,
                concept_mappings=concept_mappings,
                user=request.user,
            )
        except Exception:
            logger.exception("Failed to create resource from Biblissima data")
            return JsonResponse({"error": "Resource creation failed"}, status=500)

        return JsonResponse(
            {
                "resourceId": str(resource_id),
                "createdDependencies": created_deps,
            }
        )

    def _create_dependency_resource(self, graph_id, resource_type, bbma_data):
        """Create a Place/Group/Person resource with name and relationships."""
        from django.db import transaction
        from arches.app.models.resource import Resource

        label = (bbma_data.get("label") or "").strip()
        if not label:
            return JsonResponse({"error": "Missing label for dependency"}, status=400)

        name_conf = DEP_NAME_CONFIG[graph_id]
        member_of_id = bbma_data.get("memberOf")
        location_id = bbma_data.get("location")

        try:
            with transaction.atomic():
                resource_instance = ResourceInstance(graph_id=graph_id)
                resource_instance.save()
                resource_id = resource_instance.resourceinstanceid

                # Name tile
                self._create_tile(
                    name_conf["ng"],
                    resource_id,
                    {
                        name_conf["label"]: self._i18n_string(label),
                        name_conf["language"]: self._concept_list([CONCEPT_FRENCH]),
                        name_conf["type"]: self._concept_list(
                            [CONCEPT_PREFERRED_TERMS]
                        ),
                    },
                )

                # Group: Member of (parent group)
                if resource_type == "Group" and member_of_id:
                    self._create_tile(
                        GROUP_MEMBER_OF_NG,
                        resource_id,
                        {
                            GROUP_MEMBER_OF_NODE: self._resource_instance_ref(
                                member_of_id
                            ),
                        },
                    )

                # Group: Location (place)
                if resource_type == "Group" and location_id:
                    self._create_tile(
                        GROUP_LOCATION_NG,
                        resource_id,
                        {
                            GROUP_LOCATION_NODE: self._resource_instance_list(
                                location_id
                            ),
                        },
                    )

            resource = Resource.objects.get(resourceinstanceid=resource_id)
            resource.index()
        except Exception:
            logger.exception("Failed to create %s dependency", resource_type)
            return JsonResponse(
                {"error": f"{resource_type} creation failed"}, status=500
            )

        return JsonResponse(
            {
                "resourceId": str(resource_id),
                "displayname": label,
            }
        )

    def _create_resource(
        self,
        graph_id,
        resource_type,
        transaction_id,
        bbma_data,
        dependencies,
        concept_mappings,
        user,
    ):
        """Create a resource with all its tiles from Biblissima data.

        Wrapped in a DB transaction — if anything fails, everything rolls back.
        Elasticsearch indexing is deferred until after all DB writes succeed,
        so a rollback leaves no orphan documents in ES.
        """
        from django.db import transaction
        from arches.app.models.resource import Resource

        with transaction.atomic():
            created_deps = {"places": {}, "persons": {}, "groups": {}}
            resource_instance = ResourceInstance(graph_id=graph_id)
            resource_instance.save()
            resource_id = resource_instance.resourceinstanceid

            if resource_type == "Document":
                self._create_document_tiles(
                    resource_id,
                    transaction_id,
                    bbma_data,
                    dependencies,
                    concept_mappings,
                    created_deps,
                )
            else:
                self._create_component_tiles(
                    resource_id,
                    transaction_id,
                    bbma_data,
                    dependencies,
                    concept_mappings,
                    created_deps,
                )

            # Link to project if specified
            project_id = dependencies.get("project")
            if project_id:
                self._link_to_project(resource_id, project_id, transaction_id)

        # DB transaction succeeded — now index into Elasticsearch
        try:
            resource = Resource.objects.get(resourceinstanceid=resource_id)
            resource.index()
        except Exception:
            logger.warning(
                "ES indexing failed for resource %s (DB is committed)", resource_id
            )

        return resource_id, created_deps

    def _create_tile(
        self,
        nodegroup_id,
        resource_id,
        data,
        transaction_id=None,
        parenttile=None,
    ):
        """Create a single tile without ES indexing (deferred to after commit).

        ``parenttile`` must be set when the nodegroup has a
        ``parentnodegroup`` in the graph — without it, Arches can't
        reconstruct the tile hierarchy and the card UI won't display
        the child data under the right parent. Query the NodeGroup model
        to find which nodegroups are nested.
        """
        tile = Tile(
            tileid=uuid.uuid4(),
            nodegroup_id=nodegroup_id,
            resourceinstance_id=resource_id,
            data=data,
            sortorder=0,
        )
        if parenttile is not None:
            tile.parenttile = parenttile
        if transaction_id:
            tile.transaction_id = transaction_id
        tile.save(index=False)
        return tile

    @staticmethod
    def _i18n_string(value, lang=None):
        """Format a string as an Arches i18n dict.

        Three calling forms:

        - **plain string, no ``lang``** → mirrored under both ``"fr"`` and
          ``"en"`` keys with the same value. This is the default for
          scraped Biblissima content (which is French) and ensures the
          string displays regardless of which locale the running Arches
          server uses to render the resource — Arches has no
          "any-language" fallback in the i18n datatype, so any tile
          stored under a single key vanishes when the server picks a
          different one.
        - **plain string, explicit ``lang``** → single-language tile.
          Use when you really only want one locale (rare).
        - **dict ``{lang_code: str}``** → multilingual tile with each
          language carried separately. Empty / None values are dropped.
          Used when we genuinely have distinct French and English
          translations (e.g. dates from the ``/en/`` portal scrape).
        """
        if isinstance(value, dict):
            return {
                lang_code: {"value": str(v), "direction": "ltr"}
                for lang_code, v in value.items()
                if v
            }
        if lang is None:
            return {
                "fr": {"value": str(value), "direction": "ltr"},
                "en": {"value": str(value), "direction": "ltr"},
            }
        return {lang: {"value": str(value), "direction": "ltr"}}

    @staticmethod
    def _concept_valueid(concept_id):
        """Get the prefLabel valueid for a concept ID.

        Prefers English, falls back to any language.
        """
        try:
            # Try English first
            val = (
                Value.objects.filter(
                    concept_id=concept_id,
                    valuetype="prefLabel",
                )
                .filter(language__in=["en", "en-US", "en-UK", "English"])
                .first()
            )
            if val:
                return str(val.valueid)
            # Fallback to any language
            val = Value.objects.filter(
                concept_id=concept_id,
                valuetype="prefLabel",
            ).first()
            return str(val.valueid) if val else concept_id
        except Exception:
            return concept_id

    def _concept_list(self, concept_ids):
        """Convert a list of concept IDs to a list of valueids."""
        if isinstance(concept_ids, str):
            concept_ids = [concept_ids]
        return [self._concept_valueid(cid) for cid in concept_ids]

    def _create_document_tiles(
        self, resource_id, transaction_id, bbma_data, deps, concepts, created_deps
    ):
        """Create all tiles for a Document resource."""
        i18n = self._i18n_string
        clist = self._concept_list

        # Name
        label = bbma_data.get("label", "Untitled")
        self._create_tile(
            DOC_NAME_NG,
            resource_id,
            {
                DOC_NAME_LABEL: i18n(label),
                DOC_NAME_LANGUAGE: clist([CONCEPT_FRENCH]),
                DOC_NAME_TYPE: clist([CONCEPT_PREFERRED_TERMS]),
            },
            transaction_id,
        )

        # Second name tile for shelfmark if available
        shelfmark = bbma_data.get("shelfmark")
        if shelfmark:
            self._create_tile(
                DOC_NAME_NG,
                resource_id,
                {
                    DOC_NAME_LABEL: i18n(shelfmark),
                    DOC_NAME_LANGUAGE: clist([CONCEPT_FRENCH]),
                    DOC_NAME_TYPE: clist(["7cca3482-44b5-42ea-a1d7-120cd732b350"]),
                },
                transaction_id,
            )

        # Type (concept node, single valueid string)
        doc_type = concepts.get("type")
        if doc_type:
            # doc_type from frontend is already a valueid (selected via concept-select-widget)
            self._create_tile(
                DOC_TYPE_NG,
                resource_id,
                {DOC_TYPE_NODE: doc_type},
                transaction_id,
            )

        # Identifiers — canvas-derived payloads already carry ``arkId``;
        # entity-derived payloads only carry ``portalHash``, so derive the
        # ARK from it when needed. (``biblissimaQid`` is now exposed by
        # both shapes via _extract_entity_props.)
        ark_id = bbma_data.get("arkId") or (
            f"ark:/43093/{bbma_data['portalHash']}"
            if bbma_data.get("portalHash")
            else None
        )
        if ark_id:
            self._create_tile(
                DOC_IDENTIFIER_NG,
                resource_id,
                {
                    DOC_IDENTIFIER_VALUE: i18n(ark_id),
                    DOC_IDENTIFIER_TYPE: clist([CONCEPT_PERSISTENT_ID]),
                    DOC_IDENTIFIER_SOURCE: clist([CONCEPT_SOURCE_BIBLISSIMA]),
                },
                transaction_id,
            )

        qid = bbma_data.get("biblissimaQid")
        if qid:
            self._create_tile(
                DOC_IDENTIFIER_NG,
                resource_id,
                {
                    DOC_IDENTIFIER_VALUE: i18n(
                        f"https://data.biblissima.fr/entity/{qid}"
                    ),
                    DOC_IDENTIFIER_TYPE: clist([CONCEPT_RECORD_ID]),
                    DOC_IDENTIFIER_SOURCE: clist([CONCEPT_SOURCE_BIBLISSIMA]),
                },
                transaction_id,
            )

        aem_id = bbma_data.get("aemId")
        if aem_id:
            self._create_tile(
                DOC_IDENTIFIER_NG,
                resource_id,
                {
                    DOC_IDENTIFIER_VALUE: i18n(
                        f"https://archivesetmanuscrits.bnf.fr/ark:/12148/cc{aem_id}"
                    ),
                    DOC_IDENTIFIER_TYPE: clist([CONCEPT_TYPE_BNF_ID]),
                    DOC_IDENTIFIER_SOURCE: clist([CONCEPT_SOURCE_BIBLISSIMA]),
                },
                transaction_id,
            )

        mandragore_id = bbma_data.get("mandragoreId")
        if mandragore_id:
            self._create_tile(
                DOC_IDENTIFIER_NG,
                resource_id,
                {
                    DOC_IDENTIFIER_VALUE: i18n(mandragore_id),
                    DOC_IDENTIFIER_TYPE: clist([CONCEPT_RECORD_ID]),
                    DOC_IDENTIFIER_SOURCE: clist([CONCEPT_SOURCE_MANDRAGORE]),
                },
                transaction_id,
            )

        # Statement (description)
        legend = bbma_data.get("legend") or bbma_data.get("label", "")
        portal_url = bbma_data.get("portalUrl", "")
        if legend:
            self._create_tile(
                DOC_STATEMENT_NG,
                resource_id,
                {
                    DOC_STATEMENT_CONTENT: i18n(legend),
                    DOC_STATEMENT_TYPE: clist([CONCEPT_DESCRIPTION]),
                    DOC_STATEMENT_LANGUAGE: clist([CONCEPT_FRENCH]),
                    DOC_STATEMENT_SOURCE: (
                        {"url": portal_url, "url_label": ""} if portal_url else None
                    ),
                },
                transaction_id,
            )

        # Facsimiles (IIIF manifest) - manifest datatype accepts URL string directly
        manifest_url = bbma_data.get("manifestUrl")
        if manifest_url:
            self._create_tile(
                DOC_FACSIMILES_NG,
                resource_id,
                {DOC_FACSIMILES_NODE: manifest_url},
                transaction_id,
            )

        # Period + Production dates. The illumination detail view parses
        # the date at enrichment time and stores ISO bounds + century
        # concept on the item (``dateStart``, ``dateEnd``,
        # ``centuryConcept``). Fallback to in-situ parsing for call sites
        # that haven't enriched the item yet (e.g. IIIF search path).
        century_concepts = bbma_data.get("centuryConcept") or []
        if isinstance(century_concepts, str):
            century_concepts = [century_concepts]
        date_start = bbma_data.get("dateStart")
        date_end = bbma_data.get("dateEnd")
        if not (century_concepts or date_start or date_end):
            raw_date = bbma_data.get("date", "")
            if raw_date:
                date_start, date_end, century_concepts = parse_historical_date(raw_date)

        if century_concepts:
            self._create_tile(
                DOC_PERIOD_NG,
                resource_id,
                {
                    DOC_PERIOD_ABSOLUTE: clist(century_concepts),
                    DOC_PERIOD_PRODUCTION: clist([CONCEPT_MEDIEVAL]),
                },
                transaction_id,
            )

        # Production
        prod_data = {DOC_PROD_TIME_TYPE: False}

        if date_start:
            prod_data[DOC_PROD_DATE_START] = date_start
        if date_end:
            prod_data[DOC_PROD_DATE_END] = date_end

        place_id = deps.get("productionPlace")
        if place_id:
            prod_data[DOC_PROD_PLACE] = self._resource_instance_list(place_id)

        actor_ids = deps.get("productionActors", [])
        if actor_ids:
            prod_data[DOC_PROD_ACTORS] = self._resource_instance_list(actor_ids)

        if len(prod_data) > 1:
            self._create_tile(
                DOC_PRODUCTION_NG,
                resource_id,
                prod_data,
                transaction_id,
            )

        # Current location
        location_id = deps.get("currentLocation")
        if location_id:
            self._create_tile(
                DOC_LOCATION_NG,
                resource_id,
                {
                    DOC_LOCATION_NODE: self._resource_instance_ref(location_id),
                    DOC_LOCATION_LITERAL: None,
                },
                transaction_id,
            )

        # Current owner
        owner_ids = deps.get("currentOwner", [])
        if owner_ids:
            self._create_tile(
                DOC_OWNER_NG,
                resource_id,
                {DOC_OWNER_NODE: self._resource_instance_list(owner_ids)},
                transaction_id,
            )

        # Part of
        parent_doc_id = deps.get("partOf")
        if parent_doc_id:
            self._create_tile(
                DOC_PART_OF_NG,
                resource_id,
                {DOC_PART_OF_NODE: self._resource_instance_list(parent_doc_id)},
                transaction_id,
            )

    def _create_component_tiles(
        self, resource_id, transaction_id, bbma_data, deps, concepts, created_deps
    ):
        """Create all tiles for an illumination (Component) resource.

        Mapping Biblissima → Arches tiles (all cards cardinality=n unless
        noted; values pulled from the ``ko.toJS(item)`` payload enriched at
        step 3):

        ============================ =========================================================================
        Card                         Source
        ============================ =========================================================================
        Name of Component            ``pageTitle`` > ``label`` > ``legend``
        Type of Component            ``concepts["type"]`` (per-item valueid, correctable via inline editor)
        Item Feature                 ``deps["parentDocument"]``
        Identifier                   Biblissima ARK (``arkId``) + Mandragore ARK (``mandragoreArk``) if present
        Statement                    ``text`` → ``identification`` ; ``rubric`` → ``inscriptions``
        Iconographic representation  one tile per ``descriptorLinks[i]``: ``url = desc ARK``, ``url_label = label``
        Period                       ``date`` → century concept + medieval production period
        Production                   ``date``, ``deps["productionPlace"]``, ``deps["productionActors"]``
        Location in Document         whole-page Polygon sized from ``canvasWidth/canvasHeight``
                                     (fallback 4000×5000); ``folio`` → Location appellation
        ============================ =========================================================================

        Attention: ``folio`` lives **only** in Location appellation, not
        in Context of Component (which has no Biblissima source).
        """
        i18n = self._i18n_string
        clist = self._concept_list

        # Name of Component — prefer the h1 title we pulled from the
        # individual portal page, which is the canonical full-form name
        # with the manuscript tail ("Abdias prophétisant (France, Paris.
        # BnF, …, Latin 40 f.323v)"). Falls back to the cart label /
        # legend for items that weren't enriched yet.
        label = (
            bbma_data.get("pageTitle")
            or bbma_data.get("label")
            or bbma_data.get("legend")
            or "Untitled"
        )
        self._create_tile(
            COMP_NAME_NG,
            resource_id,
            {
                COMP_NAME_LABEL: i18n(label),
                COMP_NAME_LANGUAGE: clist([CONCEPT_FRENCH]),
                COMP_NAME_TYPE: clist([CONCEPT_PREFERRED_TERMS]),
            },
            transaction_id,
        )

        # Type (concept-list node, expects list of valueids)
        comp_type = concepts.get("type")
        if comp_type:
            # comp_type from frontend is already a valueid
            self._create_tile(
                COMP_TYPE_NG,
                resource_id,
                {COMP_TYPE_NODE: [comp_type]},
                transaction_id,
            )

        # Parent Document (required) — this is the Item Feature of
        # Component tile, which is the ROOT parent for the nested
        # Production and Location in Document tiles.
        parent_doc_id = deps.get("parentDocument")
        item_feature_tile = None
        if parent_doc_id:
            item_feature_tile = self._create_tile(
                COMP_PARENT_DOC_NG,
                resource_id,
                {COMP_PARENT_DOC_NODE: self._resource_instance_ref(parent_doc_id)},
                transaction_id,
            )

        # --- Identifiers (Identifier card is cardinality=n) -------------
        # Primary Biblissima ARK
        ark_id = bbma_data.get("arkId")
        if ark_id:
            self._create_tile(
                COMP_IDENTIFIER_NG,
                resource_id,
                {
                    COMP_IDENTIFIER_VALUE: i18n(ark_id),
                    COMP_IDENTIFIER_TYPE: clist([CONCEPT_PERSISTENT_ID]),
                    COMP_IDENTIFIER_SOURCE: clist([CONCEPT_SOURCE_BIBLISSIMA]),
                },
                transaction_id,
            )

        # Mandragore ARK — added only if the individual portal page surfaced
        # a Mandragore cross-reference (BnF manuscript lookups). Note: the
        # `mandragoreId` field that comes from the Wikibase resolution of
        # the parent manuscript is a numeric record identifier ("1449"),
        # NOT an ARK, so we deliberately don't fall back to it here.
        mandragore_ark = bbma_data.get("mandragoreArk")
        if mandragore_ark:
            self._create_tile(
                COMP_IDENTIFIER_NG,
                resource_id,
                {
                    COMP_IDENTIFIER_VALUE: i18n(mandragore_ark),
                    COMP_IDENTIFIER_TYPE: clist([CONCEPT_PERSISTENT_ID]),
                    COMP_IDENTIFIER_SOURCE: clist([CONCEPT_SOURCE_MANDRAGORE]),
                },
                transaction_id,
            )

        # Keep only external *identifiers* of the component itself in the
        # Identifier card (Biblissima ARK + Mandragore ARK above). The
        # iconographic descriptors — what the illumination *depicts* —
        # belong in Iconographic representation below, not here.
        descriptor_links = bbma_data.get("descriptorLinks") or []

        # --- Statements (Statement card is cardinality=n) ---------------
        # The "legend / Description" statement that used to mirror the
        # Name of Component was redundant and noisy — Name of Component now
        # holds the cleaner h1 title. We only emit Statements for Texte
        # (identification of the underlying work) and Rubrique (literal
        # inscription on the folio) below.

        # "Texte" → identifies the work the illumination illustrates
        text_content = bbma_data.get("text", "")
        if text_content:
            self._create_tile(
                COMP_STATEMENT_NG,
                resource_id,
                {
                    COMP_STATEMENT_CONTENT: i18n(text_content),
                    COMP_STATEMENT_TYPE: clist([CONCEPT_IDENTIFICATION]),
                    COMP_STATEMENT_LANGUAGE: clist([CONCEPT_FRENCH]),
                    COMP_STATEMENT_SOURCE: None,
                },
                transaction_id,
            )

        # "Rubrique" → literal rubric text on the folio
        rubric_content = bbma_data.get("rubric", "")
        if rubric_content:
            self._create_tile(
                COMP_STATEMENT_NG,
                resource_id,
                {
                    COMP_STATEMENT_CONTENT: i18n(rubric_content),
                    COMP_STATEMENT_TYPE: clist([CONCEPT_INSCRIPTIONS]),
                    COMP_STATEMENT_LANGUAGE: clist([CONCEPT_FRENCH]),
                    COMP_STATEMENT_SOURCE: None,
                },
                transaction_id,
            )

        # --- Iconographic representation (cardinality=n) ----------------
        # Semantically: "what is iconographically represented in this
        # component". That's the set of iconographic descriptors
        # (prophète, Abdias, ville, Dieu…), each a link to its own
        # Biblissima desc-ARK. One tile per descriptor → the Arches widget
        # renders each as a clickable hyperlink with its label.
        #
        # Digital-facsimile URLs (IIIF thumbnails) do not belong here; they
        # surface in the workflow step-3 UI only (via ``item.thumbnailUrl``
        # derived from ``_iiif_thumbnail_from_service`` on any IIIF
        # provider) for preview.
        for dlink in descriptor_links:
            uri = (dlink.get("uri") or "").strip()
            label = (dlink.get("label") or "").strip()
            if not uri:
                continue
            self._create_tile(
                COMP_ICONOGRAPHIC_NG,
                resource_id,
                {COMP_ICONOGRAPHIC_NODE: {"url": uri, "url_label": label}},
                transaction_id,
            )

        # Folio now lives only inside Location in Document's appellation
        # (built below). We no longer write it into Context of Component.

        # Period + Production dates. Same pre-parsed fields as for
        # Documents — ``dateStart`` / ``dateEnd`` / ``centuryConcept`` are
        # set at enrichment time by ``BiblissimaIlluminationDetailView``.
        # Fallback to in-situ parsing for items that never went through
        # enrichment (unusual but possible via direct-ARK add paths).
        century_concepts = bbma_data.get("centuryConcept") or []
        if isinstance(century_concepts, str):
            century_concepts = [century_concepts]
        date_start = bbma_data.get("dateStart")
        date_end = bbma_data.get("dateEnd")
        if not (century_concepts or date_start or date_end):
            raw_date = bbma_data.get("date", "")
            if raw_date:
                date_start, date_end, century_concepts = parse_historical_date(raw_date)

        # --- Nested tile chain: Item Feature → Production → Production
        # period. Each child tile must reference its parent tile via
        # `parenttile`, otherwise Arches can't reconstruct the hierarchy
        # and the card UI shows empty sub-cards even though the data
        # exists in the DB.
        #
        # IMPORTANT: "Production period" (NG e67686af) and "Absolute
        # period attribution" (node e67686b6) belong to the SAME
        # nodegroup. They must be in a single tile — not split into two.
        # The "Period" NG (e67686b1) is for alternative period identifiers
        # that we don't use from Biblissima, so we don't create a tile
        # for it.

        # Production (parent = Item Feature)
        prod_data = {COMP_PROD_TIME_TYPE: False}

        if date_start:
            prod_data[COMP_PROD_DATE_START] = date_start
        if date_end:
            prod_data[COMP_PROD_DATE_END] = date_end

        place_id = deps.get("productionPlace")
        if place_id:
            prod_data[COMP_PROD_PLACE] = self._resource_instance_list(place_id)

        actor_ids = deps.get("productionActors", [])
        if actor_ids:
            prod_data[COMP_PROD_ACTORS] = self._resource_instance_list(actor_ids)

        production_tile = None
        if len(prod_data) > 1:
            production_tile = self._create_tile(
                COMP_PRODUCTION_NG,
                resource_id,
                prod_data,
                transaction_id,
                parenttile=item_feature_tile,
            )

        # Production period — single tile with both:
        #   - "Production period" concept (e.g. medieval)
        #   - "Absolute period attribution" concept (e.g. 13th century)
        # Both nodes live in NG e67686af. Parent = Production tile.
        if production_tile:
            period_data = {COMP_PERIOD_PRODUCTION: clist([CONCEPT_MEDIEVAL])}
            if century_concepts:
                period_data[COMP_PERIOD_ABSOLUTE] = clist(century_concepts)
            self._create_tile(
                COMP_PERIOD_NG,
                resource_id,
                period_data,
                transaction_id,
                parenttile=production_tile,
            )

        # Location in Document (annotation) — build a "whole page" polygon
        # covering the full canvas when we know its dimensions, so the
        # annotation actually points at something on the IIIF viewer instead
        # of the unusable Point at (0, 0). Fallback to a small rectangle if
        # dimensions are missing.
        folio = bbma_data.get("folio", "")
        # The annotation's `canvas` property must point at the IIIF
        # *Image Service* URL (the base from which Arches' Leaflet viewer
        # constructs tile requests), NOT the Presentation API canvas @id
        # (which is JSON, not an image). `imageServiceUrl` is extracted
        # from `canvas.images[0].resource.service.@id` during enrichment.
        canvas_url = (
            bbma_data.get("imageServiceUrl")
            or bbma_data.get("canvasId")
            or bbma_data.get("imageUrl")
        )
        manifest_url = bbma_data.get("manifestUrl")
        if canvas_url and manifest_url:
            width = int(bbma_data.get("canvasWidth") or 0) or 4000
            height = int(bbma_data.get("canvasHeight") or 0) or 5000

            # Arches stores annotations in Leaflet CRS.simple coordinates,
            # not raw pixels. The conversion is:
            #   lng = pixel_x / scale
            #   lat = -pixel_y / scale   (Y axis is inverted)
            # with scale = 2^zoom. Arches' annotation widget defaults to
            # zoom=5 (scale=32). See BBoxCalculator in utils/iiif_tools.py
            # for the inverse conversion.
            scale = 2**5  # 32 — must match the Arches annotation viewer
            polygon_coords = [
                [
                    [0, 0],
                    [width / scale, 0],
                    [width / scale, -height / scale],
                    [0, -height / scale],
                    [0, 0],
                ]
            ]
            annotation_data = {
                "type": "FeatureCollection",
                "features": [
                    {
                        "id": str(uuid.uuid4()),
                        "type": "Feature",
                        "geometry": {
                            "type": "Polygon",
                            "coordinates": polygon_coords,
                        },
                        "properties": {
                            "canvas": canvas_url,
                            "manifest": manifest_url,
                            "nodeId": COMP_LOCATION_DOC_NODE,
                            "color": "#3388ff",
                            "radius": 10,
                            "weight": 3,
                            "opacity": 1,
                            "fillColor": "#3388ff",
                            "fillOpacity": 0.2,
                        },
                    }
                ],
            }
            appellation_data = i18n(folio or "")
            self._create_tile(
                COMP_LOCATION_DOC_NG,
                resource_id,
                {
                    COMP_LOCATION_DOC_NODE: annotation_data,
                    COMP_LOCATION_APPELLATION: appellation_data,
                },
                transaction_id,
                parenttile=item_feature_tile,
            )

    def _link_to_project(self, resource_id, project_id, transaction_id):
        """Add the created resource to the project's Studied Objects."""
        # Validate project_id is a proper UUID
        try:
            project_uuid = uuid.UUID(str(project_id))
        except (ValueError, AttributeError):
            logger.warning("Invalid project_id for linking: %r", project_id)
            return

        project_id = str(project_uuid)

        # Find existing tile or create new one
        existing = Tile.objects.filter(
            nodegroup_id=PROJECT_STUDIED_OBJECTS_NG,
            resourceinstance_id=project_id,
        ).first()

        new_ref = {
            "resourceId": str(resource_id),
            "ontologyProperty": "",
            "inverseOntologyProperty": "",
            "resourceXresourceId": "",
        }

        if existing:
            current_data = existing.data.get(PROJECT_STUDIED_OBJECTS_NODE, []) or []
            target_id = str(resource_id)
            # Idempotence: skip if this resource is already in the project's
            # studied_objects. Prevents duplicate entries when a Document
            # parent that was already linked is re-linked from a new
            # workflow run (cf. Q6 of the design).
            if any(ref.get("resourceId") == target_id for ref in current_data):
                return
            current_data.append(new_ref)
            existing.data[PROJECT_STUDIED_OBJECTS_NODE] = current_data
            existing.save()
        else:
            self._create_tile(
                PROJECT_STUDIED_OBJECTS_NG,
                project_id,
                {PROJECT_STUDIED_OBJECTS_NODE: [new_ref]},
                transaction_id,
            )

    def _resource_instance_ref(self, resource_id):
        """Build a resource-instance reference for a single resource."""
        if isinstance(resource_id, list):
            resource_id = resource_id[0] if resource_id else None
        if not resource_id:
            return None
        return [
            {
                "resourceId": str(resource_id),
                "ontologyProperty": "",
                "inverseOntologyProperty": "",
                "resourceXresourceId": "",
            }
        ]

    def _resource_instance_list(self, resource_ids):
        """Build a resource-instance-list reference."""
        if isinstance(resource_ids, str):
            resource_ids = [resource_ids]
        return [
            {
                "resourceId": str(rid),
                "ontologyProperty": "",
                "inverseOntologyProperty": "",
                "resourceXresourceId": "",
            }
            for rid in resource_ids
            if rid
        ]


class BiblissimaAddAltNameView(View):
    """Add a Biblissima label as alternative name to an existing resource."""

    def post(self, request):
        import json
        from arches.app.models.resource import Resource

        try:
            body = json.loads(request.body)
        except (json.JSONDecodeError, ValueError):
            return JsonResponse({"error": "Invalid JSON body"}, status=400)

        resource_id = body.get("resourceId", "")
        graph_id = body.get("graphId", "")
        label = body.get("label", "").strip()

        if not resource_id or not label or graph_id not in DEP_NAME_CONFIG:
            return JsonResponse(
                {"error": "Missing resourceId, label, or invalid graphId"}, status=400
            )

        name_conf = DEP_NAME_CONFIG[graph_id]

        # Check if this name already exists on the resource
        existing_tiles = Tile.objects.filter(
            nodegroup_id=name_conf["ng"],
            resourceinstance_id=resource_id,
        )
        for tile in existing_tiles:
            existing_label = tile.data.get(name_conf["label"], {})
            for lang_data in existing_label.values():
                if (
                    isinstance(lang_data, dict)
                    and lang_data.get("value", "").strip().lower() == label.lower()
                ):
                    return JsonResponse(
                        {"status": "already_exists", "message": "Name already present"}
                    )

        creator = BiblissimaCreateResourceView()
        try:
            tile = Tile(
                tileid=uuid.uuid4(),
                nodegroup_id=name_conf["ng"],
                resourceinstance_id=resource_id,
                data={
                    name_conf["label"]: creator._i18n_string(label),
                    name_conf["language"]: creator._concept_list([CONCEPT_FRENCH]),
                    name_conf["type"]: creator._concept_list(
                        [CONCEPT_ALTERNATE_TITLES]
                    ),
                },
                sortorder=0,
            )
            tile.save(index=False)

            resource = Resource.objects.get(resourceinstanceid=resource_id)
            resource.index()
        except Exception:
            logger.exception("Failed to add alt name to resource %s", resource_id)
            return JsonResponse({"error": "Failed to add alternative name"}, status=500)

        return JsonResponse({"status": "added", "message": "Alternative name added"})


class BiblissimaStatsView(View):
    """Debug/admin tool exposing outbound Biblissima traffic counters.

    Restricted to authenticated staff users. Intended for quick sanity checks
    after a deploy or during debugging (e.g. "is Biblissima rate-limiting us?",
    "is the cache filling up?"). Not a replacement for proper observability:

    - Counters live in process memory and reset on every Django restart.
    - Each gunicorn worker keeps its own counters, so values are per-process
      and can be misleading when multiple workers are running.

    For long-term observability, wire django-prometheus or ship 429/5xx
    events to an external collector.
    """

    @method_decorator(never_cache)
    def get(self, request):
        if not request.user.is_authenticated or not request.user.is_staff:
            return JsonResponse({"error": "Forbidden"}, status=403)

        with _biblissima_stats_lock:
            stats = dict(_biblissima_stats)
        stats["semaphore_capacity"] = _BIBLISSIMA_CONCURRENCY_LIMIT
        total_cache_lookups = stats["cache_hits"] + stats["cache_misses"]
        stats["cache_hit_ratio"] = (
            round(stats["cache_hits"] / total_cache_lookups, 3)
            if total_cache_lookups
            else None
        )
        return JsonResponse(stats)


class BiblissimaLinkToProjectView(View):
    """Idempotently link an existing resource to a Project's studied objects.

    Used by the step-3 parent-resolver (parentResolver.js) for Documents that
    were matched in Arches or manually picked, where the create-resource path
    is not invoked. Created Documents are linked through their dependencies
    payload directly. The dedup happens inside _link_to_project (cf. Task 1.7).
    """

    def post(self, request):
        import json

        try:
            body = json.loads(request.body)
        except (json.JSONDecodeError, ValueError):
            return JsonResponse({"error": "Invalid JSON"}, status=400)

        resource_id = body.get("resourceId")
        project_id = body.get("projectId")
        if not resource_id or not project_id:
            return JsonResponse(
                {"error": "resourceId and projectId are required"},
                status=400,
            )

        try:
            uuid.UUID(str(resource_id))
            uuid.UUID(str(project_id))
        except (ValueError, AttributeError):
            return JsonResponse({"error": "Invalid UUID"}, status=400)

        # Reuse the helper on BiblissimaCreateResourceView so the dedup logic
        # stays in a single place. transaction_id is None for ad-hoc links.
        BiblissimaCreateResourceView()._link_to_project(
            resource_id,
            project_id,
            transaction_id=None,
        )
        return JsonResponse({"ok": True})
