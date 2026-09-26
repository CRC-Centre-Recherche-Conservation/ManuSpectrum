"""The data package of a scope: layout, metadata tables, citations, README and RO-Crate metadata.

Usage:
    python manage.py test tests.test_explorer_export_package --settings="tests.test_settings"
"""

import csv
import datetime
import io
import json
import re
from unittest import mock

from django.http import QueryDict

from tests.test_explorer_api import FETCH, MANIFEST_JSON, CorpusCase
from tests.test_explorer_service import XRF

from manuspectrum.views.explorer_export import (
    arcname,
    csv_bytes,
    package,
    ro_crate,
)
from manuspectrum.views.explorer_scopes import resolve_scope
from manuspectrum.views.explorer_service import permalink

IMAGING = "https://example.org/iiif/maxrf/manifest"
IMAGING_SOURCE = {
    "@context": "http://iiif.io/api/presentation/3/context.json",
    "id": IMAGING,
    "type": "Manifest",
    "label": {"none": ["maXRF X01"]},
    "items": [
        {
            "id": "https://example.org/iiif/maxrf/canvas/pb",
            "type": "Canvas",
            "label": {"none": ["Pb"]},
            "width": 100,
            "height": 100,
            "items": [],
        }
    ],
}
BY = {"id": "CC-BY-4.0", "url": "https://creativecommons.org/licenses/by/4.0/"}
ND = {"id": "CC-BY-ND-4.0", "url": "https://creativecommons.org/licenses/by-nd/4.0/"}
DOI = "https://doi.org/10.48579/PRO/ZEEJTH"
EXPORTED = datetime.date(2026, 9, 26)
SHA_SLOT = "0" * 64


def fetch(url, *args, **kwargs):
    return IMAGING_SOURCE if url == IMAGING else MANIFEST_JSON


class PackageCase(CorpusCase):
    def pk(self, key):
        return str(self.analyses[key].pk)

    def scope(self, query, user=None, language="en"):
        with mock.patch(FETCH, side_effect=fetch):
            return resolve_scope(QueryDict(query), user or self.anonymous, language)

    def package(self, query, user=None, language="en"):
        scope = self.scope(query, user, language)
        with mock.patch(FETCH, side_effect=fetch):
            return scope, package(scope, EXPORTED)

    def members(self, query, user=None, language="en"):
        return {m.arcname: m for m in self.package(query, user, language)[1]}

    def crate(self, query, user=None):
        scope, members = self.package(query, user)
        with mock.patch(FETCH, side_effect=fetch):
            graph = ro_crate(scope, members, EXPORTED)["@graph"]
        return {e["@id"]: e for e in graph}

    def document_query(self):
        return f"document={self.documents['open'].pk}"

    def text(self, member):
        return member.data.decode("utf-8-sig")

    def rows(self, member):
        return list(csv.DictReader(io.StringIO(self.text(member))))

    def data_members(self, members):
        return {name: m for name, m in members.items() if m.source is not None}

    def locate_elsewhere(self, name):
        analysis = self.new_resource("analysis", name)
        self.tile(analysis, "component_observed", self.refs(self.documents["open"]))
        return analysis


