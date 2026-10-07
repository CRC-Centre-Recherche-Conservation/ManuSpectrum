import copy
import uuid
from io import StringIO
from unittest.mock import patch

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase, override_settings

from arches.app.models.models import (
    Concept,
    GraphModel,
    IIIFManifest,
    NodeGroup,
    ResourceInstance,
    TileModel,
    Value,
)
from arches_controlled_lists.models import List, ListItem

WEB = "http://dev.example:8000"
CANTALOUPE = "http://dev.example:8183"
NEW = "https://example.org/"
FROM = ("--from", WEB, "--from", CANTALOUPE)
EXTERNAL = "https://thesaurus.example.net/thesaurus/42"


def run(*args, families=()):
    out = StringIO()
    extra = [arg for family in families for arg in ("--family", family)]
    call_command("rewrite_dev_origin", *args, *extra, stdout=out)
    return out.getvalue()


def canvas_id(origin=CANTALOUPE, kind="canvas"):
    return f"{origin}/iiif/manifest/{kind}/{uuid.uuid4()}.json"


def manifest_json(canvas, name="page"):
    service = f"{WEB}/iiifserver/iiif/2/{name}.jpg"
    return {
        "@context": "http://iiif.io/api/presentation/2/context.json",
        "@id": f"{WEB}/manifest/{uuid.uuid4()}",
        "thumbnail": {"@id": service + "/full/!300,300/0/default.jpg"},
        "sequences": [
            {
                "@id": canvas.replace("canvas", "sequence"),
                "canvases": [
                    {
                        "@id": canvas,
                        "images": [
                            {
                                "on": canvas,
                                "resource": {
                                    "@id": service + "/full/full/0/default.jpg",
                                    "service": {"@id": service},
                                },
                            }
                        ],
                    }
                ],
            }
        ],
        "seeAlso": "https://gallica.example/ark:/x/manifest.json",
        "attribution": f"mirror of {WEB}/iiifserver/iiif/2/x",
    }


