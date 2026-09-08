"""Unit tests for ``manuspectrum.utils.dates``.

Pure-function tests — no HTTP, no DB. Validates the edtf-backed historical
date parser and the century resolver for the inputs the Biblissima /
Mandragore connectors actually feed it.

The third return slot of ``parse_historical_date`` is a **list** of
century concept valueids: each century the parsed range covers, low →
high inclusive (strict rule ``(year - 1) // 100 + 1``). Cross-century
intervals therefore yield more than one valueid; single-year /
within-one-century inputs yield a one-element list; unparseable inputs
yield ``[]``.

Usage:
    python manage.py test tests.test_dates --settings="tests.test_settings"
"""

from unittest import TestCase

from manuspectrum.utils.dates import (
    CENTURY_MAPPING,
    parse_century,
    parse_historical_date,
)


def _C(*nums):
    """Shorthand: ``_C(13, 14)`` → ``[CENTURY_MAPPING["13"], CENTURY_MAPPING["14"]]``."""
    return [CENTURY_MAPPING[str(n)] for n in nums]


class ParseHistoricalDateTests(TestCase):
    """``parse_historical_date`` — bounds + century concept resolution."""

    # --- Empty / null inputs ----------------------------------------------

    def test_returns_empty_list_for_none_input(self):
        self.assertEqual(parse_historical_date(None), (None, None, []))

    def test_returns_empty_list_for_empty_string(self):
        self.assertEqual(parse_historical_date(""), (None, None, []))

    def test_returns_empty_list_for_whitespace_only(self):
        self.assertEqual(parse_historical_date("   "), (None, None, []))

    # --- Standard EDTF level 1 strings ------------------------------------

    def test_parses_single_year(self):
        start, end, centuries = parse_historical_date("1250")
        self.assertEqual(start, "1250-01-01")
        self.assertEqual(end, "1250-12-31")
        self.assertEqual(centuries, _C(13))

    def test_parses_edtf_interval_within_one_century(self):
        start, end, centuries = parse_historical_date("1200/1250")
        self.assertEqual(start, "1200-01-01")
        self.assertEqual(end, "1250-12-31")
        # Strict math: 1200 is the last year of the 12th c., 1201 the
        # first of the 13th. 1200/1250 therefore covers BOTH 12 and 13.
        self.assertEqual(centuries, _C(12, 13))

    def test_parses_decade_with_xx_pattern(self):
        # "12xx" → 1200-1299. Under strict math year 1200 lands in c.12
        # and year 1299 in c.13, so both centuries are returned.
        start, end, centuries = parse_historical_date("12xx")
        self.assertEqual(start, "1200-01-01")
        self.assertEqual(end, "1299-12-31")
        self.assertEqual(centuries, _C(12, 13))

    # --- Pre-normalised year ranges (hyphen / en-dash / em-dash) ----------

    def test_parses_year_range_with_hyphen(self):
        start, end, centuries = parse_historical_date("1200-1250")
        self.assertEqual(start, "1200-01-01")
        self.assertEqual(end, "1250-12-31")
        self.assertEqual(centuries, _C(12, 13))

    def test_parses_year_range_with_en_dash(self):
        start, end, centuries = parse_historical_date("1200–1250")
        self.assertEqual(start, "1200-01-01")
        self.assertEqual(end, "1250-12-31")
        self.assertEqual(centuries, _C(12, 13))

    def test_parses_year_range_with_em_dash(self):
        start, end, _ = parse_historical_date("1200—1250")
        self.assertEqual(start, "1200-01-01")
        self.assertEqual(end, "1250-12-31")

    def test_parses_year_range_with_spaces_around_dash(self):
        start, end, _ = parse_historical_date("1200 - 1250")
        self.assertEqual(start, "1200-01-01")
        self.assertEqual(end, "1250-12-31")

    # --- English natural language (text_to_edtf fallback) -----------------

    def test_parses_english_century_phrase(self):
        # "13th century" lands in some shape edtf understands — could be
        # 1200-1299 or 1201-1300 depending on edtf version. Either way
        # the 13th c. concept must be among the returned centuries.
        _, _, centuries = parse_historical_date("13th century")
        self.assertIn(CENTURY_MAPPING["13"], centuries)

    def test_parses_english_circa_phrase(self):
        _, _, centuries = parse_historical_date("circa 1250")
        self.assertEqual(centuries, _C(13))

    # --- French century idioms (explicitly NOT supported) -----------------

    def test_rejects_french_century_idiom(self):
        # Per module docstring: French century idioms are not handled
        # natively. edtf misinterprets "13e siècle" as day-of-month 13
        # (year 0000 → 9999). Plausibility check should reject this.
        self.assertEqual(parse_historical_date("13e siècle"), (None, None, []))

    # --- Plausibility window (edtf garbage rejection) ---------------------

    def test_rejects_year_below_plausible_window(self):
        # Year 50 is below _MIN_PLAUSIBLE_YEAR (100) — should be rejected.
        self.assertEqual(parse_historical_date("0050"), (None, None, []))

    def test_rejects_year_above_plausible_window(self):
        # Year 2200 is above _MAX_PLAUSIBLE_YEAR (2100).
        self.assertEqual(parse_historical_date("2200"), (None, None, []))

    def test_rejects_unparseable_garbage(self):
        self.assertEqual(parse_historical_date("not a date at all"), (None, None, []))

    # --- Century derivation rule ------------------------------------------

    def test_century_derivation_at_boundary_years(self):
        # Year 1300 → (1300-1) // 100 + 1 = 13 → 13th century.
        _, _, centuries = parse_historical_date("1300")
        self.assertEqual(centuries, _C(13))

        # Year 1301 → (1301-1) // 100 + 1 = 14 → 14th century.
        _, _, centuries = parse_historical_date("1301")
        self.assertEqual(centuries, _C(14))

    def test_century_derivation_for_first_century(self):
        # Year 100 → (100-1) // 100 + 1 = 1 → 1st century concept.
        _, _, centuries = parse_historical_date("100")
        self.assertEqual(centuries, _C(1))

    def test_century_derivation_for_twenty_first_century(self):
        _, _, centuries = parse_historical_date("2050")
        self.assertEqual(centuries, _C(21))

    # --- Integer / non-string inputs --------------------------------------

    def test_accepts_integer_year(self):
        # parse_historical_date stringifies its input.
        start, end, _ = parse_historical_date(1250)
        self.assertEqual(start, "1250-01-01")
        self.assertEqual(end, "1250-12-31")


