"""What MultiDescriptor writes onto a resource, and what it queries to do it.

The function renders one `<node_alias>` template against a resource's tiles, for
one descriptor (`name`, `description`, `map_popup`) in one language. Arches
calls it once per descriptor per configured language, so the language and the
node lookup are the two things a caller controls: `context["language"]` and
`context["_prefetched_graph_nodes"]`.

The Arches managers are patched as the module reaches them, so nothing here
needs a database.
"""

import uuid
from unittest import mock

from django.test import SimpleTestCase
from django.utils import translation

from arches.app.models import models
from arches.app.models.resource import Resource

from manuspectrum.functions.multi_descriptor import MultiDescriptor

PATCH_NODE = "arches.app.models.models.Node"
PATCH_TILE = "arches.app.models.models.TileModel"
PATCH_FACTORY = "manuspectrum.functions.multi_descriptor.DataTypeFactory"
LOGGER = "manuspectrum.functions.multi_descriptor"

GRAPH_ID = uuid.uuid4()
NODEGROUP_ID = uuid.uuid4()
OTHER_NODEGROUP_ID = uuid.uuid4()


def make_node(alias, nodegroup_id=NODEGROUP_ID, datatype="string"):
    node = mock.Mock()
    node.alias = alias
    node.nodeid = uuid.uuid4()
    node.nodegroup_id = nodegroup_id
    node.datatype = datatype
    return node


def make_tile(values):
    tile = mock.Mock()
    tile.tileid = uuid.uuid4()
    tile.data = {str(node.nodeid): value for node, value in values.items()}
    return tile


class DescriptorTestCase(SimpleTestCase):
    def setUp(self):
        patchers = {
            "Node": mock.patch(PATCH_NODE),
            "TileModel": mock.patch(PATCH_TILE),
            "DataTypeFactory": mock.patch(PATCH_FACTORY),
        }
        for attribute, patcher in patchers.items():
            setattr(self, attribute, patcher.start())
            self.addCleanup(patcher.stop)

        self.datatype = self.DataTypeFactory.return_value.get_instance.return_value
        self.function = MultiDescriptor()

        self.resource = mock.Mock()
        self.resource.graph = GRAPH_ID
        self.resource.resourceinstanceid = uuid.uuid4()
        self.resource.descriptors = {}

        self.graph_nodes()
        self.tiles()

    def graph_nodes(self, *nodes):
        self.Node.objects.filter.return_value = list(nodes)

    def tiles(self, *tiles):
        self.TileModel.objects.filter.return_value.order_by.return_value = list(tiles)

    def display_values(self, values):
        self.datatype.get_display_value.side_effect = (
            lambda tile, node, language=None: values[node.alias]
        )

    def describe(self, template, context=None, descriptor="name"):
        return self.function.get_primary_descriptor_from_nodes(
            self.resource,
            {"nodegroup_id": str(NODEGROUP_ID), "string_template": template},
            context if context is not None else {"language": "en"},
            descriptor,
        )


