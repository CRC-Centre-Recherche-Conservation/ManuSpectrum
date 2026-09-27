"""The IIIF package builds documents without importing a view.

``django.setup()`` alone imports every view of the project (URLconf, system
checks), so the test follows the ``import`` statements of the source files
instead: every ``manuspectrum.*`` module reached from ``manuspectrum.iiif``,
module-level and function-level imports alike.

Usage:
    python manage.py test tests.test_iiif_imports --settings=tests.test_settings
"""

import ast
from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase

# Modules under manuspectrum.views the package may reach: the package roots,
# the pure value helpers, and the graph index the roles resolve through.
ALLOWED_VIEW_MODULES = {
    "manuspectrum.views",
    "manuspectrum.views.explorer",
    "manuspectrum.views.explorer.values",
    "manuspectrum.views.summary_service",
    "manuspectrum.views.graph_nodes",
}
ROOT = Path(settings.APP_ROOT)


def source_of(module):
    """The source file of a ``manuspectrum.*`` module, or None (a name imported from a package)."""
    relative = Path(*module.split(".")[1:])
    for candidate in (
        ROOT / relative.with_suffix(".py"),
        ROOT / relative / "__init__.py",
    ):
        if candidate.is_file():
            return candidate
    return None


def imported_modules(module):
    """The ``manuspectrum.*`` modules *module* imports, packages of the path included."""
    tree = ast.parse(source_of(module).read_text())
    found = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names = [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom) and node.module and not node.level:
            names = [node.module] + [f"{node.module}.{a.name}" for a in node.names]
        else:
            continue
        for name in names:
            parts = name.split(".")
            for end in range(1, len(parts) + 1):
                candidate = ".".join(parts[:end])
                if candidate.startswith("manuspectrum.") and source_of(candidate):
                    found.add(candidate)
    return found


def reached_from(roots):
    seen, todo = set(), list(roots)
    while todo:
        module = todo.pop()
        if module in seen:
            continue
        seen.add(module)
        todo.extend(imported_modules(module) - seen)
    return seen


def iiif_modules():
    """Every ``manuspectrum.iiif.*`` module on disk."""
    return sorted(
        f"manuspectrum.iiif.{path.stem}"
        for path in (ROOT / "iiif").glob("*.py")
        if path.stem != "__init__"
    )


class ImportTests(SimpleTestCase):
    def test_the_iiif_package_imports_no_view(self):
        modules = iiif_modules()
        self.assertTrue(modules)
        reached = reached_from(modules)
        views = {m for m in reached if m.startswith("manuspectrum.views")}

        self.assertEqual(views - ALLOWED_VIEW_MODULES, set())

    def test_the_walk_sees_a_view_import(self):
        reached = reached_from(["manuspectrum.views.explorer.manifest"])

        self.assertIn("manuspectrum.views.explorer.service", reached)
