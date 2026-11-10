"""The registry that imports remote IIIF manifests, the annotation receiver and the command."""

import io
import logging
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from unittest import mock

import requests
from django.contrib.auth.models import Group, User
from django.core.cache import cache
from django.core.management import call_command
from django.test import TestCase, TransactionTestCase, override_settings

from arches.app.models.models import (
    CardModel,
    GraphModel,
    IIIFManifest,
    Node,
    NodeGroup,
    ResourceInstance,
)
from arches.app.models.tile import Tile

from manuspectrum.iiif import sources
from manuspectrum.utils import manifest_registry as registry
from manuspectrum.utils.http import UnsafeURLError

from tests.test_manifest_datatype import resolves_publicly

URL = "https://example.org/iiif/book1/manifest"
SERVICE = "https://example.org/iiif/book1/page1"


def v2_manifest(label="Book 1", service=SERVICE):
    return {
        "@context": "http://iiif.io/api/presentation/2/context.json",
        "@type": "sc:Manifest",
        "@id": URL,
        "label": label,
        "sequences": [
            {
                "canvases": [
                    {
                        "@id": "https://example.org/canvas/1",
                        "images": [
                            {"resource": {"service": {"@id": service + "/"}}},
                        ],
                    }
                ]
            }
        ],
    }


def v3_manifest(service=SERVICE):
    return {
        "@context": "http://iiif.io/api/presentation/3/context.json",
        "type": "Manifest",
        "id": URL,
        "label": {"en": ["Book 3"]},
        "items": [
            {
                "items": [
                    {"items": [{"body": {"service": [{"id": service}]}}]},
                ]
            }
        ],
    }


def fetching(payload=None, error=None, delay=0):
    """Patch the registry's fetch: returns ``payload`` as JSON, or raises ``error``."""
    calls = []

    def fake(url, **kwargs):
        calls.append(url)
        if delay:
            time.sleep(delay)
        if error:
            raise error
        response = mock.MagicMock()
        response.json.return_value = payload
        return response

    patcher = mock.patch.object(registry, "fetch_iiif_manifest", side_effect=fake)
    patcher.calls = calls
    return patcher


def http_error(status):
    response = requests.Response()
    response.status_code = status
    return requests.HTTPError(response=response)


class RegistryCase(TestCase):
    def setUp(self):
        cache.clear()
        guard = resolves_publicly()
        guard.start()
        self.addCleanup(guard.stop)

    def register(self, payload, url=URL, **kwargs):
        with fetching(payload) as fetch:
            result = registry.register_remote_manifest(url, **kwargs)
        return result, fetch.call_count

    def refused(self, reason, url=URL, **kwargs):
        with self.assertRaises(registry.ManifestRegistrationError) as caught:
            registry.register_remote_manifest(url, **kwargs)
        self.assertEqual(caught.exception.reason, reason)


