from django.test import SimpleTestCase

from manuspectrum.measurement_files import matching
from manuspectrum.measurement_files.catalogue import AnalysisCard

SHELFMARK = "AB12"


def card(card_id, name, preset, sources=None, editable=True):
    return AnalysisCard(
        id=card_id,
        name=name,
        technique_ids=(),
        technique_label={},
        technique_preset=preset,
        folio_sources=tuple(sources if sources is not None else [name]),
        files=(),
        parent_tile_id=None,
        projects=(),
        editable=editable,
    )


CARDS = [
    card("a1", "AB12 f126v F21", "fors"),
    card("a2", "AB12 f1 F07", "fors"),
    card("a3", "AB12 f1v F07", "fors"),
    card("a4", "AB12 f1v IR07", "ftir"),
    card("a5", "AB12 f1v XRF 01", "xrf"),
    card("a6", "AB12 f31v IR09", "ftir"),
    card("a7", "AB12 f31v F09", "fors"),
    card("a8", "AB12 f1v F11", "fors"),
    card("a9", "AB12 f40 F05", "fors"),
    card("a10", "AB12 f40 F05", "fors"),
    card("a11", "AB12 f50 IR03", "ftir_reflection"),
    card("a12", "AB12 f60 F02", "fors", editable=False),
    card("a13", "F21", "fors", sources=["F21", "f77r"]),
    card("a14", "AB12 f42 IR05", "ftir_reflection"),
    card("a15", "X03 f55v AB12", "xrf", sources=["X03 f55v AB12", "f54r AB12"]),
]


def run(name, content, relative_dir="", codes=None, cards=CARDS):
    codes = codes or {}
    reading = matching.read_name(name, relative_dir, SHELFMARK, codes)
    return matching.propose(reading, content, cards, codes, shelfmark=SHELFMARK)


class ProposalTests(SimpleTestCase):
    def test_table(self):
        cases = [
            ("Ab12-f126v-F21", "fors", "", {}, "a1", None),
            ("AB12_f1_F07", "fors", "", {}, "a2", None),
            ("Ab12f1v_Ff07", "fors", "", {}, None, "unknown_codes"),
            ("Ab12f1v_Ff07", "fors", "", {"ff": "fors"}, "a3", None),
            ("Ab12f1v_Ffsc11test", "fors", "", {}, None, "unknown_codes"),
            ("Ab12f1v_Ffsc11test", "fors", "", {"ffsc": "fors"}, None, "name_alert"),
            ("Ab12f1v_Ffsc11test", "fors", "", {"ffsc": "ignore"}, None, "name_alert"),
            ("Ab12f31v_09b_rouge_64sc.0", "ftir", "", {}, None, "near_name"),
            ("2020-0381-AB12-f1V-bleu-X01_spectrum.mca", "xrf", "", {}, "a5", None),
            ("AB12_F07", "fors", "f1v", {}, "a3", None),
            ("F11", "fors", "AB12/f1v/FORS", {}, "a8", None),
            ("AB12_f1v_07", "fors", "FORS", {}, "a3", None),
            ("AB12_f1v_07", "ftir", "", {}, "a4", None),
            ("XY99_f1v_F07", "fors", "", {}, None, "other_shelfmark"),
            ("Ms60-f1v-F07", "fors", "", {}, None, "other_shelfmark"),
            ("AB12_f40_F05", "fors", "", {}, None, "near_name"),
            ("AB12_f50_IR03", "ftir_reflection", "", {}, "a11", None),
            ("AB12_f50_IR03", "ftir", "", {}, "a11", None),
            ("AB12_f1v_F07", "ftir", "", {}, None, "format_vs_technique"),
            ("AB12_f31v_09", "ftir", "", {}, "a6", None),
            ("AB12_f31v_09", "fors", "", {}, "a7", None),
            ("AB12_F07", "fors", "", {}, None, "no_analysis"),
            ("AB12_f1_F99", "fors", "", {}, None, "no_analysis"),
            ("AB12_f1_F07", None, "", {}, "a2", None),
            ("AB12_f1_F07_blanc", "fors", "", {}, None, "name_alert"),
            ("AB12_f1_F07_ref", "fors", "", {}, None, "name_alert"),
            ("AB12_f1_F07_Test", "fors", "", {}, None, "name_alert"),
            ("2020-0381_AB12_f1_F07", "fors", "", {}, "a2", None),
            ("ab-12_f1_F07", "fors", "", {}, "a2", None),
            ("AB 12 f1 F07.spx", "fors", "", {}, "a2", None),
            ("f1v_F07", "fors", "", {}, "a3", None),
            ("AB12_F1V_F07", "fors", "", {}, "a3", None),
            ("AB12_f1_09b", "fors", "", {}, None, "no_analysis"),
            ("AB12_f1_F007", "fors", "", {}, "a2", None),
            ("AB12_f1_FORS046", "fors", "", {}, None, "no_analysis"),
            ("AB12_f126v_FORS021", "fors", "", {}, "a1", None),
            ("AB12_f60_F02", "fors", "", {}, None, "no_analysis"),
            ("AB12_f77r_F21", "fors", "", {}, "a13", None),
            ("AB12_f126v_F21", "fors", "batch\\day", {}, "a1", None),
            ("AB12_f1_F07", "xrf", "", {}, None, "format_vs_technique"),
            ("AB12_f1v_pointe_3", "fors", "", {}, None, "unknown_codes"),
            ("", "fors", "", {}, None, "no_analysis"),
            ("AB12f42_05_bleu.0", "ftir_reflection", "", {}, "a14", None),
            (
                "2020-0401-AB12-f55V-parchemin-X03_spectrum.mca",
                "xrf",
                "",
                {},
                "a15",
                None,
            ),
            (
                "2020-0401-AB12-f54r-parchemin-X03_spectrum.mca",
                "xrf",
                "",
                {},
                "a15",
                None,
            ),
            ("AB12_f42_F05", "ftir_reflection", "", {}, None, "format_vs_technique"),
        ]
        for name, content, folder, codes, expected, cause in cases:
            with self.subTest(name=name, content=content, folder=folder):
                proposal = run(name, content, folder, codes)
                self.assertEqual(proposal.analysis_id, expected)
                self.assertEqual(proposal.cause, cause)

    def test_two_cards_fit_proposes_nothing(self):
        proposal = run("AB12_f40_F05", "fors")
        self.assertIsNone(proposal.analysis_id)
        self.assertEqual(proposal.candidates, ("a10", "a9"))

    def test_near_name_names_its_candidate(self):
        proposal = run("Ab12f31v_09b_rouge_64sc.0", "ftir")
        self.assertEqual(proposal.candidates, ("a6",))

    def test_format_mismatch_names_candidates(self):
        proposal = run("AB12_f1v_F07", "ftir")
        self.assertEqual(proposal.candidates, ("a3",))

    def test_no_card_at_all(self):
        proposal = run("AB12_f1_F07", "fors", cards=[])
        self.assertEqual(proposal.cause, "no_analysis")


