"""Every Prometheus metric of the application, and the vocabularies of their labels.

Names start with ``manuspectrum_`` and carry their unit (``_seconds``, ``_bytes``;
a counter is exposed with ``_total``). A label comes from ``ALLOWED_LABELS`` and
takes its value from a closed vocabulary, through ``bounded()`` or a helper below:
an unknown value becomes ``"other"``. Never an id, a user, a URL, a path or a
string a client sent. gunicorn and Celery run several processes sharing
``PROMETHEUS_MULTIPROC_DIR``: a Gauge is created through ``gauge()``, which
requires its multiprocess mode, and only Counter, Gauge and Histogram are used
(Info, Enum and Summary quantiles do not aggregate across processes).
"""

from django.conf import settings
from prometheus_client import Counter, Gauge, Histogram

OTHER = "other"

ALLOWED_LABELS = frozenset(
    {
        "background",
        "component",
        "endpoint",
        "kind",
        "language",
        "level",
        "memo",
        "mode",
        "outcome",
        "purpose",
        "reason",
        "resource_type",
        "source",
        "surface",
        "task",
        "tier",
    }
)
FORBIDDEN_LABELS = frozenset(
    {
        "email",
        "file_id",
        "id",
        "ip",
        "path",
        "qid",
        "query",
        "request_id",
        "resource_id",
        "resourceid",
        "url",
        "user",
        "user_id",
        "username",
    }
)
GAUGE_MODES = frozenset({"livesum", "mostrecent"})

LOG_LEVELS = ("warning", "error", "critical")
LOG_SOURCES = ("django", "arches", "manuspectrum", "celery")
MEMO_NAMES = (
    "biblissima",
    "biblissima:illuminations:raw",
    "biblissima:search:raw",
    "biblissima:suggest",
    "biblissima:suggest:prefix",
    "biblissima:wikibase:entity",
    "biblissima:wikibase:place-geo",
    "explorer-bundle",
    "explorer-home-techniques",
    "iiif",
    "model-graph",
    "public-visibility",
    "spectrum-preview",
    "spectrum-preview-config",
    "spectrum-preview-file",
    "summary",
    "summary-config",
    "summary-graph",
    "summary-graph-slugs",
    "summary-list-labels",
    "summary-restricted-nodegroups",
    "summary-restricted-resources",
)
_MEMO_BY_LENGTH = sorted(MEMO_NAMES, key=len, reverse=True)
MEMO_OUTCOMES = ("hit", "built", "waited")
IIIF_ANSWER_MODES = ("shared", "private", "not_modified")
IIIF_TOKEN_OUTCOMES = (
    "issued",
    "invalidRequest",
    "invalidOrigin",
    "missingCredentials",
    "invalidCredentials",
    "unavailable",
)
READ_SURFACES = ("summary", "thumbnail", "iiif_file", "spectrum_preview")
LOGIN_OUTCOMES = ("success", "failure")
BUNDLE_REASONS = ("cold", "data", "permissions", "visibility")
BIBLISSIMA_ENDPOINTS = ("wikibase", "portal", "iiif")
UPSTREAM_OUTCOMES = (
    "ok",
    "not_found",
    "client_error",
    "rate_limited",
    "server_error",
    "timeout",
    "error",
    "busy",
    "budget",
)
CACHE_OUTCOMES = ("hit", "miss")
SUGGEST_SOURCES = ("own", "ancestor", "upstream")
BUDGET_KINDS = ("read", "write")
CREATE_OUTCOMES = ("created", "failed", "deadline")
RESOURCE_TYPES = ("Document", "Component")
FETCH_PURPOSES = ("manifest", "image_info", "thumbnail", "biblissima")
FETCH_OUTCOMES = (
    "ok",
    "http_error",
    "unsafe",
    "too_large",
    "budget",
    "timeout",
    "error",
)
SSRF_REASONS = ("scheme", "malformed", "host", "port", "dns", "private", "redirects")
TASK_PREFIXES = ("manuspectrum.", "arches.")
TASK_OUTCOMES = ("success", "failure", "retry")
INDEX_MODES = ("transaction", "resource")
INDEX_OUTCOMES = ("indexed", "not_found", "failed")
READYZ_COMPONENTS = (
    "postgres",
    "elasticsearch",
    "celery-broker",
    "redis-broker",
    "redis-cache",
    "cantaloupe",
)

