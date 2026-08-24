import uuid

from django.conf import settings
from django.test import SimpleTestCase

from manuspectrum.utils.file_entries import (
    METADATA_FIELDS,
    build_file_entry,
    normalize_metadata,
)
from manuspectrum.constants.xy_presets import (
    ANALYST_ONLY_TRANSFORMS,
    AUTO_SAFE_TRANSFORMS,
    CONFIG_SOURCE_AUTO,
    CONFIG_SOURCE_KEY,
    CONFIG_SOURCE_MANUAL,
    TECHNIQUE_PRESETS,
    XY_PRESETS,
    XY_RENDERER_ID,
    config_id_for_techniques,
    preset_for_technique,
)
from manuspectrum.functions.xy_technique_config import (
    apply_config_to_file_entries,
    is_xy_text_file,
    technique_ids_from_tile_data,
)

# Real controlled-list item ids, from the TAPAC thesaurus.
PXRF = "a2e4b31a-53fa-3d8c-8aa6-f5b8b2564629"  # 61216 Fluorescence X portable
MICRO_XRF = "9b85c40c-132d-3664-a869-e62fae06aa10"  # 61217 Microfluorescence x
FTIR = "3e8fbf96-68f4-3dc5-9e41-5d270940cddf"  # 61308 IRTF
FORS = "65ea330e-e7ef-3cee-8266-35dc71321421"  # 61296 FORS
MALDI = "5f9bfd47-9b4c-3b0c-a59c-7012504a06ed"  # 61292 désorption laser
UNMAPPED = "716618c3-fdff-36b2-bbc5-663dc3c2d439"  # 61020 Chromatographie


class PresetTableTests(SimpleTestCase):
    def test_every_mapped_preset_key_exists(self):
        for item_id, key in TECHNIQUE_PRESETS.items():
            self.assertIn(
                key,
                XY_PRESETS,
                msg=f"{item_id} maps to unknown preset {key!r}",
            )

    def test_config_ids_are_unique_uuids(self):
        seen = set()
        for key, preset in XY_PRESETS.items():
            config_id = preset["config_id"]
            uuid.UUID(config_id)  # raises if malformed
            self.assertNotIn(config_id, seen, msg=f"{key} reuses a config id")
            seen.add(config_id)

    def test_technique_ids_are_wellformed_and_unique(self):
        for item_id in TECHNIQUE_PRESETS:
            uuid.UUID(item_id)
        self.assertEqual(len(TECHNIQUE_PRESETS), len(set(TECHNIQUE_PRESETS)))

    def test_presets_carry_a_name_a_description_and_axis_labels(self):
        for key, preset in XY_PRESETS.items():
            self.assertTrue(preset["name"], msg=f"{key} has no name")
            self.assertTrue(preset["description"], msg=f"{key} has no description")
            display = preset["config"]["display"]
            self.assertTrue(display["xAxisLabel"], msg=f"{key} has no X label")
            self.assertTrue(display["yAxisLabel"], msg=f"{key} has no Y label")

    def test_every_description_states_the_column_layout(self):
        # The description is what a curator reads in the list before picking a
        # configuration. Saying which column holds what is the fastest way to
        # tell whether a file matches — faster than opening the file.
        for key, preset in XY_PRESETS.items():
            self.assertIn(
                "Columns:",
                preset["description"],
                msg=f"{key} does not say what its columns are",
            )
            self.assertIn(
                "1 =",
                preset["description"],
                msg=f"{key} does not name its first column",
            )

    def test_the_description_describes_rather_than_translating(self):
        # RendererConfig has no i18n, and the list renders the description as a
        # tooltip beside the name — a translated name there reads as the same
        # label twice, which is what the seeded presets used to do.
        for key, preset in XY_PRESETS.items():
            self.assertNotEqual(
                preset["description"],
                preset["name"],
                msg=f"{key} describes itself with its own name",
            )

    def test_only_ftir_reverses_its_axis(self):
        reversed_keys = {
            key
            for key, preset in XY_PRESETS.items()
            if preset["config"]["display"]["xReversed"]
        }
        self.assertEqual(reversed_keys, {"ftir"})

    def test_presets_never_ship_a_transform_needing_parameters(self):
        for key, preset in XY_PRESETS.items():
            for step in preset["config"]["transforms"]:
                self.assertNotIn(
                    step["type"],
                    ANALYST_ONLY_TRANSFORMS,
                    msg=f"{key} would silently apply {step['type']}",
                )
                self.assertIn(step["type"], AUTO_SAFE_TRANSFORMS)

    def test_fors_normalises_against_its_reference_channel(self):
        transforms = XY_PRESETS["fors"]["config"]["transforms"]
        self.assertEqual([t["type"] for t in transforms], ["reference-normalize"])

    def test_the_four_techniques_in_use_all_resolve(self):
        for item_id in (PXRF, MICRO_XRF, FTIR, FORS, MALDI):
            self.assertIsNotNone(preset_for_technique(item_id))


