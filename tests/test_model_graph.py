from django.test import SimpleTestCase, TestCase

from manuspectrum.views.model_graph_service import (
    prettify_cidoc,
    group_for_slug,
    trim_node_config,
    GROUPS,
    DATATYPE_COLORS,
    DATATYPE_LABELS,
    EXCLUDED_GRAPH_SLUGS,
    EXCLUDED_GRAPH_NAMES,
)


class HelperTests(SimpleTestCase):
    def test_prettify_cidoc_full_uri(self):
        self.assertEqual(
            prettify_cidoc("http://www.cidoc-crm.org/cidoc-crm/E22_Human-Made_Object"),
            "E22 Human-Made Object",
        )

    def test_prettify_cidoc_property(self):
        self.assertEqual(
            prettify_cidoc("http://www.cidoc-crm.org/cidoc-crm/P128_carries"),
            "P128 carries",
        )

    def test_prettify_cidoc_none(self):
        self.assertEqual(prettify_cidoc(None), "")

    def test_group_for_slug_known(self):
        self.assertEqual(group_for_slug("analysis"), "observation")
        self.assertEqual(group_for_slug("document"), "studied-object")
        self.assertEqual(group_for_slug("person"), "context")
        self.assertEqual(group_for_slug("alteration"), "transformations")

    def test_group_for_slug_unknown(self):
        self.assertEqual(group_for_slug("nonexistent-slug"), "other")

    def test_groups_have_colors(self):
        ids = {g["id"] for g in GROUPS}
        self.assertTrue(
            {"studied-object", "observation", "context", "transformations"} <= ids
        )
        for g in GROUPS:
            self.assertRegex(g["color"], r"^#[0-9a-fA-F]{6}$")

    def test_trim_node_config_resource_instance(self):
        cfg = {"graphs": [{"graphid": "abc", "name": "x"}], "junk": 1}
        out = trim_node_config("resource-instance", cfg)
        self.assertEqual(out["target_graphs"], ["abc"])
        self.assertNotIn("junk", out)

    def test_trim_node_config_concept(self):
        out = trim_node_config("concept", {"rdmCollection": "coll-1", "junk": 2})
        self.assertEqual(out["collection"], "coll-1")
        self.assertNotIn("junk", out)

    def test_trim_node_config_plain(self):
        self.assertEqual(trim_node_config("string", {"anything": 1}), {})

    def test_datatype_colors_are_hex(self):
        for v in DATATYPE_COLORS.values():
            self.assertRegex(v, r"^#[0-9a-fA-F]{6}$")


class DatatypeCoverageTests(TestCase):
    """DATATYPE_COLORS must cover EVERY datatype that can appear in the payload."""

    # Custom datatypes are registered per-environment (`manage.py datatype register`),
    # so the test DB's d_data_types does not list them — pin the project's own here.
    # Keep in sync with manuspectrum/datatypes/ (DATATYPE_LOCATIONS).
    PROJECT_DATATYPES = {"manifest"}

    def test_every_registered_datatype_has_a_color(self):
        from arches.app.models.models import DDataType

        registered = set(DDataType.objects.values_list("datatype", flat=True))
        registered |= self.PROJECT_DATATYPES
        missing = registered - set(DATATYPE_COLORS)
        self.assertEqual(
            missing, set(), f"DATATYPE_COLORS is missing: {sorted(missing)}"
        )

    def test_custom_datatype_labels(self):
        self.assertEqual(DATATYPE_LABELS["manifest"], "IIIF Manifest")


class ExcludedGraphExactMatchTests(SimpleTestCase):
    """The scratch-graph exclusion must match EXACTLY, never by substring.

    A future real model whose name/slug merely *contains* "test" (e.g. a
    "Contest Entry" model, or a "Test Protocol" model) must NOT be silently
    dropped from the public explorer.
    """

    def test_known_scratch_graph_is_excluded_by_name(self):
        self.assertIn("test ressource", EXCLUDED_GRAPH_NAMES)

    def test_known_scratch_graph_slug_variants_are_excluded(self):
        for slug in (
            "test_ressource",
            "test-ressource",
            "test_resource",
            "test-resource",
        ):
            self.assertIn(slug, EXCLUDED_GRAPH_SLUGS)

    def test_real_model_name_merely_containing_test_is_not_excluded(self):
        # "contest entry" contains the substring "test" but is not the scratch
        # graph — the old `"test" not in name.lower()` check would have hidden it.
        self.assertNotIn("contest entry", EXCLUDED_GRAPH_NAMES)

    def test_real_model_slug_merely_containing_test_is_not_excluded(self):
        self.assertNotIn("contest-entry", EXCLUDED_GRAPH_SLUGS)
        self.assertNotIn("test-protocol", EXCLUDED_GRAPH_SLUGS)

    def test_exclusion_sets_use_lowercase_normalized_values(self):
        # build_model_graph() lowercases/strips before comparing, so the sets
        # themselves must already be normalized (no stray case/whitespace).
        for name in EXCLUDED_GRAPH_NAMES:
            self.assertEqual(name, name.strip().lower())
        for slug in EXCLUDED_GRAPH_SLUGS:
            self.assertEqual(slug, slug.strip().lower())


from unittest import mock

from django.core.cache import cache
from django.urls import reverse

# TestCase is already imported at the top of the file (Task 1).


class ModelGraphViewTests(TestCase):
    def setUp(self):
        cache.clear()

    def tearDown(self):
        cache.clear()

    @mock.patch("manuspectrum.views.model_graph.graph_fingerprint", return_value="fp1")
    @mock.patch("manuspectrum.views.model_graph.build_model_graph")
    def test_returns_json_for_anonymous(self, m_build, _fp):
        m_build.return_value = {"stats": {"models": 12}, "models": [], "relations": []}
        resp = self.client.get(reverse("model-graph"))
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp["Content-Type"], "application/json")
        self.assertEqual(resp.json()["stats"]["models"], 12)

    @mock.patch("manuspectrum.views.model_graph.graph_fingerprint", return_value="fp1")
    @mock.patch("manuspectrum.views.model_graph.build_model_graph")
    def test_second_call_is_cached(self, m_build, _fp):
        m_build.return_value = {"stats": {"models": 1}, "models": [], "relations": []}
        self.client.get(reverse("model-graph"))
        self.client.get(reverse("model-graph"))
        self.assertEqual(m_build.call_count, 1)  # memoized

    @mock.patch("manuspectrum.views.model_graph.build_model_graph")
    def test_fingerprint_change_busts_cache(self, m_build):
        m_build.return_value = {"stats": {"models": 1}, "models": [], "relations": []}
        with mock.patch(
            "manuspectrum.views.model_graph.graph_fingerprint", return_value="A"
        ):
            self.client.get(reverse("model-graph"))
        with mock.patch(
            "manuspectrum.views.model_graph.graph_fingerprint", return_value="B"
        ):
            self.client.get(reverse("model-graph"))
        self.assertEqual(m_build.call_count, 2)  # recomputed after republish

    @mock.patch("manuspectrum.views.model_graph.graph_fingerprint", return_value="fp1")
    @mock.patch(
        "manuspectrum.views.model_graph.build_model_graph",
        side_effect=RuntimeError("boom"),
    )
    def test_error_returns_500_json(self, _b, _fp):
        resp = self.client.get(reverse("model-graph"))
        self.assertEqual(resp.status_code, 500)
        self.assertIn("error", resp.json())
