"""Tile values turned into the Explorer's contract objects, without a database.

Usage:
    python manage.py test tests.test_explorer_values --settings="tests.test_settings"
"""

from django.test import SimpleTestCase, override_settings
from django.utils import translation

from manuspectrum.constants.licenses import effective_license
from manuspectrum.views.explorer.values import (
    acronym,
    axis_key,
    dataset_of,
    file_entries,
    label,
    name_of,
    reference_terms,
    rewrite_legacy_url,
    shape_of,
    value_refs,
)

REF = [
    {
        "uri": "http://vocab/xrf",
        "labels": [
            {
                "value": "X-ray fluorescence",
                "language_id": "en",
                "list_item_id": "i-1",
                "valuetype_id": "prefLabel",
            },
            {
                "value": "Fluorescence X",
                "language_id": "fr",
                "list_item_id": "i-1",
                "valuetype_id": "prefLabel",
            },
            {
                "value": "XRF",
                "language_id": "en",
                "list_item_id": "i-1",
                "valuetype_id": "altLabel",
            },
        ],
    }
]

CSV_ID = "11111111-1111-4111-8111-111111111111"
MCA_ID = "22222222-2222-4222-8222-222222222222"
PDF_ID = "33333333-3333-4333-8333-333333333333"


class LabelTests(SimpleTestCase):
    def test_name_falls_back_to_another_language_with_its_lang(self):
        name = name_of(
            [{"fr": {"value": "Initiale", "direction": "ltr"}}],
            {"en": "Component"},
            "3f2a9c",
            "en",
        )

        self.assertEqual(name, {"value": "Initiale", "lang": "fr"})

    def test_name_without_any_label_uses_model_and_short_id(self):
        name = name_of([], {"en": "Analysis", "fr": "Analyse"}, "3f2a9c1e-0000", "fr")

        self.assertEqual(name, {"value": "Analyse 3f2a…", "lang": "fr"})

    def test_label_prefers_the_page_language_then_english(self):
        self.assertEqual(
            label({"de": "Blau", "en": "Blue"}, "fr"), {"value": "Blue", "lang": "en"}
        )
        self.assertIsNone(label({"en": "  "}, "en"))


class ReferenceTests(SimpleTestCase):
    def test_a_reference_becomes_value_refs_keyed_by_uri(self):
        self.assertEqual(
            value_refs(REF, "fr"),
            [
                {
                    "id": "i-1",
                    "uri": "http://vocab/xrf",
                    "label": {"value": "Fluorescence X", "lang": "fr"},
                }
            ],
        )

    def test_reference_terms_carry_every_label_for_free_text(self):
        self.assertEqual(
            reference_terms(REF), {"X-ray fluorescence", "Fluorescence X", "XRF"}
        )


class DatasetAndUrlTests(SimpleTestCase):
    def test_a_doi_typed_with_a_trailing_comma_is_cleaned(self):
        dataset = dataset_of(
            {
                "url": "https://doi.org/10.48579/PRO/ZEEJTH, ",
                "url_label": " HEU, S. 2024 ",
            }
        )

        self.assertEqual(
            dataset,
            {
                "url": "https://doi.org/10.48579/PRO/ZEEJTH",
                "isDoi": True,
                "label": "HEU, S. 2024",
            },
        )
        self.assertIsNone(dataset_of({"url": ""}))

    @override_settings(
        EXPLORER_LEGACY_HOSTS=("192.168.122.250",),
        PUBLIC_SERVER_ADDRESS="https://manuspectrum.example/",
    )
    def test_a_legacy_local_host_is_rewritten_to_the_public_address(self):
        self.assertEqual(
            rewrite_legacy_url("http://192.168.122.250:8000/manifest/abc"),
            "https://manuspectrum.example/manifest/abc",
        )
        self.assertEqual(
            rewrite_legacy_url("https://iiif.unicaen.fr/x"), "https://iiif.unicaen.fr/x"
        )

    def test_without_a_configured_host_the_url_is_returned_unchanged(self):
        self.assertEqual(
            rewrite_legacy_url("http://192.168.122.250:8000/manifest/abc"),
            "http://192.168.122.250:8000/manifest/abc",
        )


class AxisAndShapeTests(SimpleTestCase):
    def test_a_preset_config_groups_by_its_canonical_labels(self):
        stored = {
            "presetKey": "xrf",
            "display": {"xAxisLabel": "énergie", "yAxisLabel": "coups"},
        }

        self.assertEqual(
            axis_key(stored), axis_key({"presetKey": "xrf", "display": {}})
        )
        self.assertTrue(axis_key(stored).endswith("|asc"))
        self.assertIsNone(axis_key({}))

    def test_a_point_and_a_rectangle_become_canvas_shapes(self):
        point = shape_of({"type": "Point", "coordinates": [10, -20]}, 4000, 5000)
        rect = shape_of(
            {
                "type": "Polygon",
                "coordinates": [
                    [[10, -10], [20, -10], [20, -20], [10, -20], [10, -10]]
                ],
            },
            4000,
            5000,
        )

        self.assertEqual(point["type"], "point")
        self.assertEqual(rect["type"], "rect")
        self.assertGreater(rect["w"], 0)


