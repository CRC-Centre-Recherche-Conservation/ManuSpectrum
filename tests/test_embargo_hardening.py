"""An embargoed resource stays out of every project surface, on real rows and real grants.

The embargo is Arches' own ``no_access_to_resourceinstance`` on the
``anonymous`` user, written through ``assign_perm``. Each surface is asked by
the anonymous visitor, who must not see the embargoed resource, and by an
editor, who still must; the readable resource answers as before. Documents,
Components and Analyses carry the real graph slugs, and the Document the graph
id the sitemap reads.

Usage:
    python manage.py test tests.test_embargo_hardening --settings="tests.test_settings"
"""

import uuid
from unittest import mock

from django.contrib.auth.models import Group, User
from django.core.cache import cache, caches
from django.test import TestCase

from arches.app.models.models import (
    GraphModel,
    GraphXPublishedGraph,
    Node,
    NodeGroup,
    ResourceInstance,
    TileModel,
)
from arches.app.utils.permission_backend import assign_perm

DEFAULT_LIFECYCLE_ID = "7e3cce56-fbfb-4a4b-8e83-59b9f9e7cb75"

DOCUMENT_GRAPH_ID = "0c8226c1-11a9-4c48-9601-a7a0c6f2df6b"
COMPONENT_GRAPH_ID = "d47595b4-f8a6-419c-8f33-b388206280c4"
ANALYSIS_GRAPH_ID = "60c85aba-f079-45bc-997f-21cdd4f77b6d"

NG_DOCUMENT = "5a1d0c0e-1111-4a11-8a11-000000000001"
NG_PART_OF = "5a1d0c0e-1111-4a11-8a11-000000000002"
NG_OBSERVED = "5a1d0c0e-1111-4a11-8a11-000000000003"
NG_ANNOTATION = "5a1d0c0e-1111-4a11-8a11-000000000006"

NODE_DOCUMENT = "6b2e1d1f-2222-4b22-9b22-000000000001"
NODE_PART_OF = "6b2e1d1f-2222-4b22-9b22-000000000002"
NODE_OBSERVED = "6b2e1d1f-2222-4b22-9b22-000000000003"
NODE_ANNOTATION = "6b2e1d1f-2222-4b22-9b22-000000000006"

CANVAS = "https://example.org/iiif/canvas-1"


def reference(resource):
    return [{"resourceId": str(resource.pk), "ontologyProperty": ""}]


class EmbargoCase(TestCase):
    """Two Documents, a Component and an Analysis on each, one side embargoed."""

    @classmethod
    def setUpTestData(cls):
        graphs = {}
        for graph_id, slug in (
            (DOCUMENT_GRAPH_ID, "document"),
            (COMPONENT_GRAPH_ID, "component"),
            (ANALYSIS_GRAPH_ID, "analysis"),
        ):
            graphs[slug] = GraphModel.objects.create(
                graphid=graph_id,
                name=slug,
                isresource=True,
                is_active=True,
                slug=slug,
                resource_instance_lifecycle_id=DEFAULT_LIFECYCLE_ID,
            )
        for node_id, nodegroup_id, slug, alias, datatype in (
            (NODE_DOCUMENT, NG_DOCUMENT, "document", "label_of_name", "string"),
            (
                NODE_PART_OF,
                NG_PART_OF,
                "component",
                "item_visual_is_part_of_document",
                "resource-instance",
            ),
            (
                NODE_OBSERVED,
                NG_OBSERVED,
                "analysis",
                "component_observed",
                "resource-instance-list",
            ),
            (NODE_ANNOTATION, NG_ANNOTATION, "analysis", "location", "annotation"),
        ):
            NodeGroup.objects.create(nodegroupid=nodegroup_id, cardinality="n")
            Node.objects.create(
                nodeid=node_id,
                graph=graphs[slug],
                nodegroup_id=nodegroup_id,
                name=alias,
                alias=alias,
                datatype=datatype,
                istopnode=False,
            )
        cls.anonymous = User.objects.get(username="anonymous")
        cls.editor = User.objects.create_user("embargo_editor", password="pw")
        cls.editor.groups.add(Group.objects.get(name="Resource Editor"))

        cls.documents = {}
        for side in ("open", "embargoed"):
            document = ResourceInstance.objects.create(graph=graphs["document"])
            component = ResourceInstance.objects.create(graph=graphs["component"])
            analysis = ResourceInstance.objects.create(graph=graphs["analysis"])
            TileModel.objects.create(
                resourceinstance=component,
                nodegroup_id=NG_PART_OF,
                data={NODE_PART_OF: reference(document)},
            )
            TileModel.objects.create(
                resourceinstance=analysis,
                nodegroup_id=NG_OBSERVED,
                data={NODE_OBSERVED: reference(component)},
            )
            TileModel.objects.create(
                resourceinstance=analysis,
                nodegroup_id=NG_ANNOTATION,
                data={
                    NODE_ANNOTATION: {
                        "type": "FeatureCollection",
                        "features": [
                            {
                                "id": str(uuid.uuid4()),
                                "type": "Feature",
                                "geometry": {"type": "Point", "coordinates": [1, 2]},
                                "properties": {"canvas": CANVAS},
                            }
                        ],
                    }
                },
            )
            cls.documents[side] = {
                "document": document,
                "component": component,
                "analysis": analysis,
            }

    def setUp(self):
        cache.clear()
        caches["user_permission"].clear()
        self.addCleanup(cache.clear)
        self.addCleanup(caches["user_permission"].clear)

    def open(self, kind):
        return self.documents["open"][kind]

    def embargoed(self, kind):
        return self.documents["embargoed"][kind]

    def embargo(self, *kinds):
        with self.captureOnCommitCallbacks(execute=True):
            for kind in kinds:
                assign_perm(
                    "no_access_to_resourceinstance",
                    self.anonymous,
                    self.embargoed(kind),
                )

    def as_editor(self):
        self.client.force_login(self.editor)


