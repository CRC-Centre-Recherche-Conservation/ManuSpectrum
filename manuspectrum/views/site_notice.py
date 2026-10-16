"""The site announcement: its JSON payload, its memo and its snapshot for nginx.

``GET /api/site-notice`` lists the announcements that have not ended, with the
labels of the banner in every language; the browser decides what to show from
the clock of the response. The answer is the same for every reader, so it is
memoised, carries an ETag and is ``public``. ``?preview=<id>`` returns one
announcement whatever its dates for a staff user and is never stored.

Each save of an announcement calls ``refresh``: the memo is replaced by the
fresh payload and the payload is written to ``SITE_NOTICE_SNAPSHOT_DIR/notice.json`` (atomic
replace), the file nginx serves while Django cannot answer.
"""

import hashlib
import json
import logging
import os
import tempfile
from zoneinfo import ZoneInfo

from django.conf import settings
from django.core.cache import cache
from django.http import HttpResponse, HttpResponseForbidden, HttpResponseNotFound
from django.http import HttpResponseNotModified
from django.utils import translation
from django.utils.cache import patch_cache_control
from django.utils.translation import gettext, pgettext
from django.views import View

from manuspectrum.models import SiteNotice, site_now
from manuspectrum.utils.cache import etag_already_held, get_or_build, stable_cache_key

logger = logging.getLogger(__name__)

LIMIT = 5
SNAPSHOT_NAME = "notice.json"
MEMO_KEY = stable_cache_key("site-notice")


def _utc(moment):
    """ISO UTC of a naive datetime typed as site time."""
    aware = moment.replace(tzinfo=ZoneInfo(settings.SITE_NOTICE_TIME_ZONE))
    return aware.astimezone(ZoneInfo("UTC")).strftime("%Y-%m-%dT%H:%M:%SZ")


def _labels():
    """The strings of the banner, one set per language of the site."""
    labels = {}
    for code, _name in settings.LANGUAGES:
        with translation.override(code):
            labels[code] = {
                "region": gettext("Site announcement"),
                "dismiss": gettext("Dismiss this announcement"),
                "upcoming": pgettext("site notice", "Upcoming"),
                "live": gettext("In progress"),
                "until": gettext("until {time}"),
                "kind": {
                    SiteNotice.INFO: gettext("Information"),
                    SiteNotice.MAINTENANCE: gettext("Maintenance"),
                    SiteNotice.IMPORTANT: gettext("Important"),
                },
            }
    return labels


def _item(notice):
    link = None
    if notice.link_url:
        link = {
            "url": notice.link_url,
            "label": {"en": notice.link_label_en, "fr": notice.link_label_fr},
        }
    return {
        "id": notice.pk,
        "version": notice.version,
        "kind": notice.kind,
        "display": notice.display,
        "start": _utc(notice.starts_at),
        "end": _utc(notice.ends_at),
        "reminders": notice.reminder_seconds(),
        "text": {"en": notice.text_en, "fr": notice.text_fr},
        "link": link,
    }


def payload_for(notices, *, preview=False):
    payload = {
        "timeZone": settings.SITE_NOTICE_TIME_ZONE,
        "notices": [_item(n) for n in notices],
        "labels": _labels(),
    }
    if preview:
        payload["preview"] = True
    return payload


def build_payload():
    """The payload of the announcements that are not over."""
    notices = SiteNotice.objects.filter(ends_at__gt=site_now()).order_by("starts_at")[
        :LIMIT
    ]
    return payload_for(notices)


def _encode(payload):
    body = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    etag = (
        '"%s"'
        % hashlib.sha1(body.encode("utf-8"), usedforsecurity=False).hexdigest()[:20]
    )
    return {"body": body, "etag": etag}


def write_snapshot(payload):
    """Write the payload where nginx reads it; returns the path, or None.

    No-op without ``SITE_NOTICE_SNAPSHOT_DIR``. The file appears whole
    (temporary file, then ``os.replace``); a failure is logged, never raised.
    """
    directory = settings.SITE_NOTICE_SNAPSHOT_DIR
    if not directory:
        return None
    target = os.path.join(directory, SNAPSHOT_NAME)
    temporary = None
    try:
        handle, temporary = tempfile.mkstemp(
            dir=directory, prefix="notice.", suffix=".tmp"
        )
        with os.fdopen(handle, "w", encoding="utf-8") as stream:
            stream.write(_encode(payload)["body"])
        os.chmod(temporary, 0o644)
        os.replace(temporary, target)
    except OSError:
        logger.exception("The site announcement snapshot could not be written")
        if temporary:
            try:
                os.unlink(temporary)
            except OSError:
                pass
        return None
    return target


def refresh():
    """Store the fresh payload in the memo and write the snapshot from it.

    The memo is set rather than dropped: it replaces a payload already
    stored. A build racing the commit can still store the previous payload
    until ``SITE_NOTICE_TTL``. A failure to build drops the memo and is
    logged, never raised.
    """
    try:
        payload = build_payload()
    except Exception:  # noqa: BLE001 — a save must not fail on the snapshot
        cache.delete(MEMO_KEY)
        logger.exception("The site announcement snapshot could not be built")
        return None
    cache.set(MEMO_KEY, _encode(payload), settings.SITE_NOTICE_TTL)
    return write_snapshot(payload)


class SiteNoticeView(View):
    """Language-neutral JSON of the announcements; GET only."""

    http_method_names = ["get", "head", "options"]

    def get(self, request):
        preview = request.GET.get("preview")
        if preview is not None:
            return self._preview(request, preview)
        entry = get_or_build(
            MEMO_KEY,
            lambda: _encode(build_payload()),
            settings.SITE_NOTICE_TTL,
        )
        if etag_already_held(request, entry["etag"]):
            response = HttpResponseNotModified()
        else:
            response = HttpResponse(
                entry["body"], content_type="application/json; charset=utf-8"
            )
        response["ETag"] = entry["etag"]
        patch_cache_control(response, public=True, max_age=60)
        return response

    @staticmethod
    def _preview(request, preview):
        user = getattr(request, "user", None)
        if not (user and user.is_authenticated and user.is_staff):
            return HttpResponseForbidden()
        notice = (
            SiteNotice.objects.filter(pk=preview).first() if preview.isdigit() else None
        )
        if notice is None:
            return HttpResponseNotFound()
        response = HttpResponse(
            _encode(payload_for([notice], preview=True))["body"],
            content_type="application/json; charset=utf-8",
        )
        patch_cache_control(response, private=True, no_store=True)
        return response
