"""The share payload of a scope: citations, parts, availability, export estimate and product links.

Usage:
    python manage.py test tests.test_explorer_share --settings="tests.test_settings"
"""

from unittest import mock

from django.conf import settings
from django.test import override_settings

from arches.app.models.models import TileModel

from tests.explorer_contract import assert_shape
from tests.test_explorer_api import FETCH, MANIFEST_JSON, CorpusCase

CSV = "11111111-1111-4111-8111-111111111111"
UNKNOWN = "00000000-0000-4000-8000-00000000000a"


class ShareRouteTests(CorpusCase):
    def get(self, query):
        with mock.patch(FETCH, return_value=MANIFEST_JSON):
            return self.client.get(f"/en/api/explorer/share?{query}")

    def pk(self, key):
        return str(self.analyses[key].pk)

    def scopes(self):
        return (
            f"ids=an:{self.pk('open')}:-",
            f"document={self.documents['open'].pk}",
            f"project={self.projects['main'].pk}",
        )

    def test_share_payload_has_the_contract_shape(self):
        for query in self.scopes():
            with self.subTest(query=query):
                response = self.get(query)

                self.assertEqual(response.status_code, 200)
                payload = response.json()
                assert_shape(self, payload, "SharePayload")
                for citation in payload["citations"]:
                    assert_shape(self, citation, "Citation")
                for part in payload["parts"]:
                    assert_shape(self, part, "SharePart")
                for document in payload["export"]["documents"]:
                    assert_shape(self, document, "ShareDocument")
                self.assertTrue(payload["citations"])
                self.assertEqual(payload["scope"]["key"], query)

    def test_the_parts_are_the_scope_analyses_with_their_permalinks(self):
        payload = self.get(f"document={self.documents['open'].pk}").json()

        self.assertEqual(
            [p["id"] for p in payload["parts"]],
            [self.pk("on_document"), self.pk("open"), self.pk("draft")],
        )
        for part in payload["parts"]:
            self.assertEqual(
                part["permalink"],
                f"{settings.PUBLIC_SERVER_ADDRESS}report/{part['id']}",
            )
        self.assertEqual(payload["scope"]["drafts"], 1)
        self.assertEqual(payload["scope"]["characterizations"], 1)

    def test_a_visitor_gets_public_no_cache_with_an_etag(self):
        query = f"document={self.documents['open'].pk}"
        response = self.get(query)

        self.assertEqual(response["Cache-Control"], "public, no-cache")
        with mock.patch(FETCH, return_value=MANIFEST_JSON):
            again = self.client.get(
                f"/en/api/explorer/share?{query}", HTTP_IF_NONE_MATCH=response["ETag"]
            )
        self.assertEqual(again.status_code, 304)

    def test_a_connected_reader_gets_private_no_store(self):
        self.client.force_login(self.editor)

        response = self.get(f"document={self.documents['open'].pk}")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Cache-Control"], "private, no-store")
        self.assertNotIn("ETag", response)

    def test_unknown_and_embargoed_documents_answer_the_same_404(self):
        self.embargo(self.documents["embargoed"])

        unknown = self.get(f"document={UNKNOWN}")
        embargoed = self.get(f"document={self.documents['embargoed'].pk}")

        for response in (unknown, embargoed):
            self.assertEqual(response.status_code, 404)
            self.assertEqual(response.content, b"")
            self.assertEqual(response["Cache-Control"], "private, no-store")

    def test_no_scope_is_a_bad_request_without_body(self):
        for query in ("", "ids=", f"document={self.documents['open'].pk}&canvases=x"):
            with self.subTest(query=query):
                response = self.get(query)

                self.assertEqual(response.status_code, 400)
                self.assertEqual(response.content, b"")

    def test_one_citation_per_dataset(self):
        self.tile(
            self.analyses["on_document"],
            "dataset_url",
            {"url": "10.48579/pro/zeejth", "url_label": ""},
        )

        payload = self.get(f"document={self.documents['open'].pk}").json()

        self.assertEqual(
            [c["csl"]["id"] for c in payload["citations"]],
            ["10.48579/pro/zeejth", self.pk("draft")],
        )
        note = payload["citations"][0]["csl"]["note"]
        for key in ("open", "on_document"):
            self.assertIn(f"report/{self.pk(key)}", note)
        self.assertIn(
            f"{settings.PUBLIC_SERVER_ADDRESS}report/{self.documents['open'].pk}",
            payload["availability"],
        )
        self.assertIn("https://doi.org/10.48579/pro/zeejth", payload["availability"])

    def test_the_export_estimate_sums_the_kept_files(self):
        whole = self.get(f"ids=an:{self.pk('open')}:-").json()
        narrowed = self.get(f"ids=af:{self.pk('open')}:{CSV}").json()

        self.assertEqual(
            whole["export"],
            {"files": 2, "bytes": 4200 + 900, "overLimit": False, "documents": []},
        )
        self.assertEqual(whole["scope"]["spectra"], 1)
        self.assertEqual(
            (narrowed["export"]["files"], narrowed["export"]["bytes"]), (1, 4200)
        )

    def test_a_file_without_a_recorded_size_is_measured_in_storage(self):
        file_id = self.stored_file(
            self.analyses["on_document"], "extra.csv", b"x" * 300
        )
        tile = TileModel.objects.get(
            resourceinstance=self.analyses["on_document"],
            nodegroup_id=self.nodes[
                ("analysis", "measurement_point_data")
            ].nodegroup_id,
        )
        node = str(self.nodes[("analysis", "measurement_point_data")].nodeid)
        data = dict(tile.data)
        data[node] = [{k: v for k, v in e.items() if k != "size"} for e in data[node]]
        TileModel.objects.filter(pk=tile.pk).update(data=data)

        export = self.get(f"ids=af:{self.pk('on_document')}:{file_id}").json()["export"]

        self.assertEqual((export["files"], export["bytes"]), (1, 300))

    @override_settings(EXPLORER_EXPORT_MAX_BYTES=1)
    def test_over_the_limits_lists_per_document_exports(self):
        spanning = self.get(
            f"ids=an:{self.pk('open')}:-,an:{self.pk('embargoed')}:-"
        ).json()
        single = self.get(f"document={self.documents['open'].pk}").json()

        self.assertTrue(spanning["export"]["overLimit"])
        documents = spanning["export"]["documents"]
        self.assertEqual(
            sorted(d["id"] for d in documents),
            sorted(str(self.documents[k].pk) for k in ("open", "embargoed")),
        )
        for document in documents:
            self.assertEqual(
                document["url"],
                f"{settings.PUBLIC_SERVER_ADDRESS}api/explorer/export"
                f"?document={document['id']}&lang=en",
            )
        self.assertTrue(single["export"]["overLimit"])
        self.assertEqual(single["export"]["documents"], [])

    @override_settings(EXPLORER_EXPORT_MAX_FILES=1)
    def test_more_files_than_the_limit_is_over_the_limit(self):
        self.assertTrue(
            self.get(f"ids=an:{self.pk('open')}:-").json()["export"]["overLimit"]
        )

    def test_series_link_only_for_a_selection_with_spectra(self):
        with_spectra = self.get(f"ids=an:{self.pk('open')}:-").json()["links"]
        without = self.get(f"ids=an:{self.pk('on_document')}:-").json()["links"]
        document = self.get(f"document={self.documents['open'].pk}").json()["links"]

        self.assertEqual(
            with_spectra["seriesCsv"],
            f"{settings.PUBLIC_SERVER_ADDRESS}api/explorer/series.csv"
            f"?ids=an:{self.pk('open')}:-&lang=en",
        )
        self.assertIsNone(without["seriesCsv"])
        self.assertIsNone(document["seriesCsv"])
        self.assertEqual(
            with_spectra["manifest"],
            f"{settings.PUBLIC_SERVER_ADDRESS}iiif/v3/explorer-manifest"
            f"?ids=an:{self.pk('open')}:-&lang=en",
        )
        self.assertEqual(
            with_spectra["export"],
            f"{settings.PUBLIC_SERVER_ADDRESS}api/explorer/export"
            f"?ids=an:{self.pk('open')}:-&lang=en",
        )

    def test_a_visitor_sees_no_restricted_count(self):
        self.embargo(self.analyses["open"])
        query = f"document={self.documents['open'].pk}"

        visitor = self.get(query).json()
        self.client.force_login(self.editor)
        reader = self.get(query).json()

        self.assertEqual(visitor["scope"]["restrictedAvailable"], 0)
        self.assertFalse(visitor["scope"]["restricted"])
        self.assertIsNone(visitor["links"]["exportRestricted"])
        self.assertNotIn(self.pk("open"), str(visitor))
        self.assertEqual(reader["scope"]["restrictedAvailable"], 1)
        self.assertEqual(
            reader["links"]["exportRestricted"],
            f"{settings.PUBLIC_SERVER_ADDRESS}api/explorer/export"
            f"?{query}&restricted=1&lang=en",
        )
        self.assertNotIn(self.pk("open"), str(reader))

    def test_restricted_scope_is_marked_and_its_links_keep_it(self):
        self.embargo(self.analyses["open"])
        self.client.force_login(self.editor)

        payload = self.get(f"document={self.documents['open'].pk}&restricted=1").json()

        self.assertTrue(payload["scope"]["restricted"])
        self.assertIn(self.pk("open"), [p["id"] for p in payload["parts"]])
        self.assertIn("&restricted=1", payload["links"]["export"])
        self.assertIn("&restricted=1", payload["links"]["manifest"])
        self.assertIsNone(payload["links"]["exportRestricted"])

    def test_the_payload_is_in_the_request_language(self):
        query = f"ids=an:{self.pk('on_document')}:-"
        with mock.patch(FETCH, return_value=MANIFEST_JSON):
            french = self.client.get(f"/fr/api/explorer/share?{query}").json()

        self.assertTrue(
            french["availability"].startswith("Les données sont disponibles")
        )
        self.assertTrue(french["links"]["manifest"].endswith("&lang=fr"))
