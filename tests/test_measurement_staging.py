import tempfile
import unicodedata
import uuid
from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase, override_settings

from manuspectrum.constants import measurement_files as vocab
from manuspectrum.measurement_files import staging


class SafeNameTests(SimpleTestCase):
    def test_table(self):
        cases = {
            "../x.0": "x.0",
            "/etc/passwd": "passwd",
            "..\\..\\win\\y.0": "y.0",
            "a\x00b.0": "ab.0",
            "tab\there\n.0": "tabhere.0",
            "": "file",
            "/": "file",
            "..": "file",
            ".": "file",
            "dir/": "file",
        }
        for raw, expected in cases.items():
            with self.subTest(raw=raw):
                self.assertEqual(staging.safe_name(raw), expected)

    def test_nfc(self):
        nfd = unicodedata.normalize("NFD", "é.0")
        self.assertEqual(staging.safe_name(nfd), unicodedata.normalize("NFC", "é.0"))

    def test_length_capped(self):
        self.assertEqual(len(staging.safe_name("a" * 300 + ".0")), 200)

    def test_no_separator_survives(self):
        for raw in ("a/b\\c", "x/../y", "..%2f"):
            name = staging.safe_name(raw)
            self.assertNotIn("/", name)
            self.assertNotIn("\\", name)


class StagingDirTests(SimpleTestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        override = override_settings(MEDIA_ROOT=self._tmp.name)
        override.enable()
        self.addCleanup(override.disable)
        self.run_id = uuid.uuid4()
        self.item_id = uuid.uuid4()

    def test_run_dir_under_media_root(self):
        path = staging.run_dir(self.run_id)
        self.assertTrue(path.is_dir())
        self.assertEqual(
            path,
            Path(self._tmp.name) / settings.MEASUREMENT_STAGING_DIR / str(self.run_id),
        )
        self.assertEqual(path.stat().st_mode & 0o777, 0o750)

    def test_store_read_round_trip(self):
        name = staging.store(self.run_id, self.item_id, b"abc", "raw")
        self.assertEqual(name, f"{self.item_id}-raw")
        self.assertEqual(staging.read(self.run_id, name), b"abc")
        self.assertEqual(
            [p.name for p in staging.run_dir(self.run_id).iterdir()], [name]
        )

    def test_store_overwrites_atomically(self):
        staging.store(self.run_id, self.item_id, b"one", "csv")
        name = staging.store(self.run_id, self.item_id, b"two", "csv")
        self.assertEqual(staging.read(self.run_id, name), b"two")
        self.assertEqual(len(list(staging.run_dir(self.run_id).iterdir())), 1)

    def test_store_refuses_traversal(self):
        for suffix in ("../../escape", "/abs", "a/b"):
            with self.subTest(suffix=suffix):
                with self.assertRaises(ValueError):
                    staging.store(self.run_id, self.item_id, b"x", suffix)
        self.assertEqual(list(Path(self._tmp.name).rglob("escape")), [])

    def test_read_refuses_traversal(self):
        outside = Path(self._tmp.name) / "secret"
        outside.write_bytes(b"s")
        with self.assertRaises(ValueError):
            staging.read(self.run_id, "../../secret")

    def test_remove_run(self):
        staging.store(self.run_id, self.item_id, b"abc", "raw")
        staging.remove_run(self.run_id)
        self.assertFalse(
            (
                Path(self._tmp.name)
                / settings.MEASUREMENT_STAGING_DIR
                / str(self.run_id)
            ).exists()
        )
        staging.remove_run(self.run_id)


class VocabularyTests(SimpleTestCase):
    def test_common_codes(self):
        self.assertEqual(vocab.COMMON_CODES["IRTF"], "ftir")
        self.assertEqual(vocab.COMMON_CODES["MALDI"], "mass_spec")
        self.assertEqual(vocab.COMMON_CODES["F"], "fors")

    def test_causes_closed(self):
        self.assertEqual(len(vocab.CAUSES), 14)
        self.assertIn("too_large", vocab.CAUSES)

    def test_settings(self):
        self.assertEqual(settings.MEASUREMENT_MAX_REQUEST_FILES, 50)
        self.assertEqual(settings.MEASUREMENT_DEFAULT_MAX_FILE_MB, 10)
        self.assertEqual(settings.MEASUREMENT_STAGING_DIR, "measurement-staging")
