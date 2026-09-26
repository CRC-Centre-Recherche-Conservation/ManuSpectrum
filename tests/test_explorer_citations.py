"""Dataset citations of the Analysis Explorer: Dataverse parsing, CSL-JSON, BibTeX, RIS, availability.

Usage:
    python manage.py test tests.test_explorer_citations --settings="tests.test_settings"
"""

import datetime
from unittest import mock

import bibtexparser
import rispy
from django.conf import settings
from django.test import SimpleTestCase
from pylatexenc.latexencode import unicode_to_latex

from manuspectrum.views.explorer.citations import (
    CitedAnalysis,
    Home,
    availability,
    citation_entries,
    citation_entry,
    dataset_id,
    _latex,
    parse_dataverse,
)

DATAVERSE = (
    'DOE, Jane; ROE, Richard; Lab Consortium, 2024, "Parchment spectra - test corpus", '
    "https://doi.org/10.1234/ABC/XYZ, data.Example, V2 "
)
DOI_URL = "https://doi.org/10.1234/ABC/XYZ"
ACCESSED = datetime.date(2026, 9, 26)
BASE = "https://manuspectrum.test/"


def analysis(n, *, start="2023-04-01", end=None, authors=(), projects=()):
    return CitedAnalysis(
        id=f"00000000-0000-4000-8000-00000000000{n}",
        name=f"XRF {n}",
        permalink=f"{BASE}report/00000000-0000-4000-8000-00000000000{n}",
        start=start,
        end=end,
        authors=tuple(authors),
        projects=tuple(projects),
    )


PROJECT = Home(
    "00000000-0000-4000-8000-0000000000a1",
    "Parchment project",
    f"{BASE}report/00000000-0000-4000-8000-0000000000a1",
)
DOCUMENT = Home(
    "00000000-0000-4000-8000-0000000000d1",
    "Ms 59",
    f"{BASE}report/00000000-0000-4000-8000-0000000000d1",
)


def dataverse_dataset(url=DOI_URL):
    return {"url": url, "isDoi": True, "label": DATAVERSE}


def walk(value):
    if isinstance(value, dict):
        for item in value.values():
            yield from walk(item)
    elif isinstance(value, list):
        for item in value:
            yield from walk(item)
    yield value


class DataverseTests(SimpleTestCase):
    def test_parses_a_complete_dataverse_citation(self):
        parsed = parse_dataverse(DATAVERSE)
        self.assertEqual(
            parsed.authors,
            (
                {"family": "DOE", "given": "Jane"},
                {"family": "ROE", "given": "Richard"},
                {"literal": "Lab Consortium"},
            ),
        )
        self.assertEqual(parsed.year, 2024)
        self.assertEqual(parsed.title, "Parchment spectra - test corpus")
        self.assertEqual(parsed.doi, "10.1234/abc/xyz")
        self.assertEqual(parsed.url, DOI_URL)
        self.assertEqual(parsed.publisher, "data.Example")
        self.assertEqual(parsed.version, "V2")

    def test_a_citation_without_version_is_complete(self):
        parsed = parse_dataverse(DATAVERSE.replace(", V2 ", ""))
        self.assertEqual(parsed.publisher, "data.Example")
        self.assertIsNone(parsed.version)

    def test_a_label_without_title_or_doi_is_not_a_dataverse_citation(self):
        self.assertIsNone(parse_dataverse("Parchment spectra on data.Example"))
        self.assertIsNone(parse_dataverse(DATAVERSE.replace(DOI_URL, "")))
        self.assertIsNone(parse_dataverse(DATAVERSE.replace('"', "")))
        self.assertIsNone(parse_dataverse(DATAVERSE.replace("2024, ", "")))
        self.assertIsNone(parse_dataverse(""))
        self.assertIsNone(parse_dataverse(None))

    def test_two_spellings_of_one_doi_have_one_dataset_id(self):
        self.assertEqual(
            dataset_id({"url": DOI_URL, "isDoi": True, "label": None}),
            dataset_id({"url": "10.1234/abc/xyz", "isDoi": True, "label": None}),
        )
        self.assertEqual(
            dataset_id(
                {"url": "https://example.org/data", "isDoi": False, "label": None}
            ),
            "https://example.org/data",
        )
        self.assertIsNone(dataset_id(None))


