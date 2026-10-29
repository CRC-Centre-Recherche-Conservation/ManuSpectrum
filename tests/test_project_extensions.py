"""Every project extension carries the identifier Arches registers it under.

`widget register` gives a widget without `widgetid` a random id, and graphs
that reference the real one then fail to import. Functions and plugins are
registered the same way from their own files.
"""

import ast
import json
import uuid
from pathlib import Path

from django.test import SimpleTestCase

ROOT = Path(__file__).resolve().parent.parent / "manuspectrum"


def is_uuid(value):
    try:
        return str(uuid.UUID(str(value))) == str(value).lower()
    except ValueError:
        return False


def widget_files(root=ROOT):
    return sorted((root / "widgets").glob("*.json"))


def widget_problems(files):
    problems, seen = [], {}
    for path in files:
        widget_id = json.loads(path.read_text("utf-8")).get("widgetid")
        if not is_uuid(widget_id):
            problems.append(f"{path.name}: widgetid missing or not a UUID")
        elif widget_id in seen:
            problems.append(f"{path.name}: widgetid also used by {seen[widget_id]}")
        else:
            seen[widget_id] = path.name
    return problems


class ProjectExtensionTests(SimpleTestCase):
    def test_every_widget_has_a_unique_uuid_widgetid(self):
        files = widget_files()
        self.assertTrue(files)
        self.assertEqual([], widget_problems(files))

    def test_a_widget_without_widgetid_is_detected(self):
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "widgets").mkdir()
            source = widget_files()[0]
            document = json.loads(source.read_text("utf-8"))
            del document["widgetid"]
            (Path(tmp) / "widgets" / source.name).write_text(json.dumps(document))
            problems = widget_problems(widget_files(Path(tmp)))
        self.assertEqual(1, len(problems))
        self.assertIn("widgetid", problems[0])

    def test_every_function_declares_a_uuid_functionid(self):
        import importlib

        names = sorted(
            p.stem for p in (ROOT / "functions").glob("*.py") if p.stem != "__init__"
        )
        self.assertTrue(names)
        ids = []
        for name in names:
            details = importlib.import_module(f"manuspectrum.functions.{name}").details
            self.assertTrue(is_uuid(details.get("functionid")), name)
            ids.append(details["functionid"])
        self.assertEqual(len(ids), len(set(ids)))

    def test_every_workflow_has_a_unique_uuid_pluginid(self):
        files = sorted((ROOT / "workflows").glob("*.json"))
        self.assertTrue(files)
        ids = [json.loads(p.read_text("utf-8")).get("pluginid") for p in files]
        for path, plugin_id in zip(files, ids):
            self.assertTrue(is_uuid(plugin_id), path.name)
        self.assertEqual(len(ids), len(set(ids)))

    def test_the_datatype_is_keyed_by_its_name(self):
        # Read without importing: the datatype module queries the database at import.
        tree = ast.parse((ROOT / "datatypes" / "manifest.py").read_text("utf-8"))
        details = next(
            node.value
            for node in tree.body
            if isinstance(node, (ast.Assign, ast.AnnAssign))
            and any(
                getattr(target, "id", None) == "details"
                for target in getattr(node, "targets", [getattr(node, "target", None)])
            )
        )
        keys = {
            k.value: v.value
            for k, v in zip(details.keys, details.values)
            if isinstance(k, ast.Constant) and isinstance(v, ast.Constant)
        }
        self.assertTrue(keys.get("datatype"))
