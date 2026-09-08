"""What the generated trigger SQL is required to say.

The two trigger bodies are templates: graph coordinates, the text-format
whitelist and the whole technique -> configuration map are substituted into
them from :mod:`manuspectrum.constants.xy_presets` and settings, so the SQL
never repeats a value Python already owns. Nothing checks the result at
``migrate`` time — PostgreSQL happily installs a trigger whose ``WHEN`` clause
names a nodegroup that does not exist, and it then simply never fires.

So these tests read the generated bodies back and assert they carry the values
they were built from: the ids, every extension, and one row per technique. The
last one is what keeps the SQL and the Python map from drifting apart, since
the map is 76 entries long and no other test compares the two.
"""

import re
import tempfile
from pathlib import Path
from unittest import mock

from django.conf import settings
from django.test import SimpleTestCase

from manuspectrum import sql_config
from manuspectrum.sql_config import drop_trigger_sql, read_sql, sql_items
from manuspectrum.constants.xy_presets import (
    DATA_FILE_NODE_ID,
    DATA_FILE_NODEGROUP_ID,
    TECHNIQUE_CONFIG_IDS,
    TECHNIQUE_NODE_ID,
    TECHNIQUE_NODEGROUP_ID,
)

ITEMS = {item.name: item for item in sql_items}
STAMP = "ms_xy_stamp_file_config"
REAPPLY = "ms_xy_reapply_on_technique"


class ReadSqlTests(SimpleTestCase):
    def _sql_dir(self, **files):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        for filename, body in files.items():
            (Path(directory.name) / filename).write_text(body, encoding="utf-8")
        patched = mock.patch.object(sql_config, "SQL_DIR", Path(directory.name))
        patched.start()
        self.addCleanup(patched.stop)

    def test_every_placeholder_is_replaced_by_its_value(self):
        self._sql_dir(**{"body.sql": "WHEN @@NODEGROUP@@ THEN @@MAP@@, @@NODEGROUP@@"})

        self.assertEqual(
            read_sql("body.sql", NODEGROUP="a-uuid", MAP="('x', 'y')"),
            "WHEN a-uuid THEN ('x', 'y'), a-uuid",
        )

    def test_a_non_string_value_is_rendered_as_text(self):
        self._sql_dir(**{"body.sql": "LIMIT @@COUNT@@"})

        self.assertEqual(read_sql("body.sql", COUNT=3), "LIMIT 3")

    def test_an_unsubstituted_placeholder_raises(self):
        self._sql_dir(**{"body.sql": "WHEN @@KNOWN@@ AND @@FORGOTTEN@@"})

        with self.assertRaises(ValueError) as raised:
            read_sql("body.sql", KNOWN="a-uuid")

        self.assertIn("body.sql", str(raised.exception))
        self.assertIn("@@FORGOTTEN@@", str(raised.exception))

    def test_the_guard_reports_a_placeholder_left_by_a_misspelled_token(self):
        self._sql_dir(**{"body.sql": "WHEN @@TECHNIQUE_NODEGROUP@@"})

        with self.assertRaises(ValueError):
            read_sql("body.sql", TECHNIQUE_NODE_GROUP="a-uuid")


class DropTriggerSqlTests(SimpleTestCase):
    def test_it_drops_both_the_trigger_and_the_function_it_calls(self):
        sql = drop_trigger_sql("ms_xy_example")

        self.assertIn("DROP TRIGGER IF EXISTS ms_xy_example ON tiles;", sql)
        self.assertIn("DROP FUNCTION IF EXISTS ms_xy_example();", sql)


