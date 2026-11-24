import hashlib
import uuid

from django.contrib.auth.models import Group, User
from django.core.exceptions import PermissionDenied
from django.db import connection
from django.test.utils import CaptureQueriesContext

from arches.app.models.models import Node, NodeGroup, ResourceInstance, TileModel
from arches.app.utils.permission_backend import assign_perm

from manuspectrum.constants.xy_presets import TECHNIQUE_PRESETS
from manuspectrum.measurement_files import catalogue
from tests.explorer_fixtures import ExplorerCase

RETIRED = "d95d9c0e-0e2c-4450-93a3-d788b91abcc8"
XRF_ITEM = next(i for i, preset in TECHNIQUE_PRESETS.items() if preset == "xrf")
FORS_ITEM = next(i for i, preset in TECHNIQUE_PRESETS.items() if preset != "xrf")

EXTRA_NODES = [
    ("analysis", "note_about_location", "string", "an_location"),
    ("analysis", "label_of_annotation_location", "string", "an_location"),
    ("analysis", "filename", "non-localized-string", "an_data"),
    ("project", "studied_object", "resource-instance-list", "proj_studied"),
]


class CatalogueCase(ExplorerCase):
    """One Document, two Components, two Projects, four Analyses.

    ``a_link`` (component 1, project P1, XRF) has raw + CSV paired by
    ``msSourceFileId``; ``a_name`` (component 2, P2) raw + CSV paired by name;
    ``a_raw`` (the Document itself, P1) a raw file alone; ``a_retired``
    (component 1, P2) is Retired, no file.
    """

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        groups = {}
        for slug, alias, datatype, key in EXTRA_NODES:
            groups.setdefault(
                key,
                NodeGroup.objects.create(
                    nodegroupid=uuid.uuid4(),
                    cardinality="1" if key == "an_data" else "n",
                ),
            )
            cls.nodes[(slug, alias)] = Node.objects.create(
                nodeid=uuid.uuid4(),
                graph=cls.graphs[slug],
                nodegroup=groups[key],
                name=alias,
                alias=alias,
                datatype=datatype,
                istopnode=False,
            )
        files_group = cls.nodes[("analysis", "measurement_point_data")].nodegroup
        files_group.parentnodegroup = groups["an_data"]
        files_group.save()
        cls.data_group = groups["an_data"]

        new = cls.new_resource
        cls.document = new("document", "Catalogue manuscript")
        cls.comp1 = new("component", "f. 1r")
        cls.comp2 = new("component", "f. 2v")
        cls.p1 = new("project", "Project one")
        cls.p2 = new("project", "Project two")
        cls.a_link = new("analysis", "A link")
        cls.a_name = new("analysis", "B name")
        cls.a_raw = new("analysis", "C raw")
        cls.a_retired = new("analysis", "D retired", state=RETIRED)
        for comp in (cls.comp1, cls.comp2):
            cls.tile(comp, "item_visual_is_part_of_document", cls.refs(cls.document))
        for analysis, target, project in (
            (cls.a_link, cls.comp1, cls.p1),
            (cls.a_name, cls.comp2, cls.p2),
            (cls.a_raw, cls.document, cls.p1),
            (cls.a_retired, cls.comp1, cls.p2),
        ):
            cls.tile(analysis, "component_observed", cls.refs(target))
            cls.tile(analysis, "analysis_by_project", cls.refs(project))
        for project in (cls.p1, cls.p2):
            cls.tile(project, "studied_object", cls.refs(cls.document))
        cls.tile(
            cls.a_link,
            "analysis_technique_used",
            [
                {
                    "uri": "https://example.org/xrf",
                    "list_id": str(uuid.uuid4()),
                    "labels": [
                        {
                            "id": str(uuid.uuid4()),
                            "value": "X-ray fluorescence",
                            "language_id": "en",
                            "list_item_id": XRF_ITEM,
                            "valuetype_id": "prefLabel",
                        },
                        {
                            "id": str(uuid.uuid4()),
                            "value": "Fluorescence X",
                            "language_id": "fr",
                            "list_item_id": XRF_ITEM,
                            "valuetype_id": "prefLabel",
                        },
                    ],
                }
            ],
        )
        cls.tile_values(
            cls.a_link,
            "analysis",
            note_about_location="Upper margin",
            label_of_annotation_location="Zone 7",
        )
        cls.tile(cls.a_link, "filename", "a-point-01", slug="analysis")
        cls.parent_tile = TileModel.objects.get(
            resourceinstance=cls.a_link, nodegroup=cls.data_group
        )

    def setUp(self):
        super().setUp()
        raw = self.stored_file(self.a_link, "a.mca", b"raw")
        csv = self.stored_file(self.a_link, "converted.csv", b"x,y\n")
        self.link_source(self.a_link, csv, raw)
        self.stored_file(self.a_name, "b.0", b"raw")
        self.stored_file(self.a_name, "b.0.csv", b"x,y\n")
        self.stored_file(self.a_raw, "c.mca", b"raw")

    def link_source(self, analysis, csv_id, raw_id):
        node = self.nodes[("analysis", "measurement_point_data")]
        tile = TileModel.objects.get(
            resourceinstance=analysis, nodegroup_id=node.nodegroup_id
        )
        entries = tile.data[str(node.nodeid)]
        for entry in entries:
            if entry["file_id"] == csv_id:
                entry["msSourceFileId"] = raw_id
                entry["msSourceSha256"] = "ab" * 32
        TileModel.objects.filter(pk=tile.pk).update(data=tile.data)

    def cards(self, user=None, project=None):
        found = catalogue.document_analyses(
            self.document.pk, user or self.editor, project and project.pk
        )
        return {card.name: card for card in found}