class RendererRegistrationTests(SimpleTestCase):
    """The renderer is declared in settings but consumed from the constants.

    Keeping the settings entry a plain literal is what Arches expects, so the
    two hold the same values in two places. These tests are the seam that stops
    them drifting.
    """

    def xy_renderers(self):
        return [r for r in settings.RENDERERS if r["id"] == XY_RENDERER_ID]

    def test_the_renderer_is_registered(self):
        self.assertEqual(len(self.xy_renderers()), 1)

    def test_registered_extension_matches_the_constants(self):
        registered = {r["ext"].lower() for r in self.xy_renderers()}
        self.assertEqual(registered, set(settings.XY_TEXT_FILE_FORMATS))

    def test_registered_extensions_are_uploadable(self):
        for extension in settings.XY_TEXT_FILE_FORMATS:
            self.assertIn(extension, settings.FILE_TYPES)

    def test_no_wildcard_mime_type(self):
        # A "text/*" wildcard would claim .asd files, which browsers mis-sniff
        # as text/x-common-lisp but which the parser cannot read.
        for renderer in self.xy_renderers():
            self.assertFalse(renderer["type"].endswith("/*"))


class TechniqueResolutionTests(SimpleTestCase):
    def test_single_technique_resolves_to_its_config(self):
        self.assertEqual(
            config_id_for_techniques([FTIR]), XY_PRESETS["ftir"]["config_id"]
        )

    def test_agreeing_techniques_resolve(self):
        # Both map to the XRF preset, so there is no ambiguity to report.
        self.assertEqual(
            config_id_for_techniques([PXRF, MICRO_XRF]),
            XY_PRESETS["xrf"]["config_id"],
        )

    def test_conflicting_techniques_resolve_to_nothing(self):
        # Mislabelled analyses do exist in the data; a wrong axis is worse than
        # no axis, so disagreement must produce no configuration at all.
        self.assertIsNone(config_id_for_techniques([FTIR, FORS]))

    def test_unmapped_technique_resolves_to_nothing(self):
        self.assertIsNone(config_id_for_techniques([UNMAPPED]))

    def test_empty_selection_resolves_to_nothing(self):
        self.assertIsNone(config_id_for_techniques([]))

    def test_unmapped_alongside_mapped_still_resolves(self):
        self.assertEqual(
            config_id_for_techniques([FORS, UNMAPPED]),
            XY_PRESETS["fors"]["config_id"],
        )


class TileDataParsingTests(SimpleTestCase):
    def test_reads_list_item_ids_from_a_reference_value(self):
        data = {
            "3bcb6798-7b55-11ef-ba46-5b6797b92ed6": [
                {
                    "uri": "61296",
                    "list_id": "12dc9a7b-b177-450a-a927-711fa7882882",
                    "labels": [
                        {
                            "value": "Spectrométrie de réflectance par fibre optique",
                            "language_id": "fr",
                            "valuetype_id": "prefLabel",
                            "list_item_id": FORS,
                        }
                    ],
                }
            ]
        }
        self.assertEqual(technique_ids_from_tile_data(data), [FORS])

    def test_tolerates_a_bare_dict_instead_of_a_list(self):
        data = {
            "3bcb6798-7b55-11ef-ba46-5b6797b92ed6": {"labels": [{"list_item_id": FTIR}]}
        }
        self.assertEqual(technique_ids_from_tile_data(data), [FTIR])

    def test_tolerates_empty_and_missing_values(self):
        self.assertEqual(technique_ids_from_tile_data(None), [])
        self.assertEqual(technique_ids_from_tile_data({}), [])
        self.assertEqual(
            technique_ids_from_tile_data(
                {"3bcb6798-7b55-11ef-ba46-5b6797b92ed6": None}
            ),
            [],
        )