@override_settings(
    RAW_INSTRUMENT_EXTENSIONS=(".mca", ".asd"),
    PUBLIC_SERVER_ADDRESS="https://manuspectrum.example/",
)
class FileEntryTests(SimpleTestCase):
    ENTRIES = [
        {
            "file_id": CSV_ID,
            "name": "X01_f1v.csv",
            "size": 42000,
            "type": "text/csv",
            "url": "/files/f-csv",
            "rendererConfig": "7a1c3f80-5d21-4e63-9b0a-2c4f8e1d6a01",
            "license": {
                "id": "CC-BY-4.0",
                "url": "https://creativecommons.org/licenses/by/4.0/",
            },
        },
        {
            "file_id": MCA_ID,
            "name": "X01_F1V.mca",
            "size": 9000,
            "type": "",
            "url": "/files/f-mca",
        },
        {
            "file_id": PDF_ID,
            "name": "report.pdf",
            "size": 100,
            "type": "application/pdf",
            "url": "/files/f-pdf",
        },
    ]

    def test_readable_raw_and_other_files_are_told_apart_and_paired(self):
        entries = {
            e["id"]: e
            for e in file_entries(
                self.ENTRIES, language="en", configs={}, kind="measurement"
            )
        }

        self.assertEqual(entries[CSV_ID]["role"], "readable")
        self.assertEqual(entries[CSV_ID]["dataKind"], "xy")
        self.assertEqual(entries[MCA_ID]["role"], "raw")
        self.assertEqual(entries[MCA_ID]["dataKind"], "file")
        self.assertEqual(entries[MCA_ID]["pairedWith"], CSV_ID)
        self.assertEqual(entries[CSV_ID]["pairedWith"], MCA_ID)
        self.assertEqual(entries[PDF_ID]["role"], "other")
        self.assertIsNone(entries[PDF_ID]["pairedWith"])
        self.assertEqual(entries[MCA_ID]["downloadUrl"], "/files/f-mca")
        self.assertIsNone(entries[MCA_ID]["previewUrl"])
        self.assertTrue(entries[CSV_ID]["previewUrl"].startswith("/"))
        self.assertTrue(
            entries[CSV_ID]["previewUrl"].endswith(f"/api/spectrum-preview/{CSV_ID}")
        )

    @override_settings(EXPLORER_LEGACY_HOSTS=("192.168.122.250",))
    def test_a_local_file_url_is_a_path_and_an_external_one_is_kept(self):
        urls = {
            "files/a": "/files/a",
            "https://manuspectrum.example/files/b?x=1": "/files/b?x=1",
            "http://192.168.122.250:8000/files/c": "/files/c",
            "https://zenodo.org/records/1/files/d.csv": "https://zenodo.org/records/1/files/d.csv",
            "//cdn.example/e": "//cdn.example/e",
        }
        entries = [
            {"file_id": f"f-{n}", "name": f"{n}.pdf", "url": url}
            for n, url in enumerate(urls)
        ]

        found = file_entries(entries, language="en", configs={}, kind="measurement")

        self.assertEqual([e["downloadUrl"] for e in found], list(urls.values()))

    def test_a_file_without_licence_gets_the_default_marked_as_such(self):
        with translation.override("en"):
            licence = effective_license(self.ENTRIES[1], "en")

        self.assertEqual(licence["id"], "CC-BY-SA-4.0")
        self.assertTrue(licence["isDefault"])
        self.assertTrue(licence["inRightsRegistry"])
        self.assertFalse(licence["noDerivatives"])

    def test_a_no_derivatives_licence_is_flagged(self):
        entry = {
            "license": {
                "id": "CC-BY-ND-4.0",
                "url": "https://creativecommons.org/licenses/by-nd/4.0/",
            }
        }

        self.assertTrue(effective_license(entry, "en")["noDerivatives"])

    def test_an_attribution_stored_per_language_gives_its_text(self):
        entry = {
            "attribution": {
                "en": {"value": "© CRC", "direction": "ltr"},
                "fr": {"value": "", "direction": "ltr"},
            }
        }

        self.assertEqual(effective_license(entry, "en")["attribution"], "© CRC")
        self.assertEqual(effective_license(entry, "fr")["attribution"], "© CRC")

    def test_an_empty_attribution_is_none(self):
        entry = {"attribution": {"fr": {"value": "", "direction": "ltr"}}}

        self.assertIsNone(effective_license(entry, "fr")["attribution"])

    def test_a_readable_file_carries_its_axis_labels(self):
        config_id = "c0000000-0000-4000-8000-000000000001"
        entries = [
            {
                "file_id": "11111111-1111-4111-8111-111111111111",
                "name": "a.csv",
                "url": "/files/a",
                "rendererConfig": config_id,
            }
        ]
        configs = {config_id: {"presetKey": "fors", "display": {}}}

        viewer = file_entries(
            entries, language="en", configs=configs, kind="measurement"
        )[0]["viewer"]

        self.assertTrue(viewer["xLabel"])
        self.assertTrue(viewer["yLabel"])


def _labelled(*labels):
    return [
        {
            "uri": "http://vocab/t",
            "labels": [
                {"value": v, "language_id": lang, "valuetype_id": kind}
                for kind, lang, v in labels
            ],
        }
    ]


class AcronymTests(SimpleTestCase):
    def test_the_acronym_every_language_shares_wins(self):
        value = _labelled(
            ("altLabel", "fr", "DRX"),
            ("altLabel", "fr", "XRD"),
            ("altLabel", "en", "XRD"),
            ("prefLabel", "en", "X-ray diffraction"),
        )

        self.assertEqual(acronym(value), "XRD")

    def test_without_a_shared_acronym_the_english_one_wins(self):
        value = _labelled(("altLabel", "fr", "SMA"), ("altLabel", "en", "AMS"))

        self.assertEqual(acronym(value), "AMS")

    def test_a_long_alternative_label_is_not_an_acronym(self):
        value = _labelled(
            ("altLabel", "fr", "Spectrométrie de Masse par Accélérateur (SMA)"),
            ("prefLabel", "en", "accelerator mass spectrometry"),
        )

        self.assertIsNone(acronym(value))
