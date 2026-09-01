import uuid
from unittest import mock

from django.conf import settings
from django.test import SimpleTestCase

from manuspectrum.utils.file_entries import (
    METADATA_FIELDS,
    build_file_entry,
    normalize_metadata,
)
from manuspectrum.constants.xy_presets import (
    ANALYST_ONLY_TRANSFORMS,
    CORRECTIVE_TRANSFORMS,
    DATA_FILE_NODE_ID,
    DATA_FILE_NODEGROUP_ID,
    ROLE_DARK,
    ROLE_REFERENCE,
    ROLE_X,
    ROLE_Y_LEFT,
    TECHNIQUE_NODE_ID,
    TECHNIQUE_NODEGROUP_ID,
    MULTI_Y_CHOICES,
    MULTI_Y_MEAN,
    MULTI_Y_REFERENCE,
    MULTI_Y_SEPARATE,
    TRANSFORM_REFERENCE_NORMALIZE,
    AUTO_SAFE_TRANSFORMS,
    CONFIG_SOURCE_AUTO,
    CONFIG_SOURCE_KEY,
    CONFIG_SOURCE_MANUAL,
    SEED_OWNED_CONFIG_KEYS,
    TECHNIQUE_PRESETS,
    XY_PRESETS,
    XY_RENDERER_ID,
    config_id_for_techniques,
    merge_seed_owned_keys,
    preset_for_technique,
)
from manuspectrum.functions.xy_technique_config import (
    XYTechniqueConfig,
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


def reference_columns(config):
    """Column indices a preset tags as the white reference."""
    return [
        assignment["columnIndex"]
        for assignment in config["display"].get("columnAssignments", [])
        if assignment["role"] == ROLE_REFERENCE
    ]


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

    def test_only_infrared_reverses_its_axis(self):
        # The descending wavenumber axis is an infrared convention, and the
        # only one among the mapped families. Raman is also in cm-1 and is
        # plotted ascending; NMR and XPS are reversed too but are deliberately
        # absent from the map. Both infrared presets share the convention —
        # they split on the quantity plotted, not on the abscissa.
        reversed_keys = {
            key
            for key, preset in XY_PRESETS.items()
            if preset["config"]["display"]["xReversed"]
        }
        self.assertEqual(reversed_keys, {"ftir", "ftir_reflection"})

    def test_every_preset_declares_a_valid_multi_y_choice(self):
        for key, preset in XY_PRESETS.items():
            self.assertIn(
                preset["config"]["multiYHandling"],
                MULTI_Y_CHOICES,
                msg=f"{key} declares a choice the engine cannot honour",
            )

    def test_a_preset_can_only_ever_apply_a_corrective_transform(self):
        # The three answers are the whole vocabulary: two apply nothing, and the
        # third applies reference normalisation, which is corrective. So a
        # preset *cannot* freeze a way of looking at the data into a shared
        # configuration — not by policy, but because there is no way to say it.
        applied = {
            MULTI_Y_SEPARATE: None,
            MULTI_Y_MEAN: None,
            MULTI_Y_REFERENCE: TRANSFORM_REFERENCE_NORMALIZE,
        }
        self.assertEqual(set(applied), MULTI_Y_CHOICES)
        for transform in applied.values():
            if transform is not None:
                self.assertIn(transform, CORRECTIVE_TRANSFORMS)

    def test_a_preset_that_normalises_ships_the_column_it_divides_by(self):
        # referenceNormalize looks the reference column up by role and returns
        # the data untouched when it finds none. So the setting alone reaches
        # nothing: declaring the correction and declaring the column are one
        # claim, and a preset that makes half of it is a no-op wearing the
        # label of a computed quantity.
        for key, preset in XY_PRESETS.items():
            config = preset["config"]
            if config["multiYHandling"] != MULTI_Y_REFERENCE:
                continue
            self.assertTrue(
                reference_columns(config),
                msg=(
                    f"{key} declares {MULTI_Y_REFERENCE} but tags no column "
                    f"{ROLE_REFERENCE!r} — the normalisation cannot run"
                ),
            )

    def test_a_presets_axis_label_cannot_lie(self):
        # Reflectance IS the ratio of measurement to white reference, so a
        # preset naming it must either compute the ratio — which takes the
        # column, not just the setting — or receive a file where the instrument
        # already did.
        for key, preset in XY_PRESETS.items():
            config = preset["config"]
            label = config["display"]["yAxisLabel"]
            if "reflectance" not in label.lower():
                continue
            computes = config["multiYHandling"] == MULTI_Y_REFERENCE and bool(
                reference_columns(config)
            )
            precorrected = config.get("yPrecorrected", False)
            self.assertTrue(
                computes or precorrected,
                msg=(
                    f"{key} labels its Y axis {label!r} but neither computes "
                    f"{MULTI_Y_REFERENCE} nor declares y_precorrected — so the "
                    f"label claims a quantity nothing reaches"
                ),
            )

    def test_reflectance_is_a_fraction_everywhere_it_is_named(self):
        # referenceNormalize returns (S-D)/(W-D) — a fraction in [0, 1]. Both
        # reader-side lenses that consume R assume the same: at R = 50 %,
        # log10(1/R) yields -1.70 instead of +0.30 (sign-flipped) and
        # Kubelka-Munk yields 24.0 instead of 0.25. A label reading "(%)"
        # invites exactly the export that breaks them, so no preset may say it.
        for key, preset in XY_PRESETS.items():
            label = preset["config"]["display"]["yAxisLabel"]
            if "reflectance" not in label.lower():
                continue
            self.assertNotIn(
                "%",
                label,
                msg=f"{key} names reflectance as a percentage; the engine produces a fraction",
            )

    def test_saving_keeps_the_keys_the_panel_cannot_send(self):
        # The editing panel builds its payload from its own form fields, so a
        # seeded key it has never heard of is absent from every request. A
        # wholesale replace dropped presetKey on the first superuser save and
        # silently emptied that technique's reader-side view palette.
        stored = {"presetKey": "ftir", "delimiterCharacter": ",", "display": {}}
        incoming = {"delimiterCharacter": ";", "display": {"xReversed": True}}

        merged = merge_seed_owned_keys(stored, incoming)

        self.assertEqual(merged["presetKey"], "ftir")
        self.assertEqual(merged["delimiterCharacter"], ";")
        self.assertEqual(merged["display"], {"xReversed": True})

    def test_saving_can_still_clear_a_field_the_panel_owns(self):
        # The panel serialises a cleared field as `undefined` and JSON omits
        # it. A blanket merge would resurrect the old value, so an axis could
        # never be un-reversed — worse than the bug being fixed.
        stored = {"presetKey": "ftir", "display": {"xReversed": True}}
        incoming = {"display": {}}

        merged = merge_seed_owned_keys(stored, incoming)

        self.assertEqual(merged["display"], {})
        self.assertEqual(merged["presetKey"], "ftir")

    def test_saving_invents_no_key_a_configuration_never_had(self):
        # A curator's own configuration carries none of the seeded keys, and
        # saving one must not grow them.
        merged = merge_seed_owned_keys({}, {"delimiterCharacter": ","})

        self.assertEqual(merged, {"delimiterCharacter": ","})
        self.assertEqual(merge_seed_owned_keys(None, {}), {})

    def test_every_seed_owned_key_is_actually_written_by_a_preset(self):
        # The list is the contract between _preset() and the save path. An
        # entry nothing writes is dead weight that reads like a guarantee.
        written = {key for p in XY_PRESETS.values() for key in p["config"]}
        for key in SEED_OWNED_CONFIG_KEYS:
            self.assertIn(
                key,
                written,
                msg=f"{key} is preserved on save but no preset ever writes it",
            )

    def test_fors_normalises_against_its_reference_channel(self):
        config = XY_PRESETS["fors"]["config"]

        self.assertEqual(config["multiYHandling"], MULTI_Y_REFERENCE)
        # wavelength / tgt_count / ref_count — the ASD text export's own layout,
        # and the shape utils/xy-transforms.spec.js resolves roles against.
        self.assertEqual(
            config["display"]["columnAssignments"],
            [
                {"columnIndex": 0, "role": ROLE_X},
                {"columnIndex": 1, "role": ROLE_Y_LEFT},
                {"columnIndex": 2, "role": ROLE_REFERENCE},
            ],
        )

    def test_the_dark_column_is_left_for_the_curator_to_tag(self):
        # The export carries it only sometimes. Tagging it here would subtract
        # whatever column 4 happens to be on a file that has no dark current.
        roles = [
            assignment["role"]
            for assignment in XY_PRESETS["fors"]["config"]["display"][
                "columnAssignments"
            ]
        ]
        self.assertNotIn(ROLE_DARK, roles)

    def test_the_two_classifications_answer_different_questions(self):
        # log10(1/R) is parameter-free, so a preset *could* apply it by itself —
        # and still must not be frozen into a shared configuration. If these
        # ever coincide, one of them has lost its meaning.
        self.assertTrue(CORRECTIVE_TRANSFORMS < AUTO_SAFE_TRANSFORMS)
        self.assertFalse(CORRECTIVE_TRANSFORMS & ANALYST_ONLY_TRANSFORMS)

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
        # IRTF resolves to the reflection preset, not the absorbance one: every
        # instrument file in this database carries PLF='RFL'. The generic term
        # cannot know that anywhere else, which is why the choice is a default
        # a curator can override per file rather than a claim about the world.
        self.assertEqual(
            config_id_for_techniques([FTIR]),
            XY_PRESETS["ftir_reflection"]["config_id"],
        )

    def test_the_two_infrared_presets_differ_only_in_the_quantity(self):
        # If they ever agree on both axes they are one preset wearing two
        # names, which is the redundancy maldi/mass_spec already demonstrates.
        absorbance = XY_PRESETS["ftir"]["config"]["display"]
        reflection = XY_PRESETS["ftir_reflection"]["config"]["display"]
        self.assertEqual(absorbance["xAxisLabel"], reflection["xAxisLabel"])
        self.assertNotEqual(absorbance["yAxisLabel"], reflection["yAxisLabel"])

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


class TechniqueBackfillWriteTests(SimpleTestCase):
    """The write path: how a derived config reaches the sibling file tiles."""

    def _technique_tile(self):
        tile = mock.Mock()
        tile.nodegroup_id = TECHNIQUE_NODEGROUP_ID
        tile.resourceinstance_id = uuid.uuid4()
        tile.data = {TECHNIQUE_NODE_ID: [{"labels": [{"list_item_id": FORS}]}]}
        return tile

    def _sibling(self):
        sibling = mock.Mock()
        sibling.tileid = uuid.uuid4()
        sibling.data = {
            DATA_FILE_NODE_ID: [{"name": "spectrum.csv", "file_id": str(uuid.uuid4())}]
        }
        return sibling

    def _run(self, siblings):
        """Drive the real save() dispatch over mocked tiles."""
        with (
            mock.patch("manuspectrum.functions.xy_technique_config.Tile") as tile_proxy,
            mock.patch("manuspectrum.functions.xy_technique_config.transaction") as tx,
        ):
            tile_proxy.objects.filter.return_value = siblings
            # A MagicMock context manager swallows exceptions; atomic() does not.
            tx.atomic.return_value.__exit__.return_value = False
            XYTechniqueConfig().save(self._technique_tile(), request=mock.Mock())
            return tx

    def test_the_derived_config_is_written_without_the_request(self):
        sibling = self._sibling()
        self._run([sibling])

        sibling.save.assert_called_once_with(index=False)
        self.assertNotIn("request", sibling.save.call_args.kwargs)

    def test_each_sibling_write_gets_its_own_savepoint(self):
        siblings = [self._sibling(), self._sibling()]
        tx = self._run(siblings)

        self.assertEqual(tx.atomic.call_count, len(siblings))

    def test_one_unwritable_sibling_does_not_stop_the_others(self):
        first, second = self._sibling(), self._sibling()
        first.save.side_effect = RuntimeError("row is locked")

        self._run([first, second])

        second.save.assert_called_once_with(index=False)

    def test_a_file_already_carrying_a_config_is_never_rewritten(self):
        untouched = self._sibling()
        untouched.data[DATA_FILE_NODE_ID][0]["rendererConfig"] = str(uuid.uuid4())

        self._run([untouched])

        untouched.save.assert_not_called()


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


class FileMetadataCompletenessTests(SimpleTestCase):
    """Every file entry must carry every language a reader can activate.

    The upload widget writes only the active language but hydrates the missing
    ones when it renders, mutating tile.data. `tile.dirty` compares that against
    a snapshot taken before the widgets mount, so an entry short of a language
    is dirty the moment the page loads: the card shows unsaved edits and the
    resource lifecycle button is disabled with nobody having touched anything.
    """

    def test_every_configured_language_is_filled_by_default(self):
        # A set, never a key order: tiledata is jsonb and Postgres normalises
        # object keys, so only which languages exist is ours to control.
        entry = {"name": "spectrum.csv"}
        normalize_metadata(entry)

        for field in METADATA_FIELDS:
            self.assertEqual(set(entry[field]), {"en", "fr"})

    def test_a_single_language_can_still_be_asked_for(self):
        entry = {"name": "spectrum.csv"}
        normalize_metadata(entry, "en")

        self.assertEqual(set(entry["title"]), {"en"})

    def test_the_language_a_curator_filled_is_never_replaced(self):
        entry = {"title": {"fr": {"value": "Verso", "direction": "ltr"}}}
        normalize_metadata(entry)

        self.assertEqual(entry["title"]["fr"]["value"], "Verso")
        self.assertEqual(entry["title"]["en"]["value"], "")

    def test_a_file_tile_is_completed_even_with_no_technique(self):
        # The guard in _on_file_saved returns early when no technique resolves,
        # so the invariant has to run before it — those are exactly the oldest
        # and most likely malformed entries.
        tile = mock.Mock()
        tile.nodegroup_id = DATA_FILE_NODEGROUP_ID
        tile.resourceinstance_id = uuid.uuid4()
        tile.data = {DATA_FILE_NODE_ID: [{"name": "spectrum.csv"}]}

        with mock.patch(
            "manuspectrum.functions.xy_technique_config.resolve_config_id",
            return_value=None,
        ):
            XYTechniqueConfig().save(tile, request=mock.Mock())

        self.assertEqual(set(tile.data[DATA_FILE_NODE_ID][0]["title"]), {"en", "fr"})
