"""Unit tests for Task 3.4: ``BiblissimaCreateAllView`` (best-effort bulk create).

These are mock-ORM unit tests — no real graph, no DB writes. They assert the
ORCHESTRATION contract of the two-pass, best-effort ``create-all`` endpoint:

- happy path: N items -> N ``"created"`` results, ONE ``TileModel.bulk_create``,
  a single ``batch_tx`` shared across every ``_write_editlog`` and the
  post-commit ``index_resources_by_transaction`` call;
- Pass-1 buffer isolation: a failing item leaves ZERO residue in the in-process
  ``_tile_buffer`` (its tiles are dropped, no editlog, no survivor record) while
  the other items are ``"created"`` — exercised for ``requests.HTTPError(403)``,
  ``UnsafeURLError``, ``FailParsingManifestIIIF`` and ``TileValidationError``.
  NB: ``transaction.atomic`` is a no-op stub here, so this asserts Python-level
  buffer isolation, not a real DB SAVEPOINT rollback (DEV-VERIFY territory);
- Hole-2: a dangling dependency ref becomes a clean Pass-1 ``"failed"``;
- Hole-1: any Pass-2 failure returns HTTP 500 and never indexes;
- the dependency pre-pass is ONE query for the whole batch;
- the view uses the INHERITED primitives (no shadowing);
- degenerate inputs (empty items / bad resourceType / bad JSON).

Patching strategy
-----------------
``BiblissimaCreateAllView.post`` uses LOCAL imports for ``Resource``,
``DataTypeFactory`` and ``index_resources_by_transaction`` (patched at their
canonical source modules), and MODULE-LEVEL ``TileModel`` / ``ResourceInstance``
(patched via the proxy namespace). ``transaction.atomic`` is replaced with a
no-op context manager so the control flow is exercised without a DB connection
(the real SAVEPOINT/ROLLBACK is DEV-VERIFY territory — see the task report).

The write-path primitives are patched on the BASE class
(``BiblissimaCreateResourceView``) so that (a) the test can assert the subclass
inherits them unshadowed and (b) call counts / kwargs / order are observable.
The two tile builders are stubbed on the view instance to append a controlled
fake tile per item that references the item's ``rid``.

Run:
    /home/rayondemiel/venv/bin/python manage.py test \\
        tests.test_biblissima_createall_unit --settings="tests.test_settings" \\
        --noinput
"""

import json
import uuid
from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import requests
from django.test import TestCase

# ---------------------------------------------------------------------------
# Patch targets
# ---------------------------------------------------------------------------
PATCH_RESOURCE = "arches.app.models.resource.Resource"  # local import in post
PATCH_FACTORY = "arches.app.datatypes.datatypes.DataTypeFactory"  # local import
PATCH_INDEX = (
    "arches.app.utils.index_database.index_resources_by_transaction"  # local import
)
PATCH_TILEMODEL = "manuspectrum.views.biblissima_proxy.TileModel"  # module-level
PATCH_RI = "manuspectrum.views.biblissima_proxy.ResourceInstance"  # module-level
PATCH_ATOMIC = "django.db.transaction.atomic"

# A real Document graph id is not needed — GRAPH_IDS lookup only requires the
# resourceType to be Document/Component; _bulk_create_resources is mocked.


@contextmanager
def _noop_atomic(*args, **kwargs):
    """Stand-in for ``transaction.atomic()`` used as a context manager.

    Yields without touching a DB connection; exceptions propagate exactly as a
    real ``atomic`` block would re-raise them, so the inner (per-item) and outer
    (Pass-2) ``try/except`` control flow is faithfully exercised.
    """
    yield


def _fake_tile(rid):
    """A minimal tile-like object tagged with the item's resourceinstance id."""
    return SimpleNamespace(
        tileid=uuid.uuid4(),
        nodegroup_id="ng-fake",
        resourceinstance_id=rid,
        data={},
        parenttile=None,
        sortorder=0,
        _mspectrum_transaction_id=None,
    )


def _make_request(body_dict):
    """Build a minimal request object with ``.body`` (bytes) and ``.user``."""
    return SimpleNamespace(
        body=json.dumps(body_dict).encode("utf-8"),
        user=SimpleNamespace(
            id=1, username="importer", first_name="", last_name="", email=""
        ),
    )


