import threading
import uuid
from unittest.mock import MagicMock, patch

from django.contrib.auth.models import AnonymousUser
from django.core.cache import cache
from django.test import RequestFactory, TestCase, override_settings

from manuspectrum.iiif import memo
from manuspectrum.utils.cache import get_or_build
from tests.observability_helpers import delta


class MemoLookupTests(TestCase):
    def setUp(self):
        cache.clear()

    def test_built_then_hit_under_the_memo_prefix(self):
        with delta(
            "manuspectrum_memo_lookups_total", memo="model-graph", outcome="built"
        ) as built:
            get_or_build("model-graph:fr:abc", lambda: {"x": 1}, 60)
        with delta(
            "manuspectrum_memo_lookups_total", memo="model-graph", outcome="hit"
        ) as hit:
            get_or_build("model-graph:fr:abc", lambda: {"x": 2}, 60)
        self.assertEqual((built.value, hit.value), (1, 1))

    def test_a_waiter_that_sees_the_value_counts_waited(self):
        cache.add("iiif:k:lock", 1, 60)
        threading.Timer(0.05, lambda: cache.set("iiif:k", {"v": 1}, 60)).start()
        with delta(
            "manuspectrum_memo_lookups_total", memo="iiif", outcome="waited"
        ) as waited:
            value = get_or_build("iiif:k", lambda: {"v": 2}, 60, wait=2, poll=0.01)
        self.assertEqual((value, waited.value), ({"v": 1}, 1))


@override_settings(IIIF_MEMO_TTL=60, IIIF_BUILD_WAIT=1)
class IiifAnswerTests(TestCase):
    def setUp(self):
        cache.clear()
        self.request = RequestFactory().get("/iiif/v3/x")

    def test_private_shared_and_not_modified(self):
        with delta("manuspectrum_iiif_answers_total", mode="private") as private:
            memo.answer(
                self.request,
                memo.Gate(False, ()),
                "k",
                ("a",),
                lambda: {"a": 1},
                content_type="application/json",
            )
        gate = memo.Gate(True, ("v", "e", "d", "l", "c"))
        with delta("manuspectrum_iiif_answers_total", mode="shared") as shared:
            response = memo.answer(
                self.request,
                gate,
                "k",
                ("a",),
                lambda: {"a": 1},
                content_type="application/json",
            )
        held = RequestFactory().get("/iiif/v3/x", HTTP_IF_NONE_MATCH=response["ETag"])
        with delta(
            "manuspectrum_iiif_answers_total", mode="not_modified"
        ) as not_modified:
            memo.answer(
                held,
                gate,
                "k",
                ("a",),
                lambda: {"a": 1},
                content_type="application/json",
            )
        self.assertEqual((private.value, shared.value, not_modified.value), (1, 1, 1))


class IiifTokenTests(TestCase):
    def test_a_refused_token_request_is_counted_by_code(self):
        from manuspectrum.views.iiif.auth import TokenView

        request = RequestFactory().get("/iiif/auth/1/token")
        request.user = AnonymousUser()
        with delta(
            "manuspectrum_iiif_auth_tokens_total", outcome="invalidRequest"
        ) as refused:
            TokenView.as_view()(request)
        self.assertEqual(refused.value, 1)


class ReadRefusalTests(TestCase):
    def test_summary(self):
        from manuspectrum.views.summary import SummaryView

        request = RequestFactory().get("/en/api/summary/x")
        request.user = AnonymousUser()
        with (
            patch(
                "manuspectrum.views.summary.user_can_read_resource", return_value=False
            ),
            delta("manuspectrum_read_refusals_total", surface="summary") as refused,
        ):
            SummaryView().get(request, resourceid=str(uuid.uuid4()))
        self.assertEqual(refused.value, 1)

    def test_thumbnail_get_and_head(self):
        from manuspectrum.views.thumbnail import CachedThumbnailView

        request = RequestFactory().get("/en/thumbnail/x")
        request.user = AnonymousUser()
        with (
            patch(
                "manuspectrum.views.thumbnail.user_can_read_resource",
                return_value=False,
            ),
            delta("manuspectrum_read_refusals_total", surface="thumbnail") as refused,
        ):
            CachedThumbnailView().get(request, resource_id=str(uuid.uuid4()))
            CachedThumbnailView().head(request, resource_id=str(uuid.uuid4()))
        self.assertEqual(refused.value, 2)

    def test_iiif_file(self):
        from manuspectrum.iiif import data

        row = MagicMock()
        row.path.name = "uploadedfiles/a.csv"
        with (
            patch.object(data, "File") as files,
            patch.object(data, "file_allowed", return_value=False),
            delta("manuspectrum_read_refusals_total", surface="iiif_file") as refused,
        ):
            files.objects.filter.return_value.defer.return_value.select_related.return_value.first.return_value = (
                row
            )
            with self.assertRaises(data.Refused):
                data.readable_file(str(uuid.uuid4()), AnonymousUser())
        self.assertEqual(refused.value, 1)


@override_settings(SPECTRUM_PREVIEW_TIERS=[200, 4096])
class SpectrumPreviewTests(TestCase):
    def call(self, n, allowed=True):
        from manuspectrum.views import spectrum_preview

        request = RequestFactory().get("/api/spectrum-preview/x", {"n": n})
        request.user = AnonymousUser()
        record = ("/tmp/a.csv", str(uuid.uuid4()), None, str(uuid.uuid4()), "a.csv")
        with (
            patch.object(spectrum_preview, "file_record", return_value=record),
            patch.object(spectrum_preview, "file_allowed", return_value=allowed),
            patch.object(
                spectrum_preview, "_series", return_value={"x": [1], "y": [2]}
            ),
            patch.object(
                spectrum_preview, "_full_series", return_value={"x": [1], "y": [2]}
            ),
            patch.object(spectrum_preview, "renderer_config", return_value=None),
        ):
            return spectrum_preview.SpectrumPreviewView().get(
                request, file_id=str(uuid.uuid4())
            )

    def test_tiers_and_refusals(self):
        cache.clear()
        with (
            delta("manuspectrum_spectrum_previews_total", tier="200") as tier200,
            delta("manuspectrum_spectrum_previews_total", tier="full") as full,
        ):
            self.call("200")
            self.call("full")
        with delta(
            "manuspectrum_read_refusals_total", surface="spectrum_preview"
        ) as refused:
            self.call("200", allowed=False)
        self.assertEqual((tier200.value, full.value, refused.value), (1, 1, 1))


class LoginTests(TestCase):
    def test_failed_and_successful_logins(self):
        from django.contrib.auth import get_user_model

        get_user_model().objects.create_user("obs-login", password="a-long-password-1")
        with delta("manuspectrum_auth_logins_total", outcome="failure") as failed:
            self.client.login(username="obs-login", password="wrong")
        with delta("manuspectrum_auth_logins_total", outcome="success") as succeeded:
            self.client.login(username="obs-login", password="a-long-password-1")
        self.assertEqual((failed.value, succeeded.value), (1, 1))