class RegisterOutcomeTests(RegistryCase):
    def test_registered_stores_url_label_and_json(self):
        (row, outcome), _ = self.register(v2_manifest())
        self.assertEqual(outcome, registry.REGISTERED)
        self.assertEqual((row.url, row.label), (URL, "Book 1"))
        self.assertEqual(row.manifest["@type"], "sc:Manifest")
        self.assertEqual(IIIFManifest.objects.filter(url=URL).count(), 1)

    def test_v3_label_from_language_map(self):
        (row, _), _ = self.register(v3_manifest())
        self.assertEqual(row.label, "Book 3")

    def test_label_falls_back_when_absent(self):
        payload = v2_manifest()
        del payload["label"]
        (row, _), _ = self.register(payload)
        self.assertEqual(row.label, "IIIF Manifest")

    def test_known_is_not_fetched(self):
        self.register(v2_manifest())
        (row, outcome), fetched = self.register(v2_manifest())
        self.assertEqual((outcome, fetched), (registry.KNOWN, 0))

    def test_known_through_normalized_variants(self):
        row = IIIFManifest.objects.create(url=URL, label="x", manifest={})
        for variant in (URL + "/", URL + "#page", URL + "/#x"):
            (found, outcome), fetched = self.register(v2_manifest(), url=variant)
            self.assertEqual((found, outcome, fetched), (row, registry.KNOWN, 0))

    def test_known_when_stored_with_trailing_slash(self):
        row = IIIFManifest.objects.create(url=URL + "/", label="x", manifest={})
        (found, outcome), _ = self.register(v2_manifest(), url=URL)
        self.assertEqual((found, outcome), (row, registry.KNOWN))

    def test_local_reference_is_never_fetched_nor_created(self):
        existing = IIIFManifest.objects.create(url="/x", label="x", manifest={})
        before = IIIFManifest.objects.count()
        (row, outcome), fetched = self.register(
            v2_manifest(), url=f"/manifest/{existing.globalid}"
        )
        self.assertEqual((row, outcome, fetched), (existing, registry.LOCAL, 0))
        (row, outcome), fetched = self.register(
            v2_manifest(), url=f"/manifest/{uuid.uuid4()}"
        )
        self.assertEqual((row, outcome, fetched), (None, registry.LOCAL, 0))
        self.assertEqual(IIIFManifest.objects.count(), before)

    @override_settings(
        PUBLIC_SERVER_ADDRESS="https://manuspectrum.test/",
        EXPLORER_LEGACY_HOSTS=("old.manuspectrum.test",),
    )
    def test_local_follows_the_legacy_host_rule(self):
        existing = IIIFManifest.objects.create(url="/x", label="x", manifest={})
        (row, outcome), fetched = self.register(
            v2_manifest(),
            url=f"https://old.manuspectrum.test/manifest/{existing.globalid}",
        )
        self.assertEqual((row, outcome, fetched), (existing, registry.LOCAL, 0))

    def test_invalid_url(self):
        self.refused(registry.INVALID_URL, url="not a url")

    def test_not_iiif(self):
        with fetching({"hello": "world"}):
            self.refused(registry.NOT_IIIF)
        self.assertFalse(IIIFManifest.objects.filter(url=URL).exists())

    def test_non_json_body_is_not_iiif(self):
        with fetching(error=ValueError("no json")):
            self.refused(registry.NOT_IIIF)

    def test_guard_refusal_is_rejected(self):
        with fetching(error=UnsafeURLError("private")):
            self.refused(registry.REJECTED)

    def test_http_4xx_is_rejected_and_5xx_unreachable(self):
        with fetching(error=http_error(404)):
            self.refused(registry.REJECTED)
        cache.clear()
        with fetching(error=http_error(503)):
            self.refused(registry.UNREACHABLE)

    def test_network_error_is_unreachable(self):
        with fetching(error=requests.ConnectionError("down")):
            self.refused(registry.UNREACHABLE)

    def test_unexpected_exception_is_not_swallowed(self):
        with fetching(error=RuntimeError("bug")):
            with self.assertRaises(RuntimeError):
                registry.register_remote_manifest(URL)


class ExpectedServiceTests(RegistryCase):
    def test_match_ignores_trailing_slash_v2_and_v3(self):
        for payload in (v2_manifest(), v3_manifest()):
            IIIFManifest.objects.filter(url=URL).delete()
            (row, outcome), _ = self.register(payload, expected_service=SERVICE + "/")
            self.assertEqual(outcome, registry.REGISTERED)

    def test_mismatch_stores_nothing(self):
        with fetching(v2_manifest()):
            self.refused(registry.CANVAS_MISMATCH, expected_service="https://other/x")
        self.assertFalse(IIIFManifest.objects.filter(url=URL).exists())


class FailureMemoTests(RegistryCase):
    def test_memo_stops_a_second_fetch(self):
        with fetching(error=requests.ConnectionError("down")) as fetch:
            self.refused(registry.UNREACHABLE)
            self.refused(registry.UNREACHABLE)
        self.assertEqual(fetch.call_count, 1)

    def test_bypass_fetches_again(self):
        with fetching(error=requests.ConnectionError("down")) as fetch:
            self.refused(registry.UNREACHABLE)
            self.refused(registry.UNREACHABLE, use_memo=False)
        self.assertEqual(fetch.call_count, 2)

    def test_not_iiif_and_mismatch_are_not_memoised(self):
        with fetching({"a": 1}) as fetch:
            self.refused(registry.NOT_IIIF)
            self.refused(registry.NOT_IIIF)
        self.assertEqual(fetch.call_count, 2)


class ConcurrencyTests(TransactionTestCase):
    def test_eight_threads_one_url_give_one_row(self):
        cache.clear()
        guard = resolves_publicly()
        guard.start()
        self.addCleanup(guard.stop)
        barrier = threading.Barrier(8)

        def run(_):
            from django.db import connection

            try:
                barrier.wait()
                return registry.register_remote_manifest(URL)[1]
            finally:
                connection.close()

        with fetching(v2_manifest(), delay=0.3):
            with ThreadPoolExecutor(8) as pool:
                outcomes = list(pool.map(run, range(8)))
        self.assertEqual(IIIFManifest.objects.filter(url=URL).count(), 1)
        self.assertEqual(outcomes.count(registry.REGISTERED), 1)
        self.assertEqual(outcomes.count(registry.KNOWN), 7)