def _item(client_id, dependencies=None):
    return {
        "clientId": client_id,
        "biblissimaData": {"label": f"Item {client_id}"},
        "dependencies": dependencies or {},
        "conceptMappings": {},
    }


class CreateAllBase(TestCase):
    """Common patch harness for ``BiblissimaCreateAllView.post`` orchestration."""

    def setUp(self):
        from manuspectrum.views.biblissima_proxy import (
            BiblissimaCreateAllView,
            BiblissimaCreateResourceView,
        )

        self.BiblissimaCreateAllView = BiblissimaCreateAllView
        self.BiblissimaCreateResourceView = BiblissimaCreateResourceView

        # Source-module / proxy-namespace patches.
        self.mock_resource_cls = self._start(patch(PATCH_RESOURCE))
        self.mock_factory = self._start(patch(PATCH_FACTORY))
        self.mock_index = self._start(patch(PATCH_INDEX))
        self.mock_tilemodel = self._start(patch(PATCH_TILEMODEL))
        self.mock_ri = self._start(patch(PATCH_RI))
        self._start(patch(PATCH_ATOMIC, new=_noop_atomic))

        # Hoisted serialized graph -> nodes_by_id == {} (harmless: primitives
        # that would read it are patched below).
        self.mock_resource_cls.return_value.get_serialized_graph.return_value = {
            "nodes": []
        }
        # Survivor fetch: Resource.objects.select_related(...).get(pk=rid).
        self.mock_survivor_resource = MagicMock(name="survivor_resource")
        (
            self.mock_resource_cls.objects.select_related.return_value.get.return_value
        ) = self.mock_survivor_resource

        # _precollect_valid_dep_ids default: no deps exist unless a test wires it.
        self.mock_ri.objects.filter.return_value.values_list.return_value = []

        # Base-class primitive patches (subclass inherits them unshadowed).
        self.created_rids = []

        def _bulk_create(graph_id, n, user):
            rid = uuid.uuid4()
            self.created_rids.append(rid)
            return [rid]

        self.mock_bulk_create = self._start(
            patch.object(
                BiblissimaCreateResourceView,
                "_bulk_create_resources",
                side_effect=_bulk_create,
            )
        )
        self.mock_collect = self._start(
            patch.object(
                BiblissimaCreateResourceView,
                "_collect_valid_concepts",
                return_value=set(),
            )
        )
        self.mock_validate = self._start(
            patch.object(BiblissimaCreateResourceView, "_validate_tiles")
        )
        self.mock_run_hook = self._start(
            patch.object(BiblissimaCreateResourceView, "_run_hook")
        )
        self.mock_batch_desc = self._start(
            patch.object(BiblissimaCreateResourceView, "_batch_save_descriptors")
        )
        self.mock_write_editlog = self._start(
            patch.object(BiblissimaCreateResourceView, "_write_editlog")
        )
        self.mock_link = self._start(
            patch.object(BiblissimaCreateResourceView, "_link_to_project_batch")
        )

        # Fresh view; stub the two builders on the instance to append a fake
        # tile per item (referencing the rid passed by post()).
        self.view = BiblissimaCreateAllView()

        def _fake_builder(rid, tx, bbma_data, deps, concepts, created_deps):
            self.view._tile_buffer.append(_fake_tile(rid))

        self.view._create_document_tiles = _fake_builder
        self.view._create_component_tiles = _fake_builder

    def _start(self, patcher):
        mock = patcher.start()
        self.addCleanup(patcher.stop)
        return mock

    def _post(self, body_dict):
        response = self.view.post(_make_request(body_dict))
        payload = json.loads(response.content)
        return response, payload


# ===========================================================================
# Happy path
# ===========================================================================


