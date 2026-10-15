"""``GET /api/iiif-annotation-counts``: the counts under the IIIF viewer thumbnails.

Usage:
    python manage.py test tests.test_iiif_annotation_counts --settings=tests.test_settings
"""

import uuid

from django.db import connection
from django.test import Client
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

from tests.explorer_fixtures import CANVAS, CANVAS_2, CANVAS_3, IIIFCase

URL = "/api/iiif-annotation-counts"


class AnnotationCountsCase(IIIFCase):
    def setUp(self):
        super().setUp()
        self.visitor = Client()
        self.reader = Client()
        self.reader.force_login(self.editor)
        self.node = self.nodes[("analysis", "literal_location_of_analysis")]

    def counts(self, client=None, node=None):
        node = node or self.node
        return (client or self.visitor).get(URL, {"nodeid": str(node.pk)})

    def core_features(self, canvas, client=None):
        response = (client or self.visitor).get(
            reverse("iiifannotations"), {"canvas": canvas, "nodeid": str(self.node.pk)}
        )
        return len(response.json()["features"])


class CountsTests(AnnotationCountsCase):
    def test_counts_equal_the_core_route_per_canvas(self):
        response = self.counts()

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body, {CANVAS: 3, CANVAS_3: 1})
        for canvas in (CANVAS, CANVAS_2, CANVAS_3):
            with self.subTest(canvas=canvas):
                self.assertEqual(body.get(canvas, 0), self.core_features(canvas))

    def test_a_canvas_without_feature_is_absent(self):
        self.assertNotIn(CANVAS_2, self.counts().json())

    def test_the_answer_is_not_stored_nor_shared(self):
        response = self.counts()

        self.assertEqual(
            set(response["Cache-Control"].split(", ")), {"private", "no-store"}
        )

    def test_a_count_costs_one_query_for_the_features(self):
        with CaptureQueriesContext(connection) as queries:
            self.counts()

        features = [q for q in queries if "jsonb_array_elements" in q["sql"]]
        self.assertEqual(len(features), 1)


class BadNodeTests(AnnotationCountsCase):
    def test_a_missing_or_malformed_node_id_is_a_bare_400(self):
        for params in ({}, {"nodeid": "nope"}):
            with self.subTest(params=params):
                response = self.visitor.get(URL, params)
                self.assertEqual(response.status_code, 400)
                self.assertEqual(response.content, b"")

    def test_an_unknown_node_is_a_bare_404(self):
        response = self.visitor.get(URL, {"nodeid": str(uuid.uuid4())})

        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.content, b"")

    def test_a_node_that_is_not_an_annotation_node_is_a_bare_404(self):
        other = self.nodes[("analysis", "measurement_point_data")]

        response = self.counts(node=other)

        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.content, b"")

    def test_post_is_refused(self):
        self.assertEqual(
            self.visitor.post(URL, {"nodeid": str(self.node.pk)}).status_code, 405
        )


class PermissionTests(AnnotationCountsCase):
    def test_a_restricted_nodegroup_is_not_counted_for_the_visitor(self):
        self.restrict_nodegroup(self.node.nodegroup_id, self.editor)

        refused = self.counts()
        granted = self.counts(self.reader)

        self.assertEqual(refused.status_code, 404)
        self.assertEqual(refused.content, b"")
        self.assertEqual(granted.json(), {CANVAS: 3, CANVAS_3: 1})

    def test_a_restricted_resource_is_not_counted_for_the_visitor(self):
        self.embargo(self.analyses["open"])

        visitor = self.counts().json()
        granted = self.counts(self.reader).json()

        self.assertEqual(visitor, {CANVAS: 2, CANVAS_3: 1})
        self.assertEqual(granted, {CANVAS: 3, CANVAS_3: 1})

    def test_the_count_is_stricter_than_the_core_list_for_a_restricted_resource(self):
        self.embargo(self.analyses["open"])

        self.assertEqual(self.core_features(CANVAS), 3)
        self.assertEqual(self.counts().json()[CANVAS], 2)

    def test_a_visitor_after_a_granted_reader_still_sees_the_restricted_count(self):
        self.embargo(self.analyses["open"])

        self.counts(self.reader)

        self.assertEqual(self.counts().json(), {CANVAS: 2, CANVAS_3: 1})
