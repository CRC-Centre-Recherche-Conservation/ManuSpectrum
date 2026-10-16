"""The imaging layer proposal rule: what a canvas label implies, and the tiles it plans and writes.

Usage:
    python manage.py test tests.test_imaging_layers_rule --settings="tests.test_settings"
"""

import uuid
from unittest import mock

from django.test import SimpleTestCase, override_settings

from arches.app.models.models import Node, TileModel
from arches_controlled_lists.models import List, ListItem, ListItemValue

from manuspectrum.constants.imaging_layers import (
    ANALYSIS_GRAPH_ID,
    IMAGING_MANIFEST_NODEGROUP_ID,
)
from manuspectrum.constants.xy_presets import (
    ANALYSIS_GRAPH_ID as XY_ANALYSIS_GRAPH_ID,
)
from manuspectrum.utils import imaging_layers as rule
from manuspectrum.utils.imaging_layers import (
    ImagingLayersConfigError,
    ManifestUnreadableError,
    Proposal,
    normalise_unit,
    propose,
)
from tests.explorer_fixtures import ExplorerCase

ELEMENT = "Element distribution"
BAND = "Spectral band"
PHOTO = "Photographic reference"
DECONV = "Deconvolution / fitting"


class ConstantsTests(SimpleTestCase):
    def test_the_analysis_graph_is_the_one_of_the_xy_presets(self):
        self.assertIs(ANALYSIS_GRAPH_ID, XY_ANALYSIS_GRAPH_ID)

    def test_the_manifest_nodegroup_is_a_uuid4(self):
        self.assertEqual(uuid.UUID(IMAGING_MANIFEST_NODEGROUP_ID).version, 4)


class ProposeTests(SimpleTestCase):
    def test_a_bare_symbol_is_an_element_distribution(self):
        self.assertEqual(propose("Pb"), Proposal(ELEMENT, ("Pb",), None, None))

    def test_a_band_is_a_spectral_band_in_nanometres(self):
        self.assertEqual(propose("650 nm"), Proposal(BAND, (), (650.0, "nm"), None))

    def test_a_decimal_comma_is_read(self):
        self.assertEqual(propose("400,5 nm").band, (400.5, "nm"))

    def test_other_units_are_kept(self):
        self.assertEqual(propose("12 keV").band, (12.0, "keV"))

    def test_the_ascii_micrometre_is_normalised(self):
        self.assertEqual(propose("3 um").band, (3.0, "µm"))

    def test_the_reciprocal_centimetre_is_normalised(self):
        self.assertEqual(propose("1500 cm-1").band, (1500.0, "cm⁻¹"))

    def test_a_trailing_symbol_after_deconv_is_a_deconvolved_element(self):
        self.assertEqual(
            propose("MS59-f2t-deconv_Fe"), Proposal(ELEMENT, ("Fe",), None, DECONV)
        )

    def test_a_lim_suffix_is_dropped_and_the_case_of_deconv_is_ignored(self):
        self.assertEqual(
            propose("Map data-Ms59-f53v-deconv-Cu-lim255"),
            Proposal(ELEMENT, ("Cu",), None, DECONV),
        )
        self.assertEqual(propose("Map-DECONV_Zn").processing, DECONV)

    def test_a_trailing_symbol_without_deconv_has_no_processing(self):
        self.assertEqual(
            propose("20200121_MS59_f1V_map2_100ms_260mic_S"),
            Proposal(ELEMENT, ("S",), None, None),
        )

    def test_the_final_token_wins_over_an_earlier_symbol(self):
        self.assertEqual(propose("MS59-f2t-deconv_sansHg-Cu").elements, ("Cu",))

    def test_a_video_frame_is_a_photographic_reference(self):
        expected = Proposal(PHOTO, (), None, None)
        self.assertEqual(propose("MS59-f2t-deconv_Video 1"), expected)
        self.assertEqual(propose("Video Mosaic"), expected)

    def test_a_word_containing_video_is_not_a_video(self):
        self.assertIsNone(propose("Audiovideotape"))

    def test_an_unreadable_label_proposes_nothing(self):
        self.assertIsNone(propose("foo"))
        self.assertIsNone(propose(""))
        self.assertIsNone(propose("   "))

    def test_surrounding_whitespace_is_ignored(self):
        self.assertEqual(propose("  Pb ").elements, ("Pb",))

    def test_a_symbol_label_beats_the_video_and_band_readings(self):
        self.assertEqual(propose("Hg").content, ELEMENT)


class NormaliseUnitTests(SimpleTestCase):
    def test_aliases(self):
        self.assertEqual(normalise_unit("um"), "µm")
        self.assertEqual(normalise_unit("cm-1"), "cm⁻¹")
        self.assertEqual(normalise_unit("nm"), "nm")
        self.assertEqual(normalise_unit("keV"), "keV")


