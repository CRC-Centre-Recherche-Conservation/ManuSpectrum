"""Guards for the export_pkg command.

The command writes a public repository from the database, so the tests pin the
two things that must never drift: the output is byte-stable, and nothing private
(origin, Mapbox key, e-mail, address, business data) can stay in it.
"""

import copy
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import uuid
from io import StringIO
from pathlib import Path
from unittest import mock

from arches.app.models.system_settings import settings
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import InternalError
from django.test import SimpleTestCase, TestCase
from rdflib import RDF, Graph, Literal, URIRef
from rdflib.namespace import DCTERMS, SKOS

from arches.app.models import models
from arches_controlled_lists.models import List, ListItem, ListItemValue
from arches_controlled_lists.utils.skos import ARCHES

from manuspectrum.management.commands import export_pkg
from manuspectrum.management.commands.export_pkg import (
    CORE_SETTINGS_JSON,
    SETTINGS_FILE,
    items_digest,
    list_digests,
    list_file_stems,
    render_skos,
    rewrite_origin,
    scan_for_leaks,
    slugify,
    values_digest,
)

ORIGIN = "https://manuspectrum.test/"
SETTINGS_NODES = {
    "app_name": "c5a2b94a-fadd-11e6-a029-6c4008b05c4c",
    "search_items_per_page": "d0987de3-fad8-11e6-a434-6c4008b05c4c",
    "mapbox_api_key": "0e9000b0-4148-11e7-bd19-c4b301baab9f",
}


def tree(root):
    root = Path(root)
    return {
        str(p.relative_to(root)): p.read_bytes()
        for p in sorted(root.rglob("*"))
        if p.is_file()
    }


def make_list(name, items=(), **kwargs):
    """items: (sortorder, parent index or None, {language: label}, uri)."""
    controlled_list = List.objects.create(id=uuid.uuid4(), name=name, **kwargs)
    made = []
    for sortorder, parent, labels, uri in items:
        item = ListItem.objects.create(
            id=uuid.uuid4(),
            uri=uri,
            list=controlled_list,
            sortorder=sortorder,
            parent=None if parent is None else made[parent],
        )
        for language, label in labels.items():
            ListItemValue.objects.create(
                id=uuid.uuid4(),
                list_item=item,
                valuetype_id="prefLabel",
                language_id=language,
                value=label,
            )
        made.append(item)
    return controlled_list, made


class RdfLanguageTests(SimpleTestCase):
    def test_a_plain_and_a_region_code_survive(self):
        for code in ("en", "fr", "pt-BR"):
            self.assertTrue(export_pkg.rdf_keeps_language(code), code)


class SlugTests(SimpleTestCase):
    def test_slug_keeps_only_safe_characters(self):
        self.assertEqual(
            slugify("AAT - Units : Weights and Lengths"),
            "aat_units_weights_and_lengths",
        )
        self.assertEqual(slugify("Échantillon / Été"), "echantillon_ete")

    def test_slug_is_restricted_to_the_safe_alphabet(self):
        self.assertRegex(slugify('..\\x:y*?"<>|/'), r"^[a-z0-9_-]*$")

    def test_colliding_slugs_get_the_id_head_and_stay_stable(self):
        a = mock.Mock(id=uuid.UUID(int=1), spec=["id", "name"])
        a.name = "Same Name"
        b = mock.Mock(id=uuid.UUID(int=2), spec=["id", "name"])
        b.name = "same name"
        c = mock.Mock(id=uuid.UUID(int=3), spec=["id", "name"])
        c.name = "Other"
        stems = list_file_stems([a, b, c])
        self.assertEqual(stems[a.id], f"same_name_{str(a.id)[:8]}")
        self.assertEqual(stems[b.id], f"same_name_{str(b.id)[:8]}")
        self.assertEqual(stems[c.id], "other")

    def test_a_name_without_letters_falls_back_to_the_id(self):
        lst = mock.Mock(id=uuid.UUID(int=5), spec=["id", "name"])
        lst.name = "???"
        self.assertEqual(list_file_stems([lst])[lst.id], str(lst.id))