class FileEntryStampingTests(SimpleTestCase):
    def setUp(self):
        self.config_id = XY_PRESETS["fors"]["config_id"]

    def test_stamps_config_and_renderer_on_a_blank_entry(self):
        entries = [{"name": "MS59_f1_F07.csv", "file_id": "x"}]
        changed = apply_config_to_file_entries(entries, self.config_id)

        self.assertEqual(changed, 1)
        self.assertEqual(entries[0]["rendererConfig"], self.config_id)
        self.assertEqual(entries[0][CONFIG_SOURCE_KEY], CONFIG_SOURCE_AUTO)
        # Without the renderer, the config pointer would never be read.
        self.assertEqual(entries[0]["renderer"], XY_RENDERER_ID)

    def test_never_overwrites_a_curators_configuration(self):
        entries = [
            {
                "name": "spectrum.csv",
                "rendererConfig": "11111111-1111-4111-8111-111111111111",
                CONFIG_SOURCE_KEY: CONFIG_SOURCE_MANUAL,
            }
        ]
        self.assertEqual(apply_config_to_file_entries(entries, self.config_id), 0)
        self.assertEqual(
            entries[0]["rendererConfig"], "11111111-1111-4111-8111-111111111111"
        )

    def test_never_restores_a_configuration_a_curator_cleared(self):
        # A cleared config keeps its provenance marker, which is what tells the
        # mapping the blank is deliberate.
        entries = [{"name": "spectrum.csv", CONFIG_SOURCE_KEY: CONFIG_SOURCE_MANUAL}]
        self.assertEqual(apply_config_to_file_entries(entries, self.config_id), 0)
        self.assertNotIn("rendererConfig", entries[0])

    def test_is_idempotent(self):
        entries = [{"name": "spectrum.csv"}]
        self.assertEqual(apply_config_to_file_entries(entries, self.config_id), 1)
        self.assertEqual(apply_config_to_file_entries(entries, self.config_id), 0)

    def test_configures_the_csv_of_a_tile_holding_its_original_too(self):
        # A measurement tile commonly holds two files: the instrument's own
        # export, kept for the record, and the CSV the reader can plot. Only the
        # CSV gets the renderer — the original must stay a plain archived file,
        # or the reader would try to plot a format it cannot read.
        entries = [
            {"name": "MS59_f1_F07.txt", "file_id": "original"},
            {"name": "MS59_f1_F07.csv", "file_id": "derivative"},
        ]
        self.assertEqual(apply_config_to_file_entries(entries, self.config_id), 1)

        self.assertNotIn("renderer", entries[0])
        self.assertNotIn("rendererConfig", entries[0])
        self.assertEqual(entries[1]["renderer"], XY_RENDERER_ID)
        self.assertEqual(entries[1]["rendererConfig"], self.config_id)

    def test_configures_the_csv_even_when_it_is_not_first(self):
        # Order is not guaranteed: the archival original is usually first, but
        # nothing enforces it. Selection is by format, never by position.
        entries = [
            {"name": "spectrum.csv"},
            {"name": "spectrum.asd"},
        ]
        self.assertEqual(apply_config_to_file_entries(entries, self.config_id), 1)
        self.assertEqual(entries[0]["rendererConfig"], self.config_id)
        self.assertNotIn("rendererConfig", entries[1])

    def test_leaves_binary_instrument_exports_alone(self):
        entries = [
            {"name": "scan.asd"},  # ASD FieldSpec
            {"name": "sample.0"},  # Bruker OPUS
            {"name": "notes.pdf"},
        ]
        self.assertEqual(apply_config_to_file_entries(entries, self.config_id), 0)
        for entry in entries:
            self.assertNotIn("rendererConfig", entry)

    def test_preserves_a_renderer_already_chosen(self):
        entries = [{"name": "spectrum.csv", "renderer": "other-renderer"}]
        apply_config_to_file_entries(entries, self.config_id)
        self.assertEqual(entries[0]["renderer"], "other-renderer")

    def test_does_nothing_without_a_config(self):
        entries = [{"name": "spectrum.csv"}]
        self.assertEqual(apply_config_to_file_entries(entries, None), 0)
        self.assertNotIn("rendererConfig", entries[0])

    def test_tolerates_junk_entries(self):
        entries = [None, "not-a-dict", {"name": "spectrum.csv"}]
        self.assertEqual(apply_config_to_file_entries(entries, self.config_id), 1)

    def test_extension_matching_is_case_insensitive(self):
        self.assertTrue(is_xy_text_file({"name": "SPECTRUM.CSV"}))
        self.assertFalse(is_xy_text_file({"name": "spectrum.txt"}))
        self.assertFalse(is_xy_text_file({"name": "noextension"}))
        self.assertFalse(is_xy_text_file({}))


