"""``iiif.facts``: one reader-filtered read of a Document or Component.

Usage:
    python manage.py test tests.test_iiif_facts --settings=tests.test_settings
"""

import copy
import uuid
from unittest import mock

from django.conf import settings
from django.contrib.auth.models import User
from django.core.files.base import ContentFile
from django.db import connection
from django.test.utils import CaptureQueriesContext

from arches.app.models.models import File, IIIFManifest, ResourceInstance, TileModel

from manuspectrum.iiif import facts
from manuspectrum.iiif.zones import annotation_features
from tests.explorer_fixtures import (
    CANVAS,
    FEATURES,
    MANIFEST,
    POINT,
    SOURCE_MANIFEST,
    IIIFCase,
)


def fresh(user):
    """*user* read again: Arches memoises its readable nodegroups on the profile instance."""
    return User.objects.get(pk=user.pk)


class FactsCase(IIIFCase):
    def facts(self, resource=None, reader=None):
        return facts.document_facts(
            str((resource or self.documents["open"]).pk),
            fresh(reader or self.anonymous),
        )

    def analysis(self, doc, key):
        return next(a for a in doc.analyses if a.id == str(self.analyses[key].pk))

    def second_file_tile(self, analysis, name):
        """A second file-list tile of *analysis* holding one stored file; returns its file id."""
        node = self.nodes[("analysis", "measurement_point_data")]
        tile = TileModel.objects.create(
            resourceinstance=analysis, nodegroup_id=node.nodegroup_id, data={}
        )
        row = File(fileid=uuid.uuid4(), tile=tile)
        row.path.save(name, ContentFile(b"x"), save=False)
        File.objects.bulk_create([row])
        entry = {"file_id": str(row.fileid), "name": name, "type": "text/csv"}
        TileModel.objects.filter(pk=tile.pk).update(data={str(node.nodeid): [entry]})
        return str(row.fileid)


class FileFactTests(FactsCase):
    def test_every_file_of_every_file_list_tile_is_a_fact(self):
        first = self.stored_file(self.analyses["open"], "a.csv", b"x,y\n1,2\n")
        second = self.stored_file(self.analyses["open"], "b.mca", b"\x00")
        third = self.second_file_tile(self.analyses["open"], "c.csv")

        files = self.analysis(self.facts(), "open").files

        self.assertEqual({f.id for f in files}, {first, second, third})
        by_id = {f.id: f for f in files}
        self.assertEqual(by_id[second].media_type, "application/octet-stream")
        self.assertEqual(by_id[first].kind, "measurement")

    def test_micro_imaging_files_are_image_facts(self):
        image = self.stored_file(
            self.analyses["open"],
            "micro.jpg",
            b"\xff",
            node_alias="micro_macro_imaging",
        )

        files = {f.id: f for f in self.analysis(self.facts(), "open").files}

        self.assertEqual(files[image].kind, "micro-imaging")
        self.assertEqual(files[image].media_type, "image/jpeg")

    def test_a_file_whose_row_hangs_from_another_tile_is_no_fact(self):
        foreign = self.stored_file(self.analyses["on_document"], "other.csv", b"x")
        node = self.nodes[("analysis", "measurement_point_data")]
        TileModel.objects.create(
            resourceinstance=self.analyses["open"],
            nodegroup_id=node.nodegroup_id,
            data={str(node.nodeid): [{"file_id": foreign, "name": "other.csv"}]},
        )

        files = self.analysis(self.facts(), "open").files

        self.assertNotIn(foreign, {f.id for f in files})

    def test_an_unreadable_nodegroup_gives_no_fact(self):
        file_id = self.stored_file(self.analyses["open"], "a.csv", b"x")
        self.restrict_nodegroup(
            self.nodes[("analysis", "measurement_point_data")].nodegroup_id, self.editor
        )

        self.assertEqual(self.analysis(self.facts(), "open").files, ())
        granted = self.analysis(self.facts(reader=self.editor), "open")
        self.assertEqual([f.id for f in granted.files], [file_id])

    def test_the_media_type_never_trusts_text_x(self):
        self.assertEqual(
            facts.media_type("s.asd", "text/x-common-lisp"), "application/octet-stream"
        )
        self.assertEqual(
            facts.media_type("s.dat", "text/x-common-lisp"), "application/octet-stream"
        )
        self.assertEqual(facts.media_type("s.txt", ""), "text/plain")
        self.assertEqual(facts.media_type("s.tsv", None), "text/tab-separated-values")
        self.assertEqual(facts.media_type("s.png", "image/png"), "image/png")
        self.assertEqual(facts.media_type("s", ""), "application/octet-stream")