class RenderSkosTests(SimpleTestCase):
    def graph(self, order):
        scheme = ARCHES["11111111-1111-4111-8111-111111111111"]
        concept = ARCHES["22222222-2222-4222-8222-222222222222"]
        child = ARCHES["33333333-3333-4333-8333-333333333333"]
        triples = [
            (scheme, RDF.type, SKOS.ConceptScheme),
            (scheme, DCTERMS.title, Literal("Lists & <more>")),
            (concept, RDF.type, SKOS.Concept),
            (concept, SKOS.inScheme, scheme),
            (concept, DCTERMS.identifier, Literal("https://example.org/a")),
            (concept, ARCHES.sortorder, Literal(3)),
            (concept, SKOS.narrower, child),
            (concept, SKOS.prefLabel, Literal('é "quoted"\nline\r two', lang="fr")),
            (concept, SKOS.prefLabel, Literal("plain", lang="en")),
            (concept, SKOS.scopeNote, Literal("  padded  ", lang="en")),
            (child, RDF.type, SKOS.Concept),
            (child, SKOS.broader, concept),
            (child, SKOS.inScheme, scheme),
        ]
        graph = Graph()
        for index in order(range(len(triples))):
            graph.add(triples[index])
        return graph

    def test_output_does_not_depend_on_insertion_order(self):
        forward = render_skos(self.graph(lambda r: list(r)))
        backward = render_skos(self.graph(lambda r: list(reversed(list(r)))))
        self.assertEqual(forward, backward)

    def test_output_parses_back_to_the_same_triples(self):
        graph = self.graph(lambda r: list(r))
        parsed = Graph().parse(data=render_skos(graph), format="xml")
        self.assertEqual(set(parsed), set(graph))

    def test_scheme_comes_first_and_namespace_is_declared(self):
        text = render_skos(self.graph(lambda r: list(r)))
        self.assertLess(text.index("ConceptScheme"), text.index("<skos:Concept "))
        self.assertIn(f'xmlns:arches="{ARCHES}"', text)

    def test_a_subject_without_a_type_is_refused(self):
        graph = Graph()
        graph.add((ARCHES["a"], SKOS.prefLabel, Literal("orphan", lang="en")))
        with self.assertRaisesMessage(CommandError, "exactly one rdf:type"):
            render_skos(graph)

    def test_a_subject_with_two_types_is_refused(self):
        graph = Graph()
        graph.add((ARCHES["a"], RDF.type, SKOS.Concept))
        graph.add((ARCHES["a"], RDF.type, SKOS.ConceptScheme))
        with self.assertRaisesMessage(CommandError, "exactly one rdf:type"):
            render_skos(graph)

    def test_a_character_xml_cannot_carry_is_refused(self):
        graph = Graph()
        graph.add((ARCHES["a"], RDF.type, SKOS.Concept))
        graph.add((ARCHES["a"], SKOS.note, Literal("bad \x0b char")))
        with self.assertRaises(CommandError):
            render_skos(graph)


class RenderAcrossProcessesTests(SimpleTestCase):
    """The unstable ordering of the stock serialiser came from the hash seed,
    which differs between processes only. The test database lives in a
    transaction no other process can see, so the whole export cannot run in a
    subprocess here; the renderer, the only place that orders the output, can."""

    SCRIPT = """
import hashlib, os, sys
os.environ["DJANGO_SETTINGS_MODULE"] = "tests.test_settings"
import django
django.setup()
from rdflib import RDF, Graph, Literal
from rdflib.namespace import DCTERMS, SKOS
from arches_controlled_lists.utils.skos import ARCHES
from manuspectrum.management.commands.export_pkg import render_skos
graph = Graph()
scheme = ARCHES["11111111-1111-4111-8111-111111111111"]
graph.add((scheme, RDF.type, SKOS.ConceptScheme))
graph.add((scheme, DCTERMS.title, Literal("Units")))
for n in range(40):
    item = ARCHES[f"00000000-0000-4000-8000-{n:012d}"]
    graph.add((item, RDF.type, SKOS.Concept))
    graph.add((item, SKOS.inScheme, scheme))
    graph.add((item, ARCHES.sortorder, Literal(n)))
    for lang in ("en", "fr", "de", "it"):
        graph.add((item, SKOS.prefLabel, Literal(f"{lang} {n}", lang=lang)))
        graph.add((item, SKOS.scopeNote, Literal(f"note {lang} {n}", lang=lang)))
sys.stdout.write(hashlib.sha256(render_skos(graph).encode()).hexdigest())
"""

    def digest(self, seed):
        result = subprocess.run(
            [sys.executable, "-c", self.SCRIPT],
            capture_output=True,
            text=True,
            env={**os.environ, "PYTHONHASHSEED": seed},
            cwd=Path(__file__).resolve().parent.parent,
        )
        self.assertEqual(result.returncode, 0, result.stderr[-2000:])
        return result.stdout.strip()[-64:]

    def test_the_rendering_does_not_depend_on_the_hash_seed(self):
        digests = {self.digest(seed) for seed in ("1", "2", "12345")}
        self.assertEqual(len(digests), 1, digests)
        self.assertEqual(len(digests.pop()), 64)


class DigestTests(SimpleTestCase):
    ROWS = [
        (uuid.UUID(int=1), None, 0),
        (uuid.UUID(int=2), None, 5),
        (uuid.UUID(int=3), uuid.UUID(int=1), 2),
    ]

    def test_digest_is_independent_of_row_order(self):
        self.assertEqual(
            list_digests(self.ROWS), list_digests(list(reversed(self.ROWS)))
        )

    def test_raw_digest_follows_the_sort_order_and_ranked_one_does_not(self):
        compacted = [(i, p, {0: 0, 5: 1, 2: 0}[s]) for i, p, s in self.ROWS]
        raw, ranked = list_digests(self.ROWS)
        raw2, ranked2 = list_digests(compacted)
        self.assertNotEqual(raw, raw2)
        self.assertEqual(ranked, ranked2)

    def test_digest_follows_the_parent(self):
        moved = [(i, None, s) for i, _, s in self.ROWS]
        self.assertNotEqual(list_digests(self.ROWS)[1], list_digests(moved)[1])

    def test_a_missing_sort_order_ranks_like_the_loader_default(self):
        rows = [(uuid.UUID(int=1), None, None), (uuid.UUID(int=2), None, 5)]
        explicit = [(uuid.UUID(int=1), None, 999999), (uuid.UUID(int=2), None, 5)]
        self.assertEqual(list_digests(rows)[1], list_digests(explicit)[1])