class ReadingTests(SimpleTestCase):
    def read(self, name, relative_dir="", codes=None):
        return matching.read_name(name, relative_dir, SHELFMARK, codes or {})

    def meanings(self, reading):
        return [(t.piece, t.meaning, t.source) for t in reading.tokens]

    def test_folio_form_and_number(self):
        reading = self.read("Ab12-f126v-F21")
        self.assertEqual(
            (reading.folio, reading.family, reading.number), ("f126v", "fors", "21")
        )
        self.assertEqual(
            self.meanings(reading),
            [
                ("Ab12", "shelfmark", "name"),
                ("f126v", "folio", "name"),
                ("F21", "code", "common"),
            ],
        )

    def test_recto_without_side(self):
        self.assertEqual(self.read("AB12_f1_F07").folio, "f1")
        self.assertEqual(self.read("AB12_f001_F07").folio, "f1")

    def test_sequence_scans_colour_word(self):
        reading = self.read("2020-0381-AB12-f1V-bleu-X01_spectrum.mca")
        self.assertEqual(
            [t.meaning for t in reading.tokens],
            ["sequence", "shelfmark", "folio", "colour", "code", "word"],
        )
        reading = self.read("Ab12f31v_09b_rouge_64sc.0")
        self.assertIn("scans", [t.meaning for t in reading.tokens])
        self.assertEqual(reading.number, "9")

    def test_folder_folio_and_family_sources(self):
        reading = self.read("AB12_F07", "campaign/f1v/FORS")
        self.assertEqual(reading.folio, "f1v")
        self.assertEqual(reading.family, "fors")
        self.assertEqual(
            {t.source for t in reading.tokens if t.meaning in ("folio", "code")},
            {"folder", "common"},
        )

    def test_dictionary_source(self):
        reading = self.read("Ab12f1v_Ff07", codes={"ff": "fors"})
        self.assertEqual(reading.family, "fors")
        self.assertIn(("Ff07", "code", "dictionary"), self.meanings(reading))

    def test_unknown_codes_and_alerts(self):
        reading = self.read("Ab12f1v_Ffsc11test")
        self.assertEqual(reading.unknown_codes, ("Ffsc",))
        self.assertEqual(reading.alerts, ("test",))
        self.assertIsNone(reading.number)

    def test_other_shelfmark(self):
        self.assertTrue(self.read("XY99_f1v_F07").other_shelfmark)
        self.assertFalse(self.read("AB12_f1v_F07").other_shelfmark)
        self.assertTrue(self.read("Ffsc11_f1v").other_shelfmark)

    def test_ftir_reflection_is_ftir(self):
        self.assertEqual(matching.family_of("ftir_reflection"), "ftir")
        self.assertEqual(matching.family_of("xrf_channel"), "xrf")
        self.assertIsNone(matching.family_of(None))


class AnalysisKeysTests(SimpleTestCase):
    def test_name_carries_everything(self):
        keys = matching.analysis_keys(CARDS[0], {}, shelfmark=SHELFMARK)
        self.assertEqual(
            (keys.folio, keys.family, keys.numbers), ("f126v", "fors", {"21"})
        )

    def test_folio_from_component_source(self):
        keys = matching.analysis_keys(CARDS[12], {}, shelfmark=SHELFMARK)
        self.assertEqual((keys.folio, keys.numbers), ("f77r", {"21"}))

    def test_reflection_family(self):
        keys = matching.analysis_keys(CARDS[10], {}, shelfmark=SHELFMARK)
        self.assertEqual(keys.family, "ftir")

    def test_two_folios_mean_none(self):
        both = card("z", "AB12 f1 F07", "fors", sources=["f1v", "f2v", "F07"])
        keys = matching.analysis_keys(both, {}, shelfmark=SHELFMARK)
        self.assertIsNone(keys.folio)
        self.assertEqual(keys.folios, {"f1v", "f2v"})