class NameTests(FactsCase):
    def test_names_carry_every_language_of_the_descriptors(self):
        ResourceInstance.objects.filter(pk=self.documents["open"].pk).update(
            descriptors={
                "en": {"name": "Ms 59", "description": ""},
                "fr": {"name": "Ms 59 (fr)"},
                "de": {"name": ""},
            }
        )

        self.assertEqual(self.facts().name, {"en": ["Ms 59"], "fr": ["Ms 59 (fr)"]})

    def test_a_name_without_descriptors_comes_from_its_readable_tile(self):
        self.assertEqual(self.facts().name, {"en": ["Ms 59"]})
        self.restrict_nodegroup(
            self.nodes[("document", "label_of_name")].nodegroup_id, self.editor
        )
        self.assertEqual(self.facts().name, {})


class ZoneTests(FactsCase):
    def test_zones_carry_their_feature_canvas_and_position(self):
        doc = self.facts()
        zones = self.analysis(doc, "on_document").zones

        self.assertEqual(
            [(z.feature, z.position, z.shape["type"]) for z in zones],
            [
                (FEATURES["on_document_1"], 1, "polygon"),
                (FEATURES["on_document_3"], 3, "rect"),
            ],
        )
        self.assertEqual(doc.canvases[0], CANVAS)
        self.assertEqual(doc.canvas_labels, ("f. 1v", "f. 2r", "f. 3r"))

    def test_a_zone_outside_the_manifest_is_unlocated(self):
        TileModel.objects.filter(
            resourceinstance=self.analyses["open"],
            nodegroup_id=self.nodes[
                ("analysis", "literal_location_of_analysis")
            ].nodegroup_id,
        ).delete()
        self.zone(
            self.analyses["open"],
            [(str(uuid.uuid4()), "https://example.org/elsewhere/canvas/9", POINT)],
        )

        fact = self.analysis(self.facts(), "open")

        self.assertEqual(fact.zones, ())

    def test_a_restricted_zone_nodegroup_gives_no_zone(self):
        self.restrict_nodegroup(
            self.nodes[("analysis", "literal_location_of_analysis")].nodegroup_id,
            self.editor,
        )

        self.assertEqual(self.analysis(self.facts(), "open").zones, ())
        self.assertTrue(self.analysis(self.facts(reader=self.editor), "open").zones)

    def test_zones_are_read_off_the_tiles_in_one_query_by_feature_id(self):
        node = self.nodes[("analysis", "literal_location_of_analysis")]
        TileModel.objects.filter(
            resourceinstance=self.analyses["open"], nodegroup_id=node.nodegroup_id
        ).delete()
        ids = sorted(uuid.uuid4() for _ in range(4))
        self.zone(self.analyses["open"], [(str(ids[3]), CANVAS, POINT)])
        self.zone(
            self.analyses["open"],
            [(str(ids[1]), CANVAS, POINT), (str(ids[0]), CANVAS, POINT)],
        )
        self.zone(self.analyses["open"], [(str(ids[2]), CANVAS, POINT)])

        with CaptureQueriesContext(connection) as queries:
            found = list(
                annotation_features(
                    node, [str(self.analyses["open"].pk)], {}, {node.nodegroup_id}
                )
            )

        self.assertEqual([feature for _, feature, _, _ in found], ids)
        self.assertEqual(
            {rid for rid, _, _, _ in found}, {str(self.analyses["open"].pk)}
        )
        self.assertEqual(len(queries), 1)
        self.assertNotIn("vw_annotations", queries[0]["sql"])


class SubjectTests(FactsCase):
    def test_a_component_reads_its_documents_manifest(self):
        doc = self.facts(self.components["open"])

        self.assertEqual(doc.manifest_url, MANIFEST)
        self.assertEqual(len(doc.canvases), 3)
        self.assertEqual(
            {a.id for a in doc.analyses},
            {str(self.analyses[k].pk) for k in ("open", "draft")},
        )

    def test_a_document_gathers_the_analyses_of_its_components(self):
        self.assertEqual(
            {a.id for a in self.facts().analyses},
            {str(self.analyses[k].pk) for k in ("open", "on_document", "draft")},
        )

    def test_the_condition_type_is_resolved_per_read_not_per_analysis(self):
        with mock.patch.object(facts, "role_node", wraps=facts.role_node) as resolve:
            doc = self.facts()

        self.assertGreater(len(doc.analyses), 2)
        resolved = [c.args for c in resolve.call_args_list]
        self.assertEqual(resolved.count(facts.ROLES["statement_type"]), 2)

    def test_an_unknown_or_unreadable_document_has_no_facts(self):
        self.assertIsNone(
            facts.document_facts(str(uuid.uuid4()), fresh(self.anonymous))
        )
        self.assertIsNone(self.facts(self.analyses["open"]))
        self.embargo(self.documents["open"])
        self.assertIsNone(self.facts())

    def test_an_analysis_of_a_hidden_project_is_left_out(self):
        self.hide_project(self.projects["main"])

        self.assertNotIn(
            str(self.analyses["open"].pk), {a.id for a in self.facts().analyses}
        )
        self.assertIs(
            facts.analysis_fact(str(self.analyses["open"].pk), fresh(self.anonymous)),
            facts.REFUSED,
        )

    def test_a_draft_analysis_is_kept_and_marked(self):
        doc = self.facts()

        self.assertTrue(self.analysis(doc, "draft").draft)
        self.assertFalse(self.analysis(doc, "open").draft)

    def test_only_keeps_the_named_analyses(self):
        kept = str(self.analyses["open"].pk)
        doc = facts.document_facts(
            str(self.documents["open"].pk),
            fresh(self.anonymous),
            only=frozenset({kept}),
        )

        self.assertEqual([a.id for a in doc.analyses], [kept])

    def test_local_manifests_are_read_from_the_database(self):
        stored = IIIFManifest.objects.create(
            label="Ms 59", url="", manifest=copy.deepcopy(SOURCE_MANIFEST)
        )
        node = self.nodes[("document", "facsimiles")]
        TileModel.objects.filter(
            resourceinstance=self.documents["open"], nodegroup_id=node.nodegroup_id
        ).update(data={str(node.nodeid): f"/manifest/{stored.globalid}"})

        doc = self.facts()

        self.fetch.assert_not_called()
        self.assertEqual(len(doc.canvases), 3)
        # Named at the IIIF route, not at Arches' language-prefixed one (#293).
        self.assertEqual(
            doc.manifest_url,
            f"{settings.PUBLIC_SERVER_ADDRESS}iiif/manifest/{stored.globalid}",
        )