class ItemsDigestTests(SimpleTestCase):
    ROWS = DigestTests.ROWS

    def test_the_sort_order_and_the_row_order_do_not_matter(self):
        reordered = [(i, p, 99) for i, p, _ in reversed(self.ROWS)]
        self.assertEqual(items_digest(self.ROWS), items_digest(reordered))

    def test_a_moved_a_lost_or_a_new_item_changes_it(self):
        base = items_digest(self.ROWS)
        moved = [(i, None, s) for i, _, s in self.ROWS]
        renamed = [(uuid.UUID(int=9), *self.ROWS[0][1:])] + self.ROWS[1:]
        for rows in (
            moved,
            renamed,
            self.ROWS[:2],
            self.ROWS + [(uuid.UUID(int=7), None, 3)],
        ):
            self.assertNotEqual(items_digest(rows), base)


class ValuesDigestTests(SimpleTestCase):
    ROWS = [
        (uuid.UUID(int=1), "prefLabel", "en", "Gram"),
        (uuid.UUID(int=1), "prefLabel", "fr", "Gramme"),
        (uuid.UUID(int=2), "scopeNote", "en", "A note"),
    ]

    def test_digest_is_independent_of_row_order(self):
        self.assertEqual(
            values_digest(self.ROWS), values_digest(list(reversed(self.ROWS)))
        )

    def test_each_part_of_a_value_changes_the_digest(self):
        base = values_digest(self.ROWS)
        changes = [
            (0, (uuid.UUID(int=9), "prefLabel", "en", "Gram")),
            (0, (uuid.UUID(int=1), "altLabel", "en", "Gram")),
            (0, (uuid.UUID(int=1), "prefLabel", "de", "Gram")),
            (0, (uuid.UUID(int=1), "prefLabel", "en", "Gramm")),
        ]
        for index, row in changes:
            rows = list(self.ROWS)
            rows[index] = row
            self.assertNotEqual(values_digest(rows), base, row)

    def test_a_lost_value_changes_the_digest(self):
        self.assertNotEqual(values_digest(self.ROWS), values_digest(self.ROWS[:2]))