class ArcnameTests(PackageCase):
    def test_arcnames_cannot_escape_the_archive(self):
        taken = set()
        names = [
            "../x.csv",
            "/etc/passwd",
            "a\\b.csv",
            "\x00",
            ".hidden",
            "..",
            "x\x01y\x7f.csv",
            "",
        ]

        found = [
            arcname(["data", "ms-59-0c8226c1"], n, taken, "file-1a2b3c4d")
            for n in names
        ]

        for name in found:
            self.assertTrue(name.startswith("data/ms-59-0c8226c1/"), name)
            leaf = name.rsplit("/", 1)[1]
            self.assertTrue(leaf, name)
            self.assertFalse(leaf.startswith("."), name)
            self.assertNotIn("..", name.split("/"))
            self.assertIsNone(re.search(r"[\x00-\x1f\x7f\\]", name), name)
            self.assertEqual(name.count("/"), 2, name)
        self.assertEqual(found[0], "data/ms-59-0c8226c1/x.csv")
        self.assertEqual(found[1], "data/ms-59-0c8226c1/passwd")
        self.assertEqual(found[2], "data/ms-59-0c8226c1/b.csv")
        self.assertEqual(found[3], "data/ms-59-0c8226c1/file-1a2b3c4d")
        self.assertEqual(len(set(found)), len(found))

    def test_a_taken_name_gets_a_number_before_its_extension(self):
        taken = set()

        first = arcname(["data"], "X01.csv", taken, "file-1")
        second = arcname(["data"], "X01.csv", taken, "file-2")
        third = arcname(["data"], "x01.CSV", taken, "file-3")

        self.assertEqual(
            [first, second, third], ["data/X01.csv", "data/X01-2.csv", "data/x01-3.CSV"]
        )


class LayoutTests(PackageCase):
    def test_the_layout_follows_the_spec(self):
        self.stored_file(self.analyses["open"], "X01.csv", b"1,2\n3,4\n", licence=BY)
        elsewhere = self.locate_elsewhere("Y07 unlocated")
        self.stored_file(elsewhere, "Y07.txt", b"hello")

        members = self.members(f"ids=an:{self.pk('open')}:-,an:{elsewhere.pk}:-")

        document = f"ms-59-{str(self.documents['open'].pk)[:8]}"
        data = sorted(self.data_members(members))
        self.assertEqual(len(data), 2)
        self.assertRegex(
            data[0],
            rf"^data/{document}/f-1v-[0-9a-f]{{8}}/x01-f-1v-{self.pk('open')[:8]}/X01\.csv$",
        )
        self.assertEqual(
            data[1],
            f"data/{document}/unlocated/y07-unlocated-{str(elsewhere.pk)[:8]}/Y07.txt",
        )
        self.assertEqual(
            set(members) - set(data),
            {
                "README.md",
                "citations.bib",
                "citations.ris",
                "citations.json",
                "manifest.json",
                "metadata/analyses.csv",
                "metadata/analyses.json",
                "metadata/characterizations.csv",
                "metadata/characterizations.json",
            },
        )
        stored = members[data[0]]
        self.assertEqual(stored.size, 8)
        self.assertEqual(stored.analysis, self.pk("open"))
        self.assertEqual(stored.licence["id"], "CC-BY-4.0")

    def test_files_of_the_visitor_only(self):
        self.stored_file(self.analyses["embargoed"], "X02.csv", b"1,2\n")
        self.stored_file(self.analyses["open"], "X01.csv", b"1,2\n")
        self.embargo(self.analyses["embargoed"])

        members = self.members(
            f"ids=an:{self.pk('open')}:-,an:{self.pk('embargoed')}:-"
        )

        self.assertEqual(
            [m.analysis for m in self.data_members(members).values()],
            [self.pk("open")],
        )
        everything = b"".join(m.data or b"" for m in members.values()).decode(
            "utf-8-sig"
        )
        self.assertNotIn(self.pk("embargoed"), everything)
        self.assertNotIn("X02", everything)

    def test_a_manifest_over_its_bound_is_left_out_and_the_readme_says_why(self):
        with self.settings(EXPLORER_MANIFEST_MAX_CANVASES=0):
            members = self.members(self.document_query())

        self.assertNotIn("manifest.json", members)
        self.assertIn(
            "The IIIF manifest of this scope is too large",
            self.text(members["README.md"]),
        )

    def test_the_manifest_is_the_manifest_of_the_same_scope(self):
        members = self.members(self.document_query())

        manifest = json.loads(members["manifest.json"].data)
        self.assertEqual(manifest["type"], "Manifest")
        self.assertIn(f"document={self.documents['open'].pk}", manifest["id"])
        self.assertEqual(members["manifest.json"].media_type, "application/ld+json")


