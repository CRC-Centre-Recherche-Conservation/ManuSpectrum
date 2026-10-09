# deploy/compose/tests/test_consultation_kinds.py
"""Contract of the consultation kinds recorded by prometheus/rules/activity.yml.

The rules map the route names (`view` label of django-prometheus) to a closed
`kind` vocabulary. Every route of manuspectrum/urls.py must be mapped to a kind
or ignored with a reason, so that a new public route cannot go uncounted without
someone deciding it.
"""

import ast
import re
import unittest
from pathlib import Path

try:
    import yaml
except ImportError:  # pragma: no cover
    yaml = None

COMPOSE_DIR = Path(__file__).resolve().parents[1]
REPO = COMPOSE_DIR.parents[1]
RULES = COMPOSE_DIR / "observability" / "prometheus" / "rules" / "activity.yml"
URLS_PY = REPO / "manuspectrum" / "urls.py"

KINDS = {
    "home",
    "about",
    "explorer_open",
    "explorer_search",
    "explorer_document",
    "explorer_analysis",
    "explorer_compare",
    "export_csv",
    "export_zip",
    "export_manifest",
    "share",
    "resource_report",
    "resource_summary",
    "search",
    "iiif_annotations",
    "iiif_manifest",
    "file_download",
}
# Arches core routes that the kinds name (arches/urls.py).
ARCHES_VIEWS = {
    "root",
    "resource_report",
    "search_results",
    "file_access",
    "download_files",
    "manifest",
}
IGNORED = {
    "password_reset": "account page, not a consultation",
    "thumbnail": "image plumbing of the cards",
    "plugins": "back-office pages and workflow steps, one route for every plugin",
    "mvt": "map tiles",
    "templates": "Knockout templates",
    "model-graph": "UI plumbing",
    "relatable-nodes": "UI plumbing",
    "summary-config": "designer configuration",
    "explorer-document-match": "UI plumbing of the Explorer filters",
    "explorer-facet": "UI plumbing of the Explorer filters",
    "explorer-home": "UI plumbing of the Explorer",
    "explorer-items": "UI plumbing of the Explorer Selection",
    "api-spectrum-preview": "counted by manuspectrum_spectrum_previews_total",
    "iiif-xy-reading-context": "static context document",
    "iiif-xy-reading-doc": "static documentation",
    "iiif-xy-reading-schema": "static schema",
    "iiif-auth-login": "IIIF sign-in plumbing",
    "iiif-auth-token-1": "IIIF sign-in plumbing",
    "iiif-auth-token-2": "IIIF sign-in plumbing",
    "iiif-auth-probe": "IIIF sign-in plumbing",
    "iiif-auth-logout": "IIIF sign-in plumbing",
    "renderer": "back-office plumbing",
    "renderer_config": "back-office plumbing",
    "robots": "crawler file",
    "django.contrib.sitemaps.views.sitemap": "crawler file",
    "healthz": "probe",
    "readyz": "probe",
    "metrics": "scrape",
}
for _name in (
    "suggest",
    "entity",
    "search",
    "search-manuscripts",
    "check-duplicates",
    "manuscript-illuminations",
    "illumination-detail",
    "create-resource",
    "create-all",
    "add-alt-name",
    "stats",
    "link-to-project",
):
    IGNORED[f"biblissima-{_name}"] = "back-office import assistant"


def project_route_names():
    """Every `name=` of manuspectrum/urls.py; `{version}` expands to 2 and 3."""
    names = set()
    tree = ast.parse(URLS_PY.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.For)
            and isinstance(node.target, ast.Tuple)
            and isinstance(node.iter, ast.List)
        ):
            targets = [t.id for t in node.target.elts if isinstance(t, ast.Name)]
            if "_name" in targets:
                position = targets.index("_name")
                names.update(
                    row.elts[position].value
                    for row in node.iter.elts
                    if isinstance(row, ast.Tuple)
                )
    for node in ast.walk(tree):
        if not isinstance(node, ast.keyword) or node.arg != "name":
            continue
        value = node.value
        if isinstance(value, ast.Constant) and isinstance(value.value, str):
            names.add(value.value)
        elif isinstance(value, ast.JoinedStr):
            for version in (2, 3):
                names.add(
                    "".join(
                        part.value if isinstance(part, ast.Constant) else str(version)
                        for part in value.values
                    )
                )
    return names


