import ast
import tempfile
from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase

from manuspectrum.cache_version import (
    CACHE_SHAPE_MODULES,
    cache_code_version,
)


class CacheCodeVersionTests(SimpleTestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        self.addCleanup(lambda: None)
        (self.root / "a.py").write_text("a = 1\n")
        (self.root / "b.py").write_text("b = 1\n")
        self.modules = ("a.py", "b.py")

    def version(self, environ=None):
        return cache_code_version(self.root, self.modules, environ or {})

    def test_is_twelve_hex_characters_and_stable(self):
        first = self.version()
        self.assertRegex(first, r"^[0-9a-f]{12}$")
        self.assertEqual(first, self.version())

    def test_moves_when_a_listed_module_changes(self):
        before = self.version()
        (self.root / "b.py").write_text("b = 2\n")
        self.assertNotEqual(before, self.version())

    def test_ignores_files_that_are_not_listed(self):
        before = self.version()
        (self.root / "c.py").write_text("c = 1\n")
        self.assertEqual(before, self.version())

    def test_depends_on_which_file_holds_the_bytes(self):
        (self.root / "a.py").write_text("x\n")
        (self.root / "b.py").write_text("y\n")
        swapped = cache_code_version(self.root, ("b.py", "a.py"), {})
        self.assertNotEqual(self.version(), swapped)

    def test_environment_override_wins_verbatim(self):
        self.assertEqual(
            self.version({"MANUSPECTRUM_CACHE_VERSION": "release-42"}), "release-42"
        )
        self.assertNotEqual(self.version({"MANUSPECTRUM_CACHE_VERSION": "  "}), "  ")

    def test_listed_modules_exist(self):
        for relative in CACHE_SHAPE_MODULES:
            self.assertTrue(Path(settings.APP_ROOT, relative).is_file(), relative)

    def test_settings_expose_the_version_and_prefix_the_default_cache(self):
        self.assertRegex(settings.CACHE_CODE_VERSION, r"^[0-9a-f]{12}$")
        self.assertEqual(
            settings.CACHES["default"].get("KEY_PREFIX"),
            f"ms:{settings.CACHE_CODE_VERSION}",
        )


BUNDLE_BUILDERS = (
    "views/explorer/service.py",
    "views/explorer/home.py",
    "views/explorer/memo.py",
    "views/explorer/values.py",
    "utils/role_links.py",
)
NOT_SHAPING = {
    "models.py": "database models: the data, not the code, of a payload",
    "utils/cache.py": "cache helpers: they name and lock entries, never fill them",
    "utils/data_version.py": "the ledger version: part of the bundle key",
    "utils/iiif_tools.py": "reads upstream manifests and draws zones of per-request payloads",
    "constants/licenses.py": "file licences of per-request payloads (document, analysis, items)",
    "constants/xy_presets.py": "renderer presets of file entries in per-request payloads",
    "views/explorer/citations.py": "citations of the analysis payload, never memoised",
    "views/explorer/conditions.py": "conditions and notes of per-request payloads",
}


def manuspectrum_imports(relative):
    """The files under the app root that the module *relative* imports from ``manuspectrum``."""
    tree = ast.parse(Path(settings.APP_ROOT, relative).read_text())
    found = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.ImportFrom) or not node.module:
            continue
        if node.module == "manuspectrum.views.explorer":
            found.update(f"views/explorer/{a.name}.py" for a in node.names)
        elif node.module.startswith("manuspectrum."):
            path = node.module.removeprefix("manuspectrum.").replace(".", "/")
            found.add(f"{path}.py")
    return found


class ShapeModulesTests(SimpleTestCase):
    def test_every_module_the_bundle_build_imports_is_listed_or_known_not_to_shape_it(
        self,
    ):
        for builder in BUNDLE_BUILDERS:
            self.assertIn(builder, CACHE_SHAPE_MODULES)
            for imported in manuspectrum_imports(builder):
                with self.subTest(builder=builder, imported=imported):
                    self.assertTrue(
                        imported in CACHE_SHAPE_MODULES or imported in NOT_SHAPING,
                        f"{imported} (imported by {builder}) is neither in "
                        "CACHE_SHAPE_MODULES nor known not to shape the bundle",
                    )