class ParseCenturyTests(TestCase):
    """``parse_century`` — convenience wrapper returning the century list."""

    def test_returns_single_century_for_valid_year(self):
        self.assertEqual(parse_century("1250"), _C(13))

    def test_returns_empty_list_for_empty_input(self):
        self.assertEqual(parse_century(""), [])

    def test_returns_empty_list_for_unparseable_input(self):
        self.assertEqual(parse_century("garbage"), [])

    def test_returns_empty_list_for_french_idiom(self):
        self.assertEqual(parse_century("13e siècle"), [])

    # --- Complex inputs return the FULL century list ----------------------

    def test_cross_century_range_returns_both_centuries(self):
        # 1290-1310 → spans 13 and 14 → both concept valueids returned.
        self.assertEqual(parse_century("1290-1310"), _C(13, 14))

    def test_uncertain_interval_returns_both_centuries(self):
        self.assertEqual(parse_century("1290?-1310?"), _C(13, 14))

    def test_circa_returns_correct_century(self):
        self.assertEqual(parse_century("ca. 1250"), _C(13))

    def test_decade_pattern_returns_correct_century(self):
        # 125x → 1250-1259, both inside 13th c.
        self.assertEqual(parse_century("125x"), _C(13))

    def test_year_month_returns_correct_century(self):
        self.assertEqual(parse_century("1250-06"), _C(13))

    def test_one_of_set_returns_century_span(self):
        # [1250,1260,1270] → 1250-1270, all inside 13th c.
        self.assertEqual(parse_century("[1250,1260,1270]"), _C(13))


