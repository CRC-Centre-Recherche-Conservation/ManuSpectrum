"""Contract between the nginx edge rules and the Django URLconf.

The location blocks under ``deploy/compose/nginx`` are read with regular
expressions (no nginx parser). Each path nginx names must still resolve to the
view it was written for, and every ``(en|fr)`` alternation must equal
``settings.LANGUAGES``. ``MS_EDGE_NGINX_DIR`` points the module at another copy
of the nginx directory.
"""

import os
import re
import uuid
from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase
from django.urls import Resolver404, resolve
from django.utils import translation

NGINX_DIR = Path(
    os.environ.get(
        "MS_EDGE_NGINX_DIR",
        Path(__file__).resolve().parent.parent / "deploy" / "compose" / "nginx",
    )
)
LOCATION = re.compile(
    r"^\s*location\s+(?:(~\*?|=|\^~)\s+)?(\"[^\"]+\"|[^\s{]+)\s*\{", re.M
)
LANGUAGE_ALTERNATION = re.compile(r"/\(([a-z]{2}(?:\|[a-z]{2})*)\)")
UUID = str(uuid.uuid4())

QUERYSETS_BLOCK = "snippets/edge-rules.conf"
QUERYSETS_PATHS = [
    ("api/resource/g", "arches_querysets:api-resources"),
    ("api/tile/g/n", "arches_querysets:api-tiles"),
    (f"api/tile-list-create/g/n/{UUID}", "arches_vue_components:api-tile-list-create"),
    ("api/tile-new-resource/g/n", "arches_vue_components:api-tile-new-resource"),
]
OPEN_PATHS = [
    (f"api/tiles/{UUID}", "api_tiles"),
    ("api/relatable-resources/g/n", "arches_vue_components:api-relatable-resources"),
]

# (nginx file, path below the language prefix or None when bare, view name)
PREFIXED = [
    ("snippets/edge-rules.conf", "api/search/export_results", "api_export_results"),
    ("snippets/edge-rules.conf", "search/export_results", "export_results"),
    ("snippets/edge-rules.conf", "temp_file", "temp_file"),
    ("snippets/edge-rules.conf", "auth/", "auth"),
    ("snippets/edge-rules.conf", "admin/login/", "admin:login"),
    ("snippets/edge-rules.conf", "password_reset/", "password_reset"),
    ("snippets/edge-rules.conf", "reset/a/b/", "password_reset_confirm"),
    ("snippets/edge-rules.conf", "o/token/", "oauth2:token"),
    (
        "snippets/edge-rules.conf",
        "two-factor-authentication-login",
        "two-factor-authentication-login",
    ),
    (
        "snippets/edge-rules.conf",
        "two-factor-authentication-reset",
        "two-factor-authentication-reset",
    ),
    ("snippets/edge-rules.conf", "api/explorer/share", "explorer-share"),
    ("snippets/media.conf", f"files/{UUID}", "file_access"),
]
BARE = [
    ("snippets/edge-rules.conf", "/healthz", "healthz"),
    ("snippets/edge-rules.conf", "/metrics", "metrics"),
    ("snippets/edge-rules.conf", "/readyz", "readyz"),
    ("snippets/edge-rules.conf", "/api/biblissima/create-all", "biblissima-create-all"),
    (
        "snippets/edge-rules.conf",
        "/api/biblissima/create-resource",
        "biblissima-create-resource",
    ),
    ("snippets/edge-rules.conf", "/api/explorer/export", "explorer-export"),
    ("snippets/edge-rules.conf", "/api/explorer/series.csv", "explorer-series-csv"),
    (
        "snippets/edge-rules.conf",
        "/iiif/v3/explorer-manifest",
        "iiif-v3-explorer-manifest",
    ),
    (
        "snippets/edge-rules.conf",
        f"/api/spectrum-preview/{UUID}",
        "api-spectrum-preview",
    ),
    ("snippets/edge-rules.conf", f"/iiif/data/{UUID}/raw", "iiif-data-raw"),
]


def token_for(path):
    """A literal fragment the dedicated location must contain (None: the generic
    ``/iiif/`` location is the intended rule)."""
    segments = [part for part in path.strip("/").split("/") if part != UUID]
    if segments[:2] == ["iiif", "data"]:
        return None
    if segments[:2] == ["iiif", "v3"]:
        return "/".join(segments[:3])
    if segments[0] in ("api", "iiif"):
        return "/".join(segments[:2])
    return segments[0][:20]


def read_locations(relative):
    """Return the (modifier, pattern) pairs of one nginx file."""
    path = NGINX_DIR / relative
    if not path.is_file():
        raise AssertionError(f"{path}: nginx file missing")
    return [
        (modifier or "", pattern.strip('"'))
        for modifier, pattern in LOCATION.findall(path.read_text())
    ]


