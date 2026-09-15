"""Cache keys and their inputs on the Biblissima proxy (PR-8)."""

from unittest.mock import MagicMock, patch

from django.contrib.auth.models import Group, User
from django.core.cache import cache
from django.test import TestCase

from manuspectrum.views import biblissima_proxy as bp

HEX40 = "a" * 40


def _editor(username):
    user = User.objects.create_user(username, password="pw")
    user.groups.add(Group.objects.get(name="Resource Editor"))
    return user


class InputShapeTests(TestCase):
    def setUp(self):
        cache.clear()
        self.client.force_login(_editor("cache_hardening_editor"))

    def tearDown(self):
        cache.clear()

    def test_a_malformed_portal_hash_is_refused_before_any_fetch(self):
        with patch.object(bp, "_bib_request") as fetch:
            for bad in (
                "mdataXYZ",
                "mdata" + HEX40 + "x",
                "../etc",
                "mdata" + "A" * 40,
            ):
                resp = self.client.get(
                    "/api/biblissima/manuscript-illuminations", {"portalHash": bad}
                )
                self.assertEqual(resp.status_code, 400, bad)
        fetch.assert_not_called()

    def test_a_well_formed_portal_hash_reaches_the_portal(self):
        with patch.object(
            bp, "_bib_request", return_value=MagicMock(text="<html></html>")
        ) as fetch:
            resp = self.client.get(
                "/api/biblissima/manuscript-illuminations",
                {"portalHash": "mdata" + HEX40},
            )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(fetch.call_count, 1)

    def test_a_malformed_descriptor_is_refused(self):
        with patch.object(bp, "_bib_request") as fetch:
            for bad in ("desc123", "desc" + HEX40 + ",zzz", HEX40[:-1]):
                resp = self.client.get("/api/biblissima/search", {"descriptors": bad})
                self.assertEqual(resp.status_code, 400, bad)
        fetch.assert_not_called()

    def test_too_many_descriptors_are_refused(self):
        many = ",".join(f"desc{i:040x}" for i in range(bp._MAX_SEARCH_DESCRIPTORS + 1))
        resp = self.client.get("/api/biblissima/search", {"descriptors": many})
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.json()["error"], "too many descriptors")
        self.assertEqual(resp.json()["max"], bp._MAX_SEARCH_DESCRIPTORS)

    def test_exactly_the_maximum_number_of_descriptors_is_accepted(self):
        enough = ",".join(f"desc{i:040x}" for i in range(bp._MAX_SEARCH_DESCRIPTORS))
        with (
            patch.object(bp, "_fetch_biblissima_canvases", return_value=[]),
            patch.object(bp, "_enrich_canvases"),
        ):
            resp = self.client.get("/api/biblissima/search", {"descriptors": enough})
        self.assertEqual(resp.status_code, 200)

    def test_a_malformed_qid_is_refused_before_any_fetch(self):
        with patch.object(bp, "_bib_request") as fetch:
            for bad in ("Q12|Q13", "x"):
                resp = self.client.get(f"/api/biblissima/entity/{bad}")
                self.assertEqual(resp.status_code, 400, bad)
        fetch.assert_not_called()

    def test_a_well_formed_qid_reaches_the_wikibase(self):
        resp = MagicMock()
        resp.json.return_value = {"entities": {"Q27392": {}}}
        with patch.object(bp, "_bib_request", return_value=resp) as fetch:
            page = self.client.get("/api/biblissima/entity/Q27392")
        self.assertNotEqual(page.status_code, 400)
        self.assertEqual(fetch.call_count, 1)

    def test_a_malformed_ifdata_hash_is_refused(self):
        with patch.object(bp, "_bib_request") as fetch:
            resp = self.client.get("/api/biblissima/illumination/ifdataXYZ")
        self.assertEqual(resp.status_code, 400)
        fetch.assert_not_called()


class HashedKeyTests(TestCase):
    def setUp(self):
        cache.clear()

    def tearDown(self):
        cache.clear()

    def test_manifest_canvas_key_never_carries_the_url(self):
        manifest = {
            "sequences": [
                {"canvases": [{"@id": "https://example/c/1", "width": 1, "height": 2}]}
            ]
        }
        resp = MagicMock()
        resp.json.return_value = manifest
        with (
            patch.object(bp, "_bib_request", return_value=resp),
            patch.object(bp.cache, "set", wraps=bp.cache.set) as set_,
        ):
            bp._fetch_canvas_dimensions(
                "https://evil.example/a b?c=d", "1r", MagicMock()
            )
        key = set_.call_args[0][0]
        self.assertNotIn("evil.example", key)
        self.assertNotIn(" ", key)
        self.assertTrue(key.startswith("biblissima:manifest-canvas:"))

    def test_search_raw_key_never_carries_the_descriptor_list(self):
        self.client.force_login(_editor("cache_hardening_search_editor"))
        with (
            patch.object(bp, "_fetch_biblissima_canvases", return_value=[]),
            patch.object(bp.cache, "set", wraps=bp.cache.set) as set_,
        ):
            self.client.get("/api/biblissima/search", {"descriptors": "desc" + HEX40})
        keys = [call.args[0] for call in set_.call_args_list]
        raw = [k for k in keys if k.startswith("biblissima:search:raw:")]
        self.assertEqual(len(raw), 1)
        self.assertNotIn(HEX40, raw[0])

    def test_iiif_manifest_key_never_carries_the_url(self):
        from manuspectrum.views.iiif_annotation import IIIFAnnotationMixin

        with (
            patch(
                "manuspectrum.utils.iiif_tools.CanvasIIIF.fetch_manifest",
                return_value={"@id": "m"},
            ),
            patch(
                "manuspectrum.views.iiif_annotation.cache.set", wraps=cache.set
            ) as set_,
        ):
            IIIFAnnotationMixin()._get_manifest_data("https://evil.example/m?x=1")
        key = set_.call_args[0][0]
        self.assertNotIn("evil.example", key)
        self.assertTrue(key.startswith("iiif_manifest_data:"))