class ThumbnailTests(EmbargoCase):
    def fetch(self, side):
        fetcher = mock.MagicMock()
        fetcher.get_thumbnail.return_value = (b"\xff\xd8\xffJPEG", "image/jpeg")
        with mock.patch(
            "manuspectrum.views.thumbnail.CachedThumbnailView.get_thumbnail_fetcher",
            return_value=fetcher,
        ):
            response = self.client.get(
                f"/en/thumbnail/{self.documents[side]['document'].pk}"
            )
        return response, fetcher

    def test_an_embargoed_resource_has_no_thumbnail_and_reaches_no_fetcher(self):
        self.embargo("document")

        response, fetcher = self.fetch("embargoed")

        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.content, b"")
        fetcher.get_thumbnail.assert_not_called()

    def test_the_editor_and_the_open_resource_keep_their_thumbnail(self):
        self.embargo("document")
        visitor, _ = self.fetch("open")
        self.as_editor()
        editor, _ = self.fetch("embargoed")

        self.assertEqual(visitor.status_code, 200)
        self.assertEqual(editor.status_code, 200)


class SitemapTests(EmbargoCase):
    def test_an_embargoed_document_leaves_the_sitemap(self):
        self.embargo("document")

        xml = self.client.get("/sitemap.xml").content.decode()

        self.assertIn(str(self.open("document").pk), xml)
        self.assertNotIn(str(self.embargoed("document").pk), xml)


class ModelGraphCountTests(EmbargoCase):
    def setUp(self):
        super().setUp()
        graph = GraphModel.objects.get(pk=ANALYSIS_GRAPH_ID)
        graph.publication = GraphXPublishedGraph.objects.create(graph=graph)
        graph.save()

    def analysis_count(self):
        """Records of the one published model, the Analysis, draft or not."""
        from manuspectrum.views.model_graph_service import build_model_graph

        payload = build_model_graph("en")
        return payload["stats"]["records"] + payload["stats"]["records_draft"]

    def test_an_embargoed_analysis_is_not_counted_and_moves_the_fingerprint(self):
        from manuspectrum.views.model_graph import graph_fingerprint

        before, fingerprint = self.analysis_count(), graph_fingerprint()

        self.embargo("analysis")

        self.assertEqual(self.analysis_count(), before - 1)
        self.assertNotEqual(graph_fingerprint(), fingerprint)