class EntryTests(SimpleTestCase):
    def entry(self, dataset, analyses, licences=("CC BY 4.0",), language="en"):
        return citation_entry(
            dataset,
            analyses,
            licences=list(licences),
            language=language,
            accessed=ACCESSED,
        )

    def test_the_recommended_text_is_the_dataverse_citation_when_complete(self):
        entry = self.entry(dataverse_dataset(), [analysis(1)])
        self.assertEqual(
            entry["recommended"],
            'DOE, Jane; ROE, Richard; Lab Consortium, 2024, "Parchment spectra - test corpus", '
            "https://doi.org/10.1234/ABC/XYZ, data.Example, V2",
        )
        self.assertEqual(entry["csl"]["title"], "Parchment spectra - test corpus")
        self.assertEqual(entry["csl"]["DOI"], "10.1234/abc/xyz")
        self.assertEqual(entry["csl"]["publisher"], "data.Example")
        self.assertEqual(entry["csl"]["version"], "V2")
        self.assertEqual(entry["csl"]["author"][2], {"literal": "Lab Consortium"})

    def test_issued_is_the_dataverse_year_and_absent_otherwise(self):
        complete = self.entry(dataverse_dataset(), [analysis(1)])
        self.assertEqual(complete["csl"]["issued"], {"date-parts": [[2024]]})
        self.assertIn("PY  - 2024", complete["ris"])
        self.assertEqual(
            bibtexparser.parse_string(complete["bibtex"]).entries[0]["year"], "2024"
        )
        for dataset in (
            None,
            {"url": DOI_URL, "isDoi": True, "label": "Parchment spectra"},
        ):
            with self.subTest(dataset=dataset):
                degraded = self.entry(
                    dataset, [analysis(1, authors=[{"literal": "A"}])]
                )
                self.assertNotIn("issued", degraded["csl"])
                self.assertNotIn("PY  -", degraded["ris"])
                self.assertNotIn(
                    "year", bibtexparser.parse_string(degraded["bibtex"]).entries[0]
                )

    def test_a_degraded_citation_has_no_empty_field(self):
        for dataset, cited in (
            (None, analysis(1, end=None, start=None)),
            (
                {"url": "https://example.org/d", "isDoi": False, "label": None},
                analysis(2),
            ),
        ):
            with self.subTest(dataset=dataset):
                entry = self.entry(dataset, [cited], licences=())
                for value in walk(entry["csl"]):
                    self.assertNotIn(value, ("", [], {}, None))
                self.assertNotRegex(entry["bibtex"], r"=\s*\{\s*\}")
                for line in entry["ris"].splitlines():
                    if line.strip() and not line.startswith("ER"):
                        self.assertRegex(line, r"^[A-Z0-9]{2}  - \S")
                for value in entry.values():
                    self.assertTrue(value)

    def test_a_record_citation_is_built_from_the_analysis_metadata(self):
        cited = analysis(
            1,
            end="2023-04-03",
            authors=[{"family": "Doe", "given": "Jane"}, {"literal": "CRC"}],
            projects=["Parchment project"],
        )
        entry = self.entry(None, [cited])
        csl = entry["csl"]
        self.assertEqual(csl["type"], "dataset")
        self.assertEqual(csl["id"], cited.id)
        self.assertEqual(csl["title"], "XRF 1")
        self.assertEqual(
            csl["author"], [{"family": "Doe", "given": "Jane"}, {"literal": "CRC"}]
        )
        self.assertEqual(csl["publisher"], settings.APP_TITLE)
        self.assertEqual(csl["URL"], cited.permalink)
        self.assertEqual(csl["collection-title"], "Parchment project")
        self.assertEqual(csl["license"], "CC BY 4.0")
        for text in (
            "Doe, Jane",
            "XRF 1",
            "Parchment project",
            settings.APP_TITLE,
            cited.permalink,
            "CC BY 4.0",
            "2026-09-26",
        ):
            self.assertIn(text, entry["recommended"])

    def test_a_dataset_without_a_complete_citation_titles_by_its_label(self):
        entry = self.entry(
            {"url": DOI_URL, "isDoi": True, "label": "Parchment spectra"},
            [analysis(1, authors=[{"literal": "Operator"}])],
        )
        self.assertEqual(entry["csl"]["title"], "Parchment spectra")
        self.assertEqual(entry["csl"]["DOI"], "10.1234/abc/xyz")
        self.assertEqual(entry["csl"]["URL"], DOI_URL)
        self.assertEqual(entry["csl"]["publisher"], settings.APP_TITLE)
        self.assertEqual(entry["csl"]["author"], [{"literal": "Operator"}])

    def test_event_date_is_the_measurement_range_and_accessed_the_given_day(self):
        entry = self.entry(
            dataverse_dataset(),
            [
                analysis(1, start="2023-04-02", end="2023-04-05"),
                analysis(2, start="2022-11", end=None),
            ],
        )
        self.assertEqual(
            entry["csl"]["event-date"], {"date-parts": [[2022, 11], [2023, 4, 5]]}
        )
        self.assertEqual(entry["csl"]["accessed"], {"date-parts": [[2026, 9, 26]]})
        self.assertIn("Y2  - 2026/09/26", entry["ris"])
        bib = bibtexparser.parse_string(entry["bibtex"]).entries[0]
        self.assertEqual(bib["urldate"], "2026-09-26")
        self.assertEqual(bib["eventdate"], "2022-11/2023-04-05")

    def test_one_measurement_day_is_one_event_date(self):
        entry = self.entry(None, [analysis(1, start="2023-04-01", end="2023-04-01")])
        self.assertEqual(entry["csl"]["event-date"], {"date-parts": [[2023, 4, 1]]})

    def test_bibtex_is_a_biblatex_dataset_entry(self):
        first = self.entry(dataverse_dataset(), [analysis(1)])
        again = self.entry(dataverse_dataset(), [analysis(1)])
        library = bibtexparser.parse_string(first["bibtex"])
        self.assertEqual(len(library.failed_blocks), 0)
        (bib,) = library.entries
        self.assertEqual(bib.entry_type, "dataset")
        self.assertRegex(bib.key, r"^doe2024[0-9a-f]{6}$")
        self.assertEqual(
            bib.key, bibtexparser.parse_string(again["bibtex"]).entries[0].key
        )
        self.assertEqual(
            bib["author"], "DOE, Jane and ROE, Richard and {Lab Consortium}"
        )
        self.assertEqual(bib["doi"], "10.1234/abc/xyz")
        self.assertEqual(bib["version"], "V2")

    def test_bibtex_escapes_latex_specials_in_curator_text(self):
        cited = CitedAnalysis(
            id="00000000-0000-4000-8000-000000000009",
            name="Fe & Cu 50% {x}",
            permalink=f"{BASE}report/x_y",
            start=None,
            end=None,
            authors=(),
        )
        bib = bibtexparser.parse_string(self.entry(None, [cited])["bibtex"])
        self.assertEqual(len(bib.failed_blocks), 0)
        (entry,) = bib.entries
        self.assertRegex(entry.key, r"^manuspectrumnd[0-9a-f]{6}$")
        self.assertIn(r"\&", entry["title"])
        self.assertIn(r"\%", entry["title"])
        self.assertEqual(entry["url"], f"{BASE}report/x_y")

    def test_ris_is_a_data_record(self):
        entry = self.entry(dataverse_dataset(), [analysis(1)])
        (record,) = rispy.loads(entry["ris"])
        self.assertEqual(record["type_of_reference"], "DATA")
        self.assertEqual(
            record["authors"], ["DOE, Jane", "ROE, Richard", "Lab Consortium"]
        )
        self.assertEqual(record["title"], "Parchment spectra - test corpus")
        self.assertEqual(record["doi"], "10.1234/abc/xyz")
        self.assertEqual(record["edition"], "V2")
        self.assertTrue(entry["ris"].startswith("TY  - DATA"))

    def test_the_parts_list_each_analysis_by_permalink(self):
        one, two = analysis(1), analysis(2)
        entry = self.entry(dataverse_dataset(), [one, two])
        note = entry["csl"]["note"]
        self.assertIn(f"XRF 1 ({one.permalink})", note)
        self.assertIn(f"XRF 2 ({two.permalink})", note)
        self.assertIn(one.permalink, entry["ris"])
        self.assertIn(
            two.permalink, bibtexparser.parse_string(entry["bibtex"]).entries[0]["note"]
        )