class ComplexEdtfDateTests(TestCase):
    """More involved EDTF inputs the connectors actually meet in the wild.

    Cross-century intervals (now resolving to **all** centuries spanned),
    approximate / uncertain markers, decade patterns, level-2 ``one-of``
    lists, English natural-language century qualifiers, and a few
    patterns we *don't* support so we can catch regressions if someone
    tries to "fix" them later.
    """

    # --- Cross-century year ranges ----------------------------------------

    def test_year_range_spanning_two_centuries_dash(self):
        # Hyphen form goes through _YEAR_RANGE_RE → "1290/1310" interval.
        # Strict math: 1290 → c.13, 1310 → c.14 → both centuries returned.
        start, end, centuries = parse_historical_date("1290-1310")
        self.assertEqual(start, "1290-01-01")
        self.assertEqual(end, "1310-12-31")
        self.assertEqual(centuries, _C(13, 14))

    def test_year_range_spanning_two_centuries_edtf_slash(self):
        start, end, centuries = parse_historical_date("1290/1310")
        self.assertEqual(start, "1290-01-01")
        self.assertEqual(end, "1310-12-31")
        self.assertEqual(centuries, _C(13, 14))

    def test_century_century_english_phrase(self):
        # edtf parses "13th-14th century" as 1300-1399 → strict math gives
        # 1300=c.13 and 1399=c.14, so both are returned.
        start, end, centuries = parse_historical_date("13th-14th century")
        self.assertEqual(centuries, _C(13, 14))
        self.assertTrue(start.startswith("13"))
        self.assertTrue(end.startswith("13"))

    def test_long_interval_spanning_three_centuries(self):
        # 1500/1700: 1500=c.15, 1700=c.17 → all three centuries returned.
        start, end, centuries = parse_historical_date("1500/1700")
        self.assertEqual(start, "1500-01-01")
        self.assertEqual(end, "1700-12-31")
        self.assertEqual(centuries, _C(15, 16, 17))

    def test_long_interval_century_aligned(self):
        # 1500/1600 → 1500=c.15, 1600=c.16. Both returned.
        _, _, centuries = parse_historical_date("1500/1600")
        self.assertEqual(centuries, _C(15, 16))

    # --- Uncertainty / approximation markers (EDTF level 1) ---------------

    def test_uncertain_year_with_question_mark(self):
        start, end, centuries = parse_historical_date("1250?")
        self.assertEqual(start, "1250-01-01")
        self.assertEqual(end, "1250-12-31")
        self.assertEqual(centuries, _C(13))

    def test_approximate_year_with_tilde(self):
        start, end, centuries = parse_historical_date("1250~")
        self.assertEqual(start, "1250-01-01")
        self.assertEqual(end, "1250-12-31")
        self.assertEqual(centuries, _C(13))

    def test_circa_english_phrase(self):
        start, end, centuries = parse_historical_date("ca. 1250")
        self.assertEqual(start, "1250-01-01")
        self.assertEqual(end, "1250-12-31")
        self.assertEqual(centuries, _C(13))

    def test_circa_english_range(self):
        start, end, centuries = parse_historical_date("circa 1250-1300")
        self.assertEqual(start, "1250-01-01")
        self.assertEqual(end, "1300-12-31")
        # 1250-1300 → both inside c.13 (1300 is last year of 13th).
        self.assertEqual(centuries, _C(13))

    def test_uncertain_interval_with_question_marks(self):
        start, end, centuries = parse_historical_date("1290?-1310?")
        self.assertEqual(start, "1290-01-01")
        self.assertEqual(end, "1310-12-31")
        self.assertEqual(centuries, _C(13, 14))

    def test_approximate_interval_with_tildes(self):
        start, end, centuries = parse_historical_date("1250~/1300~")
        self.assertEqual(start, "1250-01-01")
        self.assertEqual(end, "1300-12-31")
        self.assertEqual(centuries, _C(13))

    # --- Sub-year precision (year-month / full date) ----------------------

    def test_year_month(self):
        start, end, centuries = parse_historical_date("1250-06")
        self.assertEqual(start, "1250-06-01")
        self.assertEqual(end, "1250-06-30")
        self.assertEqual(centuries, _C(13))

    def test_full_iso_date(self):
        start, end, centuries = parse_historical_date("1250-06-15")
        self.assertEqual(start, "1250-06-15")
        self.assertEqual(end, "1250-06-15")
        self.assertEqual(centuries, _C(13))

    # --- Decade and unspecified-century patterns --------------------------

    def test_decade_pattern_with_x(self):
        # 125x → 1250-1259, both in c.13.
        start, end, centuries = parse_historical_date("125x")
        self.assertEqual(start, "1250-01-01")
        self.assertEqual(end, "1259-12-31")
        self.assertEqual(centuries, _C(13))

    def test_unspecified_century_pattern(self):
        # 12xx → 1200-1299. 1200=c.12, 1299=c.13 → BOTH centuries
        # under strict math. (The cultural label "13th century" only
        # corresponds to the upper end of the range.)
        start, end, centuries = parse_historical_date("12xx")
        self.assertEqual(start, "1200-01-01")
        self.assertEqual(end, "1299-12-31")
        self.assertEqual(centuries, _C(12, 13))

    # --- EDTF level 2 (one-of / set) --------------------------------------

    def test_one_of_set_returns_outer_bounds(self):
        start, end, centuries = parse_historical_date("[1250,1260,1270]")
        self.assertEqual(start, "1250-01-01")
        self.assertEqual(end, "1270-12-31")
        self.assertEqual(centuries, _C(13))

    # --- English natural-language century qualifiers ----------------------

    def test_early_century_phrase(self):
        # text_to_edtf collapses "early/late/mid 13th century" to the
        # full 1200-1299 interval → strict math returns [12, 13].
        _, _, centuries = parse_historical_date("early 13th century")
        self.assertIn(CENTURY_MAPPING["13"], centuries)

    def test_late_century_phrase(self):
        _, _, centuries = parse_historical_date("late 13th century")
        self.assertIn(CENTURY_MAPPING["13"], centuries)

    def test_mid_century_phrase(self):
        _, _, centuries = parse_historical_date("mid 13th century")
        self.assertIn(CENTURY_MAPPING["13"], centuries)

    # --- Inputs we explicitly do NOT support ------------------------------

    def test_unspecified_century_interval_not_supported(self):
        # "12xx/13xx" — interval of unspecified centuries. edtf can't
        # parse it; document the current behavior so a future "fix" that
        # changes it shows up in CI.
        self.assertEqual(parse_historical_date("12xx/13xx"), (None, None, []))

    def test_natural_language_between_phrase_not_supported(self):
        self.assertEqual(
            parse_historical_date("between 1200 and 1250"),
            (None, None, []),
        )

    def test_double_dot_range_not_supported(self):
        self.assertEqual(parse_historical_date("1200..1250"), (None, None, []))