class TemplateSubstitutionTests(DescriptorTestCase):
    def test_a_placeholder_becomes_the_tiles_display_value(self):
        cote = make_node("cote")
        self.graph_nodes(cote)
        self.tiles(make_tile({cote: ["Ms. 12"]}))
        self.display_values({"cote": "Ms. 12"})

        self.assertEqual(self.describe("Cote <cote>"), "Cote Ms. 12")

    def test_placeholders_from_two_nodegroups_are_both_filled(self):
        cote = make_node("cote")
        auteur = make_node("auteur", nodegroup_id=OTHER_NODEGROUP_ID)
        tiles_by_nodegroup = {
            NODEGROUP_ID: [make_tile({cote: ["Ms. 12"]})],
            OTHER_NODEGROUP_ID: [make_tile({auteur: ["Guillaume"]})],
        }

        def tiles_of_nodegroup(**kwargs):
            queryset = mock.Mock()
            queryset.order_by.return_value = tiles_by_nodegroup[kwargs["nodegroup_id"]]
            return queryset

        self.graph_nodes(cote, auteur)
        self.TileModel.objects.filter.side_effect = tiles_of_nodegroup
        self.display_values({"cote": "Ms. 12", "auteur": "Guillaume"})

        self.assertEqual(
            self.describe("<cote> — <auteur>"),
            "Ms. 12 — Guillaume",
        )

    def test_the_descriptor_language_is_handed_to_the_datatype(self):
        cote = make_node("cote")
        self.graph_nodes(cote)
        tile = make_tile({cote: ["Ms. 12"]})
        self.tiles(tile)
        self.display_values({"cote": "Ms. 12"})

        self.assertEqual(
            self.describe("Cote <cote>", context={"language": "fr"}),
            "Cote Ms. 12",
        )

        self.datatype.get_display_value.assert_called_once_with(
            tile, cote, language="fr"
        )

    def test_tiles_are_read_from_the_nodes_own_nodegroup_in_sort_order(self):
        cote = make_node("cote")
        self.graph_nodes(cote)
        self.tiles(make_tile({cote: ["Ms. 12"]}))
        self.display_values({"cote": "Ms. 12"})

        self.assertEqual(self.describe("Cote <cote>"), "Cote Ms. 12")

        self.TileModel.objects.filter.assert_called_once_with(
            nodegroup_id=cote.nodegroup_id,
            resourceinstance_id=self.resource.resourceinstanceid,
        )
        self.TileModel.objects.filter.return_value.order_by.assert_called_once_with(
            "sortorder"
        )

    def test_the_first_tile_in_sort_order_wins(self):
        cote = make_node("cote")
        first = make_tile({cote: ["Ms. 12"]})
        second = make_tile({cote: ["Ms. 99"]})
        self.graph_nodes(cote)
        self.tiles(first, second)
        self.datatype.get_display_value.side_effect = (
            lambda tile, node, language=None: {
                first.tileid: "Ms. 12",
                second.tileid: "Ms. 99",
            }[tile.tileid]
        )

        self.assertEqual(self.describe("Cote <cote>"), "Cote Ms. 12")

    def test_a_second_alias_stored_in_the_same_tile_is_left_unsubstituted(self):
        """`processed_tiles` is shared by every alias, not kept per alias."""
        cote = make_node("cote")
        auteur = make_node("auteur")
        self.graph_nodes(cote, auteur)
        self.tiles(make_tile({cote: ["Ms. 12"], auteur: ["Guillaume"]}))
        self.display_values({"cote": "Ms. 12", "auteur": "Guillaume"})

        self.assertEqual(self.describe("<cote> — <auteur>"), "Ms. 12 — <auteur>")

    def test_an_alias_with_no_matching_node_never_looks_for_a_tile(self):
        self.graph_nodes(make_node("cote"))

        self.assertEqual(self.describe("Titre <titre>"), "Titre <titre>")
        self.TileModel.objects.filter.assert_not_called()

    def test_a_node_with_no_tile_keeps_the_descriptor_already_stored(self):
        cote = make_node("cote")
        self.graph_nodes(cote)
        self.resource.descriptors = {"en": {"name": "Ms. 12, fonds ancien"}}

        self.assertEqual(self.describe("Cote <cote>"), "Ms. 12, fonds ancien")

    def test_a_node_with_no_tile_and_nothing_stored_returns_the_raw_template(self):
        self.graph_nodes(make_node("cote"))

        self.assertEqual(self.describe("Cote <cote>"), "Cote <cote>")

    def test_a_tile_holding_no_value_for_the_node_is_skipped(self):
        cote = make_node("cote")
        self.graph_nodes(cote)
        self.tiles(make_tile({cote: None}))
        self.resource.descriptors = {"en": {"name": "Ms. 12, fonds ancien"}}

        self.assertEqual(self.describe("Cote <cote>"), "Ms. 12, fonds ancien")
        self.DataTypeFactory.assert_not_called()

    def test_an_empty_display_value_gives_the_undefined_label(self):
        cote = make_node("cote")
        self.graph_nodes(cote)
        self.tiles(make_tile({cote: [""]}))
        self.display_values({"cote": ""})

        with translation.override("en"):
            self.assertEqual(self.describe("<cote>"), "Undefined")

    def test_the_undefined_label_ignores_the_requested_descriptor_language(self):
        """Characterisation, not endorsement.

        The label goes through ``gettext``, which resolves in the thread's
        ACTIVE language, while every other part of the descriptor honours
        ``context["language"]``. So a save served in English writes the English
        word into ``descriptors["fr"]``, and vice versa.
        """
        cote = make_node("cote")
        self.graph_nodes(cote)
        self.tiles(make_tile({cote: [""]}))
        self.display_values({"cote": ""})

        with translation.override("fr"):
            self.assertEqual(
                self.describe("<cote>", context={"language": "en"}), "Indéfini"
            )

    def test_a_display_value_of_none_is_substituted_as_an_empty_string(self):
        cote = make_node("cote")
        self.graph_nodes(cote)
        self.tiles(make_tile({cote: ["Ms. 12"]}))
        self.display_values({"cote": None})

        self.assertEqual(self.describe("Cote <cote>"), "Cote ")

    def test_a_datatype_failure_is_logged_and_leaves_the_stored_descriptor(self):
        cote = make_node("cote")
        self.graph_nodes(cote)
        self.tiles(make_tile({cote: ["Ms. 12"]}))
        self.datatype.get_display_value.side_effect = ValueError("no such datatype")
        self.resource.descriptors = {"en": {"name": "Ms. 12, fonds ancien"}}

        with self.assertLogs(LOGGER, level="ERROR") as logs:
            result = self.describe("Cote <cote>")

        self.assertEqual(result, "Ms. 12, fonds ancien")
        self.assertIn("no such datatype", logs.output[0])