MANIFEST_URL = "https://example.org/manifest/imaging"
CANVAS_BASE = "https://example.org/canvas/"


def manifest(*labels):
    return {
        "@context": "http://iiif.io/api/presentation/2/context.json",
        "@type": "sc:Manifest",
        "sequences": [
            {
                "canvases": [
                    {"@id": f"{CANVAS_BASE}{n}", "label": label, "images": []}
                    for n, label in enumerate(labels)
                ]
            }
        ],
    }


class RuleCase(ExplorerCase):
    """Analyses with the layer nodes wired to four controlled lists, one manifest tile on ``open``."""

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.lists = {}
        cls.items = {}
        for node_alias, list_name, items in (
            ("imaging_layer_content", "contents", (ELEMENT, BAND, PHOTO)),
            ("imaging_layer_processing_method", "methods", (DECONV, "Ratio")),
            ("imaging_layer_band_unit", "units", ("Nanometre", "Micrometre")),
            ("imaging_layer_elements", "elements", ()),
        ):
            controlled = List.objects.create(name=list_name)
            cls.lists[node_alias] = controlled
            Node.objects.filter(pk=cls.nodes[("analysis", node_alias)].pk).update(
                config={"controlledList": str(controlled.pk)}
            )
            for order, name in enumerate(items):
                cls.item(node_alias, name, order)
        cls.item("imaging_layer_elements", "Copper", 0, alt="Cu")
        cls.item("imaging_layer_elements", "Lead", 1, alt="Pb")
        cls.manifest_tile = TileModel.objects.create(
            resourceinstance=cls.analyses["open"],
            nodegroup_id=cls.nodes[
                ("analysis", "chemical_imaging_manifest")
            ].nodegroup_id,
            data={
                str(cls.nodes[("analysis", "chemical_imaging_manifest")].nodeid): {
                    "url": MANIFEST_URL
                }
            },
        )

    @classmethod
    def item(cls, node_alias, pref, order, alt=None):
        item = ListItem.objects.create(
            list=cls.lists[node_alias],
            uri=f"https://example.org/{uuid.uuid4()}",
            sortorder=order,
        )
        ListItemValue.objects.create(
            list_item=item, valuetype_id="prefLabel", language_id="en", value=pref
        )
        if alt:
            ListItemValue.objects.create(
                list_item=item, valuetype_id="altLabel", language_id="en", value=alt
            )
        return item

    def layer_node(self, alias):
        return str(self.nodes[("analysis", f"imaging_layer_{alias}")].nodeid)

    def layer_tile(self, canvas, label="stored", parent=None):
        node = self.layer_node
        return TileModel.objects.create(
            resourceinstance=self.analyses["open"],
            nodegroup_id=self.nodes[("analysis", "imaging_layer_canvas")].nodegroup_id,
            parenttile=parent or self.manifest_tile,
            data={node("canvas"): canvas, node("label"): label},
        )

    def plan(self, *labels, tile=None):
        with mock.patch.object(
            rule, "manifest_json", return_value=manifest(*labels)
        ) as read:
            result = rule.plan(self.analyses["open"].pk, tile or self.manifest_tile)
        read.assert_called_once()
        return result


class CanvasesTests(RuleCase):
    def test_canvases_are_the_raw_ids_and_labels_of_the_manifest(self):
        with mock.patch.object(
            rule, "manifest_json", return_value=manifest("Pb", "650 nm")
        ):
            found = rule.canvases({"url": MANIFEST_URL})
        self.assertEqual(
            found, [(f"{CANVAS_BASE}0", "Pb"), (f"{CANVAS_BASE}1", "650 nm")]
        )

    def test_a_v3_manifest_is_read(self):
        v3 = {
            "@context": "http://iiif.io/api/presentation/3/context.json",
            "type": "Manifest",
            "items": [{"id": "c1", "type": "Canvas", "label": {"en": ["Cu"]}}],
        }
        with mock.patch.object(rule, "manifest_json", return_value=v3):
            self.assertEqual(rule.canvases(MANIFEST_URL), [("c1", "Cu")])

    def test_a_plain_url_and_a_list_value_are_read(self):
        with mock.patch.object(
            rule, "manifest_json", return_value=manifest("Pb")
        ) as read:
            rule.canvases(MANIFEST_URL)
            rule.canvases([{"url": MANIFEST_URL}])
        self.assertEqual(read.call_args_list, [mock.call(MANIFEST_URL)] * 2)

    @override_settings(
        EXPLORER_LEGACY_HOSTS=("legacy.example.org",),
        PUBLIC_SERVER_ADDRESS="https://new.example.org/",
    )
    def test_the_manifest_is_fetched_at_its_rewritten_url_and_the_ids_stay_raw(self):
        legacy_canvas = "https://legacy.example.org/canvas/0"
        value = {"url": "https://legacy.example.org/manifest/imaging"}
        legacy = manifest("Pb")
        legacy["sequences"][0]["canvases"][0]["@id"] = legacy_canvas
        with mock.patch.object(rule, "manifest_json", return_value=legacy) as read:
            found = rule.canvases(value)
        read.assert_called_once_with("https://new.example.org/manifest/imaging")
        self.assertEqual(found, [(legacy_canvas, "Pb")])

    def test_an_unreadable_manifest_raises(self):
        with mock.patch.object(rule, "manifest_json", return_value=None):
            with self.assertRaises(ManifestUnreadableError):
                rule.canvases(MANIFEST_URL)
        with self.assertRaises(ManifestUnreadableError):
            rule.canvases(None)