class CenturyMappingTests(TestCase):
    """``CENTURY_MAPPING`` — sanity checks on the concept-id table."""

    def test_covers_centuries_one_through_twenty_one(self):
        for c in range(1, 22):
            self.assertIn(str(c), CENTURY_MAPPING)

    def test_all_values_are_uuid_strings(self):
        import uuid as _uuid

        for valueid in CENTURY_MAPPING.values():
            # Should not raise.
            _uuid.UUID(valueid)

    def test_values_are_unique(self):
        self.assertEqual(len(set(CENTURY_MAPPING.values())), len(CENTURY_MAPPING))


class CenturyConceptResolutionTests(TestCase):
    """End-to-end: parse a representative year for every century 1-21 and
    verify the resolved valueid list is the matching ``CENTURY_MAPPING``
    entry.

    This is the contract the Arches connectors actually depend on: feed a
    raw date string from Biblissima / Mandragore, get back the exact
    concept valueid the period thesaurus uses.
    """

    # Representative single year per century, chosen so the strict rule
    # ``(year - 1) // 100 + 1`` yields the labelled century unambiguously.
    REPRESENTATIVE_YEARS = {
        1: "0050",
        2: "0150",
        3: "0250",
        4: "0350",
        5: "0450",
        6: "0550",
        7: "0650",
        8: "0750",
        9: "0850",
        10: "0950",
        11: "1050",
        12: "1150",
        13: "1250",
        14: "1350",
        15: "1450",
        16: "1550",
        17: "1650",
        18: "1750",
        19: "1850",
        20: "1950",
        21: "2050",
    }

    def test_every_century_resolves_to_its_concept_valueid(self):
        # Centuries 1 and 2 fall below _MIN_PLAUSIBLE_YEAR (100) on the
        # lower bound, so they're rejected by the plausibility check.
        # Skip them — they're guarded by a separate test below.
        for century_num in range(3, 22):
            year = self.REPRESENTATIVE_YEARS[century_num]
            with self.subTest(century=century_num, year=year):
                _, _, centuries = parse_historical_date(year)
                self.assertEqual(
                    centuries,
                    [CENTURY_MAPPING[str(century_num)]],
                    msg=f"year {year} should resolve to {century_num}th c.",
                )

    def test_centuries_one_and_two_rejected_by_plausibility_window(self):
        # _MIN_PLAUSIBLE_YEAR = 100 — anything in years 1-99 is rejected,
        # which means the 1st c. concept is unreachable from a year in
        # that range. Year 100 lands in the 1st c. by the strict rule.
        self.assertEqual(parse_century("0050"), [])
        self.assertEqual(parse_century("100"), [CENTURY_MAPPING["1"]])

    def test_century_boundary_year_resolves_to_lower_century(self):
        # Year 1300 → (1300-1)//100+1 = 13 — last year of the 13th c.,
        # NOT the first of the 14th. This is the key invariant the
        # connector relies on.
        self.assertEqual(parse_century("1300"), [CENTURY_MAPPING["13"]])
        self.assertEqual(parse_century("1301"), [CENTURY_MAPPING["14"]])

    def test_century_concept_valueids_are_distinct_per_century(self):
        # Walk a sample of years across centuries; each must yield a
        # different concept valueid.
        seen = {}
        for century_num in range(3, 22):
            year = self.REPRESENTATIVE_YEARS[century_num]
            centuries = parse_century(year)
            self.assertEqual(len(centuries), 1)
            valueid = centuries[0]
            self.assertNotIn(
                valueid,
                seen,
                msg=(
                    f"year {year} (c.{century_num}) reuses valueid from "
                    f"c.{seen.get(valueid)}"
                ),
            )
            seen[valueid] = century_num

    def test_complex_input_lands_in_concept_table(self):
        # Whatever weird EDTF goes in, every returned valueid MUST be
        # present in CENTURY_MAPPING — never some other UUID.
        valid_valueids = set(CENTURY_MAPPING.values())
        for date_str in (
            "1250",
            "1290-1310",
            "1500/1600",
            "ca. 1250",
            "1250?",
            "1250~",
            "1250-06",
            "1250-06-15",
            "125x",
            "12xx",
            "1250~/1300~",
            "[1250,1260,1270]",
            "13th century",
            "early 13th century",
            "circa 1250-1300",
        ):
            with self.subTest(date_str=date_str):
                centuries = parse_century(date_str)
                self.assertGreater(
                    len(centuries), 0, msg=f"{date_str!r} returned empty list"
                )
                for v in centuries:
                    self.assertIn(v, valid_valueids)

    def test_unsupported_inputs_return_empty_list(self):
        # Garbage must yield [] — never a stray valueid.
        for bad in (
            "13e siècle",
            "12xx/13xx",
            "between 1200 and 1250",
            "1200..1250",
            "garbage",
            "9999",
        ):
            with self.subTest(bad=bad):
                self.assertEqual(parse_century(bad), [])

    def test_cross_century_returns_centuries_in_order(self):
        # Multi-century results must list centuries from low to high,
        # not as a set — order is meaningful for downstream display.
        centuries = parse_century("1290-1410")
        self.assertEqual(centuries, _C(13, 14, 15))
