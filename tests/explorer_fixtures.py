"""Explorer fixtures: real model slugs and graph ids, the roles the Explorer reads, and the Active lifecycle state.

A resource created without a lifecycle state lands in the initial state of its
lifecycle, which is a Draft for the default lifecycle; every fixture resource
here is created Active on purpose. The test database lists the core
datatypes only; the project datatype ``manifest`` is registered here.
"""

import uuid

from django.contrib.auth.models import Group, User
from django.core.cache import cache, caches
from django.test import TestCase

from arches.app.models.models import (
    DDataType,
    GraphModel,
    Node,
    NodeGroup,
    ResourceInstance,
    TileModel,
)
from arches.app.utils.permission_backend import assign_perm

LIFECYCLE = "7e3cce56-fbfb-4a4b-8e83-59b9f9e7cb75"
DRAFT = "9375c9a7-dad2-4f14-a5c1-d7e329fdde4f"
ACTIVE = "f75bb034-36e3-4ab4-8167-f520cf0b4c58"

GRAPHS = {
    "document": "0c8226c1-11a9-4c48-9601-a7a0c6f2df6b",
    "component": "d47595b4-f8a6-419c-8f33-b388206280c4",
    "analysis": "60c85aba-f079-45bc-997f-21cdd4f77b6d",
    "project": "87a4319d-3ca5-43f6-88cc-a7379fba67f6",
    "sample": "7a5eda79-6b48-49d0-826d-931d5681e84e",
    "characterization": "af6eed4f-04a3-40d8-baef-1ad37b86c4dd",
    "person": "5bf45c85-84cd-4a76-b64a-3ffe86eea1b8",
}

# (slug, alias, datatype, nodegroup key): nodes sharing a key share a nodegroup.
ROLE_NODES = [
    ("document", "label_of_name", "string", "doc_name"),
    ("document", "facsimiles", "manifest", "doc_facsimile"),
    ("component", "label_of_name", "string", "comp_name"),
    ("component", "item_visual_is_part_of_document", "resource-instance", "comp_doc"),
    ("component", "location_in_document", "annotation", "comp_zone"),
    ("analysis", "label_of_name", "string", "an_name"),
    ("analysis", "component_observed", "resource-instance", "an_observed"),
    ("analysis", "analysis_by_project", "resource-instance", "an_project"),
    ("analysis", "sample_used", "resource-instance", "an_sample"),
    ("analysis", "analysis_technique_used", "reference", "an_technique"),
    ("analysis", "performed_by_actor", "resource-instance-list", "an_actor"),
    ("analysis", "analysis_start_date", "date", "an_dates"),
    ("analysis", "analysis_end_date", "date", "an_dates"),
    ("analysis", "measurement_point_data", "file-list", "an_files"),
    ("analysis", "micro_macro_imaging", "file-list", "an_micro"),
    ("analysis", "literal_location_of_analysis", "annotation", "an_zone"),
    ("analysis", "dataset_url", "url", "an_dataset"),
    ("analysis", "bibliographic_title", "string", "an_biblio"),
    ("analysis", "type_of_statement", "reference", "an_statement"),
    ("analysis", "content_of_statement", "string", "an_statement"),
    ("project", "label_of_name", "string", "proj_name"),
    ("sample", "label_of_name", "string", "sample_name"),
    ("person", "label_of_name", "string", "person_name"),
    ("characterization", "label_of_name", "string", "char_name"),
    ("characterization", "object_observed", "resource-instance-list", "char_object"),
    (
        "characterization",
        "evidence_analyses",
        "resource-instance-list",
        "char_evidence",
    ),
    ("characterization", "identified_material", "reference", "char_material"),
    ("characterization", "material_confidence", "reference", "char_material"),
    ("characterization", "color_aspect", "reference", "char_colour"),
    ("characterization", "layer_type", "reference", "char_layer"),
    ("characterization", "detected_elements", "reference", "char_elements"),
    ("characterization", "element_level", "reference", "char_elements"),
    ("characterization", "location_of_characterization", "annotation", "char_zone"),
    ("characterization", "inference_making", "string", "char_note"),
    (
        "characterization",
        "authors_of_inference",
        "resource-instance-list",
        "char_authors",
    ),
    ("characterization", "inference_making_start_date", "date", "char_dates"),
    ("characterization", "inference_making_end_date", "date", "char_dates"),
    ("characterization", "source_of_statement", "url", "char_source"),
    ("analysis", "instrument", "resource-instance", "an_instrument"),
    ("analysis", "chemical_imaging_manifest", "manifest", "an_imaging"),
    ("document", "current_owner", "resource-instance-list", "doc_owner"),
]

CANVAS = "https://example.org/iiif/ms59/canvas/f1v"
MANIFEST = "https://example.org/iiif/ms59/manifest"
XY_CONFIG_ID = "7a1c3f80-5d21-4e63-9b0a-2c4f8e1d6a01"