XRF = "https://example.org/concepts/xrf"


class AggregateTests(FactsCase):
    def setUp(self):
        super().setUp()
        for key in ("open", "on_document"):
            self.tile(
                self.analyses[key],
                "analysis_technique_used",
                self.reference_value(XRF, "XRF", "FRX"),
            )
        self.tile_values(
            self.analyses["open"],
            "analysis",
            analysis_start_date="2024-03-05",
            analysis_end_date="2024-03-06",
        )
        self.tile_values(
            self.analyses["on_document"],
            "analysis",
            analysis_start_date="2024-02-01",
            analysis_end_date="2024-02-02",
        )

    def aggregate(self, reader=None, *keys):
        keys = keys or ("open", "on_document")
        return facts.analysis_aggregate(
            [str(self.analyses[k].pk) for k in keys], fresh(reader or self.anonymous)
        )

    def test_aggregate_dedupes_techniques_without_uri(self):
        for key in ("open", "on_document"):
            value = self.reference_value("urn:x", "Raman", "Raman")
            value[0]["uri"] = ""
            self.tile(self.analyses[key], "analysis_technique_used", value)

        found = self.aggregate()

        self.assertEqual(
            [c.labels.get("en") for c in found.techniques if c.uri is None],
            [["Raman"]],
        )

    def test_aggregate_distinct_techniques_projects_dates(self):
        found = self.aggregate()

        self.assertEqual(len(found.techniques), 1)
        self.assertEqual(found.techniques[0].uri, XRF)
        self.assertEqual(found.dates, ("2024-02-01", "2024-03-06"))
        self.assertEqual(
            set(found.projects),
            {str(self.projects["main"].pk), str(self.projects["side"].pk)},
        )
        self.assertEqual(
            found.projects[0], str(self.projects["main"].pk), "sorted by name"
        )

    def test_aggregate_follows_reader_nodegroups(self):
        node = self.nodes[("analysis", "analysis_technique_used")]
        self.restrict_nodegroup(node.nodegroup_id, self.editor)

        self.assertEqual(self.aggregate().techniques, ())
        self.assertEqual(len(self.aggregate(self.editor).techniques), 1)

    def test_aggregate_drops_hidden_project(self):
        self.hide_project(self.projects["side"])

        self.assertEqual(
            self.aggregate().projects,
            (str(self.projects["main"].pk),),
        )

    def test_aggregate_metadata_links_concept_uri(self):
        entries = facts.aggregate_metadata(self.aggregate())
        by_label = {e["label"]["en"][0]: e["value"] for e in entries}

        self.assertIn(f'href="{XRF}"', by_label["Techniques"]["en"][0])
        self.assertEqual(by_label["Dates"], {"none": ["2024-02-01 – 2024-03-06"]})
        self.assertEqual(len(by_label["Projects"]["en"]), 2)
        self.assertIn(
            f"/report/{self.projects['main'].pk}", by_label["Projects"]["en"][0]
        )

    def test_aggregate_metadata_leaves_out_empty_entries(self):
        self.assertEqual(
            facts.aggregate_metadata(facts.Aggregate((), (), None, ())), []
        )

    def test_document_facts_found_lists_unlocated_analyses(self):
        doc = facts.document_facts(
            str(self.documents["open"].pk), fresh(self.anonymous), positions=frozenset()
        )

        self.assertEqual(doc.analyses, ())
        self.assertIn(str(self.analyses["open"].pk), doc.found)
        self.assertIn(str(self.analyses["on_document"].pk), doc.found)

    def test_document_facts_source_url(self):
        self.assertEqual(self.facts().source_url, MANIFEST)