class EntriesTests(SimpleTestCase):
    def test_one_entry_per_dataset_deduplicated_by_doi(self):
        entries = citation_entries(
            [
                (dataverse_dataset(), [analysis(1)], ["CC BY 4.0"], PROJECT),
                (
                    {"url": "10.1234/abc/xyz", "isDoi": True, "label": DATAVERSE},
                    [analysis(2)],
                    ["CC0 1.0"],
                    DOCUMENT,
                ),
            ],
            language="en",
            accessed=ACCESSED,
        )
        self.assertEqual(len(entries), 1)
        self.assertIn(analysis(1).permalink, entries[0]["csl"]["note"])
        self.assertIn(analysis(2).permalink, entries[0]["csl"]["note"])

    def test_analyses_without_a_dataset_are_cited_once_per_home(self):
        entries = citation_entries(
            [
                (
                    None,
                    [analysis(1, projects=["Parchment project", "Ink survey"])],
                    ["CC BY 4.0"],
                    PROJECT,
                ),
                (dataverse_dataset(), [analysis(2)], [], PROJECT),
                (None, [analysis(3)], ["CC0 1.0"], PROJECT),
                (None, [analysis(4)], [], DOCUMENT),
                (None, [analysis(5)], [], DOCUMENT),
            ],
            language="en",
            accessed=ACCESSED,
        )

        self.assertEqual(
            [e["csl"]["id"] for e in entries],
            ["10.1234/abc/xyz", PROJECT.id, DOCUMENT.id],
        )
        for entry, home, parts in (
            (entries[1], PROJECT, (1, 3)),
            (entries[2], DOCUMENT, (4, 5)),
        ):
            self.assertEqual(entry["csl"]["title"], home.name)
            self.assertEqual(entry["csl"]["URL"], home.permalink)
            self.assertIn(home.permalink, entry["recommended"])
            for n in parts:
                self.assertIn(analysis(n).permalink, entry["csl"]["note"])
        self.assertEqual(entries[1]["csl"]["license"], "CC BY 4.0; CC0 1.0")
        self.assertEqual(entries[1]["csl"]["collection-title"], "Ink survey")
        self.assertEqual(entries[1]["recommended"].count("Parchment project"), 1)

    def test_a_grouped_citation_shows_the_count_and_the_home_only(self):
        one, two = analysis(1), analysis(2)
        entry = citation_entries(
            [(None, [one], [], PROJECT), (None, [two], [], PROJECT)],
            language="en",
            accessed=ACCESSED,
        )[0]

        note = bibtexparser.parse_string(entry["bibtex"]).entries[0]["note"]
        for shown in (note, entry["recommended"]):
            self.assertIn("2 analyses", shown)
            self.assertIn(PROJECT.permalink, shown)
        for cited in (one, two):
            self.assertNotIn(cited.permalink, entry["bibtex"])
            self.assertNotIn(cited.permalink, entry["recommended"])
            self.assertIn(cited.permalink, entry["csl"]["note"])
            self.assertIn(cited.permalink, entry["ris"])

    def test_one_analysis_without_a_dataset_is_cited_as_itself(self):
        entries = citation_entries(
            [(None, [analysis(1)], [], PROJECT), (None, [analysis(2)], [], None)],
            language="en",
            accessed=ACCESSED,
        )

        self.assertEqual(
            [e["csl"]["id"] for e in entries], [analysis(1).id, analysis(2).id]
        )
        self.assertEqual(entries[0]["csl"]["title"], "XRF 1")
        self.assertEqual(entries[0]["csl"]["URL"], analysis(1).permalink)