def first_location(locations, path):
    """Return the pattern nginx would pick for `path` (file order), or None."""
    for modifier, pattern in locations:
        if modifier == "=":
            if pattern == path:
                return pattern
        elif modifier == "^~":
            if path.startswith(pattern):
                return pattern
        elif modifier.startswith("~") and re.search(pattern, path):
            return pattern
    return None


def location_matches(locations, path):
    return first_location(locations, path) is not None


class EdgeContractTests(SimpleTestCase):
    def assertNamed(self, relative, path, token=None):
        """The location nginx picks for `path` exists and, with `token`, names it."""
        pattern = first_location(read_locations(relative), path)
        self.assertIsNotNone(
            pattern, f"{NGINX_DIR / relative}: no location matches {path}"
        )
        if token is not None:
            self.assertIn(
                token,
                pattern,
                f"{NGINX_DIR / relative}: {path} falls to location {pattern!r}, "
                f"which does not name {token!r}",
            )

    def assertNotNamed(self, relative, path):
        self.assertFalse(
            location_matches(read_locations(relative), path),
            f"{NGINX_DIR / relative}: a location matches {path}, it must not",
        )

    def assertView(self, path, view_name):
        language = path.split("/")[1]
        try:
            with translation.override(
                language if language in dict(settings.LANGUAGES) else "en"
            ):
                match = resolve(path)
        except Resolver404:
            self.fail(f"{path} no longer resolves (nginx expects {view_name})")
        self.assertEqual(match.view_name, view_name, path)

    def test_language_alternations_equal_settings_languages(self):
        codes = {code for code, _ in settings.LANGUAGES}
        files = sorted(NGINX_DIR.rglob("*.conf")) + sorted(
            NGINX_DIR.rglob("*.template")
        )
        found = 0
        for path in files:
            for alternation in LANGUAGE_ALTERNATION.findall(path.read_text()):
                found += 1
                self.assertEqual(
                    set(alternation.split("|")),
                    codes,
                    f"{path}: language alternation ({alternation}) differs from "
                    f"settings.LANGUAGES {sorted(codes)}",
                )
        self.assertGreater(found, 0, f"{NGINX_DIR}: no language alternation found")

    def test_querysets_routes_exist_and_are_blocked_in_every_language(self):
        for code, _ in settings.LANGUAGES:
            for rest, view_name in QUERYSETS_PATHS:
                path = f"/{code}/{rest}"
                self.assertView(path, view_name)
                self.assertNamed(QUERYSETS_BLOCK, path, "api/(resource")

    def test_core_tiles_and_relatable_resources_stay_open(self):
        blocking = read_locations(QUERYSETS_BLOCK)[:1]
        for code, _ in settings.LANGUAGES:
            for rest, view_name in OPEN_PATHS:
                path = f"/{code}/{rest}"
                self.assertView(path, view_name)
                self.assertFalse(
                    location_matches(blocking, path),
                    f"{NGINX_DIR / QUERYSETS_BLOCK}: the first location blocks {path}",
                )

    def test_prefixed_paths_resolve_and_are_named_in_every_language(self):
        for code, _ in settings.LANGUAGES:
            for relative, rest, view_name in PREFIXED:
                path = f"/{code}/{rest}"
                self.assertView(path, view_name)
                self.assertNamed(relative, path, token_for(rest))

    def test_silk_is_named_in_every_language_without_requiring_the_app(self):
        for code, _ in settings.LANGUAGES:
            self.assertNamed("snippets/edge-rules.conf", f"/{code}/silk/", "silk")

    def test_temp_file_download_resolves(self):
        for code, _ in settings.LANGUAGES:
            self.assertView(f"/{code}/temp_file/{UUID}", "temp_file")

    def test_bare_paths_resolve_and_are_not_prefixed(self):
        for relative, path, view_name in BARE:
            self.assertView(path, view_name)
            self.assertNamed(relative, path, token_for(path))
            for code, _ in settings.LANGUAGES:
                with translation.override(code), self.assertRaises(Resolver404):
                    resolve(f"/{code}{path}")

    def test_metrics_is_not_served_under_a_language(self):
        for code, _ in settings.LANGUAGES:
            with translation.override(code), self.assertRaises(Resolver404):
                resolve(f"/{code}/metrics")

    def test_iiif_image_server_under_language_and_bare(self):
        for code, _ in settings.LANGUAGES:
            path = f"/{code}/iiifserver/iiif/2/x"
            self.assertView(
                path, "arches.app.views.manifest_manager.IIIFServerProxyView"
            )
            self.assertNamed("snippets/iiifserver.conf", path, "iiifserver")
        self.assertNamed(
            "snippets/iiifserver.conf", "/iiifserver/iiif/2/x", "iiifserver"
        )