class TablesTests(PackageCase):
    def test_analyses_table_has_one_column_per_condition_type(self):
        self.tile_values(
            self.analyses["open"],
            "analysis",
            type_of_statement=self.reference_value(
                "http://vocab.getty.edu/aat/300386845", "configuration"
            ),
            content_of_statement=self.string_value("<p>50 kV &amp; 1 mA</p>"),
        )

        members = self.members(self.document_query())

        (row,) = [
            r
            for r in self.rows(members["metadata/analyses.csv"])
            if r["id"] == self.pk("open")
        ]
        self.assertEqual(row["conditions: configuration"], "50 kV & 1 mA")
        self.assertEqual(row["conditions"], "260 µm / 100 ms")
        self.assertEqual(row["name"], "X01 — f. 1v")
        self.assertEqual(row["technique"], "Portable XRF")
        self.assertEqual(row["technique_uri"], XRF)
        self.assertEqual(row["document"], "Ms 59")
        self.assertEqual(row["zone_canvas"], "f. 1v")
        self.assertEqual(json.loads(row["zone_shape"])["type"], "point")
        self.assertEqual(row["operators"], "Robinet, L.")
        self.assertEqual(row["date_start"], "2024-05-14")
        self.assertEqual(row["dataset"], DOI)
        self.assertEqual(row["permalink"], permalink(self.pk("open")))
        self.assertEqual(row["draft"], "false")
        rows = json.loads(members["metadata/analyses.json"].data)
        (as_json,) = [r for r in rows if r["id"] == self.pk("open")]
        self.assertEqual(as_json["conditions: configuration"], "50 kV & 1 mA")
        self.assertEqual(as_json["operators"], ["Robinet, L."])
        self.assertIs(as_json["draft"], False)

    def test_a_formula_like_cell_is_neutralised(self):
        hostile = self.locate_elsewhere('=HYPERLINK("http://evil","x")')

        members = self.members(f"ids=an:{hostile.pk}:-")

        (row,) = self.rows(members["metadata/analyses.csv"])
        self.assertFalse(row["name"].startswith("="), row["name"])
        self.assertIn('HYPERLINK("http://evil","x")', row["name"])
        (as_json,) = json.loads(members["metadata/analyses.json"].data)
        self.assertEqual(as_json["name"], '=HYPERLINK("http://evil","x")')

    def test_csv_bytes_open_with_a_byte_order_mark_and_join_lists(self):
        body = csv_bytes(["a", "b"], [{"a": ["x", "y"], "b": True}])

        self.assertTrue(body.startswith("﻿".encode()))
        self.assertEqual(
            list(csv.reader(io.StringIO(body.decode("utf-8-sig")))),
            [["a", "b"], ["x; y", "true"]],
        )

    def test_characterizations_list_only_visible_evidence(self):
        self.embargo(self.analyses["on_document"])

        members = self.members(self.document_query())

        body = self.text(members["metadata/characterizations.csv"])
        (row,) = self.rows(members["metadata/characterizations.csv"])
        self.assertEqual(row["id"], str(self.characterization.pk))
        self.assertEqual(row["evidence"], self.pk("open"))
        self.assertIn("Azurite", row["materials"])
        self.assertEqual(row["colours"], "Blue")
        self.assertEqual(row["permalink"], permalink(str(self.characterization.pk)))
        self.assertNotIn(self.pk("on_document"), body)

    def test_evidence_outside_the_scope_is_not_listed(self):
        members = self.members(
            f"ids=ch:{self.characterization.pk}:-,an:{self.pk('open')}:-"
        )

        (row,) = self.rows(members["metadata/characterizations.csv"])
        self.assertEqual(row["evidence"], self.pk("open"))

    def test_imaging_manifests_are_exported_as_json(self):
        self.tile(self.analyses["open"], "chemical_imaging_manifest", IMAGING)

        members = self.members(f"ids=an:{self.pk('open')}:-")

        (name,) = [n for n in members if n.endswith("imaging-1.json")]
        self.assertTrue(name.startswith("data/"), name)
        member = members[name]
        self.assertIsNone(member.source)
        self.assertEqual(json.loads(member.data), IMAGING_SOURCE)
        self.assertEqual(member.media_type, "application/ld+json")
        self.assertEqual(member.size, len(member.data))
        self.assertIn("IIIF", self.text(members["README.md"]))