class HappyPathTests(CreateAllBase):
    def test_happy_path_all_created(self):
        items = [_item("c0"), _item("c1"), _item("c2")]
        # captureOnCommitCallbacks(execute=True) fires transaction.on_commit
        # callbacks immediately so that _defer_indexing's sync fallback runs
        # inside the test (BIBLISSIMA_ASYNC_INDEXING=False by default in tests).
        with self.captureOnCommitCallbacks(execute=True):
            response, payload = self._post(
                {"resourceType": "Document", "items": items}
            )

        self.assertEqual(response.status_code, 200)
        results = payload["results"]
        self.assertEqual(len(results), 3)
        for r in results:
            self.assertEqual(r["status"], "created")
            self.assertIn("resourceId", r)
            # resourceId parses as a UUID
            uuid.UUID(r["resourceId"])
        # clientIds preserved in order
        self.assertEqual([r["clientId"] for r in results], ["c0", "c1", "c2"])

        # ONE bulk insert of all survivor tiles (3 tiles).
        self.mock_tilemodel.objects.bulk_create.assert_called_once()
        inserted = self.mock_tilemodel.objects.bulk_create.call_args.args[0]
        self.assertEqual(len(inserted), 3)

        # One editlog per survivor, all under a single shared batch_tx.
        self.assertEqual(self.mock_write_editlog.call_count, 3)
        txs = {c.args[3] for c in self.mock_write_editlog.call_args_list}
        self.assertEqual(len(txs), 1, "all survivors must share one batch_tx")
        batch_tx = txs.pop()

        # Indexed exactly once, post-commit, by that same batch_tx.
        # _defer_indexing's sync fallback (BIBLISSIMA_ASYNC_INDEXING=False)
        # passes recalculate_descriptors=True to match the async task's behaviour.
        self.mock_index.assert_called_once_with(
            str(batch_tx), recalculate_descriptors=True
        )

    def test_descriptors_and_hooks_run_once_for_survivors(self):
        items = [_item("c0"), _item("c1")]
        self._post({"resourceType": "Component", "items": items})

        # post_tile_save + pre_tile_save both go through the inherited _run_hook.
        methods = [c.args[3] for c in self.mock_run_hook.call_args_list]
        self.assertEqual(methods.count("pre_tile_save"), 2)  # one per item
        self.assertEqual(methods.count("post_tile_save"), 1)  # once for the batch
        # One descriptor refresh call for the whole survivor batch.
        self.mock_batch_desc.assert_called_once()
        ordered = self.mock_batch_desc.call_args.args[0]
        self.assertEqual(len(ordered), 2)


# ===========================================================================
# Pass-1 buffer isolation
# ===========================================================================


class BufferIsolationTests(CreateAllBase):
    """Per-item failure isolation, asserted at the PYTHON BUFFER level.

    ``transaction.atomic`` is patched to a no-op here (see the module docstring),
    so these tests do NOT exercise a real DB SAVEPOINT/ROLLBACK. What they DO
    assert is that a failing item leaves zero residue in the in-process
    ``_tile_buffer`` (its staged tiles are deleted), writes no editlog, and does
    not appear in the single ``bulk_create`` — while the other items are
    ``"created"``. The DB-level savepoint rollback is DEV-VERIFY territory.
    """

    def _run_with_failure_on(self, exc, fail_index=1, n=3):
        """Wire _run_hook so the ``fail_index``-th pre_tile_save raises ``exc``."""
        state = {"pre": 0}

        def _side(tiles, nodes_by_id, factory, method_name):
            if method_name == "pre_tile_save":
                idx = state["pre"]
                state["pre"] += 1
                if idx == fail_index:
                    raise exc

        self.mock_run_hook.side_effect = _side

        items = [_item(f"c{i}") for i in range(n)]
        response, payload = self._post({"resourceType": "Component", "items": items})
        return response, payload

    def test_savepoint_isolation_on_403(self):
        exc = requests.HTTPError("403 Client Error: Forbidden for url: x")
        response, payload = self._run_with_failure_on(exc, fail_index=1, n=3)

        self.assertEqual(response.status_code, 200)
        results = payload["results"]
        self.assertEqual(
            [r["status"] for r in results], ["created", "failed", "created"]
        )
        self.assertIn("403", results[1]["error"])

        # rid of the failed item (item 1) — it DID get a rid before failing.
        failed_rid = self.created_rids[1]

        # Zero residue for the failed item: no tile in the single bulk_create.
        self.mock_tilemodel.objects.bulk_create.assert_called_once()
        inserted = self.mock_tilemodel.objects.bulk_create.call_args.args[0]
        self.assertEqual(len(inserted), 2)
        self.assertNotIn(
            failed_rid,
            {t.resourceinstance_id for t in inserted},
            "failed item's tile must be dropped from the buffer",
        )

        # No editlog for the failed item (only the 2 survivors).
        self.assertEqual(self.mock_write_editlog.call_count, 2)
        for c in self.mock_write_editlog.call_args_list:
            item_tiles = c.args[0]
            self.assertNotIn(
                failed_rid,
                {t.resourceinstance_id for t in item_tiles},
                "no editlog may reference the failed item's tiles",
            )

    def test_savepoint_isolation_parametrized(self):
        from arches.app.models.tile import TileValidationError
        from manuspectrum.utils.http import UnsafeURLError

        # manuspectrum.datatypes.manifest runs a module-level
        # ``Widget.objects.get(name="manifest-widget")`` at import time, which
        # has no row in the test DB — patch it so the import succeeds.
        with patch(
            "arches.app.models.models.Widget.objects.get", return_value=MagicMock()
        ):
            from manuspectrum.datatypes.manifest import FailParsingManifestIIIF

        cases = [
            ("UnsafeURLError", UnsafeURLError("blocked host 169.254.169.254")),
            ("FailParsingManifestIIIF", FailParsingManifestIIIF("bad manifest")),
            ("TileValidationError", TileValidationError("tile invalid")),
        ]
        for name, exc in cases:
            with self.subTest(exc=name):
                # reset observable mocks between sub-cases
                self.created_rids.clear()
                self.mock_tilemodel.reset_mock()
                self.mock_write_editlog.reset_mock()
                self.mock_run_hook.reset_mock()

                response, payload = self._run_with_failure_on(exc, fail_index=1, n=3)

                self.assertEqual(response.status_code, 200)
                statuses = [r["status"] for r in payload["results"]]
                self.assertEqual(statuses, ["created", "failed", "created"])

                failed_rid = self.created_rids[1]
                self.mock_tilemodel.objects.bulk_create.assert_called_once()
                inserted = self.mock_tilemodel.objects.bulk_create.call_args.args[0]
                self.assertEqual(len(inserted), 2)
                self.assertNotIn(failed_rid, {t.resourceinstance_id for t in inserted})
                self.assertEqual(self.mock_write_editlog.call_count, 2)


