"""``GET /api/explorer/export``: the data package of a scope as a stored ZIP of announced length.

Usage:
    python manage.py test tests.test_explorer_export --settings="tests.test_settings"
"""

import hashlib
import io
import json
import zipfile
from unittest import mock

from django.core.cache import caches
from django.db import connection
from django.http import QueryDict
from django.test.utils import CaptureQueriesContext

from arches.app.models.models import File

from tests.test_explorer_export_package import BY, EXPORTED, fetch
from tests.test_explorer_api import FETCH, CorpusCase

from manuspectrum.views.explorer_export import package
from manuspectrum.views.explorer_scopes import resolve_scope

UNKNOWN = "00000000-0000-4000-8000-00000000000c"
EXPORT = "manuspectrum.views.explorer_export"
CACHE_CALLS = ("get", "get_many", "set", "add", "delete")
MARKER = b"hidden-spectrum-bytes"


class ExportCase(CorpusCase):
    def pk(self, key):
        return str(self.analyses[key].pk)

    def get(self, query, **headers):
        with mock.patch(FETCH, side_effect=fetch):
            return self.client.get(f"/api/explorer/export?{query}", **headers)

    def download(self, query):
        response = self.get(query)
        self.assertEqual(response.status_code, 200, query)
        with mock.patch(FETCH, side_effect=fetch):
            body = b"".join(response.streaming_content)
        return response, body

    def archive(self, query):
        return zipfile.ZipFile(io.BytesIO(self.download(query)[1]))

    def contents(self, query):
        """``{name: bytes}`` of the archive of *query*."""
        with self.archive(query) as archive:
            return {name: archive.read(name) for name in archive.namelist()}

    def document_query(self):
        return f"document={self.documents['open'].pk}"

    def assert_bodyless(self, response, status):
        self.assertEqual(response.status_code, status)
        self.assertEqual(response.content, b"")
        self.assertEqual(response["Cache-Control"], "private, no-store")


class ArchiveTests(ExportCase):
    def setUp(self):
        super().setUp()
        self.x01 = self.stored_file(
            self.analyses["open"], "X01.csv", b"1,2\n3,4\n", licence=BY
        )
        self.raw = self.stored_file(
            self.analyses["open"], "X01.mca", bytes(range(256)) * 40
        )

    def test_content_length_is_the_exact_size_of_the_archive(self):
        response, body = self.download(self.document_query())

        self.assertEqual(int(response["Content-Length"]), len(body))
        self.assertIsNone(zipfile.ZipFile(io.BytesIO(body)).testzip())

    def test_entries_are_stored_not_compressed(self):
        with self.archive(self.document_query()) as archive:
            infos = archive.infolist()

        self.assertTrue(infos)
        self.assertEqual({i.compress_type for i in infos}, {zipfile.ZIP_STORED})

    def test_files_are_byte_identical(self):
        found = self.contents(self.document_query())

        (csv_name,) = [n for n in found if n.endswith("/X01.csv")]
        (raw_name,) = [n for n in found if n.endswith("/X01.mca")]
        self.assertEqual(found[csv_name], b"1,2\n3,4\n")
        self.assertEqual(found[raw_name], bytes(range(256)) * 40)

    def test_ro_crate_hashes_match_the_files(self):
        found = self.contents(self.document_query())

        crate = json.loads(found["ro-crate-metadata.json"])
        files = [e for e in crate["@graph"] if e["@type"] == "File"]
        self.assertEqual(
            {e["@id"] for e in files}, set(found) - {"ro-crate-metadata.json"}
        )
        for entity in files:
            data = found[entity["@id"]]
            self.assertEqual(entity["sha256"], hashlib.sha256(data).hexdigest())
            self.assertEqual(entity["contentSize"], str(len(data)))

    def test_the_archive_holds_the_members_of_the_package(self):
        with self.archive(self.document_query()) as archive:
            names = archive.namelist()
        with mock.patch(FETCH, side_effect=fetch):
            scope = resolve_scope(
                QueryDict(self.document_query()), self.anonymous, "en"
            )
            members = package(scope, EXPORTED)

        self.assertEqual(
            names, [m.arcname for m in members] + ["ro-crate-metadata.json"]
        )

    def test_the_download_is_a_private_attachment(self):
        response = self.get(self.document_query(), HTTP_ACCEPT_ENCODING="gzip")

        self.assertEqual(response["Content-Type"], "application/zip")
        self.assertRegex(
            response["Content-Disposition"],
            r'^attachment; filename="manuspectrum-document-[0-9a-f]{12}\.zip"$',
        )
        self.assertEqual(response["Cache-Control"], "private, no-store")
        self.assertFalse(response.has_header("Content-Encoding"))
        self.assertFalse(response.has_header("ETag"))

    def test_the_readme_and_tables_follow_lang(self):
        found = self.contents(f"{self.document_query()}&lang=fr")

        self.assertIn("Comment citer", found["README.md"].decode())