def kind_views():
    """{kind: set of views} from the recording rules."""
    document = yaml.safe_load(RULES.read_text(encoding="utf-8"))
    result = {}
    for rule in document["groups"][0]["rules"]:
        if rule["record"] != "manuspectrum:consultations:total":
            continue
        views = set()
        for pattern in re.findall(r'view=~?"([^"]+)"', rule["expr"]):
            views |= set(pattern.split("|"))
        kind = rule["labels"]["kind"]
        assert kind not in result, f"two rules for {kind}"
        result[kind] = views
    return result


@unittest.skipUnless(yaml, "PyYAML missing")
class ConsultationKindTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.kinds = kind_views()
        cls.mapped = set().union(*cls.kinds.values())
        cls.routes = project_route_names()

    def test_the_kinds_are_the_closed_vocabulary(self):
        self.assertEqual(set(self.kinds), KINDS)

    def test_no_view_is_in_two_kinds(self):
        total = sum(len(views) for views in self.kinds.values())
        self.assertEqual(total, len(self.mapped))

    def test_every_route_of_urls_py_is_mapped_or_ignored(self):
        unmapped = self.routes - self.mapped - set(IGNORED)
        self.assertEqual(unmapped, set())

    def test_a_route_is_not_both_mapped_and_ignored(self):
        self.assertEqual(self.mapped & set(IGNORED), set())

    def test_the_ignore_list_names_existing_routes(self):
        self.assertEqual(set(IGNORED) - self.routes - ARCHES_VIEWS, set())

    def test_every_mapped_view_is_a_route_of_the_project_or_a_known_arches_view(self):
        self.assertEqual(self.mapped - self.routes - ARCHES_VIEWS, set())

    def test_the_homepage_is_the_root_route_only(self):
        self.assertIn("root", self.mapped)
        self.assertNotIn("home", self.mapped)

    def test_the_extractor_reads_the_iiif_f_string_names(self):
        self.assertIn("iiif-v2-annotation-page", self.routes)
        self.assertIn("iiif-v3-characterization-collection", self.routes)
        self.assertIn("explorer-search", self.routes)
        self.assertIn("about-team", self.routes)

    def test_a_new_public_route_would_be_caught(self):
        unmapped = (self.routes | {"explorer-newthing"}) - self.mapped - set(IGNORED)
        self.assertEqual(unmapped, {"explorer-newthing"})

    def test_the_rate_rule_sums_the_totals_by_kind(self):
        document = yaml.safe_load(RULES.read_text(encoding="utf-8"))
        (rate,) = [
            r
            for r in document["groups"][0]["rules"]
            if r["record"] == "manuspectrum:consultations:rate1h"
        ]
        self.assertIn("sum by (kind)", rate["expr"])
        self.assertIn("manuspectrum:consultations:total[1h]", rate["expr"])

    def test_only_successful_or_cached_gets_count(self):
        document = yaml.safe_load(RULES.read_text(encoding="utf-8"))
        for rule in document["groups"][0]["rules"]:
            if rule["record"].endswith(":total"):
                with self.subTest(kind=rule["labels"]["kind"]):
                    selectors = re.findall(r"\{[^}]*\}", rule["expr"])
                    self.assertTrue(selectors)
                    for selector in selectors:
                        self.assertIn('method="GET"', selector)
                        if 'status="302"' in selector:
                            self.assertIn('view="file_access"', selector)
                        else:
                            self.assertIn('status=~"2..|304"', selector)

    def test_a_file_download_is_the_redirect_of_file_access_not_its_thumbnail(self):
        document = yaml.safe_load(RULES.read_text(encoding="utf-8"))
        (rule,) = [
            r
            for r in document["groups"][0]["rules"]
            if r.get("labels", {}).get("kind") == "file_download"
        ]
        self.assertIn('{method="GET",status="302",view="file_access"}', rule["expr"])
        self.assertNotRegex(rule["expr"], r'status=~"2\.\.\|304"[^}]*file_access')
        self.assertNotRegex(rule["expr"], r'file_access[^}]*status=~"2\.\.\|304"')


if __name__ == "__main__":
    unittest.main()