class CitationFilesTests(PackageCase):
    def test_citations_come_from_the_generator_one_per_dataset(self):
        members = self.members(self.document_query())

        entries = json.loads(members["citations.json"].data)
        self.assertEqual(
            [e.get("DOI") for e in entries if e.get("DOI")], ["10.48579/pro/zeejth"]
        )
        self.assertEqual(len(entries), 3)
        self.assertEqual(self.text(members["citations.bib"]).count("@dataset"), 3)
        self.assertEqual(self.text(members["citations.ris"]).count("TY  - DATA"), 3)


class RoCrateTests(PackageCase):
    def test_ro_crate_has_the_descriptor_and_the_root_dataset(self):
        self.stored_file(self.analyses["open"], "X01.csv", b"1,2\n", licence=BY)
        scope, members = self.package(self.document_query())

        crate = ro_crate(scope, members, EXPORTED)

        self.assertEqual(crate["@context"], "https://w3id.org/ro/crate/1.1/context")
        graph = {e["@id"]: e for e in crate["@graph"]}
        descriptor = graph["ro-crate-metadata.json"]
        self.assertEqual(descriptor["@type"], "CreativeWork")
        self.assertEqual(
            descriptor["conformsTo"], {"@id": "https://w3id.org/ro/crate/1.1"}
        )
        self.assertEqual(descriptor["about"], {"@id": "./"})
        root = graph["./"]
        self.assertEqual(root["@type"], "Dataset")
        self.assertEqual(root["datePublished"], "2026-09-26")
        self.assertIn("Ms 59", root["name"])
        self.assertTrue(root["description"])
        self.assertEqual(
            {p["@id"] for p in root["hasPart"]}, {m.arcname for m in members}
        )
        self.assertNotIn("ro-crate-metadata.json", {m.arcname for m in members})

    def test_every_file_has_size_format_licence_and_a_fixed_width_sha256_slot(self):
        self.stored_file(self.analyses["open"], "X01.csv", b"1,2\n", licence=BY)
        self.stored_file(self.analyses["open"], "X01.mca", b"\x00\x01\x02")
        scope, members = self.package(self.document_query())

        graph = {e["@id"]: e for e in ro_crate(scope, members, EXPORTED)["@graph"]}

        for member in members:
            entity = graph[member.arcname]
            self.assertEqual(entity["@type"], "File")
            self.assertEqual(entity["contentSize"], str(member.size))
            self.assertEqual(entity["encodingFormat"], member.media_type)
            self.assertEqual(entity["sha256"], SHA_SLOT)
            if member.source is not None:
                self.assertIn("license", entity, member.arcname)
        (x01,) = [m for m in members if m.arcname.endswith("/X01.csv")]
        self.assertEqual(graph[x01.arcname]["license"], {"@id": BY["url"]})
        self.assertEqual(graph[x01.arcname]["encodingFormat"], "text/csv")
        self.assertEqual(graph[BY["url"]]["@type"], "CreativeWork")

    def test_one_create_action_per_analysis_with_its_technique_as_defined_term(self):
        self.stored_file(self.analyses["open"], "X01.csv", b"1,2\n", licence=BY)

        graph = self.crate(self.document_query())

        actions = [e for e in graph.values() if e["@type"] == "CreateAction"]
        self.assertEqual(
            {a["@id"] for a in actions},
            {permalink(self.pk(k)) for k in ("open", "on_document", "draft")},
        )
        action = graph[permalink(self.pk("open"))]
        self.assertEqual(action["additionalType"], {"@id": XRF})
        self.assertEqual(graph[XRF]["@type"], "DefinedTerm")
        self.assertEqual(graph[XRF]["name"], "Portable XRF")
        self.assertEqual(action["agent"], [{"@id": permalink(str(self.operator.pk))}])
        self.assertEqual(graph[permalink(str(self.operator.pk))]["@type"], "Person")
        self.assertEqual(action["startTime"], "2024-05-14")
        self.assertIn(
            {"@id": permalink(str(self.documents["open"].pk))}, action["object"]
        )
        self.assertIn(
            {"@id": permalink(str(self.components["open"].pk))}, action["object"]
        )
        (result,) = action["result"]
        self.assertTrue(result["@id"].endswith("/X01.csv"))
        self.assertNotIn("instrument", action)
        self.assertNotIn("location", action)

    def test_a_common_licence_or_licences_per_file(self):
        self.stored_file(self.analyses["open"], "X01.csv", b"1,2\n", licence=BY)
        self.stored_file(self.analyses["open"], "X01b.csv", b"1,2\n", licence=BY)
        query = f"ids=an:{self.pk('open')}:-"

        common = self.crate(query)
        self.stored_file(self.analyses["open"], "X01c.csv", b"1,2\n", licence=ND)
        mixed = self.crate(query)

        self.assertEqual(common["./"]["license"], {"@id": BY["url"]})
        per_file = mixed["./"]["license"]["@id"]
        self.assertEqual(mixed[per_file]["@type"], "CreativeWork")
        self.assertEqual(mixed[per_file]["name"], "Licences per file")

    def test_the_dataset_is_referenced_not_deposited_again(self):
        members = self.members(self.document_query())
        graph = self.crate(self.document_query())

        self.assertEqual(graph["./"]["isBasedOn"], [{"@id": DOI}])
        self.assertEqual(graph[DOI]["@type"], "Dataset")
        readme = self.text(members["README.md"])
        self.assertIn(DOI, readme)
        self.assertNotIn("deposit", readme.lower())