SECONDS_UPSTREAM = (0.1, 0.25, 0.5, 1, 2, 4, 8, 15, 30)
SECONDS_BUNDLE = (1, 2, 3, 5, 8, 13, 21, 34, 55, 89)
SECONDS_TASK = (0.1, 0.5, 1, 5, 15, 60, 300, 900, 3600)
MIB = 1024 * 1024
BYTES_EXPORT = tuple(n * MIB for n in (1, 5, 10, 25, 50, 100, 250, 500))


def bounded(value, allowed):
    """*value* as a string when it is in *allowed*, else ``"other"``."""
    value = "" if value is None else str(value)
    return value if value in allowed else OTHER


def language_label(code):
    return bounded(code, [language for language, _ in settings.LANGUAGES])


def memo_label(key):
    """The known memo prefix of the cache *key* (longest first), else ``"other"``."""
    key = str(key)
    for name in _MEMO_BY_LENGTH:
        if key == name or key.startswith(name + ":"):
            return name
    return OTHER


def log_source(logger_name):
    return bounded(str(logger_name).split(".", 1)[0], LOG_SOURCES)


def task_label(name):
    """A Celery task name under a known prefix (at most 100 characters), else ``"other"``."""
    if isinstance(name, str) and len(name) <= 100 and name.startswith(TASK_PREFIXES):
        return name
    return OTHER


def tier_label(n):
    if n == "full":
        return "full"
    return bounded(n, [str(tier) for tier in settings.SPECTRUM_PREVIEW_TIERS])


def gauge(name, documentation, labelnames=(), *, mode):
    """A Gauge aggregated across processes by *mode* (``livesum`` or ``mostrecent``)."""
    if mode not in GAUGE_MODES:
        raise ValueError(f"gauge {name}: multiprocess mode {mode!r} is not allowed")
    return Gauge(name, documentation, labelnames, multiprocess_mode=mode)


# Web process
INFLIGHT_REQUESTS = gauge(
    "manuspectrum_inflight_requests",
    "Requests a web process is serving, streamed bodies included.",
    mode="livesum",
)
LOG_RECORDS = Counter(
    "manuspectrum_log_records",
    "Log records at WARNING or above.",
    ["level", "source"],
)
READYZ_UP = gauge(
    "manuspectrum_readyz_component_up",
    "1 when the component answered the last /readyz probe, else 0.",
    ["component"],
    mode="mostrecent",
)

# Memos, IIIF and access
MEMO_LOOKUPS = Counter(
    "manuspectrum_memo_lookups",
    "get_or_build lookups by memo and outcome (hit, built here, waited for another build).",
    ["memo", "outcome"],
)
IIIF_ANSWERS = Counter(
    "manuspectrum_iiif_answers",
    "Memoised IIIF answers: shared (visitor's view), private (built for the reader), 304.",
    ["mode"],
)
IIIF_AUTH_TOKENS = Counter(
    "manuspectrum_iiif_auth_tokens",
    "IIIF Auth token requests by outcome.",
    ["outcome"],
)
READ_REFUSALS = Counter(
    "manuspectrum_read_refusals",
    "Reads refused by the permission guard, by surface.",
    ["surface"],
)
AUTH_LOGINS = Counter(
    "manuspectrum_auth_logins",
    "Login attempts by outcome.",
    ["outcome"],
)
SPECTRUM_PREVIEWS = Counter(
    "manuspectrum_spectrum_previews",
    "Spectrum previews served, by point tier.",
    ["tier"],
)