class ExplorerCase(TestCase):
    """Two Documents with a Component each, four Analyses, two Projects, a Sample and one identified material."""

    @classmethod
    def setUpTestData(cls):
        cls.graphs = {
            slug: GraphModel.objects.create(
                graphid=graph_id,
                name=slug,
                slug=slug,
                isresource=True,
                is_active=True,
                resource_instance_lifecycle_id=LIFECYCLE,
            )
            for slug, graph_id in GRAPHS.items()
        }
        DDataType.objects.get_or_create(
            datatype="manifest",
            defaults={
                "iconclass": "fa fa-file-image-o",
                "modulename": "manifest.py",
                "classname": "ManifestDataType",
                "isgeometric": False,
            },
        )
        nodegroups, cls.nodes = {}, {}
        for slug, alias, datatype, key in ROLE_NODES:
            if key not in nodegroups:
                nodegroups[key] = NodeGroup.objects.create(
                    nodegroupid=uuid.uuid4(), cardinality="n"
                )
            cls.nodes[(slug, alias)] = Node.objects.create(
                nodeid=uuid.uuid4(),
                graph=cls.graphs[slug],
                nodegroup=nodegroups[key],
                name=alias,
                alias=alias,
                datatype=datatype,
                istopnode=False,
            )
        cls.anonymous = User.objects.get(username="anonymous")
        cls.editor = User.objects.create_user("explorer_editor", password="pw")
        cls.editor.groups.add(Group.objects.get(name="Resource Editor"))

        new = cls.new_resource
        cls.documents = {
            "open": new("document", "Ms 59"),
            "embargoed": new("document", "Ms 211"),
        }
        cls.components = {
            "open": new("component", "f. 1v — initial"),
            "embargoed": new("component", "f. 3r"),
        }
        cls.projects = {
            "main": new("project", "EMMA"),
            "side": new("project", "Side project"),
        }
        cls.samples = {"s1": new("sample", "S1")}
        cls.operator = new("person", "Robinet, L.")
        cls.analyses = {
            "open": new("analysis", "X01 — f. 1v"),
            "on_document": new("analysis", "FORS_009 — f. 1v"),
            "embargoed": new("analysis", "X02 — f. 3r"),
            "draft": new("analysis", "X03 — draft", state=DRAFT),
        }
        cls.characterization = new("characterization", "Azurite, blue ground")

        tile = cls.tile
        tile(
            cls.components["open"],
            "item_visual_is_part_of_document",
            cls.refs(cls.documents["open"]),
        )
        tile(
            cls.components["embargoed"],
            "item_visual_is_part_of_document",
            cls.refs(cls.documents["embargoed"]),
        )
        tile(
            cls.analyses["open"], "component_observed", cls.refs(cls.components["open"])
        )
        tile(
            cls.analyses["open"], "analysis_by_project", cls.refs(cls.projects["main"])
        )
        tile(cls.analyses["open"], "sample_used", cls.refs(cls.samples["s1"]))
        tile(
            cls.analyses["on_document"],
            "component_observed",
            cls.refs(cls.documents["open"]),
        )
        tile(
            cls.analyses["on_document"],
            "analysis_by_project",
            cls.refs(cls.projects["side"]),
        )
        tile(
            cls.analyses["embargoed"],
            "component_observed",
            cls.refs(cls.components["embargoed"]),
        )
        tile(
            cls.analyses["draft"],
            "component_observed",
            cls.refs(cls.components["open"]),
        )
        tile(cls.characterization, "object_observed", cls.refs(cls.components["open"]))
        tile(
            cls.characterization,
            "evidence_analyses",
            cls.refs(cls.analyses["open"], cls.analyses["on_document"]),
        )

    @classmethod
    def new_resource(cls, slug, name, state=ACTIVE):
        resource = ResourceInstance.objects.create(
            graph=cls.graphs[slug], resource_instance_lifecycle_state_id=state
        )
        cls.tile(resource, "label_of_name", cls.string_value(name))
        return resource

    @classmethod
    def tile(cls, resource, alias, value, slug=None):
        slug = slug or next(
            s for s, g in cls.graphs.items() if g.pk == resource.graph_id
        )
        node = cls.nodes[(slug, alias)]
        return TileModel.objects.create(
            resourceinstance=resource,
            nodegroup_id=node.nodegroup_id,
            data={str(node.nodeid): value},
        )

    @staticmethod
    def string_value(en, fr=None):
        value = {"en": {"value": en, "direction": "ltr"}}
        if fr:
            value["fr"] = {"value": fr, "direction": "ltr"}
        return value

    @staticmethod
    def refs(*resources):
        return [
            {
                "resourceId": str(r.pk),
                "ontologyProperty": "",
                "inverseOntologyProperty": "",
            }
            for r in resources
        ]

    @staticmethod
    def reference_value(uri, en, fr=None, list_id=None, alt=None):
        item = str(uuid.uuid5(uuid.NAMESPACE_URL, uri))
        labels = [
            {
                "id": str(uuid.uuid4()),
                "value": en,
                "language_id": "en",
                "list_item_id": item,
                "valuetype_id": "prefLabel",
            }
        ]
        if fr:
            labels.append(
                {
                    "id": str(uuid.uuid4()),
                    "value": fr,
                    "language_id": "fr",
                    "list_item_id": item,
                    "valuetype_id": "prefLabel",
                }
            )
        if alt:
            labels.append(
                {
                    "id": str(uuid.uuid4()),
                    "value": alt,
                    "language_id": "en",
                    "list_item_id": item,
                    "valuetype_id": "altLabel",
                }
            )
        return [{"uri": uri, "list_id": list_id or str(uuid.uuid4()), "labels": labels}]

    @staticmethod
    def annotation_value(canvas, geometry):
        return {
            "type": "FeatureCollection",
            "features": [
                {
                    "id": str(uuid.uuid4()),
                    "type": "Feature",
                    "geometry": geometry,
                    "properties": {"canvas": canvas, "manifest": MANIFEST},
                }
            ],
        }

    def setUp(self):
        cache.clear()
        caches["user_permission"].clear()
        self.addCleanup(cache.clear)
        self.addCleanup(caches["user_permission"].clear)

    def embargo(self, resource):
        with self.captureOnCommitCallbacks(execute=True):
            assign_perm("no_access_to_resourceinstance", self.anonymous, resource)

    def make_draft(self, resource):
        ResourceInstance.objects.filter(pk=resource.pk).update(
            resource_instance_lifecycle_state_id=DRAFT
        )
        cache.clear()