# ===========================================================================
# Hole-2 — dangling dependency
# ===========================================================================


class DanglingDependencyTests(CreateAllBase):
    def test_dangling_dependency_reported_failed(self):
        valid_dep = str(uuid.uuid4())
        missing_dep = str(uuid.uuid4())

        # Pre-collect returns ONLY the existing dep (item0's), not the missing one.
        self.mock_ri.objects.filter.return_value.values_list.return_value = [valid_dep]

        items = [
            _item("c0", dependencies={"currentLocation": valid_dep}),
            _item("c1", dependencies={"currentLocation": missing_dep}),  # dangling
            _item("c2"),
        ]
        response, payload = self._post({"resourceType": "Document", "items": items})

        self.assertEqual(response.status_code, 200)
        results = payload["results"]
        self.assertEqual(
            [r["status"] for r in results], ["created", "failed", "created"]
        )
        # message names the dangling dep
        self.assertIn(missing_dep, results[1]["error"])

        # Zero residue for the dangling item: it never even created a resource
        # (assert_deps_exist raised BEFORE _bulk_create_resources).
        self.assertEqual(
            self.mock_bulk_create.call_count,
            2,
            "dangling item must not reach _bulk_create_resources",
        )
        # Two survivor tiles only.
        self.mock_tilemodel.objects.bulk_create.assert_called_once()
        inserted = self.mock_tilemodel.objects.bulk_create.call_args.args[0]
        self.assertEqual(len(inserted), 2)
        self.assertEqual(self.mock_write_editlog.call_count, 2)


# ===========================================================================
# Hole-1 — Pass-2 all-or-nothing
# ===========================================================================


class Pass2FailureTests(CreateAllBase):
    def test_pass2_failure_returns_500(self):
        self.mock_tilemodel.objects.bulk_create.side_effect = RuntimeError(
            "DB down during bulk insert"
        )

        items = [_item("c0"), _item("c1")]
        response, payload = self._post({"resourceType": "Document", "items": items})

        self.assertEqual(response.status_code, 500)
        self.assertEqual(payload, {"error": "Batch creation failed"})
        # A Pass-2 failure returns 500 and never reaches the post-commit index
        # call. (Whether the DB rolled back is not exercised here: atomic is a
        # no-op stub — see BufferIsolationTests / the module docstring.)
        self.mock_index.assert_not_called()