class PrefetchedNodeTests(DescriptorTestCase):
    def test_a_prefetched_node_list_replaces_the_graph_query(self):
        cote = make_node("cote")
        self.tiles(make_tile({cote: ["Ms. 12"]}))
        self.display_values({"cote": "Ms. 12"})

        result = self.describe(
            "Cote <cote>",
            context={"language": "en", "_prefetched_graph_nodes": [cote]},
        )

        self.assertEqual(result, "Cote Ms. 12")
        self.Node.objects.filter.assert_not_called()

    def test_a_prefetched_context_is_reused_by_every_later_call(self):
        cote = make_node("cote")
        self.tiles(make_tile({cote: ["Ms. 12"]}))
        self.display_values({"cote": "Ms. 12"})
        context = {"language": "en", "_prefetched_graph_nodes": [cote]}

        first = self.describe("Cote <cote>", context=context, descriptor="name")
        second = self.describe(
            "Manuscrit <cote>", context=context, descriptor="description"
        )

        self.assertEqual([first, second], ["Cote Ms. 12", "Manuscrit Ms. 12"])
        self.Node.objects.filter.assert_not_called()

    def test_without_a_prefetch_every_call_queries_the_graph_again(self):
        cote = make_node("cote")
        self.graph_nodes(cote)
        self.tiles(make_tile({cote: ["Ms. 12"]}))
        self.display_values({"cote": "Ms. 12"})
        context = {"language": "en"}

        self.describe("Cote <cote>", context=context, descriptor="name")
        self.describe("Manuscrit <cote>", context=context, descriptor="description")

        self.assertEqual(
            self.Node.objects.filter.call_args_list,
            [mock.call(graph=self.resource.graph)] * 2,
        )
        self.assertNotIn("_prefetched_graph_nodes", context)


class SaveDescriptorsTests(SimpleTestCase):
    """The whole Arches loop: three descriptors × every configured language.

    `Resource.save_descriptors` is the only caller in core, and it is what
    decides that the function runs once per language; only the Biblissima batch
    write path (`_batch_save_descriptors`) puts the node list in the context it
    hands over.
    """

    def setUp(self):
        patchers = {
            "Node": mock.patch(PATCH_NODE),
            "TileModel": mock.patch(PATCH_TILE),
            "DataTypeFactory": mock.patch(PATCH_FACTORY),
            "save": mock.patch.object(models.ResourceInstance, "save"),
        }
        for attribute, patcher in patchers.items():
            setattr(self, attribute, patcher.start())
            self.addCleanup(patcher.stop)

        self.datatype = self.DataTypeFactory.return_value.get_instance.return_value
        self.cote = make_node("cote")
        self.Node.objects.filter.return_value = [self.cote]
        self.TileModel.objects.filter.return_value.order_by.return_value = [
            make_tile({self.cote: ["Ms. 12"]})
        ]
        self.datatype.get_display_value.side_effect = (
            lambda tile, node, language=None: f"Ms. 12 ({language})"
        )

    def make_resource(self):
        function_x_graph = mock.Mock()
        function_x_graph.function.get_class_module.return_value = MultiDescriptor
        function_x_graph.config = {
            "descriptor_types": {
                "name": {
                    "nodegroup_id": str(NODEGROUP_ID),
                    "string_template": "Cote <cote>",
                },
                "description": {
                    "nodegroup_id": str(NODEGROUP_ID),
                    "string_template": "Manuscrit <cote>",
                },
                "map_popup": {
                    "nodegroup_id": str(NODEGROUP_ID),
                    "string_template": "<cote>",
                },
            }
        }
        resource = Resource(
            resourceinstanceid=uuid.uuid4(),
            graph=models.GraphModel(graphid=GRAPH_ID),
            descriptors={},
            name={},
        )
        resource.descriptor_function = [function_x_graph]
        return resource

    def test_every_configured_language_gets_its_own_descriptors(self):
        resource = self.make_resource()

        resource.save_descriptors()

        self.assertEqual(
            resource.descriptors,
            {
                "en": {
                    "name": "Cote Ms. 12 (en)",
                    "description": "Manuscrit Ms. 12 (en)",
                    "map_popup": "Ms. 12 (en)",
                },
                "fr": {
                    "name": "Cote Ms. 12 (fr)",
                    "description": "Manuscrit Ms. 12 (fr)",
                    "map_popup": "Ms. 12 (fr)",
                },
            },
        )

    def test_the_name_descriptor_also_lands_on_the_resource_name(self):
        resource = self.make_resource()

        resource.save_descriptors()

        self.assertEqual(
            resource.name, {"en": "Cote Ms. 12 (en)", "fr": "Cote Ms. 12 (fr)"}
        )

    def test_the_unprefetched_path_queries_the_graph_nodes_once_per_descriptor(self):
        """Six queries is the contract PR-10 is meant to collapse: 3 x 2.

        Three descriptors (name, description, map popup) times the two
        configured languages, each re-reading the whole node list because the
        function consumes ``_prefetched_graph_nodes`` but never populates it.
        """
        resource = self.make_resource()

        resource.save_descriptors()

        self.assertEqual(self.Node.objects.filter.call_count, 6)

    def test_a_prefetched_context_covers_every_language_and_descriptor(self):
        resource = self.make_resource()

        resource.save_descriptors(context={"_prefetched_graph_nodes": [self.cote]})

        self.assertEqual(
            resource.descriptors["fr"]["name"],
            "Cote Ms. 12 (fr)",
        )
        self.Node.objects.filter.assert_not_called()