class DocumentAnalysesTests(CatalogueCase):
    def test_lists_the_analyses_of_the_document_and_its_components(self):
        self.assertEqual(list(self.cards()), ["A link", "B name", "C raw", "D retired"])

    def test_project_keeps_only_its_analyses(self):
        self.assertEqual(list(self.cards(project=self.p1)), ["A link", "C raw"])
        self.assertEqual(list(self.cards(project=self.p2)), ["B name", "D retired"])

    def test_projects_of_each_analysis(self):
        card = self.cards()["A link"]
        self.assertEqual(card.projects, (str(self.p1.pk),))

    def test_retired_analysis_is_not_editable(self):
        cards = self.cards()
        self.assertFalse(cards["D retired"].editable)
        self.assertTrue(cards["A link"].editable)

    def test_technique_label_ids_and_preset(self):
        card = self.cards()["A link"]
        self.assertEqual(card.technique_ids, (XRF_ITEM,))
        self.assertEqual(
            card.technique_label, {"en": "X-ray fluorescence", "fr": "Fluorescence X"}
        )
        self.assertEqual(card.technique_preset, "xrf")
        none = self.cards()["B name"]
        self.assertEqual((none.technique_ids, none.technique_preset), ((), None))

    def test_several_techniques_give_no_preset(self):
        self.assertIsNone(catalogue._preset((XRF_ITEM, FORS_ITEM)))
        self.assertIsNone(catalogue._preset((XRF_ITEM, "unknown")))
        self.assertEqual(catalogue._preset((XRF_ITEM,)), "xrf")

    def test_folio_sources(self):
        self.assertEqual(
            self.cards()["A link"].folio_sources,
            ("A link", "f. 1r", "Upper margin", "Zone 7", "a-point-01"),
        )
        self.assertEqual(self.cards()["C raw"].folio_sources, ("C raw",))

    def test_parent_tile(self):
        self.assertEqual(
            self.cards()["A link"].parent_tile_id, str(self.parent_tile.pk)
        )
        self.assertIsNone(self.cards()["B name"].parent_tile_id)

    def test_csv_twin_by_source_link_and_by_name(self):
        by_name = {f.name: f for f in self.cards()["A link"].files}
        self.assertTrue(by_name["a.mca"].has_csv_twin)
        self.assertTrue(by_name["a.mca"].is_raw)
        self.assertFalse(by_name["converted.csv"].is_raw)
        self.assertEqual(by_name["converted.csv"].sha256, "ab" * 32)
        self.assertEqual(by_name["converted.csv"].extension, "csv")
        named = {f.name: f for f in self.cards()["B name"].files}
        self.assertTrue(named["b.0"].has_csv_twin)
        self.assertIsNone(named["b.0"].sha256)

    def test_raw_alone_has_no_twin(self):
        (stored,) = self.cards()["C raw"].files
        self.assertTrue(stored.is_raw)
        self.assertFalse(stored.has_csv_twin)

    def test_stored_sha256_reads_the_bytes_once_asked(self):
        file_id = self.cards()["C raw"].files[0].file_id
        self.assertEqual(
            catalogue.stored_sha256(file_id), hashlib.sha256(b"raw").hexdigest()
        )
        self.assertIsNone(catalogue.stored_sha256(uuid.uuid4()))

    def test_unreadable_document_is_refused(self):
        outsider = User.objects.create_user("catalogue_outsider", password="pw")
        outsider.groups.add(Group.objects.get(name="Resource Editor"))
        with self.captureOnCommitCallbacks(execute=True):
            assign_perm("no_access_to_resourceinstance", outsider, self.document)
        with self.assertRaises(PermissionDenied):
            catalogue.document_analyses(self.document.pk, outsider)

    def test_unknown_document_is_refused(self):
        with self.assertRaises(PermissionDenied):
            catalogue.document_analyses(uuid.uuid4(), self.editor)

    def test_unreadable_analysis_is_left_out(self):
        with self.captureOnCommitCallbacks(execute=True):
            assign_perm("no_access_to_resourceinstance", self.editor, self.a_raw)
        self.assertNotIn("C raw", self.cards())

    def test_query_count_does_not_grow_with_the_analyses(self):
        with CaptureQueriesContext(connection) as small:
            self.cards()
        for index in range(6):
            analysis = self.new_resource("analysis", f"E extra {index}")
            self.tile(analysis, "component_observed", self.refs(self.comp2))
            self.stored_file(analysis, f"e{index}.mca", b"raw")
        with CaptureQueriesContext(connection) as large:
            self.cards()
        # permission checks (read, edit) cost a bounded number each; the rest is per role
        self.assertLessEqual(len(large) - len(small), 6 * 6, (len(small), len(large)))


