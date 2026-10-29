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
from django.urls import Resolver404, resolve, reverse
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
LANGUAGE_ALTERNATION = re.compile(r"/\((?:\?P<\w+>)?([a-z]{2}(?:\|[a-z]{2})*)\)")
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
    ("snippets/edge-rules.conf", "account/activate/a/b", "account-activate"),
    ("snippets/edge-rules.conf", "account/two-factor", "account-two-factor"),
    (
        "snippets/edge-rules.conf",
        "account/two-factor/reset/a",
        "account-two-factor-reset",
    ),
    ("snippets/edge-rules.conf", "account/terms", "account-terms"),
    ("snippets/edge-rules.conf", "o/token/", "oauth2:token"),
    (
        "snippets/edge-rules.conf",
        "two-factor-authentication-login",
        "two-factor-authentication-login",
    ),
    ("snippets/edge-rules.conf", "api/explorer/share", "explorer-share"),
    ("snippets/edge-rules.conf", "api/explorer/search", "explorer-search"),
    ("snippets/edge-rules.conf", f"api/explorer/document/{UUID}", "explorer-document"),
    (
        "snippets/edge-rules.conf",
        f"api/explorer/document/{UUID}/match",
        "explorer-document-match",
    ),
    ("snippets/edge-rules.conf", "api/explorer/facet/technique", "explorer-facet"),
    ("snippets/edge-rules.conf", "api/explorer/home", "explorer-home"),
    ("snippets/edge-rules.conf", f"api/explorer/analysis/{UUID}", "explorer-analysis"),
    ("snippets/edge-rules.conf", "api/explorer/items", "explorer-items"),
    ("snippets/edge-rules.conf", "api/explorer/synthesis", "explorer-synthesis"),
    ("snippets/edge-rules.conf", "api/explorer/events", "explorer-events"),
    ("snippets/edge-rules.conf", f"mvt/{UUID}/5/16/11.pbf", "mvt"),
    ("snippets/edge-rules.conf", "iiifannotations", "iiifannotations"),
    ("snippets/media.conf", f"files/{UUID}", "file_access"),
]
# Arches routes the edge answers with a bare 404: (path below the language
# prefix, view name). Signup is closed; the 2FA settings POST trusts a form
# field, and the reset mails a link to it.
DENIED = [
    ("auth/signup", "signup"),
    ("auth/confirm_signup", "confirm_signup"),
    ("two-factor-authentication-settings", "two-factor-authentication-settings"),
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
    ("snippets/edge-rules.conf", "/api/explorer/events.csv", "explorer-events-csv"),
    (
        "snippets/edge-rules.conf",
        "/api/explorer/events.geojson",
        "explorer-events-geojson",
    ),
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
    ("snippets/edge-rules.conf", "/api/site-notice", "site-notice"),
    ("snippets/edge-rules.conf", "/api/csp-report", "csp-report"),
]


