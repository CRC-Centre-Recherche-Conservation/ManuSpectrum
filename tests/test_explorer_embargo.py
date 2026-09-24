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

from arches.app.utils.permission_backend import assign_perm

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
        self.client.force_login(self.editor)
        editor = self.client.get("/en/api/explorer/search")
        self.client.logout()
        visitor = self.client.get("/en/api/explorer/search")

        self.assertEqual(editor["Cache-Control"], "private, no-store")
        self.assertEqual(visitor["Cache-Control"], "public, no-cache")
        self.assertNotIn(str(self.analyses["draft"].pk), visitor.content.decode())
        self.assertIn(str(self.analyses["draft"].pk), editor.content.decode())

    def test_an_editor_without_extra_rights_reads_the_visitors_data_privately(self):
        """A Guest-only account still needs an explicit read grant on the Draft to
        draw a real refusal from ``user_can_edit_resource``: this fixture sets no
        nodegroup permission anywhere, and the deployed
        ``ArchesDefaultAllowPermissionFramework`` answers such an unconfigured
        nodegroup "unknown", then default-allows edit to any other signed-in
        account (``arches.app.permissions.arches_permission_base
        .get_nodegroups_by_perm_for_user_or_group``).
        """
        plain = self.editor.__class__.objects.create_user("plain_reader", password="pw")
        plain.groups.add(Group.objects.get(name="Guest"))
        assign_perm("view_resourceinstance", plain, self.analyses["draft"])
        self.client.force_login(plain)
        reader = json.loads(self.client.get("/en/api/explorer/search").content)
        self.client.logout()
        visitor = json.loads(self.client.get("/en/api/explorer/search").content)

        self.assertEqual(reader, visitor)
