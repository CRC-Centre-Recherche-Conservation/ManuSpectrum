"""The export scope shared by the share payload, the manifest, the CSV and the package.

Usage:
    python manage.py test tests.test_explorer_scopes --settings="tests.test_settings"
"""

import uuid
from unittest import mock

from django.conf import settings
from django.contrib.auth.models import User
from django.http import QueryDict

from tests import test_explorer_api as api
from tests.test_explorer_api import ReadRightsCase

from manuspectrum.views.explorer_scopes import (
    ScopeError,
    export_language,
    kept_files,
    resolve_scope,
    scope_file,
)
from manuspectrum.views.explorer_service import analysis_files

CSV = api.ItemsRouteTests.CSV
MCA = "22222222-2222-4222-8222-222222222222"
UNKNOWN = "00000000-0000-4000-8000-00000000000a"
MANIFEST_JSON = "manuspectrum.views.explorer_service.manifest_json"


class ScopeTests(ReadRightsCase):
    def resolve(self, text, user=None, language="en"):
        return resolve_scope(QueryDict(text), user or self.anonymous, language)

    def pk(self, key):
        return str(self.analyses[key].pk)

    def test_no_scope_parameter_is_a_bad_request(self):
        for text in ("", "lang=en", "ids=", "document="):
            with self.subTest(text=text), self.assertRaises(ScopeError):
                self.resolve(text)

    def test_two_scope_parameters_are_a_bad_request(self):
        with self.assertRaises(ScopeError):
            self.resolve(
                f"ids=an:{self.pk('open')}:-&document={self.documents['open'].pk}"
            )
        with self.assertRaises(ScopeError):
            self.resolve(
                f"document={self.documents['open'].pk}"
                f"&document={self.documents['embargoed'].pk}"
            )

    def test_more_keys_than_the_selection_holds_are_a_bad_request(self):
        keys = [f"an:{uuid.uuid4()}:-" for _ in range(settings.EXPLORER_ITEMS_MAX + 1)]

        with self.assertRaises(ScopeError):
            self.resolve("ids=" + ",".join(keys))

    def test_a_malformed_key_is_a_bad_request(self):
        for key in ("an:nope", f"zz:{self.pk('open')}:-", f"an:{self.pk('open')}"):
            with self.subTest(key=key), self.assertRaises(ScopeError):
                self.resolve(f"ids={key}")
        with self.assertRaises(ScopeError):
            self.resolve("document=not-a-uuid")
        with self.assertRaises(ScopeError):
            self.resolve(f"document={self.documents['open'].pk}&restricted=yes")

    def test_canvases_all_outside_a_document_scope_is_a_bad_request(self):
        with self.assertRaises(ScopeError):
            self.resolve(f"project={self.projects['main'].pk}&canvases=all")
        with self.assertRaises(ScopeError):
            self.resolve(f"ids=an:{self.pk('open')}:-&canvases=all")
        with self.assertRaises(ScopeError):
            self.resolve(f"document={self.documents['open'].pk}&canvases=some")

        scope = self.resolve(f"document={self.documents['open'].pk}&canvases=all")

        self.assertTrue(scope.canvases_all)
        self.assertEqual(
            scope.key, f"document={self.documents['open'].pk}&canvases=all"
        )

    def test_an_unknown_language_is_a_bad_request(self):
        self.assertEqual(export_language(QueryDict("")), settings.LANGUAGE_CODE)
        self.assertEqual(export_language(QueryDict("lang=fr")), "fr")
        for text in ("lang=xx", "lang="):
            with self.subTest(text=text), self.assertRaises(ScopeError):
                export_language(QueryDict(text))

    def test_an_unknown_document_and_an_embargoed_one_both_resolve_to_none(self):
        self.embargo(self.documents["embargoed"])

        self.assertIsNone(self.resolve(f"document={UNKNOWN}"))
        self.assertIsNone(self.resolve(f"document={self.documents['embargoed'].pk}"))
        self.assertIsNone(self.resolve(f"project={UNKNOWN}"))

    def test_a_document_scope_holds_its_analyses_in_corpus_order(self):
        document = str(self.documents["open"].pk)

        scope = self.resolve(f"document={document}")

        self.assertEqual((scope.kind, scope.subject), ("document", document))
        self.assertEqual(
            scope.analyses,
            (self.pk("on_document"), self.pk("open"), self.pk("draft")),
        )
        self.assertEqual(scope.characterizations, (str(self.characterization.pk),))
        self.assertEqual(scope.documents, (document,))
        self.assertEqual(scope.key, f"document={document}")
        self.assertRegex(scope.digest, r"^[0-9a-f]{12}$")
        self.assertEqual(scope.language, "en")

    def test_a_project_scope_holds_its_visible_analyses_only(self):
        self.tile(
            self.analyses["draft"],
            "analysis_by_project",
            self.refs(self.projects["main"]),
        )
        self.embargo(self.analyses["open"])

        scope = self.resolve(f"project={self.projects['main'].pk}")

        self.assertEqual(scope.analyses, (self.pk("draft"),))
        self.assertEqual(scope.characterizations, ())
        self.assertEqual(scope.documents, (str(self.documents["open"].pk),))

    def test_ids_keep_the_visible_keys_and_list_the_others_as_missing(self):
        self.embargo(self.analyses["on_document"])
        kept = f"an:{self.pk('open')}:-"
        material = f"ch:{self.characterization.pk}:-"
        hidden = f"an:{self.pk('on_document')}:-"
        unknown = f"an:{UNKNOWN}:-"
        not_whole = f"an:{self.pk('draft')}:0"

        scope = self.resolve(
            "ids=" + ",".join([kept, material, hidden, unknown, not_whole])
        )

        self.assertEqual(scope.kind, "ids")
        self.assertIsNone(scope.subject)
        self.assertEqual(scope.analyses, (self.pk("open"),))
        self.assertEqual(scope.characterizations, (str(self.characterization.pk),))
        self.assertEqual(scope.missing, tuple(sorted([hidden, unknown, not_whole])))
        self.assertEqual(scope.narrowed, {})
        self.assertEqual(
            scope.key,
            "ids=" + ",".join(sorted([kept, material, hidden, unknown, not_whole])),
        )

    def test_ids_with_no_visible_key_resolve_to_none(self):
        self.embargo(self.analyses["open"])

        self.assertIsNone(
            self.resolve(f"ids=an:{self.pk('open')}:-,an:{UNKNOWN}:-,ch:{UNKNOWN}:-")
        )

    def test_a_connected_reader_gets_the_visitors_part_by_default(self):
        self.embargo(self.analyses["open"])

        scope = self.resolve(f"document={self.documents['open'].pk}", self.editor)

        self.assertNotIn(self.pk("open"), scope.analyses)
        self.assertIn(self.pk("on_document"), scope.analyses)
        self.assertEqual(scope.restricted_available, 1)
        self.assertFalse(scope.restricted)
        self.assertEqual(scope.reader.pk, self.anonymous.pk)
        self.assertEqual(scope.viewer.pk, self.editor.pk)

    def test_restricted_includes_the_readers_items_and_says_so(self):
        self.embargo(self.analyses["open"])

        scope = self.resolve(
            f"document={self.documents['open'].pk}&restricted=1", self.editor
        )

        self.assertIn(self.pk("open"), scope.analyses)
        self.assertTrue(scope.restricted)
        self.assertEqual(scope.restricted_available, 0)
        self.assertEqual(scope.reader.pk, self.editor.pk)
        self.assertTrue(scope.key.endswith("&restricted=1"))

    def test_restricted_without_restricted_items_is_not_marked(self):
        scope = self.resolve(
            f"document={self.documents['open'].pk}&restricted=1", self.editor
        )

        self.assertFalse(scope.restricted)
        self.assertEqual(scope.key, f"document={self.documents['open'].pk}")

    def test_a_visitor_never_learns_of_restricted_items(self):
        self.embargo(self.analyses["open"])

        scope = self.resolve(f"document={self.documents['open'].pk}&restricted=1")

        self.assertNotIn(self.pk("open"), scope.analyses)
        self.assertFalse(scope.restricted)
        self.assertEqual(scope.restricted_available, 0)

    def test_drafts_are_counted(self):
        document = f"document={self.documents['open'].pk}"

        self.assertEqual(self.resolve(document).drafts, 1)

        self.make_draft(self.characterization)

        self.assertEqual(self.resolve(document).drafts, 2)

    def test_an_af_key_narrows_to_its_file_and_an_im_key_to_its_imaging_manifest(self):
        self.tile(
            self.analyses["open"],
            "chemical_imaging_manifest",
            "https://example.org/iiif/imaging/x",
        )
        opened = self.pk("open")

        scope = self.resolve(
            f"ids=af:{opened}:{CSV},im:{opened}:0,an:{self.pk('on_document')}:-"
        )
        with mock.patch(
            MANIFEST_JSON, return_value=api.ItemsRouteTests.IMAGING_MANIFEST
        ):
            files = analysis_files(opened, self.anonymous, "en")

        self.assertEqual(
            scope.narrowed, {opened: frozenset({f"file:{CSV}", "layer:0"})}
        )
        self.assertEqual(
            [f["dataKind"] for f in files], ["xy", "file", "chemical-imaging"]
        )
        self.assertEqual(
            [f["id"] for f in kept_files(scope, opened, files)],
            [CSV, f"{opened}:imaging:0"],
        )

        whole = self.resolve(f"ids=af:{opened}:{CSV},an:{opened}:-")

        self.assertEqual(whole.narrowed, {})
        self.assertEqual(len(kept_files(whole, opened, files)), 3)

    def test_a_file_named_in_the_tile_data_of_another_resource_is_refused(self):
        other = self.stored_file(self.analyses["on_document"], "b.csv", b"1,2\n3,4\n")
        self.tile(
            self.analyses["open"],
            "measurement_point_data",
            [{"file_id": other, "name": "b.csv", "url": f"/files/{other}"}],
        )
        scope = self.resolve(
            f"ids=an:{self.pk('open')}:-,an:{self.pk('on_document')}:-"
        )

        self.assertIsNone(scope_file(scope, self.pk("open"), other))
        self.assertTrue(scope_file(scope, self.pk("on_document"), other))
        self.assertIsNone(scope_file(scope, self.pk("open"), "not-a-uuid"))
        self.assertIsNone(scope_file(scope, self.pk("open"), UNKNOWN))

    def test_a_file_outside_the_scope_or_its_narrowing_is_refused(self):
        stored = self.stored_file(self.analyses["open"], "a.csv", b"1,2\n3,4\n")

        other_analysis = self.resolve(f"ids=an:{self.pk('on_document')}:-")
        narrowed = self.resolve(f"ids=af:{self.pk('open')}:{CSV}")
        whole = self.resolve(f"ids=an:{self.pk('open')}:-")

        self.assertIsNone(scope_file(other_analysis, self.pk("open"), stored))
        self.assertIsNone(scope_file(narrowed, self.pk("open"), stored))
        path = scope_file(whole, self.pk("open"), stored)
        with open(path, "rb") as handle:
            self.assertEqual(handle.read(), b"1,2\n3,4\n")

    def test_a_file_of_an_unreadable_nodegroup_is_refused(self):
        stored = self.stored_file(self.analyses["open"], "a.csv", b"1,2\n3,4\n")
        query = f"ids=an:{self.pk('open')}:-"
        self.assertTrue(scope_file(self.resolve(query), self.pk("open"), stored))
        files = [
            {"id": stored, "dataKind": "xy", "layers": []},
            {"id": "m", "dataKind": "micro-imaging", "layers": []},
        ]

        self.deny(("analysis", "measurement_point_data"))
        scope = self.resolve(query, User.objects.get(pk=self.anonymous.pk))

        self.assertIsNone(scope_file(scope, self.pk("open"), stored))
        self.assertEqual(
            [f["id"] for f in kept_files(scope, self.pk("open"), files)], ["m"]
        )

    def test_names_visible_keeps_what_both_the_reader_and_the_viewer_may_name(self):
        self.embargo(self.operator)
        ids = [str(self.operator.pk), str(self.projects["main"].pk)]

        by_default = self.resolve(f"document={self.documents['open'].pk}", self.editor)
        restricted = self.resolve(
            f"document={self.documents['open'].pk}&restricted=1", self.editor
        )

        self.assertEqual(by_default.names_visible(ids), [str(self.projects["main"].pk)])
        self.assertEqual(restricted.names_visible(ids), sorted(ids))
