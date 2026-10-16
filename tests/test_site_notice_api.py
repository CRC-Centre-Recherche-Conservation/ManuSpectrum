import json
from datetime import timedelta

from django.contrib.auth.models import User
from django.core.cache import cache
from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

from manuspectrum.models import SiteNotice, site_now
from manuspectrum.views.site_notice import MEMO_KEY

URL = "/api/site-notice"


def make(offset_days=1, hours=2, **overrides):
    start = site_now() + timedelta(days=offset_days)
    fields = {
        "text_en": "The site will be unavailable.",
        "text_fr": "Le site sera indisponible.",
        "starts_at": start,
        "ends_at": start + timedelta(hours=hours),
    }
    fields.update(overrides)
    return SiteNotice.objects.create(**fields)


class SiteNoticeApiTests(TestCase):
    def setUp(self):
        cache.delete(MEMO_KEY)
        self.addCleanup(cache.delete, MEMO_KEY)

    def get(self, **extra):
        return self.client.get(URL, **extra)

    def test_route_is_language_neutral(self):
        self.assertEqual(reverse("site-notice"), URL)

    def test_payload_shape(self):
        notice = make(
            link_url="https://example.org/more",
            link_label_en="Details",
            link_label_fr="Détails",
        )
        response = self.get()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "application/json; charset=utf-8")
        data = json.loads(response.content)
        self.assertEqual(data["timeZone"], "Europe/Paris")
        self.assertNotIn("preview", data)
        (item,) = data["notices"]
        self.assertEqual(item["id"], notice.pk)
        self.assertEqual(item["version"], notice.version)
        self.assertEqual(item["kind"], "maintenance")
        self.assertEqual(item["display"], "event")
        self.assertRegex(item["start"], r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ$")
        self.assertEqual(item["reminders"], [604800, 86400, 3600, 600])
        self.assertEqual(item["text"]["fr"], "Le site sera indisponible.")
        self.assertEqual(
            item["link"],
            {
                "url": "https://example.org/more",
                "label": {"en": "Details", "fr": "Détails"},
            },
        )

    def test_a_shown_once_notice_carries_its_display_and_no_reminders(self):
        make(display="once", reminders="")
        (item,) = json.loads(self.get().content)["notices"]
        self.assertEqual(item["display"], "once")
        self.assertEqual(item["reminders"], [])

    def test_start_is_converted_from_paris_time_to_utc(self):
        from datetime import datetime

        make(
            starts_at=datetime(2026, 11, 12, 8, 0),
            ends_at=datetime(2026, 11, 12, 10, 0),
        )
        SiteNotice.objects.update(ends_at=site_now() + timedelta(days=400))
        cache.delete(MEMO_KEY)
        item = json.loads(self.get().content)["notices"][0]
        self.assertEqual(item["start"], "2026-11-12T07:00:00Z")

    def test_link_is_null_without_a_url(self):
        make()
        self.assertIsNone(json.loads(self.get().content)["notices"][0]["link"])

    def test_labels_come_in_both_languages_without_html(self):
        make()
        labels = json.loads(self.get().content)["labels"]
        self.assertEqual(set(labels), {"en", "fr"})
        for code in labels:
            self.assertEqual(
                set(labels[code]),
                {"region", "dismiss", "live", "until", "kind"},
            )
            self.assertEqual(
                set(labels[code]["kind"]), {"info", "maintenance", "important"}
            )
        self.assertEqual(labels["en"]["kind"]["maintenance"], "Maintenance")
        self.assertEqual(labels["fr"]["dismiss"], "Fermer cette annonce")
        self.assertIn("{time}", labels["fr"]["until"])

    def test_inactive_and_ended_are_excluded_and_order_follows_start(self):
        late = make(offset_days=5, text_en="late")
        soon = make(offset_days=1, text_en="soon")
        make(offset_days=2, is_active=False, text_en="draft")
        make(offset_days=-3, hours=1, text_en="over")
        texts = [n["text"]["en"] for n in json.loads(self.get().content)["notices"]]
        self.assertEqual(texts, [soon.text_en, late.text_en])

    def test_an_event_in_progress_is_listed(self):
        make(offset_days=0, hours=3)
        SiteNotice.objects.update(starts_at=site_now() - timedelta(hours=1))
        cache.delete(MEMO_KEY)
        self.assertEqual(len(json.loads(self.get().content)["notices"]), 1)

    def test_at_most_five_notices(self):
        for day in range(1, 8):
            make(offset_days=day)
        self.assertEqual(len(json.loads(self.get().content)["notices"]), 5)

    def test_public_cache_headers_and_etag(self):
        make()
        response = self.get()
        self.assertEqual(response["Cache-Control"], "public, max-age=60")
        self.assertRegex(response["ETag"], r'^"[0-9a-f]{20}"$')

    def test_matching_etag_gets_304_without_body(self):
        make()
        etag = self.get()["ETag"]
        response = self.get(HTTP_IF_NONE_MATCH=etag)
        self.assertEqual(response.status_code, 304)
        self.assertEqual(response.content, b"")
        self.assertEqual(response["ETag"], etag)

    def test_empty_list_when_nothing_is_published(self):
        self.assertEqual(json.loads(self.get().content)["notices"], [])

    def test_other_methods_are_refused(self):
        for method in ("post", "put", "delete"):
            with self.subTest(method=method):
                self.assertEqual(getattr(self.client, method)(URL).status_code, 405)

    def test_second_read_hits_the_memo(self):
        make()
        self.get()
        with CaptureQueriesContext(connection) as queries:
            self.assertEqual(self.get().status_code, 200)
        self.assertFalse(
            [q for q in queries if "ms_site_notice" in q["sql"]],
            queries.captured_queries,
        )

    def test_memo_lookups_are_counted_under_the_site_notice_name(self):
        from manuspectrum.observability import metrics

        self.assertEqual(metrics.memo_label(MEMO_KEY), "site-notice")

    def test_saving_refreshes_the_memo(self):
        notice = make(text_en="first")
        self.get()
        with self.captureOnCommitCallbacks(execute=True):
            notice.text_en = "second"
            notice.save()
        texts = [n["text"]["en"] for n in json.loads(self.get().content)["notices"]]
        self.assertEqual(texts, ["second"])

    def test_deleting_refreshes_the_memo(self):
        notice = make()
        self.get()
        with self.captureOnCommitCallbacks(execute=True):
            notice.delete()
        self.assertEqual(json.loads(self.get().content)["notices"], [])


class RefreshMemoTests(TestCase):
    def setUp(self):
        cache.delete(MEMO_KEY)
        self.addCleanup(cache.delete, MEMO_KEY)

    def test_a_save_stores_the_fresh_payload_in_the_memo(self):
        make(text_en="first")
        with self.captureOnCommitCallbacks(execute=True):
            make(text_en="second")
        stored = cache.get(MEMO_KEY)
        texts = [n["text"]["en"] for n in json.loads(stored["body"])["notices"]]
        self.assertEqual(texts, ["first", "second"])
        with CaptureQueriesContext(connection) as queries:
            served = json.loads(self.client.get(URL).content)
        self.assertEqual(
            [q for q in queries.captured_queries if "ms_site_notice" in q["sql"]], []
        )
        self.assertEqual(len(served["notices"]), 2)

    def test_a_stale_in_flight_payload_is_replaced_by_the_save(self):
        stale = json.dumps({"notices": []})
        cache.set(MEMO_KEY, {"body": stale, "etag": '"stale"'}, 300)
        with self.captureOnCommitCallbacks(execute=True):
            make()
        self.assertEqual(len(json.loads(cache.get(MEMO_KEY)["body"])["notices"]), 1)


class PreviewTests(TestCase):
    def setUp(self):
        cache.delete(MEMO_KEY)
        self.staff = User.objects.create_user("editor", password="x", is_staff=True)
        self.plain = User.objects.create_user("reader", password="x")
        self.notice = make(offset_days=-9, hours=1, is_active=False)

    def test_anonymous_preview_is_refused_without_body(self):
        response = self.client.get(URL, {"preview": self.notice.pk})
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.content, b"")

    def test_non_staff_preview_is_refused(self):
        self.client.force_login(self.plain)
        self.assertEqual(
            self.client.get(URL, {"preview": self.notice.pk}).status_code, 403
        )

    def test_staff_sees_an_inactive_ended_notice_privately(self):
        self.client.force_login(self.staff)
        response = self.client.get(URL, {"preview": self.notice.pk})
        self.assertEqual(response.status_code, 200)
        data = json.loads(response.content)
        self.assertTrue(data["preview"])
        self.assertEqual([n["id"] for n in data["notices"]], [self.notice.pk])
        self.assertIn("no-store", response["Cache-Control"])
        self.assertIn("private", response["Cache-Control"])
        self.assertNotIn("ETag", response)

    def test_preview_never_fills_the_memo(self):
        self.client.force_login(self.staff)
        self.client.get(URL, {"preview": self.notice.pk})
        self.assertIsNone(cache.get(MEMO_KEY))
        self.assertEqual(json.loads(self.client.get(URL).content)["notices"], [])

    def test_unknown_or_malformed_preview_is_404_for_staff(self):
        self.client.force_login(self.staff)
        for value in ("999999", "abc", ""):
            with self.subTest(value=value):
                self.assertEqual(
                    self.client.get(URL, {"preview": value}).status_code, 404
                )