# Explorer
EXPLORER_BUNDLE_BUILD_SECONDS = Histogram(
    "manuspectrum_explorer_bundle_build_seconds",
    "Duration of one Explorer corpus bundle build.",
    ["language"],
    buckets=SECONDS_BUNDLE,
)
EXPLORER_BUNDLE_BYTES = gauge(
    "manuspectrum_explorer_bundle_bytes",
    "Stored (packed) size of the last Explorer corpus bundle built.",
    ["language"],
    mode="mostrecent",
)
EXPLORER_BUNDLE_ROWS = gauge(
    "manuspectrum_explorer_bundle_rows",
    "Analyses in the last Explorer corpus bundle built.",
    ["language"],
    mode="mostrecent",
)
EXPLORER_BUNDLE_BUILDS = Counter(
    "manuspectrum_explorer_bundle_builds",
    "Explorer corpus bundle builds by reason and place (request or background thread).",
    ["language", "reason", "background"],
)
EXPLORER_STALE_SERVED = Counter(
    "manuspectrum_explorer_stale_served",
    "Explorer answers given from the previous bundle while a rebuild ran.",
    ["language"],
)
EXPLORER_REBUILD_FAILURES = Counter(
    "manuspectrum_explorer_rebuild_failures",
    "Background Explorer rebuilds that raised or returned nothing.",
    ["language"],
)
EXPLORER_EXPORT_BYTES = Histogram(
    "manuspectrum_explorer_export_bytes",
    "Size of the Explorer data packages streamed.",
    buckets=BYTES_EXPORT,
)

# Biblissima
BIBLISSIMA_UPSTREAM_REQUESTS = Counter(
    "manuspectrum_biblissima_upstream_requests",
    "Outbound Biblissima calls by endpoint family and outcome.",
    ["endpoint", "outcome"],
)
BIBLISSIMA_UPSTREAM_LATENCY = Histogram(
    "manuspectrum_biblissima_upstream_latency_seconds",
    "Duration of the outbound Biblissima calls that were made.",
    ["endpoint"],
    buckets=SECONDS_UPSTREAM,
)
BIBLISSIMA_SLOT_TIMEOUTS = Counter(
    "manuspectrum_biblissima_slot_timeouts",
    "Biblissima calls refused because no concurrency slot freed in time.",
)
BIBLISSIMA_INFLIGHT = gauge(
    "manuspectrum_biblissima_inflight",
    "Biblissima concurrency slots held.",
    mode="livesum",
)
BIBLISSIMA_CACHE = Counter(
    "manuspectrum_biblissima_cache",
    "Biblissima cache lookups by outcome.",
    ["outcome"],
)
BIBLISSIMA_SUGGEST_PREFIX = Counter(
    "manuspectrum_biblissima_suggest_prefix",
    "Suggest prefix entries: the query's own, an ancestor's, or fetched upstream.",
    ["source"],
)
UPSTREAM_BUDGET_SPENT = Counter(
    "manuspectrum_upstream_budget_spent",
    "Upstream budgets whose deadline had passed when their block ended.",
    ["kind"],
)
BIBLISSIMA_CREATED_ITEMS = Counter(
    "manuspectrum_biblissima_created_items",
    "Items of Biblissima create-all requests by outcome.",
    ["resource_type", "outcome"],
)

# Outbound fetches
OUTBOUND_FETCHES = Counter(
    "manuspectrum_outbound_fetches",
    "Guarded outbound fetches (safe_fetch) by purpose and outcome.",
    ["purpose", "outcome"],
)
OUTBOUND_FETCH_SECONDS = Histogram(
    "manuspectrum_outbound_fetch_seconds",
    "Duration of guarded outbound fetches.",
    ["purpose"],
    buckets=SECONDS_UPSTREAM,
)
SSRF_REJECTIONS = Counter(
    "manuspectrum_ssrf_rejections",
    "Outbound URLs refused by the SSRF guard, by reason.",
    ["reason"],
)

# Celery
CELERY_TASKS = Counter(
    "manuspectrum_celery_tasks",
    "Celery tasks run, by task and outcome.",
    ["task", "outcome"],
)
CELERY_TASK_SECONDS = Histogram(
    "manuspectrum_celery_task_seconds",
    "Run time of Celery tasks.",
    ["task"],
    buckets=SECONDS_TASK,
)
INDEX_RESOURCES = Counter(
    "manuspectrum_index_resources",
    "Resources (or transactions) indexed by the index_resources task.",
    ["mode", "outcome"],
)
DATA_CHANGE_ROWS = gauge(
    "manuspectrum_data_change_rows",
    "Rows of the ms_data_change ledger after the last prune.",
    mode="mostrecent",
)
DATA_CHANGE_PRUNED = gauge(
    "manuspectrum_data_change_pruned_timestamp_seconds",
    "Unix time of the last ms_data_change prune.",
    mode="mostrecent",
)