def token_for(path):
    """A literal fragment the dedicated location must contain (None: the generic
    ``/iiif/`` location is the intended rule)."""
    segments = [part for part in path.strip("/").split("/") if part != UUID]
    if segments[:2] == ["iiif", "data"]:
        return None
    if segments[:2] == ["iiif", "v3"]:
        return "/".join(segments[:3])
    if segments[0] in ("api", "iiif", "account"):
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

    def location_body(self, relative, path):
        text = (NGINX_DIR / relative).read_text()
        pattern = first_location(read_locations(relative), path)
        self.assertIsNotNone(pattern, f"no location matches {path}")
        body = re.search(
            r"location\s+~\s+\"?" + re.escape(pattern) + r"\"?\s*\{(.*?)\n\}",
            text,
            re.S,
        )
        self.assertIsNotNone(body, f"{path}: location block not found")
        return body.group(1)

    def test_map_tiles_use_the_tiles_zone(self):
        for code, _ in settings.LANGUAGES:
            body = self.location_body(
                "snippets/edge-rules.conf", f"/{code}/mvt/{UUID}/5/16/11.pbf"
            )
            self.assertIn("limit_req zone=tiles", body)
            bound = re.search(r"limit_conn tiles_conn (\d+);", body)
            self.assertIsNotNone(bound)
            self.assertGreaterEqual(int(bound.group(1)), 100)
            self.assertNotIn("perip", body)

    def test_explorer_calls_spend_a_pace_zone_and_an_hourly_budget(self):
        zones = (NGINX_DIR / "snippets/ratelimit.conf").read_text()
        self.assertRegex(zones, r"zone=explorer:\w+\s+rate=10r/s;")
        budget = re.search(r"zone=explorer_budget:\w+\s+rate=(\d+)r/m;", zones)
        self.assertIsNotNone(budget)
        self.assertEqual(int(budget.group(1)), 100)
        paths = [f"/{code}/api/explorer/search" for code, _ in settings.LANGUAGES]
        paths.append(f"/api/spectrum-preview/{UUID}")
        for path in paths:
            with self.subTest(path=path):
                body = self.location_body("snippets/edge-rules.conf", path)
                self.assertIn("limit_req zone=explorer burst=40 nodelay;", body)
                burst = re.search(
                    r"limit_req zone=explorer_budget burst=(\d+) nodelay;", body
                )
                self.assertIsNotNone(burst)
                self.assertEqual(int(burst.group(1)), 6000)
                self.assertEqual(int(budget.group(1)) * 60, int(burst.group(1)))
                self.assertNotIn("zone=api ", body)

    def test_share_and_the_downloads_keep_their_own_zones_above_the_explorer_ones(self):
        for code, _ in settings.LANGUAGES:
            body = self.location_body(
                "snippets/edge-rules.conf", f"/{code}/api/explorer/share"
            )
            self.assertIn("limit_req zone=share", body)
            self.assertNotIn("zone=explorer", body)
        for path in ("/api/explorer/export", "/api/explorer/events.csv"):
            body = self.location_body("snippets/edge-rules.conf", path)
            self.assertIn("limit_req zone=heavy", body)

    def test_iiif_annotations_have_their_own_rate_and_connection_zones(self):
        for code, _ in settings.LANGUAGES:
            body = self.location_body(
                "snippets/edge-rules.conf", f"/{code}/iiifannotations"
            )
            self.assertRegex(body, r"limit_req zone=annotations burst=\d+;")
            self.assertRegex(body, r"limit_req zone=annotations_site burst=\d+;")
            self.assertNotIn("nodelay", body)
            self.assertIn("limit_conn annotations_conn", body)
            self.assertNotIn("perip", body)
        zones = (NGINX_DIR / "snippets/ratelimit.conf").read_text()
        self.assertIn("zone=annotations:", zones)
        self.assertIn("zone=annotations_site:", zones)
        self.assertIn("zone=annotations_conn:", zones)

    def test_geojson_barrier_reads_the_session_cookie_of_the_settings(self):
        zones = (NGINX_DIR / "snippets/ratelimit.conf").read_text()
        self.assertIn(f"$cookie_{settings.SESSION_COOKIE_NAME}", zones)
        self.assertNotIn("$arg_format", zones.split("anonymous_geojson_export")[1])
        for code, _ in settings.LANGUAGES:
            for rest in ("api/search/export_results", "search/export_results"):
                body = self.location_body("snippets/edge-rules.conf", f"/{code}/{rest}")
                self.assertRegex(
                    body,
                    r"if \(\$anonymous_geojson_export\) \{\s*" r"return 403;",
                    rest,
                )

    def test_geojson_refusal_is_the_site_403_page(self):
        template = (
            NGINX_DIR / "templates/conf.d/manuspectrum.conf.template"
        ).read_text()
        edge = (NGINX_DIR / "snippets/edge-rules.conf").read_text()
        self.assertIn("error_page 403 /_errors/403.html;", template)
        self.assertNotIn("geojson-export", template + edge)
        self.assertNotIn("_denied", edge)
        page = (NGINX_DIR / "errors/403.html").read_text()
        for code, _ in settings.LANGUAGES:
            with translation.override(code):
                auth = reverse("auth")
                root = reverse("root")
                contact = reverse("about-contact")
            self.assertEqual(root, f"/{code}/")
            self.assertIn(f'href="{auth}?next={root}"', page)
            self.assertIn(f'href="{root}"', page)
            self.assertIn(f'href="{contact}"', page)
            self.assertView(auth, "auth")
            self.assertView(contact, "about-contact")
        self.assertIn('<html lang="en">', page)
        self.assertIn('lang="fr"', page)

    def test_temp_file_without_an_id_is_refused_by_the_edge(self):
        for code, _ in settings.LANGUAGES:
            body = self.location_body("snippets/edge-rules.conf", f"/{code}/temp_file")
            self.assertEqual(body.strip(), "return 404;")
            self.assertView(f"/{code}/temp_file/{UUID}", "temp_file")
            self.assertEqual(
                self.location_body(
                    "snippets/edge-rules.conf", f"/{code}/temp_file/abc"
                ).strip(),
                "return 404;",
            )
            self.assertEqual(
                self.location_body(
                    "snippets/edge-rules.conf", f"/{code}/temp_file/1-2-3-4-5"
                ).strip(),
                "return 404;",
            )
            self.assertIn(
                "proxy_pass",
                self.location_body(
                    "snippets/edge-rules.conf", f"/{code}/temp_file/{UUID}"
                ),
            )

    def test_denied_routes_exist_and_are_refused_in_every_language(self):
        text = (NGINX_DIR / "snippets/edge-rules.conf").read_text()
        for code, _ in settings.LANGUAGES:
            for rest, view_name in DENIED:
                path = f"/{code}/{rest}"
                self.assertView(path, view_name)
                pattern = first_location(
                    read_locations("snippets/edge-rules.conf"), path
                )
                self.assertIsNotNone(pattern, f"no location matches {path}")
                body = re.search(
                    r"location\s+~\s+" + re.escape(pattern) + r"\s*\{([^}]*)\}",
                    text,
                )
                self.assertIsNotNone(body, f"{path}: location block not found")
                self.assertEqual(body.group(1).strip(), "return 404;", path)

    def test_two_factor_reset_link_gets_a_static_page_and_never_reaches_django(self):
        page = (NGINX_DIR / "errors/two-factor-reset.html").read_text()
        for code, _ in settings.LANGUAGES:
            path = f"/{code}/two-factor-authentication-reset"
            self.assertView(path, "two-factor-authentication-reset")
            body = self.location_body("snippets/edge-rules.conf", path)
            self.assertNotIn("proxy_pass", body)
            self.assertRegex(
                body,
                r"if \(\$request_method !~ \^\(\?:GET\|HEAD\)\$\) \{\s*"
                r"return 303 /\$lang/two-factor-authentication-reset;",
            )
            self.assertIn("root /etc/nginx/errors;", body)
            self.assertIn("try_files /two-factor-reset.html =404;", body)
            self.assertIn("include snippets/security-headers.conf;", body)
            with translation.override(code):
                auth = reverse("auth")
                contact = reverse("about-contact")
            self.assertIn(f'href="{auth}"', page)
            self.assertIn(f'href="{contact}"', page)
            self.assertView(auth, "auth")
            self.assertView(contact, "about-contact")
        self.assertIn('<html lang="en">', page)
        self.assertIn('lang="fr"', page)
        self.assertNotIn("<script", page)

    def test_root_favicon_is_the_icon_the_templates_link(self):
        from django.contrib.staticfiles import finders

        template = Path(settings.APP_ROOT, "templates", "ms_base.htm").read_text()
        icon = re.search(r"webpack_static '([^']*favicon\.ico)'", template)
        self.assertIsNotNone(icon, "ms_base.htm links no favicon.ico")
        self.assertIsNotNone(finders.find(icon[1]), f"{icon[1]} is not collected")
        text = (NGINX_DIR / "snippets/static.conf").read_text()
        block = re.search(r"location = /favicon\.ico\s*\{(.*?)\n\}", text, re.S)
        self.assertIsNotNone(block, "static.conf: no location = /favicon.ico")
        self.assertIn(f"alias /srv/static/current/{icon[1]};", block[1])
        self.assertIn("include snippets/security-headers.conf;", block[1])

    def test_spectrum_previews_have_their_own_connection_zone(self):
        body = self.location_body(
            "snippets/edge-rules.conf", f"/api/spectrum-preview/{UUID}"
        )
        self.assertNotIn("perip", body)
        bound = re.search(r"limit_conn preview_conn (\d+);", body)
        self.assertIsNotNone(bound)
        zones = (NGINX_DIR / "snippets/ratelimit.conf").read_text()
        self.assertIn("zone=preview_conn:", zones)
        http = Path(
            settings.APP_ROOT,
            "src/manuspectrum/pages/AnalysisExplorer/api/http.ts",
        ).read_text()
        in_flight = re.search(r"PREVIEW_FETCHES_IN_FLIGHT = (\d+);", http)
        self.assertIsNotNone(in_flight, "http.ts: no PREVIEW_FETCHES_IN_FLIGHT")
        self.assertGreaterEqual(int(bound[1]), 5 * int(in_flight[1]))

    def test_one_compare_view_of_full_series_fits_the_preview_full_burst(self):
        body = self.location_body(
            "snippets/edge-rules.conf", f"/api/spectrum-preview/{UUID}"
        )
        burst = re.search(r"limit_req zone=preview_full burst=(\d+) nodelay;", body)
        self.assertIsNotNone(burst)
        http = Path(
            settings.APP_ROOT,
            "src/manuspectrum/pages/AnalysisExplorer/api/http.ts",
        ).read_text()
        room = re.search(r"FULL_SERIES_MAX_ENTRIES = (\d+);", http)
        self.assertIsNotNone(room, "http.ts: no FULL_SERIES_MAX_ENTRIES")
        self.assertGreaterEqual(int(burst[1]) + 1, int(room[1]))

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

    def test_site_notice_falls_back_to_the_snapshot_django_writes(self):
        text = (NGINX_DIR / "snippets/edge-rules.conf").read_text()
        self.assertIn("error_page 500 502 503 504 = @site_notice_snapshot;", text)
        snapshot = re.search(
            r"location @site_notice_snapshot\s*\{(.*?)\n\}", text, re.S
        )
        self.assertIsNotNone(snapshot)
        compose = Path(
            settings.APP_ROOT, "..", "deploy/compose/compose.yaml"
        ).read_text()
        web = re.search(r"(?ms)^  web:\n(.*?)^  \w[\w-]*:\n", compose)[1]
        directory = re.search(r"(?m)^\s+SITE_NOTICE_SNAPSHOT_DIR: (\S+)$", web)[1]
        self.assertIn(f"site_notice:{directory}", web)
        self.assertIn(f"root {directory};", snapshot[1])
        self.assertIn("try_files /notice.json =404;", snapshot[1])
        from manuspectrum.views.site_notice import SNAPSHOT_NAME

        self.assertEqual(SNAPSHOT_NAME, "notice.json")

    def test_csp_report_location_is_small_post_only_and_limited(self):
        text = (NGINX_DIR / "snippets/edge-rules.conf").read_text()
        block = re.search(r"location = /api/csp-report\s*\{(.*?)\n\}", text, re.S)
        self.assertIsNotNone(block)
        body = block.group(1)
        self.assertIn("$request_method != POST", body)
        self.assertIn("client_max_body_size 16k;", body)
        self.assertIn("limit_req zone=csp_report burst=30 nodelay;", body)
        zones = (NGINX_DIR / "snippets/ratelimit.conf").read_text()
        self.assertRegex(zones, r"zone=csp_report:\w+\s+rate=30r/m;")

    def test_csp_report_endpoint_is_named_by_the_policy_and_the_reporting_header(self):
        text = (NGINX_DIR / "snippets/security-headers.conf").read_text()
        self.assertIn("report-uri /api/csp-report;", text)
        self.assertIn("report-to csp-endpoint", text)
        self.assertIn("Reporting-Endpoints 'csp-endpoint=\"/api/csp-report\"'", text)

    def test_reporting_endpoints_is_nginx_only(self):
        text = (NGINX_DIR / "snippets/proxy-web-core.conf").read_text()
        self.assertIn("proxy_hide_header Reporting-Endpoints;", text)

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


class ErrorLogTests(SimpleTestCase):
    LEVELS = ["debug", "info", "notice", "warn", "error", "crit", "alert", "emerg"]

    def directive(self, relative, name):
        text = re.sub(r"(?m)^\s*#.*$", "", (NGINX_DIR / relative).read_text())
        found = re.findall(rf"(?m)^\s*{name}\s+(?:\S+\s+)?(\w+)\s*;", text)
        self.assertEqual(len(found), 1, f"{relative}: {name} must be set once")
        return found[0]

    def test_refused_requests_are_logged_below_the_error_log_level(self):
        threshold = self.LEVELS.index(self.directive("nginx.conf", "error_log"))
        for name in ("limit_req_log_level", "limit_conn_log_level"):
            level = self.directive("snippets/ratelimit.conf", name)
            self.assertLess(
                self.LEVELS.index(level),
                threshold,
                f"{name} {level} would write the refused request line to error.log",
            )