class PlanTests(RuleCase):
    def test_every_canvas_without_a_tile_gets_its_proposal(self):
        plan = self.plan("Pb", "650 nm", "Video 1")
        self.assertEqual(
            [(p.position, p.canvas, p.label) for p in plan.proposed],
            [
                (0, f"{CANVAS_BASE}0", "Pb"),
                (1, f"{CANVAS_BASE}1", "650 nm"),
                (2, f"{CANVAS_BASE}2", "Video 1"),
            ],
        )
        self.assertEqual(plan.existing, 0)
        self.assertEqual(plan.skipped, [])
        self.assertEqual(plan.orphans, [])

    def test_the_planned_items_are_resolved_by_label_in_the_nodes_list(self):
        plan = self.plan("MS59-f2t-deconv_Cu", "650 nm")
        element, band = plan.proposed
        self.assertEqual(
            element.items["content"],
            str(self.item_id("imaging_layer_content", ELEMENT)),
        )
        self.assertEqual(
            element.items["elements"],
            [str(self.item_id("imaging_layer_elements", "Copper"))],
        )
        self.assertEqual(
            element.items["method"],
            str(self.item_id("imaging_layer_processing_method", DECONV)),
        )
        self.assertEqual(
            band.items["unit"],
            str(self.item_id("imaging_layer_band_unit", "Nanometre")),
        )
        self.assertIsNone(band.items.get("method"))

    def item_id(self, node_alias, pref):
        return ListItemValue.objects.get(
            list_item__list=self.lists[node_alias], value=pref
        ).list_item_id

    def test_a_canvas_with_a_tile_is_counted_and_left_alone(self):
        self.layer_tile(f"{CANVAS_BASE}0")
        plan = self.plan("Pb", "Cu")
        self.assertEqual(plan.existing, 1)
        self.assertEqual([p.label for p in plan.proposed], ["Cu"])

    def test_a_tile_stored_under_a_legacy_host_is_matched(self):
        self.layer_tile("http://old-host:8183/canvas/0")
        with override_settings(
            EXPLORER_LEGACY_HOSTS=["old-host"], PUBLIC_SERVER_ADDRESS=CANVAS_BASE[:-7]
        ):
            plan = self.plan("Pb")
        self.assertEqual(plan.existing, 1)
        self.assertEqual(plan.proposed, [])

    def test_a_tile_of_another_manifest_tile_is_not_an_existing_layer(self):
        other = TileModel.objects.create(
            resourceinstance=self.analyses["open"],
            nodegroup_id=self.manifest_tile.nodegroup_id,
            data={},
        )
        self.layer_tile(f"{CANVAS_BASE}0", parent=other)
        self.assertEqual(self.plan("Pb").existing, 0)

    def test_a_tile_whose_canvas_left_the_manifest_is_an_orphan_never_deleted(self):
        orphan = self.layer_tile("https://example.org/canvas/gone")
        plan = self.plan("Pb")
        self.assertEqual(plan.orphans, [orphan.pk])
        self.assertTrue(TileModel.objects.filter(pk=orphan.pk).exists())

    def test_an_unreadable_label_is_skipped_and_listed(self):
        plan = self.plan("foo", "Pb")
        self.assertEqual(plan.skipped, [(0, f"{CANVAS_BASE}0", "foo")])
        self.assertEqual([p.label for p in plan.proposed], ["Pb"])

    def test_a_symbol_the_elements_list_does_not_know_is_skipped(self):
        plan = self.plan("Zz")
        self.assertEqual(plan.proposed, [])
        self.assertEqual(plan.skipped, [(0, f"{CANVAS_BASE}0", "Zz")])

    def test_a_missing_item_raises_instead_of_planning_a_partial_tile(self):
        ListItemValue.objects.filter(
            list_item__list=self.lists["imaging_layer_content"], value=PHOTO
        ).delete()
        with self.assertRaisesMessage(ImagingLayersConfigError, PHOTO):
            self.plan("Pb", "Video 1")

    def test_an_ambiguous_item_raises(self):
        self.item("imaging_layer_content", BAND, 9)
        with self.assertRaisesMessage(ImagingLayersConfigError, BAND):
            self.plan("650 nm")

    def test_an_ambiguous_symbol_raises(self):
        self.item("imaging_layer_elements", "Copper bis", 5, alt="Cu")
        with self.assertRaisesMessage(ImagingLayersConfigError, "Cu"):
            self.plan("Cu")

    def test_a_node_without_a_controlled_list_raises(self):
        Node.objects.filter(
            pk=self.nodes[("analysis", "imaging_layer_content")].pk
        ).update(config={})
        with self.assertRaises(ImagingLayersConfigError):
            self.plan("Pb")

    def test_an_unknown_layer_node_raises(self):
        Node.objects.filter(
            pk=self.nodes[("analysis", "imaging_layer_note")].pk
        ).update(alias="renamed")
        with self.assertRaises(ImagingLayersConfigError):
            self.plan("Pb")