class DatatypeSharesTheRowTests(RegistryCase):
    def test_facsimiles_reuses_the_registered_row_without_a_fetch(self):
        with mock.patch("arches.app.models.models.Widget") as widget:
            widget.objects.get.return_value = mock.MagicMock()
            from manuspectrum.datatypes.manifest import ManifestDataType

        (row, _), _ = self.register(v2_manifest())
        tile = mock.MagicMock()
        nodeid = str(uuid.uuid4())
        tile.data = {nodeid: URL}
        with fetching(v2_manifest()) as fetch:
            ManifestDataType().pre_tile_save(tile, nodeid)
        self.assertEqual(fetch.call_count, 0)
        self.assertEqual(tile.data[nodeid], f"/manifest/{row.globalid}")

    def test_registering_leaves_local_readers_unchanged(self):
        local = IIIFManifest.objects.create(
            url="/x", label="Local", manifest=v2_manifest("Local")
        )
        path = f"/manifest/{local.globalid}"
        before = (sources.manifest_json(path), sources.local_manifests([path]))
        self.register(v2_manifest())
        after = (sources.manifest_json(path), sources.local_manifests([path]))
        self.assertEqual(before, after)
        self.assertEqual(before[0]["label"], "Local")


# ---------------------------------------------------------------------------
# Receiver
# ---------------------------------------------------------------------------


def feature_collection(manifest=URL, canvas=SERVICE):
    return {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "properties": {"manifest": manifest, "canvas": canvas},
                "geometry": {"type": "Polygon", "coordinates": []},
            }
        ],
    }