class ScanForLeaksTests(SimpleTestCase):
    def scan(self, files, key_node_id=None):
        with tempfile.TemporaryDirectory() as root:
            for name, content in files.items():
                path = Path(root) / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(content, encoding="utf-8")
            return scan_for_leaks(root, key_node_id)

    def rules(self, files, **kwargs):
        return {hit[1] for hit in self.scan(files, **kwargs)}

    def test_clean_tree_has_no_hit(self):
        self.assertEqual(
            self.scan({"a.xml": "https://vocab.getty.edu/aat/300 v8.1.5 10.1.2"}), []
        )

    def test_localhost_and_loopback(self):
        self.assertEqual(self.rules({"a": "http://localhost:8000/x"}), {"localhost"})
        self.assertEqual(
            self.rules({"a": "http://127.0.0.1/x"}),
            {"loopback or private IPv4 address"},
        )

    def test_private_ranges(self):
        for address in ("10.0.0.5", "172.16.3.4", "172.31.255.1", "192.168.1.20"):
            self.assertEqual(
                self.rules({"a": f"host {address} up"}),
                {"loopback or private IPv4 address"},
                address,
            )

    def test_public_and_lookalike_addresses_pass(self):
        for text in ("172.32.0.1", "8.8.8.8", "1.10.0.0.1", "version 2.10.1.2.3"):
            self.assertEqual(self.scan({"a": text}), [], text)

    def test_mapbox_token_is_masked(self):
        hits = self.scan({"a": "key pk.eyJ1IjoiYWJjZGVmZ2hpamtsbW5vcCJ9.abcdef"})
        self.assertEqual({hit[1] for hit in hits}, {"Mapbox token"})
        self.assertNotIn("eyJ1", hits[0][3])

    def test_mapbox_key_value(self):
        self.assertEqual(
            self.rules({"a.json": '{"mapbox_api_key": "abc"}'}), {"Mapbox key value"}
        )
        self.assertEqual(self.scan({"a.json": '{"mapbox_api_key": ""}'}), [])

    def test_email(self):
        self.assertEqual(
            self.rules({"a": "write to someone@example.org"}), {"e-mail address"}
        )

    def test_business_data_folder_with_content(self):
        self.assertEqual(
            self.rules({"business_data/files/a.json": "{}"}), {"business data"}
        )
        self.assertEqual(self.scan({"business_data/files/.gitkeep": ""}), [])

    def test_settings_key_set_in_any_language(self):
        node = "0e9000b0-4148-11e7-bd19-c4b301baab9f"

        def settings_file(value):
            tile = {"data": {node: value}}
            return json.dumps({"business_data": {"resources": [{"tiles": [tile]}]}})

        dirty = {SETTINGS_FILE.as_posix(): settings_file({"fr": {"value": "secret"}})}
        clean = {
            SETTINGS_FILE.as_posix(): settings_file(
                {"en": {"value": ""}, "fr": {"value": ""}}
            )
        }
        self.assertEqual(self.rules(dirty, key_node_id=node), {"Mapbox key value"})
        self.assertEqual(self.scan(clean, key_node_id=node), [])

    def test_git_directory_is_skipped(self):
        self.assertEqual(self.scan({".git/config": "http://localhost/"}), [])

    def test_local_ipv6_addresses(self):
        for address in ("::1", "fd12:3456:789a::1", "fc00::5", "fe80::1", "febf::2"):
            self.assertEqual(
                self.rules({"a": f"host [{address}]:80 up"}),
                {"loopback or private IPv6 address"},
                address,
            )

    def test_ipv6_lookalikes_pass(self):
        for text in (
            "2001:db8::1",
            "2606:4700:4700::1111",
            "at 12:34:56 today",
            "aa:bb:cc:dd:ee:ff",
            "ratio 3:1 or 10:30",
            "see skos:prefLabel and rdf:about",
            "fec0::1",
        ):
            self.assertEqual(self.scan({"a": text}), [], text)

    def test_local_host_names(self):
        for name in ("printer.local", "db.internal", "nas.home.lan", "Wiki.LAN"):
            self.assertEqual(
                self.rules({"a": f"see http://{name}/x"}), {"local host name"}, name
            )

    def test_local_host_name_lookalikes_pass(self):
        for text in (
            "the file.localized and a.internals",
            "a lan",
            "internal use only.",
            "localpath.landing",
            "x.lan-party.org",
        ):
            self.assertEqual(self.scan({"a": text}), [], text)

    def test_port_on_the_public_origin(self):
        origin = "https://manuspectrum.test/"
        for text in ("https://manuspectrum.test:8000/x", "manuspectrum.test:80"):
            self.assertEqual(
                {h[1] for h in self.scan_origin({"a": text}, origin)},
                {"port on the public origin"},
                text,
            )

    def test_port_lookalikes_pass(self):
        origin = "https://manuspectrum.test/"
        for text in (
            "https://manuspectrum.test:443/x",
            "https://manuspectrum.test/x",
            "https://other.test:8000/x",
            "https://xmanuspectrum.test:8000/x",
            "https://manuspectrum.test.example/x:8000",
        ):
            self.assertEqual(self.scan_origin({"a": text}, origin), [], text)

    def scan_origin(self, files, origin):
        with tempfile.TemporaryDirectory() as root:
            for name, content in files.items():
                (Path(root) / name).write_text(content, encoding="utf-8")
            return scan_for_leaks(root, origin=origin)

    def test_only_the_listed_files_are_read(self):
        with tempfile.TemporaryDirectory() as root:
            for name in ("written.txt", "foreign.txt"):
                (Path(root) / name).write_text("http://localhost/", encoding="utf-8")
            hits = scan_for_leaks(root, files=[Path("written.txt")])
        self.assertEqual([str(h[0]) for h in hits], ["written.txt"])

    def test_business_data_is_reported_even_for_listed_files(self):
        self.assertEqual(
            {h[1] for h in self.scan({"business_data/files/a.json": "{}", "b": ""})},
            {"business data"},
        )
        with tempfile.TemporaryDirectory() as root:
            (Path(root) / "business_data").mkdir()
            (Path(root) / "business_data" / "a.json").write_text("{}")
            (Path(root) / "b").write_text("clean")
            hits = scan_for_leaks(root, files=[Path("b")])
        self.assertEqual({h[1] for h in hits}, {"business data"})


class RewriteOriginTests(SimpleTestCase):
    def test_only_the_local_origin_is_replaced(self):
        with tempfile.TemporaryDirectory() as root:
            (Path(root) / "a.xml").write_text(
                'a="http://localhost:8000/x" b="https://getty.edu/http://localhost:80"',
                encoding="utf-8",
            )
            count = rewrite_origin(root, [Path("a.xml")], ORIGIN)
            text = (Path(root) / "a.xml").read_text(encoding="utf-8")
        self.assertEqual(count, 1)
        self.assertIn(f'a="{ORIGIN}x"', text)
        self.assertIn("http://localhost:80", text)


def make_root(graph):
    if not graph.node_set.filter(istopnode=True).exists():
        models.Node.objects.create(
            graph=graph,
            alias="root",
            name="root",
            datatype="semantic",
            istopnode=True,
        )


def make_widget_row(graph, widget=None):
    widget = widget or models.Widget.objects.first()
    make_root(graph)
    group = models.NodeGroup.objects.create(nodegroupid=uuid.uuid4())
    node = models.Node.objects.create(
        nodeid=group.pk,
        graph=graph,
        alias=f"n{uuid.uuid4().hex[:8]}",
        name="n",
        datatype="string",
        nodegroup=group,
        istopnode=False,
    )
    card = models.CardModel.objects.create(
        graph=graph, nodegroup=group, name="c", active=True
    )
    return models.CardXNodeXWidget.objects.create(
        card=card, node=node, widget=widget, config={}, label="l"
    )