class CollectionTests(EmbargoCase):
    """The project IIIF collection of a Document, read off the tiles."""

    def readable(self, user, side="open"):
        from manuspectrum.views.iiif_annotation import IIIFAnnotationCollectionView

        analyses, public = IIIFAnnotationCollectionView()._readable_analyses(
            user, self.documents[side]["document"]
        )
        return {str(a.pk) for a in analyses}, public

    def test_without_embargo_the_collection_is_public(self):
        self.assertEqual(
            self.readable(self.anonymous), ({str(self.open("analysis").pk)}, True)
        )

    def test_an_analysis_of_an_embargoed_component_is_hidden_with_it(self):
        self.embargo("component")

        self.assertEqual(self.readable(self.anonymous, "embargoed"), (set(), False))
        self.assertEqual(
            self.readable(self.editor, "embargoed"),
            ({str(self.embargoed("analysis").pk)}, False),
        )
        self.assertEqual(
            self.readable(self.anonymous), ({str(self.open("analysis").pk)}, True)
        )

    def test_an_embargoed_analysis_makes_its_collection_private(self):
        self.embargo("analysis")

        self.assertEqual(self.readable(self.anonymous, "embargoed"), (set(), False))

    def test_an_unreadable_resource_answers_like_an_unknown_one(self):
        self.embargo("document")

        refused = self.client.get(
            f"/iiif/v3/annotation-collection/{self.embargoed('document').pk}"
        )
        unknown = self.client.get(f"/iiif/v3/annotation-collection/{uuid.uuid4()}")

        self.assertEqual(refused.status_code, 404)
        self.assertEqual(refused.content, unknown.content)
        self.assertEqual(refused["Cache-Control"], unknown["Cache-Control"])


class VisibilityMemoTests(EmbargoCase):
    def test_hidden_ids_follow_a_grant_on_commit(self):
        from manuspectrum.utils.public_visibility import hidden_resource_ids

        self.assertEqual(hidden_resource_ids(self.anonymous), frozenset())

        self.embargo("analysis")

        self.assertEqual(
            hidden_resource_ids(self.anonymous),
            {str(self.embargoed("analysis").pk)},
        )
        self.assertEqual(hidden_resource_ids(self.editor), frozenset())

    def test_a_grant_set_without_view_hides_the_resource(self):
        from manuspectrum.utils.public_visibility import hidden_resource_ids

        with self.captureOnCommitCallbacks(execute=True):
            assign_perm(
                "change_resourceinstance",
                Group.objects.get(name="Guest"),
                self.embargoed("analysis"),
            )

        self.assertIn(
            str(self.embargoed("analysis").pk), hidden_resource_ids(self.anonymous)
        )

    def test_a_group_membership_change_drops_the_memo(self):
        from manuspectrum.utils.public_visibility import hidden_resource_ids

        group = Group.objects.create(name="Embargo probe")
        with self.captureOnCommitCallbacks(execute=True):
            assign_perm(
                "no_access_to_resourceinstance", group, self.embargoed("analysis")
            )
        self.assertEqual(hidden_resource_ids(self.editor), frozenset())

        with self.captureOnCommitCallbacks(execute=True):
            self.editor.groups.add(group)

        self.assertEqual(
            hidden_resource_ids(self.editor), {str(self.embargoed("analysis").pk)}
        )

    def test_a_nodegroup_grant_drops_the_readable_nodegroups(self):
        from manuspectrum.utils.public_visibility import readable_nodegroup_ids

        self.assertIn(NG_ANNOTATION, readable_nodegroup_ids(self.editor))

        with self.captureOnCommitCallbacks(execute=True):
            assign_perm(
                "no_access_to_nodegroup",
                self.editor,
                NodeGroup.objects.get(pk=NG_ANNOTATION),
            )

        reread = User.objects.get(pk=self.editor.pk)
        self.assertNotIn(NG_ANNOTATION, readable_nodegroup_ids(reread))


class PermScopeTests(EmbargoCase):
    def test_a_grant_set_without_view_keys_the_scope_on_the_reader(self):
        from manuspectrum.views.summary_service import perm_scope

        self.assertEqual(perm_scope(self.anonymous), "public")

        with self.captureOnCommitCallbacks(execute=True):
            assign_perm(
                "change_resourceinstance",
                Group.objects.get(name="Guest"),
                self.embargoed("analysis"),
            )

        self.assertEqual(perm_scope(self.anonymous), str(self.anonymous.pk))