class AnnotationFixtures(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.graph = GraphModel.objects.create(
            graphid=uuid.uuid4(), name="annot", isresource=True, is_active=True
        )
        cls.nodegroup = NodeGroup.objects.create(nodegroupid=uuid.uuid4())
        cls.annotation = cls._node("zone", "annotation")
        cls.other = cls._node("shape", "geojson-feature-collection")
        CardModel.objects.create(
            cardid=uuid.uuid4(), graph=cls.graph, nodegroup=cls.nodegroup, name="zone"
        )
        cls.resource = ResourceInstance.objects.create(graph=cls.graph)

    @classmethod
    def _node(cls, alias, datatype):
        return Node.objects.create(
            nodeid=uuid.uuid4(),
            graph=cls.graph,
            nodegroup=cls.nodegroup,
            name=alias,
            alias=alias,
            datatype=datatype,
            istopnode=False,
        )

    def setUp(self):
        cache.clear()
        guard = resolves_publicly()
        guard.start()
        self.addCleanup(guard.stop)

    def save(self, node, value, user=None):
        tile = Tile(
            resourceinstance_id=self.resource.pk,
            nodegroup_id=self.nodegroup.pk,
            data={str(self.annotation.pk): None, str(self.other.pk): None},
        )
        tile.data[str(node.pk)] = value
        tile.serialized_graph = {
            "nodes": [
                {"nodeid": str(self.annotation.pk), "datatype": "annotation"},
                {
                    "nodeid": str(self.other.pk),
                    "datatype": "geojson-feature-collection",
                },
            ],
            "cards": [],
            "widgets": [],
        }
        tile.save(index=False, user=user)
        return tile


class AnnotationReceiverTests(AnnotationFixtures):
    def saved(self, node, value, payload=None, **kwargs):
        """Save a tile and run the on-commit callbacks, returning the fetch patcher."""
        with fetching(payload or v2_manifest()) as fetch:
            with self.captureOnCommitCallbacks(execute=True):
                self.save(node, value, **kwargs)
        return fetch

    def test_annotation_save_registers_the_manifest(self):
        fetch = self.saved(self.annotation, feature_collection())
        row = IIIFManifest.objects.get(url=URL)
        self.assertEqual((row.label, fetch.call_count), ("Book 1", 1))

    def test_registration_waits_for_the_commit(self):
        with fetching(v2_manifest()) as fetch:
            with self.captureOnCommitCallbacks(execute=False):
                self.save(self.annotation, feature_collection())
        self.assertEqual(fetch.call_count, 0)

    def test_tile_data_is_not_rewritten(self):
        tile = None
        with fetching(v2_manifest()):
            with self.captureOnCommitCallbacks(execute=True):
                tile = self.save(self.annotation, feature_collection())
        stored = Tile.objects.get(pk=tile.pk).data[str(self.annotation.pk)]
        self.assertEqual(stored["features"][0]["properties"]["manifest"], URL)

    def test_non_annotation_node_registers_nothing(self):
        fetch = self.saved(self.other, feature_collection())
        self.assertEqual(fetch.call_count, 0)
        self.assertFalse(IIIFManifest.objects.filter(url=URL).exists())

    def test_provisional_save_registers_nothing(self):
        editor = User.objects.create_user("plain_editor", password="pw")
        fetch = self.saved(self.annotation, feature_collection(), user=editor)
        self.assertEqual(fetch.call_count, 0)
        self.assertFalse(IIIFManifest.objects.filter(url=URL).exists())

    def test_reviewer_save_registers(self):
        reviewer = User.objects.create_user("reviewer", password="pw")
        reviewer.groups.add(Group.objects.get(name="Resource Reviewer"))
        self.saved(self.annotation, feature_collection(), user=reviewer)
        self.assertTrue(IIIFManifest.objects.filter(url=URL).exists())

    def test_local_manifest_reference_registers_nothing(self):
        fetch = self.saved(
            self.annotation, feature_collection(manifest=f"/manifest/{uuid.uuid4()}")
        )
        self.assertEqual(fetch.call_count, 0)

    def test_fetch_failure_keeps_the_tile_and_logs_a_warning(self):
        with fetching(error=requests.ConnectionError("down")):
            with self.assertLogs("manuspectrum.manifests", logging.WARNING) as logs:
                with self.captureOnCommitCallbacks(execute=True):
                    tile = self.save(self.annotation, feature_collection())
        record = logs.records[0]
        self.assertEqual(record.levelno, logging.WARNING)
        self.assertEqual(
            (record.tile, record.user_id, record.url, record.outcome),
            (str(tile.pk), None, URL, registry.UNREACHABLE),
        )
        self.assertTrue(Tile.objects.filter(pk=tile.pk).exists())

    def test_unexpected_error_is_logged_and_swallowed(self):
        with mock.patch.object(
            registry, "register_remote_manifest", side_effect=RuntimeError("bug")
        ):
            with self.assertLogs("manuspectrum.manifests", logging.ERROR) as logs:
                with self.captureOnCommitCallbacks(execute=True):
                    tile = self.save(self.annotation, feature_collection())
        self.assertEqual(logs.records[0].outcome, "error")
        self.assertTrue(Tile.objects.filter(pk=tile.pk).exists())

    def test_registered_is_logged_at_info_with_the_numeric_user(self):
        request = mock.MagicMock()
        request.user = User.objects.create_user("someone", password="pw")
        with mock.patch("manuspectrum.signals.current_request", return_value=request):
            with self.assertLogs("manuspectrum.manifests", logging.INFO) as logs:
                self.saved(self.annotation, feature_collection())
        record = logs.records[0]
        self.assertEqual(
            (record.levelno, record.outcome, record.user_id),
            (logging.INFO, registry.REGISTERED, request.user.pk),
        )
        self.assertNotIn("someone", logs.output[0])


class RegisterManifestsCommandTests(AnnotationFixtures):
    def seed(self):
        with fetching(v2_manifest()):
            with self.captureOnCommitCallbacks(execute=False):
                self.save(self.annotation, feature_collection())

    def run_command(self, *args):
        out = io.StringIO()
        call_command("register_manifests", *args, stdout=out)
        return out.getvalue()

    def test_dry_run_writes_nothing(self):
        self.seed()
        with fetching(v2_manifest()) as fetch:
            report = self.run_command()
        self.assertEqual(fetch.call_count, 0)
        self.assertFalse(IIIFManifest.objects.filter(url=URL).exists())
        self.assertIn("would register\t1\t" + URL, report)

    def test_apply_registers_then_reports_known(self):
        self.seed()
        with fetching(v2_manifest()):
            report = self.run_command("--apply")
        self.assertIn("registered\t1\t" + URL, report)
        self.assertTrue(IIIFManifest.objects.filter(url=URL).exists())
        with fetching(v2_manifest()) as fetch:
            report = self.run_command("--apply")
        self.assertEqual(fetch.call_count, 0)
        self.assertIn("known\t1\t" + URL, report)

    def test_apply_bypasses_the_failure_memo_and_reports_failures(self):
        self.seed()
        with fetching(error=requests.ConnectionError("down")) as fetch:
            with self.assertRaises(registry.ManifestRegistrationError):
                registry.register_remote_manifest(URL)
            report = self.run_command("--apply")
        self.assertEqual(fetch.call_count, 2)
        self.assertIn("FAILED unreachable\t1\t" + URL, report)
