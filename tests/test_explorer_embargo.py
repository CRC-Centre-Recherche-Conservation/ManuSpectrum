"""An embargoed resource leaks through no Corpus channel of the Explorer (spec §4, C7–C9, C12, C14).

C11 (spectrum-preview) is covered in ``tests.test_spectrum_preview_permissions``
(Task 5, including a test against a real ``visible_set``). C13 (project IIIF
collection) is covered in ``tests.test_explorer_visibility`` (Task 4).

Usage:
    python manage.py test tests.test_explorer_embargo --settings="tests.test_settings"
"""

import datetime
import io
import json
import zipfile
from unittest import mock

from django.contrib.auth.models import Group
from guardian.shortcuts import remove_perm

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

    def products(self):
        """``{channel: body}`` of every product of every scope; the share's ``scope.missing`` echo is left out."""
        found = {}
        for query in self.scopes():
            share = self.share(query)
            if share is not None:
                share["scope"].pop("missing")
            found[f"share {query}"] = json.dumps(share, ensure_ascii=False)
            found[f"manifest {query}"] = (self.manifest(query) or b"").decode()
        ids = self.scopes()[0]
        found[f"series {ids}"] = self.series(ids) or ""
        return found

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


class EmbargoMatrixTests(ProductsCase):
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


class PublicViewForEveryoneTests(ProductsCase):
    """Discover shows every reader what the visitor sees (spec D59)."""

    def setUp(self):
        super().setUp()
        self.stored_file(
            self.analyses["open"], "X01.csv", b"1,2\n3,4\n", config=UNKNOWN
        )
        self.stored_file(
            self.analyses["on_document"], "FORS_009.csv", b"5,6\n7,8\n", config=UNKNOWN
        )

    def export(self, query):
        """``{member name: bytes}`` of the data package of *query*, or None."""
        with mock.patch(FETCH, return_value=MANIFEST_JSON):
            response = self.client.get(f"/api/explorer/export?{query}")
        if response.status_code != 200:
            return None
        archive = zipfile.ZipFile(io.BytesIO(b"".join(response.streaming_content)))
        return {name: archive.read(name) for name in sorted(archive.namelist())}

    def seen(self):
        """Every Explorer answer the current client gets, the data packages included."""
        found = {
            k: v if isinstance(v, str) else v.decode()
            for k, v in self.everything().items()
        }
        for query in self.scopes():
            package = self.export(query)
            found[f"export {query}"] = (
                ""
                if package is None
                else "".join(
                    f"{name}\n{data.decode(errors='replace')}\n"
                    for name, data in package.items()
                )
            )
        return found

    def test_a_signed_in_reader_with_a_grant_sees_exactly_the_visitors_payloads(self):
        self.embargo(self.analyses["open"])
        visitor = self.seen()
        self.client.force_login(self.editor)
        reader = self.seen()
        response = self.client.get("/en/api/explorer/search")

        self.assertEqual(reader, visitor)
        self.assertEqual(response["Cache-Control"], "private, no-store")

    def test_an_embargoed_resource_appears_for_no_reader(self):
        hidden = str(self.analyses["open"].pk)
        self.embargo(self.analyses["open"])

        for login in (None, self.editor):
            if login:
                self.client.force_login(login)
            for channel, body in self.seen().items():
                self.assertNotIn(hidden, body, f"{login} {channel}")
                self.assertNotIn("X01.csv", body, f"{login} {channel}")

    def test_lifting_the_embargo_makes_the_resource_appear(self):
        hidden = str(self.analyses["open"].pk)
        self.embargo(self.analyses["open"])
        self.client.force_login(self.editor)
        before = self.client.get("/en/api/explorer/search").content.decode()

        with self.captureOnCommitCallbacks(execute=True):
            remove_perm(
                "no_access_to_resourceinstance", self.anonymous, self.analyses["open"]
            )
        reader = self.client.get("/en/api/explorer/search").content.decode()
        self.client.logout()
        visitor = self.client.get("/en/api/explorer/search").content.decode()

        self.assertNotIn(hidden, before)
        self.assertIn(hidden, reader)
        self.assertIn(hidden, visitor)