class FileEntryBuilderTests(SimpleTestCase):
    """A file entry written outside the upload widget must still be indexable.

    ``FileListDataType.append_to_document`` walks ``f[field].keys()`` with no
    guard, so one entry whose localised metadata is ``None`` aborts the whole
    search reindex. The widget fills those fields on upload; server-side writers
    — importers, the conversion workflow, repair scripts — have to do it too.
    """

    def test_builds_an_entry_the_indexer_can_walk(self):
        entry = build_file_entry(
            file_id="8f14e45f-ceea-467a-9e4a-1b0c8e1a0001",
            name="MS59_f1_F07.csv",
            path="uploadedfiles/MS59_f1_F07.csv",
            size=93649,
            content_type="text/csv",
        )

        for field in METADATA_FIELDS:
            # The exact shape the indexer expects: {lang: {value, direction}}.
            self.assertIsInstance(entry[field], dict)
            self.assertTrue(entry[field])
            for localized in entry[field].values():
                self.assertIn("value", localized)
                self.assertIn("direction", localized)

        self.assertEqual(entry["url"], "/files/8f14e45f-ceea-467a-9e4a-1b0c8e1a0001")
        self.assertTrue(entry["accepted"])

    def test_carries_renderer_keys_when_the_caller_knows_them(self):
        entry = build_file_entry(
            file_id="8f14e45f-ceea-467a-9e4a-1b0c8e1a0002",
            name="spectrum.csv",
            path="uploadedfiles/spectrum.csv",
            size=10,
            content_type="text/csv",
            renderer=XY_RENDERER_ID,
        )
        self.assertEqual(entry["renderer"], XY_RENDERER_ID)

    def test_repairs_missing_metadata_without_touching_what_is_there(self):
        entry = {
            "name": "scan.asd",
            "altText": None,
            "title": {"en": {"value": "Recto", "direction": "ltr"}},
            # attribution and description absent entirely
        }
        filled = normalize_metadata(entry, "en")

        self.assertEqual(filled, 3)
        self.assertEqual(entry["title"]["en"]["value"], "Recto")
        self.assertEqual(entry["altText"]["en"]["value"], "")
        self.assertIn("attribution", entry)
        self.assertIn("description", entry)

    def test_repairing_twice_changes_nothing_the_second_time(self):
        entry = {"name": "scan.asd"}
        self.assertEqual(normalize_metadata(entry, "en"), 4)
        self.assertEqual(normalize_metadata(entry, "en"), 0)

    def test_adds_a_missing_language_beside_an_existing_one(self):
        entry = {"title": {"fr": {"value": "Verso", "direction": "ltr"}}}
        self.assertEqual(normalize_metadata(entry, "en"), 4)
        self.assertEqual(entry["title"]["fr"]["value"], "Verso")
        self.assertEqual(entry["title"]["en"]["value"], "")

    def test_tolerates_junk(self):
        self.assertEqual(normalize_metadata(None), 0)
        self.assertEqual(normalize_metadata("not-a-dict"), 0)