class SQLItemDeclarationTests(SimpleTestCase):
    def test_exactly_the_two_xy_triggers_are_declared(self):
        self.assertEqual(set(ITEMS), {STAMP, REAPPLY})
        self.assertEqual(len(sql_items), 2)

    def test_each_item_replaces_rather_than_drops(self):
        # Both bodies are CREATE OR REPLACE, so an AlterSQL migration must not
        # emit a drop first: dropping the function would drop the trigger with
        # it, leaving a window with no rule installed.
        for name, item in ITEMS.items():
            with self.subTest(item=name):
                self.assertTrue(item.replace)

    def test_the_reverse_sql_removes_the_trigger_and_the_function(self):
        for name, item in ITEMS.items():
            with self.subTest(item=name):
                self.assertIn(
                    f"DROP TRIGGER IF EXISTS {name} ON tiles;", item.reverse_sql
                )
                self.assertIn(f"DROP FUNCTION IF EXISTS {name}();", item.reverse_sql)

    def test_no_placeholder_marker_survives_in_either_body(self):
        for name, item in ITEMS.items():
            with self.subTest(item=name):
                self.assertNotIn("@@", item.sql)


class StampBodyTests(SimpleTestCase):
    @property
    def sql(self):
        return ITEMS[STAMP].sql

    def test_it_reads_the_file_value_of_the_measurement_node(self):
        self.assertIn(f"NEW.tiledata -> '{DATA_FILE_NODE_ID}'", self.sql)

    def test_it_writes_back_to_the_same_node(self):
        self.assertIn(f"ARRAY['{DATA_FILE_NODE_ID}']", self.sql)

    def test_it_reads_the_technique_from_the_technique_node(self):
        self.assertIn(f"technique.tiledata -> '{TECHNIQUE_NODE_ID}'", self.sql)
        self.assertIn(
            f"technique.nodegroupid = '{TECHNIQUE_NODEGROUP_ID}'::uuid", self.sql
        )

    def test_it_fires_before_the_write_on_the_file_nodegroup(self):
        # BEFORE, because the function stamps NEW.tiledata in place; an AFTER
        # trigger would have nothing to assign to.
        self.assertIn("BEFORE INSERT OR UPDATE ON tiles", self.sql)
        self.assertIn(
            f"WHEN (NEW.nodegroupid = '{DATA_FILE_NODEGROUP_ID}'::uuid)", self.sql
        )

    def test_every_configured_text_format_is_quoted_in_the_extension_list(self):
        self.assertTrue(
            settings.XY_TEXT_FILE_FORMATS,
            msg="an empty whitelist renders ARRAY[]::text[] and stamps nothing",
        )
        literal = re.search(r"ARRAY\[(.*?)\]::text\[\]", self.sql)
        self.assertIsNotNone(literal)

        quoted = [part.strip() for part in literal.group(1).split(",")]
        for part in quoted:
            self.assertRegex(part, r"^'[^']*'$")
        self.assertEqual(
            [part.strip("'") for part in quoted],
            list(settings.XY_TEXT_FILE_FORMATS),
        )

    def test_the_values_list_holds_one_row_per_mapped_technique(self):
        block = self.sql.split("JOIN (VALUES")[1].split(") AS preset")[0]
        pairs = re.findall(r"\('([^']+)', '([^']+)'::uuid\)", block)

        self.assertEqual(len(pairs), len(TECHNIQUE_CONFIG_IDS))
        self.assertEqual(dict(pairs), dict(TECHNIQUE_CONFIG_IDS))


class ReapplyBodyTests(SimpleTestCase):
    @property
    def sql(self):
        return ITEMS[REAPPLY].sql

    def test_it_fires_after_a_technique_write(self):
        self.assertIn("AFTER INSERT OR UPDATE ON tiles", self.sql)
        self.assertIn(
            f"WHEN (NEW.nodegroupid = '{TECHNIQUE_NODEGROUP_ID}'::uuid)", self.sql
        )

    def test_it_touches_the_file_nodegroup_of_the_same_resource_only(self):
        self.assertIn(f"WHERE nodegroupid = '{DATA_FILE_NODEGROUP_ID}'::uuid", self.sql)
        self.assertIn("AND resourceinstanceid = NEW.resourceinstanceid", self.sql)

    def test_the_nodegroup_it_fires_on_is_not_the_one_it_touches(self):
        # Equal ids would make the UPDATE re-enter this same trigger.
        fires_on = re.search(r"WHEN \(NEW\.nodegroupid = '([^']+)'::uuid\)", self.sql)
        touches = re.search(r"WHERE nodegroupid = '([^']+)'::uuid", self.sql)

        self.assertNotEqual(fires_on.group(1), touches.group(1))