class BoundsTests(ExportCase):
    def setUp(self):
        super().setUp()
        self.stored_file(self.analyses["open"], "X01.csv", b"1,2\n3,4\n")
        self.stored_file(self.analyses["open"], "X01.mca", b"\x00" * 100)

    def test_over_the_byte_ceiling_answers_413_without_body(self):
        with (
            self.settings(EXPLORER_EXPORT_MAX_BYTES=107),
            mock.patch(
                "manuspectrum.views.explorer_export.open", create=True
            ) as opened,
        ):
            response = self.get(self.document_query())

        self.assert_bodyless(response, 413)
        opened.assert_not_called()

    def test_at_the_byte_ceiling_the_archive_is_served(self):
        with self.settings(EXPLORER_EXPORT_MAX_BYTES=108):
            response = self.get(self.document_query())

        self.assertEqual(response.status_code, 200)

    def test_over_the_file_count_answers_413_without_body(self):
        with self.settings(EXPLORER_EXPORT_MAX_FILES=1):
            response = self.get(self.document_query())

        self.assert_bodyless(response, 413)

    def test_a_file_that_changed_size_aborts_the_stream(self):
        (row,) = File.objects.filter(path__endswith="X01.csv")
        response = self.get(self.document_query())
        with open(row.path.path, "wb") as handle:
            handle.write(b"1,2\n")

        with self.assertRaises(RuntimeError):
            b"".join(response.streaming_content)

    def test_a_file_that_grew_aborts_the_stream(self):
        (row,) = File.objects.filter(path__endswith="X01.csv")
        response = self.get(self.document_query())
        with open(row.path.path, "ab") as handle:
            handle.write(b"5,6\n" * 1000)

        with self.assertRaises(RuntimeError):
            b"".join(response.streaming_content)


class EarlyRefusalTests(ExportCase):
    def setUp(self):
        super().setUp()
        self.stored_file(self.analyses["open"], "X01.csv", b"1,2\n3,4\n")
        self.stored_file(self.analyses["open"], "X01.mca", b"\x00" * 100)

    def refused(self, **limits):
        with (
            self.settings(**limits),
            mock.patch(f"{EXPORT}.analysis_zones", side_effect=AssertionError),
            mock.patch(f"{EXPORT}._data_members", side_effect=AssertionError),
            mock.patch(f"{EXPORT}.build_manifest", side_effect=AssertionError),
        ):
            return self.get(self.document_query())

    def test_too_many_files_are_refused_before_any_member_is_built(self):
        self.assert_bodyless(self.refused(EXPLORER_EXPORT_MAX_FILES=1), 413)

    def test_too_many_bytes_are_refused_before_any_member_is_built(self):
        self.assert_bodyless(self.refused(EXPLORER_EXPORT_MAX_BYTES=107), 413)


class ConstantWorkTests(ExportCase):
    def work(self, query):
        """``(SQL queries, cache calls)`` of a warm ``package`` of *query*."""
        with mock.patch(FETCH, side_effect=fetch):
            scope = resolve_scope(QueryDict(query), self.anonymous, "en")
            package(scope, EXPORTED)
        backend = type(caches["default"])
        calls = []

        def spy(name):
            real = getattr(backend, name)

            def counted(cache, *args, **kwargs):
                calls.append(name)
                return real(cache, *args, **kwargs)

            return counted

        patches = [mock.patch.object(backend, n, spy(n)) for n in CACHE_CALLS]
        with CaptureQueriesContext(connection) as queries:
            with mock.patch(FETCH, side_effect=fetch):
                for patch in patches:
                    patch.start()
                try:
                    package(scope, EXPORTED)
                finally:
                    for patch in patches:
                        patch.stop()
        return len(queries), len(calls)

    def test_reading_the_files_costs_the_same_for_one_file_or_many(self):
        query = f"ids=an:{self.pk('open')}:-"
        self.stored_file(self.analyses["open"], "X01.csv", b"1,2\n")
        one = self.work(query)
        for index in range(2, 7):
            self.stored_file(self.analyses["open"], f"X0{index}.csv", b"1,2\n")

        many = self.work(query)

        self.assertEqual(many, one)


class VisibilityTests(ExportCase):
    def setUp(self):
        super().setUp()
        self.stored_file(self.analyses["open"], "X01.csv", b"1,2\n3,4\n")
        self.stored_file(self.analyses["embargoed"], "X02.csv", MARKER)

    def test_nothing_the_visitor_cannot_see(self):
        self.embargo(self.analyses["embargoed"])

        found = self.contents(f"ids=an:{self.pk('open')}:-,an:{self.pk('embargoed')}:-")

        everything = b"".join(found.values())
        self.assertNotIn(MARKER, everything)
        self.assertNotIn(self.pk("embargoed").encode(), everything)
        self.assertNotIn(b"X02", everything)
        self.assertTrue(any(n.endswith("/X01.csv") for n in found))

    def test_restricted_inclusion_is_explicit_and_marked(self):
        self.embargo(self.analyses["embargoed"])
        query = f"ids=an:{self.pk('open')}:-,an:{self.pk('embargoed')}:-"
        visitor = self.contents(query)
        self.client.force_login(self.editor)

        default = self.contents(query)
        restricted = self.contents(f"{query}&restricted=1")

        self.assertEqual(default, visitor)
        self.assertIn(MARKER, b"".join(restricted.values()))
        self.assertIn(
            "Contains restricted-access data", restricted["README.md"].decode()
        )
        crate = json.loads(restricted["ro-crate-metadata.json"])
        (root,) = [e for e in crate["@graph"] if e["@id"] == "./"]
        self.assertIn("Contains restricted-access data", root["description"])
        self.assertNotIn(b"restricted", default["README.md"].lower())

    def test_unknown_and_embargoed_scopes_answer_the_same_404(self):
        self.embargo(self.documents["embargoed"])

        unknown = self.get(f"document={UNKNOWN}")
        embargoed = self.get(f"document={self.documents['embargoed'].pk}")

        self.assert_bodyless(unknown, 404)
        self.assert_bodyless(embargoed, 404)
        self.assertEqual(
            sorted(unknown.headers.items()), sorted(embargoed.headers.items())
        )

    def test_no_scope_is_a_bad_request_without_body(self):
        for query in ("", "lang=en", f"{self.document_query()}&lang=xx", "ids=nope"):
            with self.subTest(query=query):
                response = self.get(query)
                self.assertEqual(response.status_code, 400)
                self.assertEqual(response.content, b"")
