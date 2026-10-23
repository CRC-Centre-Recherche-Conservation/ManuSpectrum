"""``POST /api/csp-report``: where browsers send the violations of the nginx
Content-Security-Policy-Report-Only header.

Both wire formats are read, whatever the declared content type (browsers send
``application/csp-report`` for ``report-uri`` and ``application/reports+json``
for the Reporting API, and a beacon may fall back to ``text/plain``):

- legacy: ``{"csp-report": {"effective-directive": ..., "blocked-uri": ...}}``;
- Reporting API: ``[{"type": "csp-violation", "body": {"effectiveDirective": ...}}]``.

Public and unauthenticated, so it keeps nothing a client could use to fill a
store: a violation becomes one increment of ``manuspectrum_csp_violations_total``
(closed vocabulary) and one INFO line holding the directive, the blocked target
reduced to a keyword or ``scheme://host``, the route name of the page (never
its path: activation and reset links carry a token in it) and the disposition. No address, user, user agent or sample is read.
At most ``MAX_VIOLATIONS`` reports are read per request and the body is read
bounded, never whole.
"""

import json
import logging
import unicodedata
from urllib.parse import urlsplit

from django.conf import settings
from django.http import HttpResponse
from django.urls import resolve
from django.utils import translation
from django.views import View
from django.views.decorators.csrf import csrf_exempt
from django.utils.decorators import method_decorator

from manuspectrum.observability import metrics

logger = logging.getLogger("manuspectrum.csp")

MAX_BODY_BYTES = 16 * 1024
MAX_VIOLATIONS = 20
MAX_FIELD_LENGTH = 200

BLOCKED_KEYWORDS = ("inline", "eval", "wasm-eval", "data", "blob", "self")
DISPOSITIONS = ("enforce", "report")


def clean(value):
    """*value* as a bounded string without control or format characters."""
    if not isinstance(value, str):
        return ""
    text = "".join(
        c
        for c in value
        if unicodedata.category(c)[0] != "C"
        and unicodedata.category(c) not in ("Zl", "Zp")
    )
    return text[:MAX_FIELD_LENGTH]


def field(body, *names):
    for name in names:
        value = body.get(name)
        if isinstance(value, str) and value:
            return value
    return ""


def directive_of(body):
    """The effective directive, else the first token of the violated one."""
    value = field(body, "effective-directive", "effectiveDirective")
    if not value:
        value = field(body, "violated-directive", "violatedDirective")
    return clean(value.split(None, 1)[0] if value.strip() else "").lower()


def blocked_target(value):
    """A keyword (``inline``, ``eval``, ``data``, ``blob``...) or ``scheme://host``.

    The path, the query, the port and any credentials of the blocked URL are
    dropped: they can carry an identifier or a token.
    """
    value = clean(value).strip()
    lowered = value.lower()
    if lowered in BLOCKED_KEYWORDS:
        return lowered
    if lowered.startswith(("data:", "blob:")):
        return lowered.split(":", 1)[0]
    try:
        parts = urlsplit(value)
        host = parts.hostname
    except ValueError:
        return metrics.OTHER
    if not parts.scheme or not host:
        return metrics.OTHER
    return f"{parts.scheme.lower()}://{host}"


def document_route(value):
    """The route name of the page that violated the policy, else ``other``.

    The path itself is never kept: it can hold a token or a resource id. The
    language prefix is resolved as Django resolves it, under the language it
    names (a prefixed pattern only matches while its language is active).
    """
    try:
        path = urlsplit(clean(value)).path
        code = path.split("/", 2)[1] if path.startswith("/") else ""
        if code in dict(settings.LANGUAGES):
            with translation.override(code):
                match = resolve(path)
        else:
            match = resolve(path)
        return clean(match.url_name or "") or metrics.OTHER
    except Exception:
        return metrics.OTHER


def violations(payload):
    """The violation bodies of a legacy report or of a Reporting API batch."""
    if isinstance(payload, dict):
        if isinstance(payload.get("csp-report"), dict):
            return [payload["csp-report"]]
        payload = [payload]
    if not isinstance(payload, list):
        return []
    found = []
    for report in payload:
        if (
            isinstance(report, dict)
            and report.get("type") == "csp-violation"
            and isinstance(report.get("body"), dict)
        ):
            found.append(report["body"])
    return found


@method_decorator(csrf_exempt, name="dispatch")
class CspReportView(View):
    http_method_names = ["post"]

    def post(self, request):
        try:
            declared = int(request.META.get("CONTENT_LENGTH") or 0)
        except ValueError:
            return HttpResponse(status=400)
        if declared > MAX_BODY_BYTES:
            return HttpResponse(status=413)
        raw = request.read(MAX_BODY_BYTES)
        try:
            payload = json.loads(raw)
        except (ValueError, RecursionError):
            return HttpResponse(status=400)
        for body in violations(payload)[:MAX_VIOLATIONS]:
            directive = metrics.bounded(directive_of(body), metrics.CSP_DIRECTIVES)
            metrics.CSP_VIOLATIONS.labels(directive=directive).inc()
            logger.info(
                "CSP violation: %s",
                directive,
                extra={
                    "directive": directive,
                    "blocked": blocked_target(
                        field(body, "blocked-uri", "blockedURL", "blockedURI")
                    ),
                    "document": document_route(
                        field(body, "document-uri", "documentURL", "documentURI")
                    ),
                    "disposition": metrics.bounded(
                        clean(field(body, "disposition")).lower(), DISPOSITIONS
                    ),
                },
            )
        return HttpResponse(status=204)