class WriteTests(RuleCase):
    def written(self, *labels):
        plan = self.plan(*labels)
        saved = []

        def record(tile, **kwargs):
            saved.append((tile, kwargs))

        with mock.patch.object(rule.Tile, "save", autospec=True, side_effect=record):
            rule.write(plan, resource="the-resource")
        return saved

    def test_a_tile_is_saved_per_proposal_under_the_manifest_tile(self):
        saved = self.written("Pb", "foo", "650 nm")
        self.assertEqual(len(saved), 2)
        for tile, _ in saved:
            self.assertEqual(tile.parenttile_id, self.manifest_tile.pk)
            self.assertEqual(tile.resourceinstance_id, self.analyses["open"].pk)
            self.assertEqual(
                str(tile.nodegroup_id),
                str(self.nodes[("analysis", "imaging_layer_canvas")].nodegroup_id),
            )
        self.assertEqual([tile.sortorder for tile, _ in saved], [0, 2])

    def test_each_save_is_the_system_without_a_request_and_without_index(self):
        for _, kwargs in self.written("Pb"):
            self.assertEqual(
                kwargs,
                {
                    "user": None,
                    "request": None,
                    "index": False,
                    "resource": "the-resource",
                },
            )

    def test_the_data_holds_every_node_of_the_group_and_the_proposed_values(self):
        (element, _), (band, _) = self.written("MS59-deconv_Pb", "650,5 nm")
        node = self.layer_node
        self.assertEqual(
            set(element.data),
            {
                node(a)
                for a in (
                    "canvas",
                    "label",
                    "content",
                    "elements",
                    "emission_line",
                    "band_value",
                    "band_lower",
                    "band_upper",
                    "band_unit",
                    "processing_method",
                    "component_index",
                    "processing_inputs",
                    "note",
                )
            },
        )
        self.assertEqual(element.data[node("canvas")], f"{CANVAS_BASE}0")
        self.assertEqual(element.data[node("label")], "MS59-deconv_Pb")
        self.assertIsNone(element.data[node("band_value")])
        self.assertIsNone(element.data[node("note")])
        self.assertEqual(band.data[node("band_value")], 650.5)
        self.assertIsNone(band.data[node("elements")])

    def test_references_are_stored_as_the_reference_datatype_transforms_them(self):
        from arches_controlled_lists.datatypes.datatypes import ReferenceDataType

        ((element, _),) = self.written("MS59-deconv_Pb")
        node = self.layer_node
        content = self.item_id("imaging_layer_content", ELEMENT)
        lead = self.item_id("imaging_layer_elements", "Lead")
        transform = ReferenceDataType().transform_value_for_tile
        self.assertEqual(element.data[node("content")], transform([str(content)]))
        self.assertEqual(element.data[node("elements")], transform([str(lead)]))
        self.assertEqual(
            element.data[node("processing_method")],
            transform([str(self.item_id("imaging_layer_processing_method", DECONV))]),
        )
        self.assertEqual(
            element.data[node("content")][0]["list_id"],
            str(self.lists["imaging_layer_content"].pk),
        )

    def item_id(self, node_alias, pref):
        return ListItemValue.objects.get(
            list_item__list=self.lists[node_alias], value=pref
        ).list_item_id

    def test_a_band_stores_its_unit(self):
        ((band, _),) = self.written("3 um")
        ref = band.data[self.layer_node("band_unit")]
        self.assertEqual(ref[0]["labels"][0]["value"], "Micrometre")

    def test_the_canvas_is_stored_raw(self):
        with override_settings(
            EXPLORER_LEGACY_HOSTS=["example.org"], PUBLIC_SERVER_ADDRESS="https://x/"
        ):
            ((tile, _),) = self.written("Pb")
        self.assertEqual(tile.data[self.layer_node("canvas")], f"{CANVAS_BASE}0")

    def test_a_plan_with_nothing_proposed_writes_nothing(self):
        self.assertEqual(self.written("foo"), [])
