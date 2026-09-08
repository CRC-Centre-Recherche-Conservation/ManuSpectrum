from django.test import SimpleTestCase, TestCase

from manuspectrum.views.model_graph_service import (
    prettify_cidoc,
    property_code,
    group_for_slug,
    trim_node_config,
    skip_from_counts,
    structure_depths,
    finalize_structure,
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

    def test_group_for_slug_instrument(self):
        # The graph's slug was always correct ("instrument"); only its display
        # name carried the typo, and that was fixed in the database itself
        # (see .superpowers/sdd/fix_instrument_typo.py) rather than patched here.
        self.assertEqual(group_for_slug("instrument"), "context")

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


class PropertyCodeTests(SimpleTestCase):
    """The P-number is precomputed server-side so the client runs no per-edge regex."""

    def test_plain_property(self):
        self.assertEqual(property_code("P4 has time-span"), "P4")

    def test_inverse_property_keeps_its_letter(self):
        # P98i / P106i / P67i are all real in this dataset; dropping the trailing
        # "i" would silently reverse the direction of the relationship.
        self.assertEqual(property_code("P98i was born"), "P98i")
        self.assertEqual(property_code("P82a begin of the begin"), "P82a")

    def test_no_property(self):
        self.assertEqual(property_code(""), "")
        self.assertEqual(property_code(None), "")

    def test_class_code_is_not_mistaken_for_a_property(self):
        self.assertEqual(property_code("E67 Birth"), "")


class StatsInvariantTests(SimpleTestCase):
    """`stats.nodes` is 452 and must stay 452 — pinned at the rule that decides it.

    The Structure view needs every graph's top node (a tree needs a root), while
    the published counts have always excluded it. Those two requirements pull in
    opposite directions on the same loop, so the rule lives in one named function
    and is tested from both sides here. Breaking it silently shifts the "452
    fields" figure printed on /about/model and /about/explorer, and breaks the
    matrix, table and datatypes views that read `counts`.
    """

    def test_top_node_is_excluded_from_counts(self):
        self.assertTrue(skip_from_counts("semantic", True))

    def test_ordinary_semantic_branch_is_counted(self):
        # A semantic node that is NOT the top node is a real branch in the model
        # (Birth, Time-Span, Joining) and has always been part of the nodegroup
        # count, even though it is not a data field.
        self.assertFalse(skip_from_counts("semantic", False))

    def test_data_nodes_are_never_skipped(self):
        for dt in ("string", "concept", "resource-instance", "date", "manifest"):
            self.assertFalse(skip_from_counts(dt, False))
            # A non-semantic top node cannot occur today, but if one ever did it
            # would be a real field and must still count.
            self.assertFalse(skip_from_counts(dt, True))

    def test_falsy_istopnode_variants(self):
        for falsy in (None, 0, False, ""):
            self.assertFalse(skip_from_counts("semantic", falsy))

    def test_root_is_skipped_from_counts_but_present_in_the_structure(self):
        """The two-sided invariant, in one test."""
        nodes = [
            {"id": "root", "name": "Person", "datatype": "semantic", "nodegroup": None},
            {"id": "kid", "name": "Name", "datatype": "string", "nodegroup": "ng"},
        ]
        out = finalize_structure(nodes, {"root": None, "kid": "root"}, {})
        self.assertEqual(out["root"], "root")
        self.assertEqual({n["id"] for n in out["nodes"]}, {"root", "kid"})
        # ...and the very same node is kept out of every published count.
        self.assertTrue(skip_from_counts("semantic", True))


class StructureDepthTests(SimpleTestCase):
    def test_linear_chain(self):
        depths = structure_depths({"a": None, "b": "a", "c": "b", "d": "c"})
        self.assertEqual(depths, {"a": 0, "b": 1, "c": 2, "d": 3})

    def test_branching_tree(self):
        depths = structure_depths({"r": None, "x": "r", "y": "r", "z": "x"})
        self.assertEqual(depths["x"], 1)
        self.assertEqual(depths["y"], 1)
        self.assertEqual(depths["z"], 2)

    def test_parent_outside_the_graph_is_treated_as_a_root(self):
        # Edges never cross graphs today, but a dangling parent must not produce
        # a KeyError on a public endpoint.
        self.assertEqual(structure_depths({"a": "elsewhere"}), {"a": 0})

    def test_cycle_degrades_to_a_flat_drawing_instead_of_hanging(self):
        # Every model is a verified strict tree, so this should be unreachable —
        # but a corrupt Edge table must not spin the request forever.
        depths = structure_depths({"a": "b", "b": "a"})
        self.assertEqual(set(depths), {"a", "b"})
        for v in depths.values():
            self.assertLess(v, 3)

    def test_empty(self):
        self.assertEqual(structure_depths({}), {})


class FinalizeStructureTests(SimpleTestCase):
    def _nodes(self):
        return [
            {"id": "c", "name": "Zeta", "datatype": "string", "nodegroup": "ng1"},
            {"id": "a", "name": "Root", "datatype": "semantic", "nodegroup": None},
            {"id": "b", "name": "Alpha", "datatype": "string", "nodegroup": "ng1"},
        ]

    NG = {"ng1": {"cardinality": "n", "parent_nodegroup": "ng0"}}

    def test_attaches_parent_depth_and_nodegroup_metadata(self):
        out = finalize_structure(
            self._nodes(), {"a": None, "b": "a", "c": "b"}, self.NG
        )
        by_id = {n["id"]: n for n in out["nodes"]}
        self.assertEqual(by_id["a"]["depth"], 0)
        self.assertEqual(by_id["b"]["depth"], 1)
        self.assertEqual(by_id["c"]["depth"], 2)
        self.assertEqual(by_id["c"]["parent"], "b")
        self.assertEqual(by_id["b"]["cardinality"], "n")
        self.assertEqual(by_id["b"]["parent_nodegroup"], "ng0")

    def test_node_without_a_nodegroup_gets_null_cardinality(self):
        out = finalize_structure(
            self._nodes(), {"a": None, "b": "a", "c": "b"}, self.NG
        )
        root = next(n for n in out["nodes"] if n["id"] == "a")
        self.assertIsNone(root["cardinality"])
        self.assertIsNone(root["parent_nodegroup"])

    def test_root_is_the_parentless_node(self):
        out = finalize_structure(
            self._nodes(), {"a": None, "b": "a", "c": "b"}, self.NG
        )
        self.assertEqual(out["root"], "a")

    def test_output_order_is_deterministic_not_database_order(self):
        """A payload people diff and cite must not depend on row order."""
        parents = {"a": None, "b": "a", "c": "b"}
        first = finalize_structure(self._nodes(), parents, self.NG)
        shuffled = list(reversed(self._nodes()))
        second = finalize_structure(shuffled, parents, self.NG)
        self.assertEqual(
            [n["id"] for n in first["nodes"]], [n["id"] for n in second["nodes"]]
        )
        # depth, then name — so siblings read alphabetically.
        self.assertEqual([n["id"] for n in first["nodes"]], ["a", "b", "c"])

    def test_unknown_nodegroup_does_not_raise(self):
        nodes = [{"id": "a", "name": "A", "datatype": "string", "nodegroup": "missing"}]
        out = finalize_structure(nodes, {"a": None}, {})
        self.assertIsNone(out["nodes"][0]["cardinality"])


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
        # str(): the values are gettext_lazy proxies now.
        self.assertEqual(str(DATATYPE_LABELS["manifest"]), "IIIF Manifest")


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


# --- Task 5 (feat/homepage_v2 audit): cache versioning, headers, drafts ------

from django.test import override_settings

from manuspectrum.views.model_graph import PAYLOAD_VERSION
from manuspectrum.views.model_graph_service import draft_state_ids


class DraftStateIdsTests(SimpleTestCase):
    def test_initial_state_of_multi_state_lifecycle_is_draft(self):
        states = [
            {
                "id": "d",
                "is_initial_state": True,
                "resource_instance_lifecycle_id": "L1",
            },
            {
                "id": "a",
                "is_initial_state": False,
                "resource_instance_lifecycle_id": "L1",
            },
            {
                "id": "r",
                "is_initial_state": False,
                "resource_instance_lifecycle_id": "L1",
            },
        ]
        self.assertEqual(draft_state_ids(states), {"d"})

    def test_single_state_lifecycle_publishes_immediately(self):
        # The sole state of a one-state lifecycle is initial AND active: not a draft.
        states = [
            {
                "id": "only",
                "is_initial_state": True,
                "resource_instance_lifecycle_id": "L2",
            },
        ]
        self.assertEqual(draft_state_ids(states), set())

    def test_mixed_lifecycles(self):
        states = [
            {
                "id": "d1",
                "is_initial_state": True,
                "resource_instance_lifecycle_id": "L1",
            },
            {
                "id": "a1",
                "is_initial_state": False,
                "resource_instance_lifecycle_id": "L1",
            },
            {
                "id": "only",
                "is_initial_state": True,
                "resource_instance_lifecycle_id": "L2",
            },
        ]
        self.assertEqual(draft_state_ids(states), {"d1"})


class ModelGraphCachingTests(TestCase):
    """Versioned key, ETag/304, gzip — behaviours added by the audit fixes."""

    PAYLOAD = {"stats": {"models": 12}, "models": [{"pad": "x" * 40}] * 30}

    def setUp(self):
        cache.clear()

    def tearDown(self):
        cache.clear()

    @mock.patch("manuspectrum.views.model_graph.graph_fingerprint", return_value="fp1")
    @mock.patch("manuspectrum.views.model_graph.build_model_graph")
    def test_etag_carries_language_and_version(self, m_build, _fp):
        m_build.return_value = self.PAYLOAD
        resp = self.client.get(reverse("model-graph"))
        self.assertIn("fp1", resp["ETag"])
        self.assertIn(f"v{PAYLOAD_VERSION}", resp["ETag"])
        self.assertIn("en", resp["ETag"])
        self.assertIn("max-age", resp["Cache-Control"])

    @mock.patch("manuspectrum.views.model_graph.graph_fingerprint", return_value="fp1")
    @mock.patch("manuspectrum.views.model_graph.build_model_graph")
    def test_if_none_match_returns_304_without_rebuilding(self, m_build, _fp):
        m_build.return_value = self.PAYLOAD
        etag = self.client.get(reverse("model-graph"))["ETag"]
        resp = self.client.get(reverse("model-graph"), HTTP_IF_NONE_MATCH=etag)
        self.assertEqual(resp.status_code, 304)
        self.assertEqual(m_build.call_count, 1)

    @mock.patch("manuspectrum.views.model_graph.graph_fingerprint", return_value="fp1")
    @mock.patch("manuspectrum.views.model_graph.build_model_graph")
    def test_weak_if_none_match_matches_too(self, m_build, _fp):
        # GZipMiddleware weakens ETags (W/"…"), so browsers echo the weak form.
        m_build.return_value = self.PAYLOAD
        etag = self.client.get(reverse("model-graph"))["ETag"]
        resp = self.client.get(reverse("model-graph"), HTTP_IF_NONE_MATCH=f"W/{etag}")
        self.assertEqual(resp.status_code, 304)

    @mock.patch("manuspectrum.views.model_graph.graph_fingerprint", return_value="fp1")
    @mock.patch("manuspectrum.views.model_graph.build_model_graph")
    def test_stale_etag_gets_fresh_payload(self, m_build, _fp):
        m_build.return_value = self.PAYLOAD
        resp = self.client.get(
            reverse("model-graph"), HTTP_IF_NONE_MATCH='"old-fingerprint:en:v1"'
        )
        self.assertEqual(resp.status_code, 200)

    @mock.patch("manuspectrum.views.model_graph.graph_fingerprint", return_value="fp1")
    @mock.patch("manuspectrum.views.model_graph.build_model_graph")
    def test_response_is_gzipped_when_accepted(self, m_build, _fp):
        m_build.return_value = self.PAYLOAD
        resp = self.client.get(reverse("model-graph"), HTTP_ACCEPT_ENCODING="gzip")
        self.assertEqual(resp.get("Content-Encoding"), "gzip")

    @mock.patch("manuspectrum.views.model_graph.graph_fingerprint", return_value="fp1")
    @mock.patch("manuspectrum.views.model_graph.build_model_graph")
    def test_language_isolation_of_cache_and_etag(self, m_build, _fp):
        # The route sits inside i18n_patterns (prefix_default_language=False):
        # the language is carried by the URL, never by a cookie.
        m_build.return_value = self.PAYLOAD
        etag_en = self.client.get("/api/model-graph")["ETag"]

        resp_fr = self.client.get("/fr/api/model-graph")
        self.assertNotEqual(etag_en, resp_fr["ETag"])
        self.assertIn(":fr:", resp_fr["ETag"])
        # One build per language: the fr request must not reuse the en cache.
        self.assertEqual(m_build.call_count, 2)
        m_build.assert_any_call("fr")


class PayloadEnrichmentTests(TestCase):
    def test_payload_carries_slugs_and_generated_at(self):
        from manuspectrum.views.model_graph_service import build_model_graph

        payload = build_model_graph("en")
        self.assertIn("generated_at", payload)
        for m in payload["models"]:
            self.assertTrue(m.get("slug"), f"model {m['name']} missing slug")

    def test_datatype_chart_labels_are_localized(self):
        # Regression: DATATYPE_LABELS was a plain dict — FR pages showed
        # "Concept List", "Resource Instance"… in English next to French axes.
        # Pure resolution test (the test DB has no graphs, so the built payload
        # carries no datatypes) — this is exactly what the build site does:
        # str() the lazy proxy inside translation.override(language).
        from django.utils import translation

        from manuspectrum.views.model_graph_service import DATATYPE_LABELS

        with translation.override("fr"):
            self.assertEqual(str(DATATYPE_LABELS["string"]), "Texte")
            self.assertEqual(
                str(DATATYPE_LABELS["resource-instance"]), "Instance de ressource"
            )
            self.assertEqual(str(DATATYPE_LABELS["file-list"]), "Liste de fichiers")
            self.assertEqual(str(DATATYPE_LABELS["manifest"]), "Manifeste IIIF")
        with translation.override("en"):
            self.assertEqual(str(DATATYPE_LABELS["string"]), "String")
