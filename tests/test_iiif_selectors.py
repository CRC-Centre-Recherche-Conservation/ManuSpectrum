"""Selectors and targets of IIIF annotations, v3 (Web Annotation) and v2 (Open Annotation).

Usage:
    python manage.py test tests.test_iiif_selectors --settings=tests.test_settings
"""

import re

from django.test import SimpleTestCase, override_settings

from manuspectrum.iiif import selectors
from tests.iiif_schema import assert_valid_iiif

CANVAS = "https://example.org/iiif/ms59/canvas/f2r"
MANIFEST = "https://example.org/iiif/ms59/manifest"
POINT = {"type": "point", "x": 1520, "y": 2210}
RECT = {"type": "rect", "x": 10, "y": 20, "w": 30, "h": 40}
POLYGON = {"type": "polygon", "points": [[10, 20], [50, 25], [30, 70]]}
CIRCLE = re.compile(
    r'^<svg xmlns="http://www.w3.org/2000/svg"><path d="'
    r"M (\d+) (\d+) A (\d+) (\d+) 0 1 1 (\d+) (\d+) A (\d+) (\d+) 0 1 1 (\d+) (\d+)"
    r'"/></svg>$'
)


@override_settings(IIIF_POINT_RADIUS=12)
class SelectorTests(SimpleTestCase):
    def test_a_point_is_a_point_selector_and_a_circle_path(self):
        point, svg = selectors.selectors(POINT)

        self.assertEqual(point, {"type": "PointSelector", "x": 1520, "y": 2210})
        self.assertEqual(svg["type"], "SvgSelector")
        numbers = [int(n) for n in CIRCLE.match(svg["value"]).groups()]
        self.assertEqual(numbers, [1520, 2198, 12, 12, 1520, 2222, 12, 12, 1520, 2198])

    def test_the_circle_path_is_the_viewer_form(self):
        self.assertEqual(
            selectors.circle_path(5, 30, 12),
            "M 5 18 A 12 12 0 1 1 5 42 A 12 12 0 1 1 5 18",
        )

    def test_a_rectangle_is_one_xywh_fragment(self):
        self.assertEqual(
            selectors.selectors(RECT),
            {
                "type": "FragmentSelector",
                "conformsTo": "http://www.w3.org/TR/media-frags/",
                "value": "xywh=10,20,30,40",
            },
        )

    def test_a_polygon_is_an_svg_polygon_and_its_bounding_box(self):
        svg, box = selectors.selectors(POLYGON)

        self.assertEqual(
            svg["value"],
            '<svg xmlns="http://www.w3.org/2000/svg">'
            '<polygon points="10,20 50,25 30,70"/></svg>',
        )
        self.assertEqual(box["type"], "FragmentSelector")
        self.assertEqual(box["value"], "xywh=10,20,40,50")

    def test_no_shape_targets_the_canvas(self):
        self.assertEqual(selectors.target(CANVAS, MANIFEST, None), CANVAS)
        self.assertEqual(selectors.v2_on(CANVAS, MANIFEST, None), CANVAS)

    def test_the_target_names_its_canvas_within_its_manifest(self):
        target = selectors.target(CANVAS, MANIFEST, RECT)

        self.assertEqual(target["type"], "SpecificResource")
        self.assertEqual(
            target["source"],
            {
                "id": CANVAS,
                "type": "Canvas",
                "partOf": [{"id": MANIFEST, "type": "Manifest"}],
            },
        )

    def test_a_target_without_manifest_has_no_part_of(self):
        target = selectors.target(CANVAS, None, RECT)

        self.assertEqual(target["source"], {"id": CANVAS, "type": "Canvas"})

    def test_the_v2_rectangle_is_a_fragment_of_the_canvas(self):
        self.assertEqual(
            selectors.v2_on(CANVAS, MANIFEST, RECT), f"{CANVAS}#xywh=10,20,30,40"
        )

    def test_the_v2_point_is_a_choice_of_box_and_svg(self):
        on = selectors.v2_on(CANVAS, MANIFEST, POINT)

        self.assertEqual(on["@type"], "oa:SpecificResource")
        self.assertEqual(on["full"], CANVAS)
        self.assertEqual(on["within"], {"@id": MANIFEST, "@type": "sc:Manifest"})
        choice = on["selector"]
        self.assertEqual(choice["@type"], "oa:Choice")
        self.assertEqual(
            choice["default"],
            {"@type": "oa:FragmentSelector", "value": "xywh=1508,2198,24,24"},
        )
        self.assertEqual(choice["item"]["@type"], "oa:SvgSelector")
        self.assertRegex(choice["item"]["value"], CIRCLE)

    def test_the_v2_polygon_defaults_to_its_bounding_box(self):
        choice = selectors.v2_on(CANVAS, MANIFEST, POLYGON)["selector"]

        self.assertEqual(choice["default"]["value"], "xywh=10,20,40,50")
        self.assertIn("<polygon", choice["item"]["value"])

    def test_every_selector_document_validates(self):
        for shape in (POINT, RECT, POLYGON, None):
            with self.subTest(shape=shape):
                assert_valid_iiif(
                    self,
                    {
                        "@context": "http://iiif.io/api/presentation/3/context.json",
                        "id": "https://ms.example/iiif/v3/annotation/a/b",
                        "type": "Annotation",
                        "motivation": "supplementing",
                        "target": selectors.target(CANVAS, MANIFEST, shape),
                    },
                )