class LatexTests(SimpleTestCase):
    def test_pieces_are_encoded_like_the_whole(self):
        text = "Doe & Co; 50 % {x}; Æthelred — f. 1v_2; café #3; ~$"

        self.assertEqual(_latex(text), unicode_to_latex(text))

    def test_the_encoder_reads_one_part_at_a_time(self):
        parts = [analysis(n % 10) for n in range(500)]

        with mock.patch(
            "manuspectrum.views.explorer.citations.unicode_to_latex",
            wraps=unicode_to_latex,
        ) as encoder:
            citation_entries(
                [(None, parts, [], PROJECT)], language="en", accessed=ACCESSED
            )

        self.assertLess(max(len(call.args[0]) for call in encoder.call_args_list), 200)


class AvailabilityTests(SimpleTestCase):
    permalink = f"{BASE}report/00000000-0000-4000-8000-000000000001"

    def test_availability_names_manuspectrum_the_dataset_and_one_licence(self):
        expected = {
            "en": (
                f"The data are available in ManuSpectrum ({self.permalink}) and in "
                f"Parchment spectra - test corpus (https://doi.org/10.1234/abc/xyz), "
                f"under CC BY 4.0."
            ),
            "fr": (
                f"Les données sont disponibles dans ManuSpectrum ({self.permalink}) et dans "
                f"Parchment spectra - test corpus (https://doi.org/10.1234/abc/xyz), "
                f"sous licence CC BY 4.0."
            ),
        }
        for language, text in expected.items():
            with self.subTest(language=language):
                self.assertEqual(
                    availability(
                        [dataverse_dataset()],
                        licences=["CC BY 4.0", "CC BY 4.0"],
                        permalink=self.permalink,
                        language=language,
                    ),
                    text,
                )

    def test_availability_with_several_licences_points_to_each_file(self):
        expected = {
            "en": "under the licences given for each file.",
            "fr": "sous les licences indiquées pour chaque fichier.",
        }
        for language, ending in expected.items():
            with self.subTest(language=language):
                text = availability(
                    [dataverse_dataset()],
                    licences=["CC BY 4.0", "CC0 1.0"],
                    permalink=self.permalink,
                    language=language,
                )
                self.assertTrue(text.endswith(ending), text)

    def test_availability_without_dataset_or_file_names_manuspectrum_only(self):
        self.assertEqual(
            availability([None], licences=[], permalink=self.permalink, language="en"),
            f"The data are available in ManuSpectrum ({self.permalink}).",
        )
        self.assertEqual(
            availability([], licences=[], permalink=self.permalink, language="fr"),
            f"Les données sont disponibles dans ManuSpectrum ({self.permalink}).",
        )

    def test_the_entry_carries_the_availability_of_its_analyses(self):
        entry = citation_entry(
            dataverse_dataset(),
            [analysis(1)],
            licences=["CC BY 4.0"],
            language="en",
            accessed=ACCESSED,
        )
        self.assertEqual(
            entry["availability"],
            availability(
                [dataverse_dataset()],
                licences=["CC BY 4.0"],
                permalink=analysis(1).permalink,
                language="en",
            ),
        )
