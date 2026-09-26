"""Building blocks of the Explorer's IIIF v3 manifest: selectors, targets, canvases, data annotations.

Usage:
    python manage.py test tests.test_explorer_manifest_parts --settings="tests.test_settings"
"""

import copy

from django.conf import settings
from django.test import SimpleTestCase, override_settings
from lxml import etree

from manuspectrum.views.explorer.manifest import (
    PRESENTATION_3,
    data_annotation,
    layer_canvas,
    mint,
    selector,
    target,
    v3_canvas,
)
from tests.iiif_schema import assert_valid_manifest

SOURCE_V3 = "https://example.org/iiif/ms59/manifest"
CANVAS_V3 = "https://example.org/iiif/ms59/canvas/f1v"
SOURCE_V2 = "https://example.org/iiif/ms60/manifest.json"
CANVAS_V2 = "https://example.org/iiif/ms60/canvas/p1"
SERVICE_V2 = "https://example.org/iiif/image/ms60-p1"
IMAGING = "https://example.org/iiif/maxrf/manifest"
LAYER = "https://example.org/iiif/maxrf/canvas/pb"
DIGEST = "0123456789ab"

CANVAS_3 = {
    "id": CANVAS_V3,
    "type": "Canvas",
    "label": {"none": ["f. 1v"]},
    "width": 4000,
    "height": 5000,
    "rights": "http://creativecommons.org/licenses/by/4.0/",
    "requiredStatement": {
        "label": {"en": ["Attribution"]},
        "value": {"en": ["Bibliothèque municipale d'Avranches"]},
    },
    "items": [
        {
            "id": f"{CANVAS_V3}/page",
            "type": "AnnotationPage",
            "items": [
                {
                    "id": f"{CANVAS_V3}/page/image",
                    "type": "Annotation",
                    "motivation": "painting",
                    "target": CANVAS_V3,
                    "body": {
                        "id": "https://example.org/iiif/image/f1v/full/max/0/default.jpg",
                        "type": "Image",
                        "format": "image/jpeg",
                        "service": [
                            {
                                "id": "https://example.org/iiif/image/f1v",
                                "type": "ImageService3",
                                "profile": "level1",
                            }
                        ],
                    },
                }
            ],
        }
    ],
    "annotations": [
        {"id": f"{CANVAS_V3}/comments", "type": "AnnotationPage", "items": []}
    ],
}
MANIFEST_3 = {
    "@context": PRESENTATION_3,
    "id": SOURCE_V3,
    "type": "Manifest",
    "label": {"none": ["Ms 59"]},
    "items": [CANVAS_3],
}

CANVAS_2 = {
    "@id": CANVAS_V2,
    "@type": "sc:Canvas",
    "label": "p. 1",
    "width": 2000,
    "height": 3000,
    "images": [
        {
            "@type": "oa:Annotation",
            "motivation": "sc:painting",
            "on": CANVAS_V2,
            "resource": {
                "@id": f"{SERVICE_V2}/full/full/0/default.jpg",
                "@type": "dctypes:Image",
                "format": "image/jpeg",
                "width": 2000,
                "height": 3000,
                "service": {
                    "@context": "http://iiif.io/api/image/2/context.json",
                    "@id": SERVICE_V2,
                    "profile": "http://iiif.io/api/image/2/level2.json",
                },
            },
        }
    ],
}
MANIFEST_2 = {
    "@context": "http://iiif.io/api/presentation/2/context.json",
    "@id": SOURCE_V2,
    "@type": "sc:Manifest",
    "label": "Ms 60",
    "license": "https://creativecommons.org/publicdomain/mark/1.0/",
    "attribution": "Bibliothèque nationale de France",
    "sequences": [{"@type": "sc:Sequence", "canvases": [CANVAS_2]}],
}