class Base(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.graph = GraphModel.objects.create(
            graphid=uuid.uuid4(),
            name="Rewrite",
            isresource=True,
            is_active=True,
            slug="rewrite-dev-origin-tests",
            resource_instance_lifecycle_id="7e3cce56-fbfb-4a4b-8e83-59b9f9e7cb75",
        )
        cls.group = NodeGroup.objects.create(nodegroupid=uuid.uuid4(), cardinality="n")

    def tile(self, data):
        resource = ResourceInstance.objects.create(graph=self.graph)
        return TileModel.objects.create(
            resourceinstance=resource, nodegroup_id=self.group.pk, data=data
        )

    def manifest(self, data):
        return IIIFManifest.objects.create(
            label="m", url=f"/manifest/{uuid.uuid4()}", manifest=data
        )

    @staticmethod
    def stored_tile(tile):
        return TileModel.objects.get(pk=tile.pk).data

    @staticmethod
    def stored_manifest(row):
        return IIIFManifest.objects.get(pk=row.pk).manifest


class ConceptTests(Base):
    def concept(self, legacyoid):
        return Concept.objects.create(legacyoid=legacyoid, nodetype_id="Concept")

    def test_legacyoid_of_a_dev_concept_is_rewritten(self):
        key = uuid.uuid4()
        row = self.concept(f"{WEB}/{key}")
        run(*FROM, "--to", NEW)
        self.assertEqual(Concept.objects.get(pk=row.pk).legacyoid, f"{NEW}{key}")

    def test_an_external_thesaurus_concept_is_untouched(self):
        row = self.concept(EXTERNAL)
        run(*FROM, "--to", NEW)
        self.assertEqual(Concept.objects.get(pk=row.pk).legacyoid, EXTERNAL)

    def test_identifier_values_of_every_origin_are_rewritten(self):
        concept = self.concept(EXTERNAL)
        keys = {}
        for origin in (WEB, "http://dev.example:8001"):
            key = uuid.uuid4()
            keys[origin] = Value.objects.create(
                concept=concept,
                valuetype_id="identifier",
                language_id="en",
                value=f"{origin}/{key}",
            )
        other = Value.objects.create(
            concept=concept,
            valuetype_id="prefLabel",
            language_id="en",
            value=f"{WEB}/not-an-identifier",
        )
        run(*FROM, "--from", "http://dev.example:8001", "--to", NEW)
        for origin, row in keys.items():
            stored = Value.objects.get(pk=row.pk).value
            self.assertTrue(stored.startswith(NEW), origin)
        self.assertEqual(Value.objects.get(pk=other.pk).value, other.value)


class ListTests(Base):
    def item(self, uri, vocab=None):
        vocab = vocab or List.objects.create(name=f"l{uuid.uuid4()}")
        return ListItem.objects.create(list=vocab, uri=uri, sortorder=0)

    def reference(self, uri):
        return [{"uri": uri, "labels": [], "list_id": str(uuid.uuid4())}]

    def test_item_uris_are_rewritten_and_the_tile_copy_follows(self):
        key = uuid.uuid4()
        old = f"{WEB}/plugins/controlled-list-manager/item/{key}"
        item = self.item(old)
        tile = self.tile({"node": self.reference(old)})
        run(*FROM, "--to", NEW)
        new = f"{NEW}plugins/controlled-list-manager/item/{key}"
        self.assertEqual(ListItem.objects.get(pk=item.pk).uri, new)
        self.assertEqual(self.stored_tile(tile)["node"][0]["uri"], new)

    def test_a_bare_uuid_uri_is_rewritten(self):
        key = uuid.uuid4()
        item = self.item(f"{WEB}/{key}")
        run(*FROM, "--to", NEW)
        self.assertEqual(ListItem.objects.get(pk=item.pk).uri, f"{NEW}{key}")

    def test_a_value_that_is_not_a_url_is_untouched(self):
        item = self.item("61149")
        external = self.item(EXTERNAL)
        run(*FROM, "--to", NEW)
        self.assertEqual(ListItem.objects.get(pk=item.pk).uri, "61149")
        self.assertEqual(ListItem.objects.get(pk=external.pk).uri, EXTERNAL)


class ManifestTests(Base):
    def test_image_service_thumbnail_and_own_ids_are_rewritten(self):
        row = self.manifest(manifest_json(canvas_id()))
        before = copy.deepcopy(row.manifest)
        run(*FROM, "--to", NEW)
        data = self.stored_manifest(row)
        base = "https://example.org/iiifserver/iiif/2/page.jpg"
        resource = data["sequences"][0]["canvases"][0]["images"][0]["resource"]
        self.assertEqual(resource["service"]["@id"], base)
        self.assertEqual(resource["@id"], base + "/full/full/0/default.jpg")
        self.assertEqual(
            data["thumbnail"]["@id"], base + "/full/!300,300/0/default.jpg"
        )
        self.assertTrue(data["@id"].startswith("https://example.org/manifest/"))
        self.assertEqual(data["seeAlso"], before["seeAlso"])
        self.assertEqual(data["attribution"], before["attribution"])
        self.assertEqual(data["@context"], before["@context"])
        data.pop("attribution")
        self.assertNotIn(WEB, str(data))
        self.assertNotIn(CANTALOUPE, str(data))

    def test_canvas_and_sequence_ids_move_under_the_iiifserver_prefix(self):
        key = uuid.uuid4()
        canvas = f"{CANTALOUPE}/iiif/manifest/canvas/{key}.json"
        row = self.manifest(manifest_json(canvas))
        run(*FROM, "--to", NEW)
        data = self.stored_manifest(row)
        sequence = data["sequences"][0]
        new = f"https://example.org/iiifserver/iiif/manifest/canvas/{key}.json"
        self.assertEqual(sequence["canvases"][0]["@id"], new)
        self.assertEqual(sequence["canvases"][0]["images"][0]["on"], new)
        self.assertEqual(
            sequence["@id"],
            f"https://example.org/iiifserver/iiif/manifest/sequence/{key}.json",
        )

    def test_web_origin_canvas_ids_get_the_same_mapping(self):
        canvas = canvas_id(WEB)
        row = self.manifest(manifest_json(canvas))
        run(*FROM, "--to", NEW)
        stored = self.stored_manifest(row)["sequences"][0]["canvases"][0]["@id"]
        self.assertEqual(stored, canvas.replace(WEB + "/", NEW + "iiifserver/"))

    def test_other_origin_is_untouched(self):
        row = self.manifest(manifest_json(canvas_id("http://elsewhere.example:8183")))
        data = row.manifest
        data["@id"] = "http://elsewhere.example/manifest/x"
        row.manifest = data
        row.save()
        run("--from", "http://nowhere.example", "--to", NEW)
        self.assertEqual(self.stored_manifest(row), data)


class CanvasConsistencyTests(Base):
    def test_a_tile_reference_and_the_manifest_canvas_become_the_same_string(self):
        for origin in (CANTALOUPE, WEB):
            with self.subTest(origin=origin):
                canvas = canvas_id(origin)
                row = self.manifest(manifest_json(canvas))
                tile = self.tile(
                    {"annotation": {"source": canvas}, "layers": [canvas, canvas]}
                )
                run(*FROM, "--to", NEW)
                in_manifest = self.stored_manifest(row)["sequences"][0]["canvases"][0][
                    "@id"
                ]
                data = self.stored_tile(tile)
                self.assertTrue(in_manifest.startswith(NEW))
                self.assertEqual(data["annotation"]["source"], in_manifest)
                self.assertEqual(data["layers"], [in_manifest, in_manifest])


class TileTests(Base):
    def test_only_strings_starting_with_an_origin_change(self):
        tile = self.tile(
            {
                "a": f"{WEB}/en/report/1",
                "b": [{"deep": f"{CANTALOUPE}/x"}],
                "c": f"see {WEB}/en/report/1",
                "d": "https://gallica.example/x",
                "e": 3,
                "f": None,
                "g": WEB,
            }
        )
        run(*FROM, "--to", NEW)
        data = self.stored_tile(tile)
        self.assertEqual(data["a"], f"{NEW}en/report/1")
        self.assertEqual(data["b"], [{"deep": f"{NEW}x"}])
        self.assertEqual(data["c"], f"see {WEB}/en/report/1")
        self.assertEqual(data["d"], "https://gallica.example/x")
        self.assertEqual((data["e"], data["f"], data["g"]), (3, None, WEB))

    def test_blob_urls_are_counted_and_never_rewritten(self):
        blob = f"blob:{WEB}/3b5d5c8e-0000-4000-8000-000000000000"
        html = f'<img src="{blob}">'
        tile = self.tile({"file": blob, "html": html, "url": f"{WEB}/x"})
        output = run(*FROM, "--to", NEW)
        data = self.stored_tile(tile)
        self.assertEqual((data["file"], data["html"]), (blob, html))
        self.assertIn("2 blob", output)

    def test_update_does_not_call_save(self):
        tile = self.tile({"a": f"{WEB}/x"})
        with patch.object(TileModel, "save", side_effect=AssertionError("save")):
            run(*FROM, "--to", NEW)
        self.assertEqual(self.stored_tile(tile)["a"], f"{NEW}x")


class CommandTests(Base):
    def seed(self):
        key = uuid.uuid4()
        return {
            "concept": Concept.objects.create(
                legacyoid=f"{WEB}/{key}", nodetype_id="Concept"
            ),
            "manifest": self.manifest(manifest_json(canvas_id())),
            "tile": self.tile({"a": f"{WEB}/x"}),
        }

    def snapshot(self, rows):
        return (
            Concept.objects.get(pk=rows["concept"].pk).legacyoid,
            self.stored_manifest(rows["manifest"]),
            self.stored_tile(rows["tile"]),
        )

    def test_dry_run_counts_and_writes_nothing(self):
        rows = self.seed()
        before = self.snapshot(rows)
        output = run(*FROM, "--to", NEW, "--dry-run")
        self.assertEqual(self.snapshot(rows), before)
        for family in ("concepts", "lists", "manifests", "tiles"):
            self.assertIn(f"{family}:", output)
        self.assertIn("would rewrite", output)
        self.assertNotIn("Follow-up", output)

    def test_second_run_changes_nothing(self):
        self.seed()
        first = run(*FROM, "--to", NEW)
        second = run(*FROM, "--to", NEW)
        self.assertNotIn("concepts: rewrote 0 string", first)
        for family in ("concepts", "manifests", "tiles"):
            self.assertIn(f"{family}: rewrote 0 string(s) in 0 row(s)", second)

    def test_family_limits_the_run(self):
        rows = self.seed()
        output = run(*FROM, "--to", NEW, families=("tiles",))
        legacyoid, manifest, tile = self.snapshot(rows)
        self.assertTrue(legacyoid.startswith(WEB))
        self.assertEqual(manifest, rows["manifest"].manifest)
        self.assertEqual(tile["a"], f"{NEW}x")
        self.assertIn("tiles:", output)
        self.assertNotIn("concepts:", output)

    def test_unknown_family_is_refused(self):
        with self.assertRaises(CommandError):
            run(*FROM, "--to", NEW, families=("nope",))

    def test_follow_up_steps_follow_a_real_run(self):
        self.seed()
        self.assertIn("es reindex_database", run(*FROM, "--to", NEW))

    @override_settings(PUBLIC_SERVER_ADDRESS="https://default.example/")
    def test_to_defaults_to_public_server_address(self):
        tile = self.tile({"a": f"{WEB}/x"})
        run(*FROM)
        self.assertEqual(self.stored_tile(tile)["a"], "https://default.example/x")

    def test_to_must_end_with_a_slash(self):
        with self.assertRaises(CommandError):
            run(*FROM, "--to", "https://example.org")

    def test_to_cannot_be_one_of_the_origins(self):
        with self.assertRaises(CommandError):
            run("--from", WEB, "--to", WEB + "/")

    def test_from_is_required_and_must_be_an_origin(self):
        with self.assertRaises(CommandError):
            run("--to", NEW)
        for bad in (
            "dev.example",
            "ftp://dev.example",
            f"{WEB}/",
            f"{WEB}/iiifserver",
            "http://",
            "",
        ):
            with self.subTest(bad=bad), self.assertRaises(CommandError):
                run("--from", bad, "--to", NEW)

    def test_output_names_counts_only(self):
        self.seed()
        output = run(*FROM, "--to", NEW)
        self.assertNotIn("http", output)
        self.assertNotIn("example", output)
