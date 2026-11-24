import hashlib
import io
import tempfile
from pathlib import Path

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import SimpleTestCase

from manuspectrum.measurement_files.converters import check_csv, csv_name

FIXTURES = Path(__file__).parent / "fixtures" / "measurement_files"
OUTCOMES = ("csv", "raw-only", "unsupported")


def snapshot(root):
    return {
        str(p.relative_to(root)): (
            p.stat().st_size,
            hashlib.sha256(p.read_bytes()).hexdigest(),
        )
        for p in sorted(root.rglob("*"))
        if p.is_file()
    }


def run(*args):
    out = io.StringIO()
    call_command("convert_raw_files", *args, stdout=out)
    return out.getvalue()


class ConvertRawFilesTests(SimpleTestCase):
    """`databases = set()`: SimpleTestCase fails any query, so a pass proves
    the command never touches the database."""

    databases = set()

    def test_reports_every_fixture(self):
        files = [p for p in sorted(FIXTURES.rglob("*")) if p.is_file()]
        with tempfile.TemporaryDirectory() as out_dir:
            report = run(str(FIXTURES), "--out", out_dir)
            lines = report.rstrip("\n").split("\n")
            self.assertEqual(len(lines), len(files))
            self.assertEqual(
                [line.split("\t")[0] for line in lines],
                [str(p.relative_to(FIXTURES)) for p in files],
            )
            for line in lines:
                fields = line.split("\t")
                self.assertEqual(len(fields), 7, line)
                outcome = fields[2]
                self.assertTrue(
                    outcome in OUTCOMES or outcome.startswith("unreadable:"), line
                )
            written = [p for p in Path(out_dir).rglob("*.csv")]
            self.assertTrue(written)
            for path in written:
                self.assertEqual(check_csv(path.read_bytes()), (), path)
                for lang in ("en", "fr"):
                    self.assertTrue(
                        path.with_name(f"{path.name}.description.{lang}.txt").is_file()
                    )
            csv_lines = [x for x in lines if x.split("\t")[2] == "csv"]
            self.assertEqual(len(csv_lines), len(written))
            first = csv_lines[0].split("\t")[0]
            rel = Path(first)
            self.assertTrue((Path(out_dir) / rel.parent / csv_name(rel.name)).is_file())

    def test_never_writes_next_to_inputs(self):
        before = snapshot(FIXTURES)
        with tempfile.TemporaryDirectory() as out_dir:
            run(str(FIXTURES), "--out", out_dir)
        self.assertEqual(snapshot(FIXTURES), before)

    def test_without_out_writes_nothing(self):
        before = snapshot(FIXTURES)
        self.assertTrue(run(str(FIXTURES)).strip())
        self.assertEqual(snapshot(FIXTURES), before)

    def test_refuses_out_inside_input_and_input_inside_out(self):
        with tempfile.TemporaryDirectory() as root:
            tree = Path(root) / "in"
            tree.mkdir()
            (tree / "a.txt").write_text("x")
            with self.assertRaises(CommandError):
                run(str(tree), "--out", str(tree / "out"))
            with self.assertRaises(CommandError):
                run(str(tree), "--out", str(tree))
            with self.assertRaises(CommandError):
                run(str(tree / "a.txt"), "--out", str(root))

    def test_skips_symlinks(self):
        with tempfile.TemporaryDirectory() as root:
            tree = Path(root) / "in"
            tree.mkdir()
            (tree / "a.txt").write_text("x")
            (tree / "link.txt").symlink_to(tree / "a.txt")
            lines = run(str(tree)).rstrip("\n").split("\n")
            self.assertEqual([x.split("\t")[0] for x in lines], ["a.txt"])

    def test_missing_input_is_an_error(self):
        with self.assertRaises(CommandError):
            run("/nonexistent-path-for-test")