class ExportPkgTests(TestCase):
    def setUp(self):
        for model in (List, ListItem, ListItemValue):
            for method in ("index", "delete_index"):
                if not hasattr(model, method):
                    continue
                patcher = mock.patch.object(model, method)
                patcher.start()
                self.addCleanup(patcher.stop)
        for code in ("en", "fr"):
            models.Language.objects.get_or_create(
                code=code,
                defaults={"name": code, "default_direction": "ltr", "scope": "system"},
            )
        self.system_settings_nodes()
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)

    def system_settings_nodes(self):
        """The test database has no System Settings model (`setup_db` loads it)."""
        graph, _ = models.GraphModel.objects.get_or_create(
            graphid=settings.SYSTEM_SETTINGS_RESOURCE_MODEL_ID,
            defaults={"name": "Arches System Settings", "isresource": True},
        )
        for alias, node_id in SETTINGS_NODES.items():
            group, _ = models.NodeGroup.objects.get_or_create(nodegroupid=node_id)
            models.Node.objects.get_or_create(
                nodeid=node_id,
                defaults={
                    "graph": graph,
                    "alias": alias,
                    "name": alias,
                    "datatype": "string",
                    "nodegroup": group,
                    "istopnode": False,
                },
            )

    def export(self, name="out", origin=ORIGIN, **kwargs):
        out = self.base / name
        stdout = StringIO()
        call_command(
            "export_pkg", out=str(out), public_origin=origin, stdout=stdout, **kwargs
        )
        return out

    def populate(self):
        return make_list(
            "AAT - Units : Weights",
            [
                (
                    0,
                    None,
                    {"en": "Gram", "fr": "Gramme"},
                    "http://localhost:8000/plugins/controlled-list-manager/item/x",
                ),
                (1, None, {"en": "Metre"}, "https://vocab.getty.edu/aat/300"),
                (0, 0, {"en": "Milligram"}, "https://vocab.getty.edu/aat/301"),
            ],
            searchable=True,
        )

    def test_two_runs_in_one_process_are_byte_identical(self):
        self.populate()
        make_list("Second", [(0, None, {"en": "One"}, "https://example.org/1")])
        first, second = self.export("one"), self.export("two")
        self.assertEqual(tree(first), tree(second))

    def test_layout_and_files(self):
        controlled_list, _ = self.populate()
        out = self.export()
        files = tree(out)
        self.assertIn("reference_data/controlled_lists/aat_units_weights.xml", files)
        self.assertIn("post_sql/controlled_lists_searchable.sql", files)
        self.assertIn("system_settings/System_Settings.json", files)
        self.assertIn("package_config.json", files)
        self.assertIn("expected-inventory.json", files)
        self.assertIn("map_layers/mapbox_spec_json/basemaps/.gitkeep", files)
        self.assertIn("map_layers/mapbox_spec_json/overlays/.gitkeep", files)
        self.assertTrue((out / "graphs" / "resource_models").is_dir())
        self.assertTrue((out / "graphs" / "branches").is_dir())
        sql = files["post_sql/controlled_lists_searchable.sql"].decode()
        self.assertIn(str(controlled_list.id), sql)

    def test_origin_is_rewritten_and_round_trips(self):
        controlled_list, items = self.populate()
        out = self.export()
        path = out / "reference_data/controlled_lists/aat_units_weights.xml"
        text = path.read_text(encoding="utf-8")
        self.assertNotIn("localhost", text)
        self.assertIn(f'xmlns:arches="{ORIGIN}"', text)
        parsed = Graph().parse(data=text, format="xml")
        item = URIRef(f"{ORIGIN}{items[0].id}")
        self.assertIn(
            (
                item,
                DCTERMS.identifier,
                Literal(f"{ORIGIN}plugins/controlled-list-manager/item/x"),
            ),
            parsed,
        )
        self.assertIn((item, SKOS.prefLabel, Literal("Gramme", lang="fr")), parsed)
        self.assertEqual(
            parsed.value(URIRef(f"{ORIGIN}{items[2].id}"), SKOS.broader), item
        )
        self.assertEqual(
            int(
                parsed.value(
                    URIRef(f"{ORIGIN}{items[1].id}"), URIRef(f"{ORIGIN}sortorder")
                )
            ),
            1,
        )

    def test_origin_must_be_https_with_trailing_slash(self):
        for origin in (
            "http://pkg.example/",
            "https://pkg.example",
            "https:///",
            "pkg.example/",
            "https://pkg.example/ x/",
        ):
            with self.subTest(origin=origin):
                with self.assertRaises(CommandError):
                    self.export(origin=origin)
        self.assertFalse((self.base / "out").exists())

    def test_non_empty_out_is_refused_unless_forced(self):
        out = self.base / "out"
        out.mkdir()
        (out / "README.md").write_text("keep me")
        with self.assertRaises(CommandError):
            self.export()
        self.export(force=True)
        self.assertEqual((out / "README.md").read_text(), "keep me")

    def test_force_clears_only_the_managed_folders(self):
        make_list("Old", [(0, None, {"en": "x"}, "https://example.org/x")])
        out = self.export()
        stale = out / "reference_data" / "controlled_lists" / "stale.xml"
        stale.write_text("stale")
        other = out / "ontologies" / "kept.rdf"
        other.parent.mkdir()
        other.write_text("kept")
        self.export(force=True)
        self.assertFalse(stale.exists())
        self.assertTrue(other.exists())

    def foreign_github_file(self, content):
        path = self.base / "out" / ".github" / "workflows" / "load.yml"
        path.parent.mkdir(parents=True)
        path.write_text(content)
        return path

    def test_a_foreign_file_with_localhost_does_not_fail_the_export(self):
        make_list("Old", [(0, None, {"en": "x"}, "https://example.org/x")])
        workflow = self.foreign_github_file(
            "PGHOST: localhost\nCONTACT: ci@example.invalid\n"
        )
        out = self.export(force=True)
        self.assertEqual(
            workflow.read_text(), "PGHOST: localhost\nCONTACT: ci@example.invalid\n"
        )
        self.assertTrue((out / "reference_data/controlled_lists/old.xml").exists())

    def test_a_leak_in_a_written_file_still_fails_beside_a_foreign_file(self):
        make_list(
            "Leaky",
            [(0, None, {"en": "see https://localhost/x"}, "https://example.org/l")],
        )
        workflow = self.foreign_github_file("PGHOST: localhost\n")
        with self.assertRaisesMessage(CommandError, "reference_data"):
            self.export(force=True)
        self.assertTrue(workflow.exists())
        self.assertFalse((self.base / "out" / export_pkg.LISTS_DIR).exists())

    def test_business_data_beside_foreign_files_is_still_refused(self):
        self.foreign_github_file("clean\n")
        (self.base / "out" / "business_data").mkdir()
        (self.base / "out" / "business_data" / "x.json").write_text("{}")
        with self.assertRaisesMessage(CommandError, "business data"):
            self.export(force=True)

    def test_a_port_on_the_public_origin_in_a_value_is_refused(self):
        make_list(
            "Ported",
            [
                (
                    0,
                    None,
                    {"en": "see https://manuspectrum.test:8000/x"},
                    "https://example.org/l",
                )
            ],
        )
        with self.assertRaisesMessage(CommandError, "port on the public origin"):
            self.export()

    def test_an_origin_with_a_value_type_name_is_refused(self):
        for origin in ("https://pkg.example/", "https://notes.test/"):
            with self.subTest(origin=origin):
                with self.assertRaisesMessage(CommandError, "value type name"):
                    self.export(origin=origin)

    def image_value(self, language):
        kind = models.DValueType.objects.filter(category="image").first()
        if kind is None:
            self.skipTest("the test database has no image value type")
        _, items = make_list("Img", [(0, None, {"en": "x"}, "https://example.org/g")])
        ListItemValue.objects.create(
            id=uuid.uuid4(),
            list_item=items[0],
            valuetype=kind,
            language_id=language,
            value="picture.png",
        )

    def test_an_image_value_is_refused(self):
        self.image_value("en")
        with self.assertRaisesMessage(CommandError, "cannot read"):
            self.export()

    def test_a_value_without_a_language_is_refused(self):
        self.image_value(None)
        with self.assertRaisesMessage(CommandError, "without a language"):
            self.export()

    def test_a_language_code_rdf_changes_is_refused(self):
        make_list("Odd", [(0, None, {"en": "x"}, "https://example.org/g")])
        with mock.patch.object(export_pkg, "rdf_keeps_language", return_value=False):
            with self.assertRaisesMessage(CommandError, "language code en"):
                self.export()

    def test_two_graphs_of_the_same_name_are_refused(self):
        for _ in range(2):
            models.GraphModel.objects.create(
                name="Same name", isresource=True, slug=f"same-{uuid.uuid4()}"
            )
        fake = mock.Mock()
        fake.export_graphs.side_effect = lambda dest, ids, kind: (
            Path(dest) / "Same name.json"
        ).write_text('{"graph": []}')
        with mock.patch.object(export_pkg, "PackagesCommand", return_value=fake):
            with self.assertRaisesMessage(CommandError, "overwrite one file"):
                self.export()

    def test_a_draft_does_not_count_as_a_graph_of_its_own(self):
        source = models.GraphModel.objects.create(
            name="Has a draft", isresource=True, slug="has-a-draft"
        )
        models.GraphModel.objects.create(
            name="Has a draft", isresource=True, source_identifier=source
        )
        fake = mock.Mock()
        fake.export_graphs.side_effect = lambda dest, ids, kind: (
            Path(dest) / "Has a draft.json"
        ).write_text('{"graph": [{"cards": []}]}')
        with mock.patch.object(export_pkg, "PackagesCommand", return_value=fake):
            with mock.patch.object(
                export_pkg.Command, "export_lists", side_effect=RuntimeError("stop")
            ):
                with self.assertRaisesMessage(RuntimeError, "stop"):
                    self.export()

    def test_a_value_changed_without_changing_a_count_changes_the_digest(self):
        controlled_list, items = make_list(
            "Digested", [(0, None, {"en": "Gram"}, "https://example.org/g")]
        )
        before = json.loads(
            (self.export("one") / "expected-inventory.json").read_text("utf-8")
        )["controlled_lists"]["per_list"][str(controlled_list.id)]
        ListItemValue.objects.filter(list_item=items[0]).update(value="Gramm")
        after = json.loads(
            (self.export("two") / "expected-inventory.json").read_text("utf-8")
        )["controlled_lists"]["per_list"][str(controlled_list.id)]
        self.assertEqual(before["values"], after["values"])
        self.assertNotEqual(before["digest_values"], after["digest_values"])
        self.assertEqual(len(before["digest_values"]), 64)

    def test_dynamic_list_is_refused(self):
        make_list("Dyn", dynamic=True)
        with self.assertRaisesMessage(CommandError, "Dynamic lists"):
            self.export()
        self.assertEqual(tree(self.base / "out"), {})

    def test_guide_item_is_refused(self):
        _, items = make_list("G", [(0, None, {"en": "x"}, "https://example.org/g")])
        ListItem.objects.filter(pk=items[0].pk).update(guide=True)
        with self.assertRaisesMessage(CommandError, "guide"):
            self.export()

    def test_leak_in_a_list_removes_the_written_files(self):
        make_list(
            "Leaky",
            [(0, None, {"en": "contact someone@example.org"}, "https://example.org/l")],
        )
        with self.assertRaisesMessage(CommandError, "e-mail address"):
            self.export()
        self.assertEqual(tree(self.base / "out"), {})

    def test_localhost_left_in_a_value_is_refused(self):
        make_list(
            "Leaky",
            [(0, None, {"en": "see https://localhost/x"}, "https://example.org/l")],
        )
        with self.assertRaisesMessage(CommandError, "localhost"):
            self.export()

    def test_private_address_in_a_value_is_refused(self):
        make_list(
            "Leaky", [(0, None, {"en": "on 192.168.1.4"}, "https://example.org/l")]
        )
        with self.assertRaisesMessage(CommandError, "private IPv4"):
            self.export()

    def test_business_data_content_is_refused(self):
        out = self.base / "out"
        (out / "business_data" / "files").mkdir(parents=True)
        (out / "business_data" / "files" / "x.json").write_text("{}")
        with self.assertRaisesMessage(CommandError, "business data"):
            self.export(force=True)

    def test_system_settings_key_is_emptied_in_every_language(self):
        document = json.loads(CORE_SETTINGS_JSON.read_text(encoding="utf-8"))
        key = str(
            models.Node.objects.get(
                graph_id=settings.SYSTEM_SETTINGS_RESOURCE_MODEL_ID,
                alias="mapbox_api_key",
            ).pk
        )
        dirty = copy.deepcopy(document)
        for tile in dirty["business_data"]["resources"][0]["tiles"]:
            if key in tile["data"]:
                tile["data"][key] = {
                    "en": {
                        "direction": "ltr",
                        "value": "pk.eyJ1IjoiYWJjZGVmZ2hpamtsbW5vcCJ9.abcdef",
                    },
                    "fr": {"direction": "ltr", "value": "another-key"},
                }
        source = self.base / "dirty.json"
        source.write_text(json.dumps(dirty), encoding="utf-8")
        with mock.patch.object(export_pkg, "CORE_SETTINGS_JSON", source):
            out = self.export()
        text = (out / SETTINGS_FILE).read_text(encoding="utf-8")
        self.assertNotIn("pk.", text)
        self.assertNotIn("another-key", text)
        written = json.loads(text)
        values = [
            tile["data"][key]
            for tile in written["business_data"]["resources"][0]["tiles"]
            if key in tile["data"]
        ]
        self.assertEqual(len(values), 1)
        self.assertEqual(set(values[0]), {code for code, _ in settings.LANGUAGES})
        self.assertTrue(all(v["value"] == "" for v in values[0].values()))

    def test_system_settings_carry_the_app_name_and_page_size(self):
        out = self.export()
        text = (out / SETTINGS_FILE).read_text(encoding="utf-8")
        written = json.loads(text)
        data = {}
        for tile in written["business_data"]["resources"][0]["tiles"]:
            data.update(tile["data"])
        nodes = dict(
            models.Node.objects.filter(
                graph_id=settings.SYSTEM_SETTINGS_RESOURCE_MODEL_ID,
                alias__in=["app_name", "search_items_per_page"],
            ).values_list("alias", "nodeid")
        )
        self.assertEqual(data[str(nodes["app_name"])]["en"]["value"], "Manuspectrum")
        self.assertEqual(data[str(nodes["search_items_per_page"])], 10)

    def test_core_map_rows_are_accepted_and_others_refused(self):
        self.assertEqual(export_pkg.non_core_map_rows(), [])
        self.export()
        models.MapLayer.objects.create(
            name="project-layer", layerdefinitions=[{"id": "x"}], icon=""
        )
        with self.assertRaisesMessage(CommandError, "project-layer"):
            self.export("again")

    def test_a_modified_core_map_source_is_refused(self):
        source = models.MapSource.objects.filter(name="mapbox-streets").first()
        if source is None:
            self.skipTest("the test database has no core map source")
        source.source = {"type": "vector", "url": "mapbox://changed"}
        source.save()
        with self.assertRaisesMessage(CommandError, "mapbox-streets"):
            self.export()

    def test_constraints_file_is_sorted_with_an_empty_load_order(self):
        nodes = list(
            models.Node.objects.filter(
                graph_id=settings.SYSTEM_SETTINGS_RESOURCE_MODEL_ID
            )[:2]
        )
        created = [
            models.Resource2ResourceConstraint.objects.create(
                resourceclassfrom=nodes[0], resourceclassto=nodes[1]
            )
            for _ in range(3)
        ]
        out = self.export()
        document = json.loads((out / "package_config.json").read_text("utf-8"))
        ids = [
            r["resource2resourceid"]
            for r in document["permitted_resource_relationships"]
        ]
        self.assertEqual(ids, sorted(ids))
        self.assertTrue({str(c.pk) for c in created} <= set(ids))
        self.assertEqual(document["business_data_load_order"], [])
        self.assertEqual(
            json.loads((out / "expected-inventory.json").read_text("utf-8"))[
                "resource_to_resource_constraints"
            ],
            len(ids),
        )

    def test_inventory_counts_and_digests(self):
        searchable, _ = self.populate()
        plain, _ = make_list("Plain", [(0, None, {"en": "a"}, "https://example.org/a")])
        first = self.export("one")
        inventory = json.loads((first / "expected-inventory.json").read_text("utf-8"))
        self.assertEqual(inventory["public_origin"], ORIGIN)
        lists = inventory["controlled_lists"]
        self.assertEqual(lists["lists"], List.objects.count())
        self.assertEqual(lists["items"], ListItem.objects.count())
        self.assertEqual(lists["values"], ListItemValue.objects.count())
        self.assertEqual(lists["searchable"], 1)
        entry = lists["per_list"][str(searchable.id)]
        self.assertEqual(entry["items"], 3)
        self.assertEqual(entry["values"], 4)
        self.assertTrue(entry["searchable"])
        self.assertEqual(len(entry["digest_sortorder"]), 64)
        again = json.loads(
            (self.export("two") / "expected-inventory.json").read_text("utf-8")
        )
        self.assertEqual(inventory, again)

        ListItem.objects.filter(list=plain).update(sortorder=7)
        changed = json.loads(
            (self.export("three") / "expected-inventory.json").read_text("utf-8")
        )
        before = lists["per_list"][str(plain.id)]
        after = changed["controlled_lists"]["per_list"][str(plain.id)]
        self.assertNotEqual(before["digest_sortorder"], after["digest_sortorder"])
        self.assertEqual(before["digest_sibling_rank"], after["digest_sibling_rank"])

    def test_graph_directories_are_listed_in_the_inventory(self):
        out = self.export()
        graphs = json.loads((out / "expected-inventory.json").read_text("utf-8"))[
            "graphs"
        ]
        self.assertEqual(
            graphs["resource_models"],
            sorted(p.name for p in (out / "graphs" / "resource_models").iterdir()),
        )
        self.assertEqual(
            graphs["branches"],
            sorted(p.name for p in (out / "graphs" / "branches").iterdir()),
        )

    def test_widgets_and_rows_per_graph_are_listed_in_the_inventory(self):
        widgets = list(models.Widget.objects.all()[:2])
        graph = models.GraphModel.objects.create(
            name="With widgets", isresource=True, slug="with-widgets"
        )
        make_widget_row(graph, widgets[0])
        make_widget_row(graph, widgets[0])
        make_widget_row(graph, widgets[1])
        inventory = json.loads(
            (self.export() / "expected-inventory.json").read_text("utf-8")
        )
        self.assertEqual(sorted(str(w.widgetid) for w in widgets), inventory["widgets"])
        self.assertEqual({str(graph.pk): 3}, inventory["widget_rows"])

    def test_a_draft_graph_widgets_are_not_inventoried(self):
        source = models.GraphModel.objects.create(
            name="Src", isresource=True, slug="src"
        )
        make_root(source)
        draft = models.GraphModel.objects.create(
            name="Src draft", isresource=True, source_identifier=source
        )
        make_widget_row(draft)
        inventory = json.loads(
            (self.export() / "expected-inventory.json").read_text("utf-8")
        )
        self.assertEqual([], inventory["widgets"])
        self.assertEqual({}, inventory["widget_rows"])

    def test_published_graphs_are_the_current_publications_per_language(self):
        graph = models.GraphModel.objects.create(
            name="Model", isresource=True, slug="model"
        )
        for code, _ in settings.LANGUAGES:
            models.Language.objects.get_or_create(
                code=code,
                defaults={"name": code, "default_direction": "ltr", "scope": "system"},
            )
        publications = [
            models.GraphXPublishedGraph.objects.create(
                graph=graph, notes="n", published_time="2026-01-01T00:00:00Z"
            )
            for _ in range(3)
        ]
        for publication in publications:
            for code, _ in settings.LANGUAGES:
                models.PublishedGraph.objects.create(
                    publication=publication, language_id=code, serialized_graph={}
                )
        models.GraphModel.objects.filter(pk=graph.pk).update(
            publication=publications[-1]
        )
        wanted = {f"Model|{code}" for code, _ in settings.LANGUAGES}
        self.assertEqual(export_pkg.published_pairs(), wanted)
        self.assertEqual(export_pkg.expected_published(), wanted)
        self.assertGreater(models.PublishedGraph.objects.count(), len(wanted))

    def test_a_graph_without_a_publication_is_expected_published_at_load(self):
        models.GraphModel.objects.create(name="Bare", isresource=True, slug="bare")
        self.assertEqual(export_pkg.published_pairs(), set())
        self.assertIn("Bare|en", export_pkg.expected_published())

    def test_the_database_is_read_inside_a_read_only_transaction(self):
        def write(command, out, lists):
            List.objects.create(id=uuid.uuid4(), name="written by the export")

        before = List.objects.count()
        with mock.patch.object(export_pkg.Command, "export_lists", write):
            with self.assertRaises(InternalError):
                self.export()
        self.assertEqual(List.objects.count(), before)

    def test_the_connection_is_writable_again_afterwards(self):
        self.export()
        List.objects.create(id=uuid.uuid4(), name="after")
        self.assertTrue(List.objects.filter(name="after").exists())
