"""The share payload of a scope: citations, availability, export estimate and product links.

Usage:
    python manage.py test tests.test_explorer_share --settings="tests.test_settings"
"""

import datetime
import json
import re
from unittest import mock

import bibtexparser
from urllib.parse import parse_qs, quote, urlsplit

from django.conf import settings
from django.db import connection
from django.http import QueryDict
from django.test import override_settings
from django.test.utils import CaptureQueriesContext

from arches.app.models.models import TileModel

from manuspectrum.views.explorer.citations import Home
from manuspectrum.views.explorer.scopes import (
    resolve_scope,
    scope_content,
    share_payload,
)
from tests.explorer_contract import assert_shape
from manuspectrum.views.explorer.service import manifest_json
from tests.explorer_fixtures import CANVAS, MANIFEST, XY_CONFIG_ID
from tests.test_explorer_api import FETCH, MANIFEST_JSON, CorpusCase

UNKNOWN = "00000000-0000-4000-8000-00000000000a"


def cited(citation):
    """The fields of the one BibTeX entry of a payload *citation*."""
    return bibtexparser.parse_string(citation["bibtex"]).entries[0].fields_dict


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
                for document in payload["export"]["documents"]:
                    assert_shape(self, document, "ShareDocument")
                self.assertTrue(payload["citations"])
                self.assertEqual(payload["scope"]["key"], query)

    def test_the_scope_counts_its_analyses_drafts_and_materials(self):
        payload = self.get(f"document={self.documents['open'].pk}").json()

        self.assertEqual(payload["scope"]["analyses"], 3)
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
            [
                cited(c).get("doi") and cited(c)["doi"].value
                for c in payload["citations"]
            ],
            ["10.48579/pro/zeejth", None],
        )
        self.assertEqual(
            cited(payload["citations"][1])["url"].value,
            f"{settings.PUBLIC_SERVER_ADDRESS}report/{self.pk('draft')}",
        )
        note = cited(payload["citations"][0])["note"].value
        self.assertIn(
            f"2 analyses: {settings.PUBLIC_SERVER_ADDRESS}report/{self.documents['open'].pk}",
            note,
        )
        for key in ("open", "on_document"):
            self.assertNotIn(f"report/{self.pk(key)}", note)
        self.assertIn(
            f"{settings.PUBLIC_SERVER_ADDRESS}report/{self.documents['open'].pk}",
            payload["availability"],
        )
        self.assertIn("https://doi.org/10.48579/pro/zeejth", payload["availability"])

    def test_a_citation_carries_its_text_and_its_bibtex_only(self):
        payload = self.get(f"document={self.documents['open'].pk}").json()

        for citation in payload["citations"]:
            self.assertEqual(set(citation), {"text", "bibtex"})
            self.assertIn(settings.APP_TITLE, citation["text"])
            self.assertTrue(citation["bibtex"].startswith("@dataset{"))

    def test_analyses_without_a_dataset_are_cited_once_per_project(self):
        side = self.projects["side"]
        self.tile(self.analyses["draft"], "analysis_by_project", self.refs(side))

        payload = self.get(f"document={self.documents['open'].pk}").json()

        self.assertEqual(len(payload["citations"]), 2)
        fields = cited(payload["citations"][1])
        self.assertEqual(fields["title"].value, "Side project")
        self.assertEqual(
            fields["url"].value, f"{settings.PUBLIC_SERVER_ADDRESS}report/{side.pk}"
        )
        self.assertIn("2 analyses", fields["note"].value)

    def test_an_analysis_without_project_is_cited_under_its_document(self):
        document = self.documents["open"]
        scope = resolve_scope(QueryDict(f"document={document.pk}"), "en")

        homes = {group[1][0].id: group[3] for group in scope_content(scope).groups}

        self.assertEqual(
            homes[self.pk("draft")],
            Home(
                str(document.pk),
                "Ms 59",
                f"{settings.PUBLIC_SERVER_ADDRESS}report/{document.pk}",
            ),
        )
        self.assertEqual(
            homes[self.pk("on_document")].id, str(self.projects["side"].pk)
        )

    def test_a_project_scope_cites_under_its_project(self):
        main = self.projects["main"]
        earlier = self.new_resource("project", "Atramenta")
        self.tile(self.analyses["open"], "analysis_by_project", self.refs(earlier))
        scope = resolve_scope(QueryDict(f"project={main.pk}"), "en")

        homes = {group[3].id for group in scope_content(scope).groups}

        self.assertEqual(homes, {str(main.pk)})

    def test_the_export_estimate_sums_the_stored_files_of_the_scope(self):
        spectrum = self.stored_file(self.analyses["open"], "X01.csv", b"1,2\n" * 10)
        self.stored_file(self.analyses["open"], "X01.mca", b"\x00" * 9)
        whole = self.get(f"ids=an:{self.pk('open')}:-").json()
        narrowed = self.get(f"ids=af:{self.pk('open')}:{spectrum}").json()

        self.assertEqual(
            whole["export"],
            {"files": 2, "bytes": 40 + 9, "overLimit": False, "documents": []},
        )
        self.assertEqual(whole["scope"]["spectra"], 1)
        self.assertEqual(
            (narrowed["export"]["files"], narrowed["export"]["bytes"]), (1, 40)
        )

    @override_settings(EXPLORER_EXPORT_MAX_BYTES=100)
    def test_the_estimate_and_the_export_apply_one_size_rule(self):
        self.stored_file(self.analyses["on_document"], "big.csv", b"x" * 500)
        node = self.nodes[("analysis", "measurement_point_data")]
        tile = TileModel.objects.get(
            resourceinstance=self.analyses["on_document"],
            nodegroup_id=node.nodegroup_id,
        )
        data = dict(tile.data)
        data[str(node.nodeid)] = [{**e, "size": 10} for e in data[str(node.nodeid)]] + [
            {"file_id": UNKNOWN, "name": "gone.csv", "size": 20}
        ]
        TileModel.objects.filter(pk=tile.pk).update(data=data)
        query = f"ids=an:{self.pk('on_document')}:-"

        estimate = self.get(query).json()["export"]
        with mock.patch(FETCH, return_value=MANIFEST_JSON):
            export = self.client.get(f"/api/explorer/export?{query}")

        self.assertEqual((estimate["files"], estimate["bytes"]), (1, 500))
        self.assertTrue(estimate["overLimit"])
        self.assertEqual(export.status_code, 413)

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
        for key in ("open", "embargoed"):
            self.stored_file(self.analyses[key], f"{key}.csv", b"1,2\n")
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
        key_of = {
            str(self.documents["open"].pk): f"an:{self.pk('open')}:-",
            str(self.documents["embargoed"].pk): f"an:{self.pk('embargoed')}:-",
        }
        for document in documents:
            assert_shape(self, document, "ShareDocument")
            path = f"/api/explorer/export?ids={key_of[document['id']]}&lang=en"
            self.assertEqual(document["path"], path)
            self.assertEqual(
                document["url"], f"{settings.PUBLIC_SERVER_ADDRESS}{path[1:]}"
            )
        self.assertTrue(single["export"]["overLimit"])
        self.assertEqual(single["export"]["documents"], [])

    @override_settings(EXPLORER_EXPORT_MAX_BYTES=1)
    def test_a_document_over_the_limits_whose_material_spans_documents_is_not_split(
        self,
    ):
        node = self.nodes[("characterization", "object_observed")]
        TileModel.objects.filter(
            resourceinstance=self.characterization, nodegroup_id=node.nodegroup_id
        ).update(
            data={
                str(node.nodeid): self.refs(
                    self.components["open"], self.documents["embargoed"]
                )
            }
        )
        self.stored_file(self.analyses["open"], "open.csv", b"1,2\n")

        response = self.get(f"document={self.documents['open'].pk}")

        self.assertEqual(response.status_code, 200)
        export = response.json()["export"]
        self.assertTrue(export["overLimit"])
        self.assertEqual(export["documents"], [])

    @override_settings(EXPLORER_EXPORT_MAX_BYTES=1)
    def test_a_project_over_the_limits_splits_into_its_items_per_document(self):
        main = self.projects["main"]
        self.tile(self.analyses["embargoed"], "analysis_by_project", self.refs(main))
        for key in ("open", "embargoed"):
            self.stored_file(self.analyses[key], f"{key}.csv", b"1,2\n")

        documents = self.get(f"project={main.pk}").json()["export"]["documents"]

        paths = {d["id"]: d["path"] for d in documents}
        opened = str(self.documents["open"].pk)
        self.assertEqual(
            paths[opened],
            f"/api/explorer/export?project={main.pk}&document={opened}&lang=en",
        )
        scope = resolve_scope(QueryDict(f"project={main.pk}&document={opened}"), "en")
        self.assertEqual(scope.analyses, (self.pk("open"),))
        self.assertEqual(scope.key, f"project={main.pk}&document={opened}")
        self.assertEqual(scope.documents, (opened,))

    @override_settings(EXPLORER_EXPORT_MAX_BYTES=1)
    def test_a_project_split_leaves_out_documents_without_its_analyses(self):
        main = self.projects["main"]
        self.tile(self.analyses["embargoed"], "analysis_by_project", self.refs(main))
        for key in ("open", "embargoed"):
            self.stored_file(self.analyses[key], f"{key}.csv", b"1,2\n")
        second = self.new_resource("document", "Second document")
        node = self.nodes[("characterization", "object_observed")]
        TileModel.objects.filter(
            resourceinstance=self.characterization, nodegroup_id=node.nodegroup_id
        ).update(data={str(node.nodeid): self.refs(self.components["open"], second)})

        documents = self.get(f"project={main.pk}").json()["export"]["documents"]

        self.assertEqual(
            sorted(d["id"] for d in documents),
            sorted(str(self.documents[k].pk) for k in ("open", "embargoed")),
        )

    @override_settings(EXPLORER_EXPORT_MAX_BYTES=1)
    def test_a_project_on_one_document_is_not_split(self):
        main = self.projects["main"]
        self.stored_file(self.analyses["open"], "open.csv", b"1,2\n")
        node = self.nodes[("characterization", "object_observed")]
        TileModel.objects.filter(
            resourceinstance=self.characterization, nodegroup_id=node.nodegroup_id
        ).update(
            data={
                str(node.nodeid): self.refs(
                    self.components["open"], self.documents["embargoed"]
                )
            }
        )

        export = self.get(f"project={main.pk}").json()["export"]

        self.assertTrue(export["overLimit"])
        self.assertEqual(export["documents"], [])

    @override_settings(EXPLORER_EXPORT_MAX_FILES=1)
    def test_more_files_than_the_limit_is_over_the_limit(self):
        for name in ("a.csv", "b.csv"):
            self.stored_file(self.analyses["open"], name, b"1,2\n")
        self.assertTrue(
            self.get(f"ids=an:{self.pk('open')}:-").json()["export"]["overLimit"]
        )

    def test_series_link_only_for_a_selection_with_spectra(self):
        with_spectra = self.get(f"ids=an:{self.pk('open')}:-").json()["links"]
        without = self.get(f"ids=an:{self.pk('on_document')}:-").json()["links"]
        document = self.get(f"document={self.documents['open'].pk}").json()["links"]

        self.assertIsNotNone(with_spectra["seriesCsv"])
        self.assertIsNone(without["seriesCsv"])
        self.assertIsNone(document["seriesCsv"])

    def test_links_are_site_paths_to_follow_and_absolute_urls_to_copy(self):
        links = self.get(f"ids=an:{self.pk('open')}:-").json()["links"]
        query = f"?ids=an:{self.pk('open')}:-&lang=en"

        for name, path in (
            ("seriesCsv", f"/api/explorer/series.csv{query}"),
            ("manifest", f"/iiif/v3/explorer-manifest{query}"),
            ("export", f"/api/explorer/export{query}"),
        ):
            with self.subTest(link=name):
                self.assertEqual(
                    links[name],
                    {
                        "path": path,
                        "url": f"{settings.PUBLIC_SERVER_ADDRESS}{path[1:]}",
                    },
                )

    def test_a_signed_in_reader_gets_the_visitors_share_payload(self):
        self.embargo(self.analyses["open"])
        query = f"document={self.documents['open'].pk}"

        visitor = self.get(query).json()
        self.client.force_login(self.editor)
        reader = self.get(f"{query}&restricted=1").json()

        self.assertEqual(reader, visitor)
        self.assertNotIn(self.pk("open"), str(reader))
        self.assertNotIn("restricted", json.dumps(reader))

    def test_a_scope_placing_no_canvas_offers_no_manifest(self):
        placed = self.get(f"ids=an:{self.pk('open')}:-").json()
        unplaced = self.get(f"ids=an:{self.pk('embargoed')}:-").json()

        self.assertIsNotNone(placed["links"]["manifest"])
        self.assertIsNone(unplaced["links"]["manifest"])

    def test_the_manifest_link_reads_source_manifests_until_one_places_a_canvas(
        self,
    ):
        other = "https://example.org/iiif/ms211/manifest"
        self.tile(self.documents["embargoed"], "facsimiles", other)
        self.tile(
            self.analyses["embargoed"],
            "literal_location_of_analysis",
            self.annotation_value(CANVAS, {"type": "Point", "coordinates": [1, -1]}),
        )
        with mock.patch(
            "manuspectrum.views.explorer.scopes.manifest_json",
            wraps=manifest_json,
        ) as read:
            payload = self.get(
                f"ids=an:{self.pk('open')}:-,an:{self.pk('embargoed')}:-"
            ).json()

        self.assertIsNotNone(payload["links"]["manifest"])
        sources = [
            c.args[0] for c in read.call_args_list if c.args[0] in (MANIFEST, other)
        ]
        self.assertEqual(len(sources), 1)

    def test_links_encode_a_key_carrying_url_delimiters(self):
        key = f"af:{self.pk('open')}:x&y#z%w"

        payload = self.get(f"ids={quote(key, safe=':')}").json()

        self.assertEqual(payload["scope"]["key"], f"ids={key}")
        for name in ("manifest", "export"):
            for form in ("path", "url"):
                with self.subTest(link=name, form=form):
                    parts = urlsplit(payload["links"][name][form])
                    self.assertEqual(parts.fragment, "")
                    self.assertEqual(
                        parse_qs(parts.query), {"ids": [key], "lang": ["en"]}
                    )

    def test_the_payload_is_in_the_request_language(self):
        query = f"ids=an:{self.pk('on_document')}:-"
        with mock.patch(FETCH, return_value=MANIFEST_JSON):
            french = self.client.get(f"/fr/api/explorer/share?{query}").json()

        self.assertTrue(
            french["availability"].startswith("Les données sont disponibles")
        )
        self.assertTrue(french["links"]["manifest"]["url"].endswith("&lang=fr"))
        self.assertTrue(french["links"]["manifest"]["path"].endswith("&lang=fr"))


