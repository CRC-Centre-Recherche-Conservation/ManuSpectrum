"""An embargoed resource leaks through no Corpus channel of the Explorer (spec §4, C7–C9, C12).

C11 (spectrum-preview) is covered in ``tests.test_spectrum_preview_permissions``
(Task 5, including a test against a real ``visible_set``). C13 (project IIIF
collection) is covered in ``tests.test_explorer_visibility`` (Task 4).

Usage:
    python manage.py test tests.test_explorer_embargo --settings="tests.test_settings"
"""

import json
from unittest import mock

from django.contrib.auth.models import Group

from tests.test_explorer_api import FETCH, MANIFEST_JSON, CorpusCase


class EmbargoMatrixTests(CorpusCase):
    def everything(self):
        with mock.patch(FETCH, return_value=MANIFEST_JSON):
            return {
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
            }

    def test_an_embargoed_analysis_appears_in_no_payload(self):
        hidden = str(self.analyses["on_document"].pk)
        self.embargo(self.analyses["on_document"])

        for channel, body in self.everything().items():
            self.assertNotIn(hidden, body.decode(), channel)
            self.assertNotIn("FORS_009", body.decode(), channel)

    def test_an_embargoed_document_takes_its_names_out_of_facets_and_results(self):
        self.embargo(self.documents["embargoed"])

        for channel, body in self.everything().items():
            for text in ("Ms 211", "f. 3r", "X02 — f. 3r"):
                self.assertNotIn(text, body.decode(), channel)

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
