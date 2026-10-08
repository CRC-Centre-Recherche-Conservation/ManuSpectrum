"""XRF line table: builder, byte-stable serialisation and the committed file.

Usage:
    python manage.py test tests.test_xrf_line_table --settings="tests.test_settings"
"""

import json
import tempfile
from importlib.util import find_spec
from io import StringIO
from pathlib import Path
from types import SimpleNamespace
from unittest import SkipTest, TestCase, mock, skipUnless

from django.test import SimpleTestCase

from django.core.management import call_command
from django.core.management.base import CommandError

from manuspectrum.utils import xrf_line_table as table

SYMBOLS = {z: f"E{z}" for z in range(1, 100)}


class FakeSource:
    version = "9.9.9"

    def symbol(self, z):
        return SYMBOLS[z]

    def lines(self, symbol):
        return {
            "Ka1": (6404.9, 0.58012, "K"),
            "Lb1": (899.4, 0.5, "L2"),
            "La1": (900.0, 0.123456, "L3"),
        }

    def edges(self, symbol):
        return {
            "K": 7112.0,
            "L1": 1000.4,
            "L3": 899.0,
            "M5": 1200.0,
            "N1": 5000.0,
            "O1": 9000.0,
        }


class BuildTableTests(TestCase):
    def setUp(self):
        self.result = table.build_table(FakeSource())

    def test_z_bounds(self):
        elements = self.result["elements"]
        self.assertEqual(len(elements), 92 - 11 + 1)
        self.assertEqual(elements["E11"]["z"], 11)
        self.assertEqual(elements["E92"]["z"], 92)
        self.assertNotIn("E10", elements)
        self.assertNotIn("E93", elements)

    def test_lines_below_floor_are_dropped(self):
        lines = self.result["elements"]["E26"]["lines"]
        self.assertNotIn("Lb1", lines)
        self.assertIn("La1", lines)

    def test_rounding(self):
        lines = self.result["elements"]["E26"]["lines"]
        self.assertEqual(lines["Ka1"], [6.405, 0.58, "K"])
        self.assertEqual(lines["La1"], [0.9, 0.123, "L3"])

    def test_edge_set_and_floor(self):
        edges = self.result["elements"]["E26"]["edges"]
        self.assertEqual(edges, {"K": 7.112, "L1": 1.0, "M5": 1.2})

    def test_source_and_version(self):
        self.assertEqual(self.result["version"], "9.9.9")
        self.assertTrue(self.result["source"].startswith("XrayDB 9.9.9 (CC0 1.0)"))

    def test_dumps_is_deterministic_compact_and_sorted(self):
        first = table.dumps(self.result)
        second = table.dumps(table.build_table(FakeSource()))
        self.assertEqual(first, second)
        self.assertNotIn(
            ", ", json.dumps(self.result["elements"], separators=(",", ":"))
        )
        self.assertNotIn("\n ", first)
        self.assertEqual(json.loads(first), self.result)
        keys = list(json.loads(first)["elements"]["E26"]["lines"])
        self.assertEqual(keys, sorted(keys))


class CommittedTableTests(TestCase):
    def setUp(self):
        self.committed = json.loads(table.TABLE_PATH.read_text(encoding="utf-8"))

    def line(self, symbol, name):
        return self.committed["elements"][symbol]["lines"][name]

    def test_spot_values(self):
        self.assertEqual(self.line("Pb", "La1")[0], 10.551)
        self.assertEqual(self.line("As", "Ka1")[0], 10.543)
        self.assertEqual(self.line("Fe", "Ka1")[0], 6.405)
        self.assertEqual(self.line("S", "Ka1")[0], 2.309)
        self.assertEqual(self.committed["elements"]["Pb"]["edges"]["L3"], 13.035)

    def test_covers_z_range_and_floor(self):
        elements = self.committed["elements"]
        self.assertEqual(sorted(e["z"] for e in elements.values())[0], 11)
        self.assertEqual(max(e["z"] for e in elements.values()), 92)
        for element in elements.values():
            for energy, _, _ in element["lines"].values():
                self.assertGreaterEqual(energy, table.MIN_LINE_KEV)

    def test_file_is_in_canonical_form(self):
        text = table.TABLE_PATH.read_text(encoding="utf-8")
        self.assertEqual(text, table.dumps(self.committed))


@skipUnless(find_spec("xraydb"), "xraydb is not installed")
class CheckCommandTests(TestCase):
    def test_check_matches_committed_file(self):
        out = StringIO()
        call_command("xrf_line_table", "--check", stdout=out)
        self.assertIn("up to date", out.getvalue())


class MissingXraydbTests(SimpleTestCase):
    def test_command_explains_the_install_when_xraydb_is_missing(self):
        if find_spec("xraydb"):
            raise SkipTest("xraydb is installed")
        with self.assertRaisesMessage(CommandError, "xraydb==") as context:
            call_command("xrf_line_table", "--check")
        self.assertIn("PYTHONPATH", str(context.exception))


class CommandWithFakeSourceTests(SimpleTestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.path = Path(folder.name) / "xrf" / "xray-lines.json"
        for target, value in (("xraydb_source", FakeSource), ("TABLE_PATH", self.path)):
            patcher = mock.patch.object(table, target, value)
            patcher.start()
            self.addCleanup(patcher.stop)

    def test_write_then_check(self):
        out = StringIO()
        call_command("xrf_line_table", "--write", stdout=out)
        self.assertEqual(
            self.path.read_text(encoding="utf-8"),
            table.dumps(table.build_table(FakeSource())),
        )
        self.assertIn("Wrote", out.getvalue())

        call_command("xrf_line_table", "--check", stdout=out)
        self.assertIn("up to date", out.getvalue())

    def test_check_refuses_a_missing_or_stale_file(self):
        with self.assertRaisesMessage(CommandError, "9.9.9"):
            call_command("xrf_line_table", "--check")
        self.path.parent.mkdir(parents=True)
        self.path.write_text("{}\n", encoding="utf-8")
        with self.assertRaisesMessage(CommandError, "differs"):
            call_command("xrf_line_table", "--check")


class XrayDBSourceTests(TestCase):
    def setUp(self):
        line = SimpleNamespace(energy=10551.0, intensity=0.68, initial_level="L3")
        self.module = SimpleNamespace(
            __version__="4.5.8",
            atomic_symbol=lambda z: {82: "Pb"}[z],
            xray_lines=lambda symbol: {"La1": line},
            xray_edges=lambda symbol: {"L3": SimpleNamespace(energy=13035.0)},
        )

    def test_reads_symbols_lines_and_edges_from_the_module(self):
        with mock.patch.dict("sys.modules", {"xraydb": self.module}):
            source = table.xraydb_source()

        self.assertEqual(source.version, "4.5.8")
        self.assertEqual(source.symbol(82), "Pb")
        self.assertEqual(source.lines("Pb"), {"La1": (10551.0, 0.68, "L3")})
        self.assertEqual(source.edges("Pb"), {"L3": 13035.0})
