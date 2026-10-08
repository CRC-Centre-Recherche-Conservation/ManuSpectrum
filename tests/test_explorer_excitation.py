import time

from django.test import SimpleTestCase

from manuspectrum.views.explorer.excitation import excitation_of


def found(anode, kv):
    return {"anode": anode, "kV": kv, "source": "conditions"}


class ExcitationOfTests(SimpleTestCase):
    def test_symbol_after_tube(self):
        self.assertEqual(excitation_of(["Tube Ag, 40 kV, 200 µA"]), found("Ag", 40))

    def test_french_name_and_decimal_comma(self):
        self.assertEqual(
            excitation_of(["tube à anode de rhodium, 12,5 kV"]), found("Rh", 12.5)
        )

    def test_symbol_before_tube(self):
        self.assertEqual(excitation_of(["Rh tube 45kV"]), found("Rh", 45))

    def test_symbol_before_hyphenated_anode(self):
        self.assertEqual(excitation_of(["Rh-anode, 15 kVp"]), found("Rh", 15))

    def test_english_and_french_names(self):
        for text, anode in [
            ("silver anode", "Ag"),
            ("anode en argent", "Ag"),
            ("tungsten target", "W"),
            ("cible de tungstène", "W"),
            ("molybdène tube", "Mo"),
            ("tube molybdenum", "Mo"),
            ("anode de cuivre", "Cu"),
            ("chrome anode", "Cr"),
            ("tube chromium", "Cr"),
            ("palladium tube", "Pd"),
            ("titane target", "Ti"),
            ("target titanium", "Ti"),
            ("tube rhenium", "Re"),
        ]:
            with self.subTest(text=text):
                result = excitation_of([text])
                self.assertEqual(result and result["anode"], anode)

    def test_no_tube_word_means_no_anode(self):
        self.assertIsNone(excitation_of(["Cu Kα détecté"]))

    def test_kev_is_not_kv(self):
        self.assertIsNone(excitation_of(["20 keV"]))
        self.assertEqual(excitation_of(["tube Rh, 20 keV, 40 kV"]), found("Rh", 40))

    def test_two_kv_values_leave_kv_empty(self):
        self.assertEqual(
            excitation_of(["tube Ag 40 kV", "tube Ag 50 kV"]), found("Ag", None)
        )

    def test_conflicting_anodes_leave_anode_empty(self):
        self.assertEqual(
            excitation_of(["tube Ag, 40 kV", "tube Rh, 40 kV"]), found(None, 40)
        )

    def test_same_value_in_every_language_is_not_a_conflict(self):
        self.assertEqual(
            excitation_of(["Tube Rh 40 kV", "Tube à anode de rhodium, 40 kV"]),
            found("Rh", 40),
        )

    def test_html_and_nbsp(self):
        self.assertEqual(
            excitation_of(["<p>Tube&nbsp;Ag, 40&nbsp;kV</p><script>x</script>"]),
            found("Ag", 40),
        )

    def test_or_is_gold_only_right_after_anode(self):
        self.assertIsNone(excitation_of(["tube, or le fond est sombre"]))
        self.assertIsNone(excitation_of(["anode choisie, or nous avons mesuré"]))
        self.assertEqual(excitation_of(["anode d'or"]), found("Au", None))
        self.assertEqual(excitation_of(["anode gold"]), found("Au", None))
        self.assertIsNone(excitation_of(["gold tube"]))

    def test_out_of_range_kv_is_ignored(self):
        self.assertIsNone(excitation_of(["0 kV", "250 kV"]))
        self.assertEqual(excitation_of(["tube Ag 0.5 kV 40 kV"]), found("Ag", 40))

    def test_kv_alone(self):
        self.assertEqual(excitation_of(["40 kV"]), found(None, 40))

    def test_empty_and_none(self):
        self.assertIsNone(excitation_of([]))
        self.assertIsNone(excitation_of(["", None]))

    def test_only_first_4000_characters_are_scanned(self):
        self.assertIsNone(excitation_of(["x " * 2100 + "tube Ag 40 kV"]))

    def test_large_input_is_fast(self):
        text = ("tube " + "Rh " * 10 + "kV 4.0. " + "a" * 30) * 1000
        text = text[:50_000]
        start = time.perf_counter()
        excitation_of([text])
        self.assertLess(time.perf_counter() - start, 0.05)