class DocumentStatusTests(CatalogueCase):
    def test_counts(self):
        status = catalogue.document_status(self.document.pk, self.editor)
        self.assertEqual(status["analyses"], 4)
        self.assertEqual(status["complete"], 2)
        self.assertEqual(status["raw_without_csv"], 1)
        self.assertEqual(status["without_file"], 1)
        self.assertEqual(
            {tuple(e["technique_ids"]): e["analyses"] for e in status["by_technique"]},
            {(XRF_ITEM,): 1, (): 3},
        )

    def test_other_projects_lists_the_second_project(self):
        status = catalogue.document_status(
            self.document.pk, self.editor, project_id=self.p1.pk
        )
        self.assertEqual(status["analyses"], 2)
        self.assertEqual(
            status["other_projects"],
            [{"project_id": str(self.p2.pk), "name": "Project two", "analyses": 2}],
        )

    def test_without_project_both_studying_projects_are_listed(self):
        status = catalogue.document_status(self.document.pk, self.editor)
        self.assertEqual(
            [p["name"] for p in status["other_projects"]],
            ["Project one", "Project two"],
        )

    def test_single_studying_project_lists_nothing(self):
        TileModel.objects.filter(resourceinstance=self.p2).exclude(
            nodegroup_id=self.nodes[("project", "label_of_name")].nodegroup_id
        ).delete()
        status = catalogue.document_status(self.document.pk, self.editor)
        self.assertEqual(status["other_projects"], [])


class EditableDocumentsTests(CatalogueCase):
    def names(self, *args, **kwargs):
        return [d["name"] for d in catalogue.editable_documents(*args, **kwargs)]

    def test_lists_documents_with_an_editable_analysis(self):
        self.assertIn("Catalogue manuscript", self.names(self.editor))

    def test_project_restricts_to_its_studied_documents(self):
        self.assertEqual(
            self.names(self.editor, project_id=self.p1.pk), ["Catalogue manuscript"]
        )
        other = self.new_resource("project", "Empty project")
        self.assertEqual(self.names(self.editor, project_id=other.pk), [])

    def test_document_with_only_retired_analyses_is_left_out(self):
        for analysis in (self.a_link, self.a_name, self.a_raw):
            ResourceInstance.objects.filter(pk=analysis.pk).update(
                resource_instance_lifecycle_state_id=RETIRED
            )
        self.assertNotIn("Catalogue manuscript", self.names(self.editor))

    def test_query_filters_names_and_cap(self):
        self.assertEqual(
            self.names(self.editor, query="catalogue"), ["Catalogue manuscript"]
        )
        self.assertEqual(self.names(self.editor, query="zzz"), [])
        for index in range(55):
            document = self.new_resource("document", f"Doc {index:02d}")
            analysis = self.new_resource("analysis", f"Z {index}")
            self.tile(analysis, "component_observed", self.refs(document))
        listed = catalogue.editable_documents(self.editor, query="doc ")
        self.assertEqual(len(listed), 50)
        self.assertEqual(listed[0]["name"], "Doc 00")

    def test_unreadable_document_is_left_out(self):
        with self.captureOnCommitCallbacks(execute=True):
            assign_perm("no_access_to_resourceinstance", self.editor, self.document)
        self.assertNotIn("Catalogue manuscript", self.names(self.editor))
