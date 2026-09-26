"""An embargoed resource leaks through no Corpus channel of the Explorer (spec §4, C7–C9, C12, C14).

C11 (spectrum-preview) is covered in ``tests.test_spectrum_preview_permissions``
(Task 5, including a test against a real ``visible_set``). C13 (project IIIF
collection) is covered in ``tests.test_explorer_visibility`` (Task 4).

Usage:
    python manage.py test tests.test_explorer_embargo --settings="tests.test_settings"
"""

import datetime
import json
from unittest import mock

from django.contrib.auth.models import Group

from tests.test_explorer_api import FETCH, MANIFEST_JSON, CorpusCase

UNKNOWN = "00000000-0000-4000-8000-00000000000c"


def csv_body(response):
    """The body of a streamed CSV without its « generated on » line."""
    text = b"".join(response.streaming_content).decode()
    return "".join(
        line
        for line in text.splitlines(keepends=True)
        if not line.startswith("# Generated on ")
    )


class ProductsCase(CorpusCase):
    """The share payload, the IIIF manifest and ``series.csv`` of the fixture scopes."""

    def keys(self, *names):
        return "ids=" + ",".join(f"an:{self.analyses[n].pk}:-" for n in names)

    def scopes(self):
        return (
            self.keys("open", "on_document", "embargoed", "draft"),
            f"document={self.documents['open'].pk}",
            f"project={self.projects['main'].pk}",
            f"project={self.projects['side'].pk}",
        )

    def share(self, query):
        with mock.patch(FETCH, return_value=MANIFEST_JSON):
            response = self.client.get(f"/en/api/explorer/share?{query}")
        return json.loads(response.content) if response.status_code == 200 else None

    def manifest(self, query):
        with mock.patch(FETCH, return_value=MANIFEST_JSON):
            response = self.client.get(f"/iiif/v3/explorer-manifest?{query}")
        return response.content if response.status_code == 200 else None

    def series(self, query):
        response = self.client.get(f"/api/explorer/series.csv?{query}")
        return csv_body(response) if response.status_code == 200 else None

    def products(self, suffix=""):
        """``{channel: body}`` of every product of every scope; the share's ``scope.missing`` echo is left out."""
        found = {}
        for query in self.scopes():
            share = self.share(query + suffix)
            if share is not None:
                share["scope"].pop("missing")
            found[f"share {query}"] = json.dumps(share, ensure_ascii=False)
            found[f"manifest {query}"] = (self.manifest(query + suffix) or b"").decode()
        ids = self.scopes()[0]
        found[f"series {ids}"] = self.series(ids + suffix) or ""
        return found