class ReadmeTests(PackageCase):
    def test_the_readme_names_contents_citation_licences_and_availability(self):
        self.stored_file(self.analyses["open"], "X01.csv", b"1,2\n", licence=BY)

        for language, heading, availability, licences in (
            ("en", "How to cite", "The data are available in", "Licences per file"),
            (
                "fr",
                "Comment citer",
                "Les données sont disponibles dans",
                "Licences par fichier",
            ),
        ):
            with self.subTest(language=language):
                members = self.members(self.document_query(), language=language)
                readme = self.text(members["README.md"])
                citations = json.loads(members["citations.json"].data)

                self.assertIn(heading, readme)
                self.assertIn(availability, readme)
                self.assertIn(licences, readme)
                for name in self.data_members(members):
                    self.assertIn(name, readme)
                self.assertIn("metadata/analyses.csv", readme)
                self.assertIn("ro-crate-metadata.json", readme)
                self.assertIn("CC BY 4.0", readme)
                self.assertIn(citations[0]["title"], readme)

    def test_drafts_and_restricted_inclusion_are_marked_in_the_readme(self):
        drafts = self.members(f"ids=an:{self.pk('draft')}:-")
        plain = self.members(f"ids=an:{self.pk('open')}:-")
        self.embargo(self.analyses["open"])
        restricted = self.members(
            f"ids=an:{self.pk('open')}:-&restricted=1", user=self.editor
        )
        french = self.members(f"ids=an:{self.pk('draft')}:-", language="fr")

        self.assertIn("Contains drafts", self.text(drafts["README.md"]))
        self.assertIn("Contient des brouillons", self.text(french["README.md"]))
        self.assertNotIn("Contains drafts", self.text(plain["README.md"]))
        self.assertNotIn("restricted", self.text(plain["README.md"]).lower())
        self.assertIn(
            "Contains restricted-access data", self.text(restricted["README.md"])
        )
        self.assertIn(self.pk("open"), self.text(restricted["metadata/analyses.csv"]))
