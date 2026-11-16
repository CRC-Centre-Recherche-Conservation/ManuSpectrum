"""Building blocks of the Explorer's IIIF v3 manifest: source canvases, minted ids, page filters.

Usage:
    python manage.py test tests.test_explorer_manifest_parts --settings="tests.test_settings"
"""

import copy

from django.conf import settings
from django.test import SimpleTestCase, override_settings
from django.utils import translation

from manuspectrum.iiif import language as lang
from manuspectrum.iiif.constants import PRESENTATION_3
from manuspectrum.iiif.ids import explorer_part as mint
from manuspectrum.iiif.manifest import (
    Header,
    imaging_metadata,
    manifest_header,
    page_filter,
    provider,
    required_statement,
    summary_counts,
)
from manuspectrum.iiif.sources import canvas_thumbnail, v3_canvas
from tests.iiif_schema import assert_valid_manifest

SOURCE_V3 = "https://example.org/iiif/ms59/manifest"
CANVAS_V3 = "https://example.org/iiif/ms59/canvas/f1v"
SOURCE_V2 = "https://example.org/iiif/ms60/manifest.json"
CANVAS_V2 = "https://example.org/iiif/ms60/canvas/p1"
SERVICE_V2 = "https://example.org/iiif/image/ms60-p1"
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
    def assert_valid(self, canvases, annotations=()):
        assert_valid_manifest(self, wrapped(canvases, annotations))

    def canvas_3(self):
        return v3_canvas(CANVAS_3, MANIFEST_3, SOURCE_V3, mint_id)

    def canvas_2(self):
        return v3_canvas(CANVAS_2, MANIFEST_2, SOURCE_V2, mint_id)

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

    def test_a_v2_attribution_is_labelled_in_every_language(self):
        with translation.override("fr"):
            canvas = self.canvas_2()

        statement = canvas["requiredStatement"]
        self.assertEqual(statement["label"], lang.gettext_map("Attribution"))
        self.assertNotIn("none", statement["label"])
        self.assertEqual(
            statement["value"], {"none": ["Bibliothèque nationale de France"]}
        )

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

    def test_a_page_is_filtered_unless_the_scope_keeps_the_whole_document(self):
        self.assertEqual(page_filter({"a", "b"}), frozenset({"a", "b"}))
        self.assertIsNone(page_filter({"a"}, whole=True))
        self.assertIsNone(page_filter(set()))
        with override_settings(IIIF_PAGE_FILTER_MAX=1):
            self.assertIsNone(page_filter({"a", "b"}))


BASE = settings.PUBLIC_SERVER_ADDRESS


class HeaderTests(SimpleTestCase):
    def test_header_key_order_and_empty_parts_left_out(self):
        out = manifest_header(
            Header(label=lang.none("X"), summary=None, metadata=(), homepage=())
        )
        self.assertEqual(list(out), ["label", "requiredStatement", "provider"])

    def test_header_full_key_order(self):
        out = manifest_header(
            Header(
                label=lang.none("X"),
                summary=lang.none("S"),
                metadata=({"label": {}, "value": {}},),
                homepage=({"id": "h"},),
                rendering=({"id": "r"},),
                thumbnail=[{"id": "t"}],
            )
        )
        self.assertEqual(
            list(out),
            [
                "label",
                "summary",
                "metadata",
                "requiredStatement",
                "provider",
                "homepage",
                "rendering",
                "thumbnail",
            ],
        )

    def test_required_statement_names_app_title_in_every_language(self):
        st = required_statement()
        self.assertEqual(set(st["label"]), set(lang.languages()))
        self.assertTrue(all(settings.APP_TITLE in v[0] for v in st["value"].values()))

    def test_provider_is_one_agent_on_public_address(self):
        (agent,) = provider()
        self.assertEqual(
            (agent["id"], agent["type"]), (settings.PUBLIC_SERVER_ADDRESS, "Agent")
        )
        self.assertEqual(agent["label"], lang.none(settings.APP_TITLE))
        self.assertEqual(
            {h["language"][0] for h in agent["homepage"]}, set(lang.languages())
        )

    def test_summary_counts_english(self):
        s = summary_counts(81, 3, 10, lang.none("Ms. 59"), 1)
        self.assertEqual(
            s["en"], ["81 analyses and 3 identified materials on 10 pages of Ms. 59"]
        )

    def test_summary_counts_leaves_out_zero_part(self):
        s = summary_counts(0, 1, 1, lang.none("Ms. 59"), 1)
        self.assertEqual(s["en"], ["1 identified material on 1 page of Ms. 59"])

    def test_summary_counts_several_documents(self):
        self.assertEqual(
            summary_counts(2, 0, 3, None, 2)["en"],
            ["2 analyses on 3 pages of 2 documents"],
        )

    def test_imaging_metadata_links_each_manifest(self):
        e = imaging_metadata([(f"{BASE}iiif/manifest/abc", lang.none("maXRF map1"))])
        self.assertEqual(e["label"]["en"], ["Chemical imaging"])
        self.assertIn(f'href="{BASE}iiif/manifest/abc"', e["value"]["none"][0])

    def test_imaging_metadata_none_without_entries(self):
        self.assertIsNone(imaging_metadata([]))

    def test_canvas_thumbnail_from_image_service(self):
        canvas = {
            "items": [{"items": [{"body": {"service": [{"id": "https://img/x/"}]}}]}]
        }
        self.assertEqual(
            canvas_thumbnail(canvas)[0]["id"],
            "https://img/x/full/!300,300/0/default.jpg",
        )

    def test_canvas_thumbnail_none_without_service(self):
        self.assertIsNone(canvas_thumbnail({"items": []}))