# ===========================================================================
# Dependency pre-pass is a single query
# ===========================================================================


class PrecollectQueryTests(CreateAllBase):
    def test_precollect_dep_ids_single_query(self):
        dep_a = str(uuid.uuid4())
        dep_b = str(uuid.uuid4())
        self.mock_ri.objects.filter.return_value.values_list.return_value = [
            dep_a,
            dep_b,
        ]

        items = [
            _item("c0", dependencies={"currentLocation": dep_a}),
            _item("c1", dependencies={"currentOwner": [dep_b]}),
        ]
        self._post({"resourceType": "Document", "items": items})

        # ONE ResourceInstance.objects.filter for the entire batch pre-pass.
        self.assertEqual(self.mock_ri.objects.filter.call_count, 1)


# ===========================================================================
# Inheritance (no shadowing of primitives)
# ===========================================================================


class InheritancePrimitiveTests(CreateAllBase):
    def test_inherits_primitives(self):
        # The subclass must not redefine the primitives.
        for name in (
            "_run_hook",
            "_validate_tiles",
            "_collect_valid_concepts",
            "_write_editlog",
        ):
            self.assertNotIn(
                name,
                self.BiblissimaCreateAllView.__dict__,
                f"{name} must be inherited, not shadowed",
            )

        # A patch on the BASE class is observed by the view instance.
        self._post({"resourceType": "Document", "items": [_item("c0")]})
        self.assertGreaterEqual(self.mock_run_hook.call_count, 1)
        self.mock_write_editlog.assert_called()


# ===========================================================================
# Degenerate inputs
# ===========================================================================