LICENCE_BY = {
    "id": "CC-BY-4.0",
    "url": "https://creativecommons.org/licenses/by/4.0/",
    "label": {"value": "CC BY 4.0", "lang": "en"},
    "attribution": "CRC",
    "noDerivatives": False,
    "inRightsRegistry": True,
    "isDefault": False,
}
LICENCE_CUSTOM = {
    "id": "custom",
    "url": "https://example.org/terms",
    "label": {"value": "Terms of the lab", "lang": "en"},
    "attribution": "Lab",
    "noDerivatives": False,
    "inRightsRegistry": False,
    "isDefault": False,
}


def file_entry(**overrides):
    entry = {
        "id": "11111111-1111-4111-8111-111111111111",
        "name": "X01_f1v.csv",
        "size": 4200,
        "format": "text/csv",
        "role": "readable",
        "pairedWith": None,
        "dataKind": "xy",
        "layers": [],
        "license": LICENCE_BY,
        "downloadUrl": "/files/11111111-1111-4111-8111-111111111111",
        "previewUrl": None,
        "zone": None,
    }
    entry.update(overrides)
    return entry


ANALYSIS = {
    "id": "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
    "name": "X01 — f. 1v",
    "permalink": "https://manuspectrum.example/report/aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
    "technique": "Portable XRF",
    "dates": "2024-05-14",
    "operators": ["Robinet, L."],
    "conditions": ["260 µm / 100 ms"],
    "document": "Ms 59",
    "component": "f. 1v — initial",
    "dataset": {
        "url": "https://doi.org/10.48579/PRO/ZEEJTH",
        "isDoi": True,
        "label": "HEU, S. 2024",
    },
}


def mint_id(*parts):
    return mint(DIGEST, *parts)


def wrapped(canvases, annotations=()):
    """A minimal manifest holding *canvases*, the first one carrying *annotations*."""
    canvases = copy.deepcopy(list(canvases))
    if annotations:
        canvases[0]["annotations"] = [
            {
                "id": mint_id("page", "test"),
                "type": "AnnotationPage",
                "items": list(annotations),
            }
        ]
    return {
        "@context": PRESENTATION_3,
        "id": mint_id(),
        "type": "Manifest",
        "label": {"en": ["test"]},
        "items": canvases,
    }