class EmbargoMatrixTests(ProductsCase):
    def everything(self):
        products = self.products()
        with mock.patch(FETCH, return_value=MANIFEST_JSON):
            return products | {
                "search": self.client.get("/en/api/explorer/search").content,
                "documents": self.client.get(
                    "/en/api/explorer/search?grain=documents"
                ).content,
                "document": self.client.get(
                    f"/en/api/explorer/document/{self.documents['open'].pk}"
                ).content,
                "analysis": self.client.get(
                    f"/en/api/explorer/analysis/{self.analyses['open'].pk}"
                ).content,
                "items": self.client.get(
                    "/en/api/explorer/items",
                    {"ids": f"ch:{self.characterization.pk}:-"},
                ).content,
                "match": self.client.get(
                    f"/en/api/explorer/document/{self.documents['open'].pk}/match"
                ).content,
                "home": self.client.get(
                    "/en/api/explorer/home",
                    {"day": datetime.date.today().isoformat()},
                ).content,
                "parts": self.client.get("/en/api/explorer/facet/part").content,
            }

    def test_an_embargoed_analysis_appears_in_no_payload(self):
        hidden = str(self.analyses["on_document"].pk)
        stored = self.stored_file(
            self.analyses["on_document"], "FORS_009.csv", b"1,2\n3,4\n", config=UNKNOWN
        )
        shown = self.stored_file(
            self.analyses["draft"], "X03.csv", b"1,2\n3,4\n", config=UNKNOWN
        )
        self.embargo(self.analyses["on_document"])

        everything = self.everything()
        for channel, body in everything.items():
            body = body if isinstance(body, str) else body.decode()
            self.assertNotIn(hidden, body, channel)
            self.assertNotIn("FORS_009", body, channel)
            self.assertNotIn(stored, body, channel)
        self.assertIn(shown, everything[f"series {self.scopes()[0]}"])

    def test_an_embargoed_document_takes_its_names_out_of_facets_and_results(self):
        self.embargo(self.documents["embargoed"])

        for channel, body in self.everything().items():
            body = body if isinstance(body, str) else body.decode()
            for text in ("Ms 211", "f. 3r", "X02 — f. 3r"):
                self.assertNotIn(text, body, channel)

    def test_a_hidden_key_is_answered_like_an_unknown_one(self):
        hidden = f"an:{self.analyses['on_document'].pk}:-"
        unknown = f"an:{UNKNOWN}:-"
        kept = f"an:{self.analyses['open'].pk}:-"
        self.embargo(self.analyses["on_document"])

        with_hidden = self.share(f"ids={kept},{hidden}")
        with_unknown = self.share(f"ids={kept},{unknown}")

        self.assertEqual(with_hidden["scope"].pop("missing"), [hidden])
        self.assertEqual(with_unknown["scope"].pop("missing"), [unknown])
        self.assertEqual(with_hidden, with_unknown)
        self.assertEqual(
            self.manifest(f"ids={kept},{hidden}"),
            self.manifest(f"ids={kept},{unknown}"),
        )

    def test_a_signed_in_reader_never_fills_the_visitors_answer(self):
        hidden = str(self.analyses["on_document"].pk)
        self.embargo(self.analyses["on_document"])
        self.client.force_login(self.editor)
        editor = self.client.get("/en/api/explorer/search")
        self.client.logout()
        visitor = self.client.get("/en/api/explorer/search")

        self.assertEqual(editor["Cache-Control"], "private, no-store")
        self.assertEqual(visitor["Cache-Control"], "public, no-cache")
        self.assertIn(hidden, editor.content.decode())
        self.assertNotIn(hidden, visitor.content.decode())

    def test_the_visitor_sees_the_draft_analysis_marked_unpublished(self):
        visitor = json.loads(self.client.get("/en/api/explorer/search").content)

        marked = {r["id"]: r["unpublished"] for r in visitor["results"]}
        self.assertIs(marked[str(self.analyses["draft"].pk)], True)

    def test_a_guest_account_reads_the_visitors_data_privately(self):
        plain = self.editor.__class__.objects.create_user("plain_reader", password="pw")
        plain.groups.add(Group.objects.get(name="Guest"))
        self.client.force_login(plain)
        response = self.client.get("/en/api/explorer/search")
        self.client.logout()
        visitor = json.loads(self.client.get("/en/api/explorer/search").content)

        self.assertEqual(response["Cache-Control"], "private, no-store")
        self.assertEqual(json.loads(response.content), visitor)


class ConnectedExportTests(ProductsCase):
    """A signed-in reader's products are the visitor's unless they ask for restricted data (spec §4)."""

    def setUp(self):
        super().setUp()
        self.stored_file(
            self.analyses["open"], "X01.csv", b"1,2\n3,4\n", config=UNKNOWN
        )
        self.stored_file(
            self.analyses["on_document"], "FORS_009.csv", b"5,6\n7,8\n", config=UNKNOWN
        )
        self.embargo(self.analyses["open"])

    def without_restricted_hints(self, products):
        """*products* without the share fields that offer a signed-in reader the restricted build."""
        found = {}
        for channel, body in products.items():
            if channel.startswith("share ") and body != "null":
                share = json.loads(body)
                share["scope"].pop("restrictedAvailable")
                share["links"].pop("exportRestricted")
                body = json.dumps(share, ensure_ascii=False)
            found[channel] = body
        return found

    def test_a_connected_readers_default_products_equal_the_visitors(self):
        visitor = self.products()
        self.client.force_login(self.editor)
        reader = self.products()

        self.assertEqual(
            self.without_restricted_hints(reader),
            self.without_restricted_hints(visitor),
        )
        self.assertNotIn(str(self.analyses["open"].pk), "".join(reader.values()))
        share = json.loads(reader[f"share {self.scopes()[1]}"])
        self.assertEqual(share["scope"]["restrictedAvailable"], 1)

    def test_restricted_inclusion_is_marked_on_every_product(self):
        hidden = str(self.analyses["open"].pk)
        self.client.force_login(self.editor)

        products = self.products("&restricted=1")

        document = self.scopes()[1]
        share = json.loads(products[f"share {document}"])
        manifest = json.loads(products[f"manifest {document}"])
        series = products[f"series {self.scopes()[0]}"]
        self.assertTrue(share["scope"]["restricted"])
        self.assertTrue(any(hidden in c["bibtex"] for c in share["citations"]))
        self.assertIn("Contains restricted-access data", manifest["summary"]["en"])
        self.assertIn("X01 — f. 1v", json.dumps(manifest, ensure_ascii=False))
        self.assertIn("# Contains restricted-access data\r\n", series)
        self.assertIn(hidden, series)

    def test_a_visitor_asking_restricted_gets_the_visitors_products(self):
        plain = self.products()
        asking = self.products("&restricted=1")

        self.assertEqual(asking, plain)
        self.assertNotIn(str(self.analyses["open"].pk), "".join(asking.values()))