class DegenerateInputTests(CreateAllBase):
    def test_empty_items(self):
        response, payload = self._post({"resourceType": "Document", "items": []})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(payload, {"results": []})
        self.mock_tilemodel.objects.bulk_create.assert_not_called()
        self.mock_index.assert_not_called()

    def test_missing_items_key(self):
        response, payload = self._post({"resourceType": "Component"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(payload, {"results": []})

    def test_bad_resource_type(self):
        response, payload = self._post(
            {"resourceType": "Place", "items": [_item("c0")]}
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("error", payload)

    def test_missing_resource_type(self):
        response, payload = self._post({"items": [_item("c0")]})
        self.assertEqual(response.status_code, 400)

    def test_invalid_json(self):
        request = SimpleNamespace(
            body=b"{not valid json",
            user=SimpleNamespace(id=1, username="u"),
        )
        response = self.view.post(request)
        self.assertEqual(response.status_code, 400)

    def test_non_list_items_returns_400(self):
        # A truthy non-list ``items`` (e.g. a string) is a client error and must
        # be a clean 400, not a raw 500 from the read-only pre-pass.
        response, payload = self._post(
            {"resourceType": "Document", "items": "notalist"}
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("error", payload)
        self.mock_tilemodel.objects.bulk_create.assert_not_called()
        self.mock_index.assert_not_called()


# ===========================================================================
# FIX I-1 — dangling project id -> per-item 'failed' (not a whole-batch 500)
# ===========================================================================


class DanglingProjectTests(CreateAllBase):
    def test_dangling_project_reported_failed(self):
        valid_project = str(uuid.uuid4())
        missing_project = str(uuid.uuid4())
        # Only the valid project exists in the DB.
        self.mock_ri.objects.filter.return_value.values_list.return_value = [
            valid_project
        ]

        items = [
            _item("c0", dependencies={"project": valid_project}),
            _item("c1", dependencies={"project": missing_project}),  # dangling
            _item("c2"),  # no project at all
        ]
        # captureOnCommitCallbacks fires _defer_indexing's on_commit callback so
        # mock_index is called within the test (BIBLISSIMA_ASYNC_INDEXING=False).
        with self.captureOnCommitCallbacks(execute=True):
            response, payload = self._post(
                {"resourceType": "Document", "items": items}
            )

        self.assertEqual(response.status_code, 200)
        results = payload["results"]
        self.assertEqual(
            [r["status"] for r in results], ["created", "failed", "created"]
        )
        # message names the dangling project
        self.assertIn(missing_project, results[1]["error"])

        # Existence-checked BEFORE ri creation: the dangling-project item never
        # reached _bulk_create_resources -> zero residue, two survivors.
        self.assertEqual(self.mock_bulk_create.call_count, 2)
        self.mock_tilemodel.objects.bulk_create.assert_called_once()
        inserted = self.mock_tilemodel.objects.bulk_create.call_args.args[0]
        self.assertEqual(len(inserted), 2)
        self.assertEqual(self.mock_write_editlog.call_count, 2)

        # Survivors are NOT prevented from indexing (no whole-batch 500).
        self.mock_index.assert_called_once()
        # The valid project is linked for its survivor.
        self.mock_link.assert_called_once()

    def test_non_string_project_reported_failed(self):
        # FIX I-2: a non-string (numeric/array) project value must NOT slip past
        # the Pass-1 guard into _link_to_project_batch (invalid-UUID query ->
        # outer rollback -> whole-batch 500 losing survivors). It becomes a
        # clean per-item 'failed' while the other items are created.
        items = [
            _item("c0"),
            _item("c1", dependencies={"project": 123}),  # non-string project
            _item("c2"),
        ]
        with self.captureOnCommitCallbacks(execute=True):
            response, payload = self._post(
                {"resourceType": "Document", "items": items}
            )

        self.assertEqual(response.status_code, 200)
        statuses = [r["status"] for r in payload["results"]]
        self.assertEqual(statuses, ["created", "failed", "created"])
        self.assertIn("123", payload["results"][1]["error"])

        # Bad-project item never reached _bulk_create_resources; two survivors.
        self.assertEqual(self.mock_bulk_create.call_count, 2)
        self.mock_tilemodel.objects.bulk_create.assert_called_once()
        inserted = self.mock_tilemodel.objects.bulk_create.call_args.args[0]
        self.assertEqual(len(inserted), 2)
        # No project link attempted (neither survivor had a valid project).
        self.mock_link.assert_not_called()
        # Survivors still indexed — no whole-batch 500.
        self.mock_index.assert_called_once()


# ===========================================================================
# FIX (Minor) — malformed / non-string dep value -> per-item 'failed'
# ===========================================================================


class MalformedDepValueTests(CreateAllBase):
    def test_non_string_dep_value_reported_failed(self):
        # A numeric dep ref is malformed: it must become a clean per-item
        # 'failed' rather than a downstream str()-coercion DataError/500.
        items = [
            _item("c0"),
            _item("c1", dependencies={"currentLocation": 123}),
            _item("c2"),
        ]
        response, payload = self._post({"resourceType": "Document", "items": items})

        self.assertEqual(response.status_code, 200)
        statuses = [r["status"] for r in payload["results"]]
        self.assertEqual(statuses, ["created", "failed", "created"])
        self.assertIn("123", payload["results"][1]["error"])

        # Malformed item never reached _bulk_create_resources; two survivors.
        self.assertEqual(self.mock_bulk_create.call_count, 2)
        self.mock_tilemodel.objects.bulk_create.assert_called_once()
        inserted = self.mock_tilemodel.objects.bulk_create.call_args.args[0]
        self.assertEqual(len(inserted), 2)

    def test_none_dep_value_is_absent_not_failed(self):
        # A present-but-None dependency key is semantically identical to an
        # absent key (both ``.get()`` to None) -> 'no dependency', so it must
        # NOT fail the item.
        items = [_item("c0", dependencies={"currentLocation": None})]
        response, payload = self._post({"resourceType": "Document", "items": items})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(payload["results"][0]["status"], "created")


# ===========================================================================
# FIX I-2 — persisted ref equals the stripped/verified string
# ===========================================================================


class ResourceRefStripTests(CreateAllBase):
    def test_resource_instance_ref_strips_uuid(self):
        u = str(uuid.uuid4())
        ref = self.view._resource_instance_ref(f"  {u}  ")
        self.assertEqual(ref[0]["resourceId"], u)

    def test_resource_instance_list_strips_and_skips_blank(self):
        u = str(uuid.uuid4())
        out = self.view._resource_instance_list([f" {u} ", "   ", ""])
        self.assertEqual([r["resourceId"] for r in out], [u])