@override_settings(PUBLIC_SERVER_ADDRESS="https://manuspectrum.example/")
class ManifestPartsTests(SimpleTestCase):
    def annotation(self, shape, files=None):
        return data_annotation(
            mint_id("annotation", "1"),
            ANALYSIS,
            [file_entry()] if files is None else files,
            target(CANVAS_V3, SOURCE_V3, shape),
            "en",
        )

    def assert_valid(self, canvases, annotations=()):
        assert_valid_manifest(self, wrapped(canvases, annotations))

    def canvas_3(self):
        return v3_canvas(CANVAS_3, MANIFEST_3, SOURCE_V3, mint_id)

    def canvas_2(self):
        return v3_canvas(CANVAS_2, MANIFEST_2, SOURCE_V2, mint_id)

    def test_a_point_targets_a_point_selector(self):
        annotation = self.annotation({"type": "point", "x": 120, "y": 340})

        self.assertEqual(
            annotation["target"]["selector"],
            {"type": "PointSelector", "x": 120, "y": 340},
        )
        self.assertEqual(annotation["target"]["source"]["id"], CANVAS_V3)
        self.assert_valid([self.canvas_3()], [annotation])

    def test_a_rect_targets_an_xywh_fragment(self):
        annotation = self.annotation(
            {"type": "rect", "x": 10, "y": 20, "w": 300, "h": 400}
        )

        self.assertEqual(
            annotation["target"]["selector"],
            {
                "type": "FragmentSelector",
                "conformsTo": "http://www.w3.org/TR/media-frags/",
                "value": "xywh=10,20,300,400",
            },
        )
        self.assert_valid([self.canvas_3()], [annotation])

    def test_a_polygon_targets_an_svg_selector(self):
        points = [[10, 20], [300, 25], [150, 400]]
        annotation = self.annotation({"type": "polygon", "points": points})

        found = annotation["target"]["selector"]
        self.assertEqual(found["type"], "SvgSelector")
        svg = etree.fromstring(found["value"].encode())
        self.assertEqual(svg.tag, "{http://www.w3.org/2000/svg}svg")
        polygon = svg.find("{http://www.w3.org/2000/svg}polygon")
        self.assertEqual(
            [
                [int(n) for n in pair.split(",")]
                for pair in polygon.get("points").split()
            ],
            points,
        )
        self.assert_valid([self.canvas_3()], [annotation])

    def test_no_shape_targets_the_canvas(self):
        self.assertEqual(target(CANVAS_V3, SOURCE_V3, None), CANVAS_V3)

    def test_a_v2_canvas_becomes_a_v3_canvas_with_an_image_service_2(self):
        canvas = self.canvas_2()

        self.assertEqual(canvas["id"], CANVAS_V2)
        self.assertEqual(canvas["type"], "Canvas")
        self.assertEqual(canvas["label"], {"none": ["p. 1"]})
        self.assertEqual((canvas["width"], canvas["height"]), (2000, 3000))
        painting = canvas["items"][0]["items"][0]
        self.assertEqual(painting["motivation"], "painting")
        self.assertEqual(painting["target"], CANVAS_V2)
        self.assertEqual(painting["body"]["type"], "Image")
        self.assertEqual(
            painting["body"]["service"],
            [{"id": SERVICE_V2, "type": "ImageService2", "profile": "level2"}],
        )
        self.assert_valid([canvas])

    def test_a_v3_canvas_keeps_its_id_items_and_rights(self):
        canvas = self.canvas_3()

        self.assertEqual(canvas["id"], CANVAS_V3)
        self.assertEqual(canvas["items"], CANVAS_3["items"])
        self.assertEqual(canvas["rights"], CANVAS_3["rights"])
        self.assertEqual(canvas["requiredStatement"], CANVAS_3["requiredStatement"])
        self.assertNotIn("annotations", canvas)
        self.assert_valid([canvas])

    @override_settings(EXPLORER_LEGACY_HOSTS=["old.example.org"])
    def test_a_legacy_host_is_rewritten_in_every_id(self):
        legacy = copy.deepcopy(CANVAS_3)
        legacy["items"][0]["items"][0]["body"]["service"][0][
            "id"
        ] = "https://old.example.org/iiif/image/f1v"

        canvas = v3_canvas(legacy, MANIFEST_3, SOURCE_V3, mint_id)

        self.assertEqual(
            canvas["items"][0]["items"][0]["body"]["service"][0]["id"],
            "https://manuspectrum.example/iiif/image/f1v",
        )

    def test_a_v2_licence_in_a_registry_becomes_canvas_rights_in_http(self):
        canvas = self.canvas_2()

        self.assertEqual(
            canvas["rights"], "http://creativecommons.org/publicdomain/mark/1.0/"
        )
        self.assertEqual(
            canvas["requiredStatement"]["value"],
            {"none": ["Bibliothèque nationale de France"]},
        )
        self.assert_valid([canvas])

    def test_a_licence_outside_the_registries_gives_the_canvas_no_rights(self):
        manifest = dict(MANIFEST_2, license="https://example.org/terms")

        canvas = v3_canvas(CANVAS_2, manifest, SOURCE_V2, mint_id)

        self.assertNotIn("rights", canvas)
        self.assert_valid([canvas])

    def test_every_canvas_is_part_of_its_source_manifest(self):
        for canvas, source in (
            (self.canvas_3(), SOURCE_V3),
            (self.canvas_2(), SOURCE_V2),
        ):
            with self.subTest(source=source):
                self.assertEqual(canvas["partOf"], [{"id": source, "type": "Manifest"}])

    def test_a_dataset_body_has_http_rights_only_for_a_registry_licence(self):
        annotation = self.annotation(
            {"type": "point", "x": 1, "y": 2},
            files=[file_entry(), file_entry(license=LICENCE_CUSTOM, format="csv")],
        )

        by_registry, custom = annotation["body"]
        self.assertEqual(annotation["motivation"], "supplementing")
        self.assertEqual(by_registry["type"], "Dataset")
        self.assertEqual(
            by_registry["id"],
            "https://manuspectrum.example/files/11111111-1111-4111-8111-111111111111",
        )
        self.assertEqual(by_registry["format"], "text/csv")
        self.assertEqual(by_registry["label"], {"en": ["X01_f1v.csv"]})
        self.assertEqual(
            by_registry["rights"], "http://creativecommons.org/licenses/by/4.0/"
        )
        self.assertNotIn("rights", custom)
        self.assertEqual(custom["format"], "application/octet-stream")
        self.assert_valid([self.canvas_3()], [annotation])

    def test_a_licence_outside_the_registries_gives_a_required_statement(self):
        annotation = self.annotation(
            {"type": "point", "x": 1, "y": 2},
            files=[file_entry(license=LICENCE_CUSTOM)],
        )

        body = annotation["body"][0]
        self.assertEqual(
            body["requiredStatement"],
            {"label": {"en": ["Licence"]}, "value": {"en": ["Terms of the lab — Lab"]}},
        )
        self.assert_valid([self.canvas_3()], [annotation])

    def test_an_imaging_entry_is_a_manifest_body(self):
        imaging = file_entry(
            id="a:imaging:0",
            name="maXRF",
            format="application/ld+json",
            dataKind="chemical-imaging",
            downloadUrl=IMAGING,
        )

        annotation = self.annotation(None, files=[imaging])

        self.assertEqual(annotation["body"], [{"id": IMAGING, "type": "Manifest"}])
        self.assert_valid([self.canvas_3()], [annotation])

    def test_the_annotation_names_its_analysis_and_links_its_report_and_dataset(self):
        annotation = self.annotation({"type": "point", "x": 1, "y": 2})

        self.assertEqual(annotation["label"], {"en": ["X01 — f. 1v"]})
        self.assertEqual(
            annotation["seeAlso"],
            [
                {
                    "id": ANALYSIS["permalink"],
                    "type": "Text",
                    "format": "text/html",
                    "label": {"en": ["X01 — f. 1v"]},
                },
                {
                    "id": "https://doi.org/10.48579/PRO/ZEEJTH",
                    "type": "Dataset",
                    "format": "text/html",
                    "label": {"en": ["HEU, S. 2024"]},
                },
            ],
        )
        values = {
            entry["label"]["en"][0]: entry["value"]["en"]
            for entry in annotation["metadata"]
        }
        self.assertEqual(values["Technique"], ["Portable XRF"])
        self.assertEqual(values["Operators"], ["Robinet, L."])
        self.assertEqual(values["Conditions"], ["260 µm / 100 ms"])
        self.assertEqual(values["Document"], ["Ms 59"])

    def test_a_layer_canvas_keeps_its_source_id_and_takes_the_folio_label(self):
        layer = dict(CANVAS_3, id=LAYER, label={"none": ["Pb"]})
        imaging = dict(MANIFEST_3, id=IMAGING, items=[layer])

        canvas = layer_canvas(layer, imaging, IMAGING, {"en": ["f. 1v — Pb"]}, mint_id)

        self.assertEqual(canvas["id"], LAYER)
        self.assertEqual(canvas["label"], {"en": ["f. 1v — Pb"]})
        self.assertEqual(canvas["partOf"], [{"id": IMAGING, "type": "Manifest"}])
        self.assert_valid([canvas])

    def test_minted_ids_live_under_the_explorer_manifest_path(self):
        self.assertEqual(
            mint(DIGEST, "annotation", "a b"),
            "https://manuspectrum.example/iiif/v3/explorer-manifest/"
            "0123456789ab/annotation/a%20b",
        )
        self.assertEqual(
            mint(DIGEST),
            "https://manuspectrum.example/iiif/v3/explorer-manifest/0123456789ab",
        )
        v2_ids = {self.canvas_2()["items"][0]["id"]}
        v2_ids.add(self.canvas_2()["items"][0]["items"][0]["id"])
        for minted in v2_ids:
            self.assertTrue(
                minted.startswith(
                    f"{settings.PUBLIC_SERVER_ADDRESS}iiif/v3/explorer-manifest/{DIGEST}/"
                ),
                minted,
            )
        self.assertEqual(len(v2_ids), 2)