class ShareCostTests(CorpusCase):
    def project_of(self, name, count):
        project = self.new_resource("project", name)
        for n in range(count):
            analysis = self.new_resource("analysis", f"{name} {n}")
            self.tile(
                analysis, "component_observed", self.refs(self.components["open"])
            )
            self.tile(analysis, "analysis_by_project", self.refs(project))
            self.tile(
                analysis,
                "measurement_point_data",
                [
                    {
                        "file_id": f"{n + 1:08d}-aaaa-4aaa-8aaa-{len(name):012d}",
                        "name": f"{name}_{n}.csv",
                        "size": 100,
                        "type": "text/csv",
                        "url": f"/files/{n + 1:08d}-aaaa-4aaa-8aaa-{len(name):012d}",
                        "rendererConfig": XY_CONFIG_ID,
                    }
                ],
            )
        return project

    def share_queries(self, project):
        query = QueryDict(f"project={project.pk}")
        scope = resolve_scope(query, "en")
        share_payload(scope, datetime.date(2026, 9, 26))
        with CaptureQueriesContext(connection) as queries:
            share_payload(scope, datetime.date(2026, 9, 26))
        return len(queries)

    def test_a_project_payload_names_none_of_its_analyses(self):
        project = self.project_of("Bulk project", 5)
        scope = resolve_scope(QueryDict(f"project={project.pk}"), "en")

        payload = share_payload(scope, datetime.date(2026, 9, 26))

        self.assertNotIn("parts", payload)
        self.assertEqual(len(payload["citations"]), 1)
        self.assertEqual(
            set(re.findall(r"report/([0-9a-f-]{36})", json.dumps(payload))),
            {str(project.pk)},
        )

    def test_the_share_payload_reads_the_same_queries_for_one_or_five_analyses(self):
        one = self.project_of("Single", 1)
        five = self.project_of("Bulk project", 5)

        self.assertEqual(self.share_queries(five), self.share_queries(one))
