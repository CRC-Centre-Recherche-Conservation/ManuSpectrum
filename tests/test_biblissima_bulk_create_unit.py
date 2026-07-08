"""Unit tests for Task 3.3: _bulk_create_resources and _link_to_project_batch.

Group A — _bulk_create_resources: plumbing/invariants for the bulk INSERT
  (lifecycle state, publication_id, principaluser, once-per-graph resolution,
  guard for missing lifecycle, guard for missing FK, n<=0 early-exit, UUID4).

Group B — _link_to_project_batch: select_for_update lock, idempotent dedup,
  append new ids, single save with index=False, transaction tagging.

No real DB writes; all ORM calls are mocked.

Patching strategy
-----------------
- GraphModel: LOCAL import inside _bulk_create_resources → patch at the
  canonical source module so the local `from ... import GraphModel` inside
  the function body gets the mock from sys.modules at call time.
    PATCH_GRAPHMODEL = "arches.app.models.models.GraphModel"
- ResourceInstanceLifecycleState: A.5/A.6 intentionally reference the real exception
    class rather than patching it (DoesNotExist is used as a side_effect value, not a
    patch target — patching the class would replace DoesNotExist itself).
- ResourceInstance: MODULE-LEVEL import in biblissima_proxy → patch via the
  proxy namespace.
    PATCH_RI = "manuspectrum.views.biblissima_proxy.ResourceInstance"
- Tile: MODULE-LEVEL import in biblissima_proxy → patch via the proxy namespace.
    PATCH_TILE = "manuspectrum.views.biblissima_proxy.Tile"

Run:
    /home/rayondemiel/venv/bin/python manage.py test \\
        tests.test_biblissima_bulk_create_unit --settings="tests.test_settings" \\
        --noinput
"""

import uuid
from unittest.mock import MagicMock, call, patch

from django.test import TestCase

# ---------------------------------------------------------------------------
# Patch targets
# ---------------------------------------------------------------------------
PATCH_GRAPHMODEL = "arches.app.models.models.GraphModel"
PATCH_RI = "manuspectrum.views.biblissima_proxy.ResourceInstance"
PATCH_TILE = "manuspectrum.views.biblissima_proxy.Tile"

# ---------------------------------------------------------------------------
# Constants used in tests (mirrors manuspectrum.constants.biblissima)
# ---------------------------------------------------------------------------
PROJECT_STUDIED_OBJECTS_NG = "a8fb3c9e-bbc4-11ef-bd5f-ed806b645d76"
PROJECT_STUDIED_OBJECTS_NODE = "a8fb3c9e-bbc4-11ef-bd5f-ed806b645d76"

GRAPH_ID = "graph-aaaa-bbbb-cccc-dddddddddddd"
PROJECT_ID = "project-1111-2222-3333-444444444444"
TX_ID = str(uuid.uuid4())


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_view():
    """Return a fresh BiblissimaCreateResourceView instance."""
    from manuspectrum.views.biblissima_proxy import BiblissimaCreateResourceView

    return BiblissimaCreateResourceView()


def _make_mock_graph(
    publication_id=None,
    initial_state=None,
    lifecycle=None,
):
    """Return a mock GraphModel instance with a lifecycle that returns initial_state."""
    mock_state = initial_state if initial_state is not None else MagicMock(name="initial_state")
    mock_lifecycle = lifecycle if lifecycle is not None else MagicMock()
    mock_lifecycle.get_initial_resource_instance_lifecycle_state.return_value = mock_state

    mock_graph = MagicMock()
    mock_graph.publication_id = publication_id or str(uuid.uuid4())
    mock_graph.resource_instance_lifecycle = mock_lifecycle
    return mock_graph, mock_lifecycle, mock_state


def _setup_graphmodel_mock(MockGraphModel, mock_graph):
    """Wire MockGraphModel.objects.select_related(...).get(...) → mock_graph."""
    MockGraphModel.objects.select_related.return_value.get.return_value = mock_graph


# ===========================================================================
# Group A — _bulk_create_resources
# ===========================================================================


class BulkCreateResourcesTests(TestCase):
    """Group A: unit tests for BiblissimaCreateResourceView._bulk_create_resources."""

    # -----------------------------------------------------------------------
    # A.1 — lifecycle state set on every constructed instance (NOT-NULL)
    # -----------------------------------------------------------------------
    @patch(PATCH_GRAPHMODEL)
    @patch(PATCH_RI)
    def test_lifecycle_state_set_on_every_instance(self, MockRI, MockGraphModel):
        """Every constructed ResourceInstance must carry the resolved initial_state."""
        n = 4
        mock_graph, _, mock_state = _make_mock_graph()
        _setup_graphmodel_mock(MockGraphModel, mock_graph)
        MockRI.objects.bulk_create.return_value = []

        user = MagicMock(id=7)
        view = _make_view()
        view._bulk_create_resources(GRAPH_ID, n, user)

        calls = MockRI.call_args_list
        self.assertEqual(len(calls), n)
        for c in calls:
            self.assertEqual(
                c.kwargs.get("resource_instance_lifecycle_state"),
                mock_state,
                msg="resource_instance_lifecycle_state must be the resolved initial_state on every instance",
            )

    # -----------------------------------------------------------------------
    # A.2 — graph_publication_id mirrors graph.publication_id
    # -----------------------------------------------------------------------
    @patch(PATCH_GRAPHMODEL)
    @patch(PATCH_RI)
    def test_graph_publication_set(self, MockRI, MockGraphModel):
        """graph_publication_id on every instance must equal graph.publication_id."""
        pub_id = str(uuid.uuid4())
        mock_graph, _, _ = _make_mock_graph(publication_id=pub_id)
        _setup_graphmodel_mock(MockGraphModel, mock_graph)
        MockRI.objects.bulk_create.return_value = []

        view = _make_view()
        view._bulk_create_resources(GRAPH_ID, 3, MagicMock(id=1))

        for c in MockRI.call_args_list:
            self.assertEqual(c.kwargs.get("graph_publication_id"), pub_id)

    # -----------------------------------------------------------------------
    # A.3 — principaluser is NOT set (aligns bulk with the unitary path, M-6)
    # -----------------------------------------------------------------------
    @patch(PATCH_GRAPHMODEL)
    @patch(PATCH_RI)
    def test_principaluser_not_set(self, MockRI, MockGraphModel):
        """principaluser_id must NOT be passed, matching the unitary
        _create_resource path (bare ResourceInstance, principaluser NULL), so
        edit-permission ownership does not diverge by endpoint."""
        mock_graph, _, _ = _make_mock_graph()
        _setup_graphmodel_mock(MockGraphModel, mock_graph)
        MockRI.objects.bulk_create.return_value = []

        user = MagicMock(id=42)
        view = _make_view()
        view._bulk_create_resources(GRAPH_ID, 2, user)

        for c in MockRI.call_args_list:
            self.assertNotIn(
                "principaluser_id",
                c.kwargs,
                "principaluser_id must not be passed (aligns with unitary path)",
            )

    # -----------------------------------------------------------------------
    # A.4 — lifecycle resolved ONCE regardless of n
    # -----------------------------------------------------------------------
    @patch(PATCH_GRAPHMODEL)
    @patch(PATCH_RI)
    def test_lifecycle_resolved_once_per_graph(self, MockRI, MockGraphModel):
        """get_initial_resource_instance_lifecycle_state must be called exactly once."""
        n = 10
        mock_graph, mock_lifecycle, _ = _make_mock_graph()
        _setup_graphmodel_mock(MockGraphModel, mock_graph)
        MockRI.objects.bulk_create.return_value = []

        view = _make_view()
        view._bulk_create_resources(GRAPH_ID, n, MagicMock(id=1))

        mock_lifecycle.get_initial_resource_instance_lifecycle_state.assert_called_once()

    # -----------------------------------------------------------------------
    # A.5 — DoesNotExist from get_initial_... → ValueError (guard fires)
    # -----------------------------------------------------------------------
    @patch(PATCH_GRAPHMODEL)
    @patch(PATCH_RI)
    def test_missing_initial_state_raises_valueerror(self, MockRI, MockGraphModel):
        """When get_initial_resource_instance_lifecycle_state raises DoesNotExist,
        the method must raise ValueError and NOT call bulk_create."""
        from arches.app.models.models import ResourceInstanceLifecycleState

        mock_lifecycle = MagicMock()
        mock_lifecycle.get_initial_resource_instance_lifecycle_state = MagicMock(
            side_effect=ResourceInstanceLifecycleState.DoesNotExist
        )

        mock_graph = MagicMock()
        mock_graph.publication_id = str(uuid.uuid4())
        mock_graph.resource_instance_lifecycle = mock_lifecycle
        _setup_graphmodel_mock(MockGraphModel, mock_graph)

        view = _make_view()
        with self.assertRaises(ValueError) as ctx:
            view._bulk_create_resources(GRAPH_ID, 3, MagicMock(id=1))

        self.assertIn("no initial", str(ctx.exception).lower())
        MockRI.objects.bulk_create.assert_not_called()

    # -----------------------------------------------------------------------
    # A.6 — nullable lifecycle FK → ValueError (AttributeError branch)
    # -----------------------------------------------------------------------
    @patch(PATCH_GRAPHMODEL)
    @patch(PATCH_RI)
    def test_missing_lifecycle_fk_raises_valueerror(self, MockRI, MockGraphModel):
        """When graph.resource_instance_lifecycle is None (nullable FK),
        AttributeError is caught and ValueError is raised; bulk_create is NOT called."""
        mock_graph = MagicMock()
        mock_graph.publication_id = str(uuid.uuid4())
        mock_graph.resource_instance_lifecycle = None  # nullable FK → AttributeError
        _setup_graphmodel_mock(MockGraphModel, mock_graph)

        view = _make_view()
        with self.assertRaises(ValueError) as ctx:
            view._bulk_create_resources(GRAPH_ID, 2, MagicMock(id=1))

        self.assertIn("no initial", str(ctx.exception).lower())
        MockRI.objects.bulk_create.assert_not_called()

    # -----------------------------------------------------------------------
    # A.7 — n <= 0 returns [] without any DB call
    # -----------------------------------------------------------------------
    @patch(PATCH_GRAPHMODEL)
    @patch(PATCH_RI)
    def test_zero_or_negative_n_returns_empty(self, MockRI, MockGraphModel):
        """n<=0 must return [] immediately with no GraphModel fetch or bulk_create."""
        view = _make_view()

        result_zero = view._bulk_create_resources(GRAPH_ID, 0, MagicMock(id=1))
        result_neg = view._bulk_create_resources(GRAPH_ID, -5, MagicMock(id=1))

        self.assertEqual(result_zero, [])
        self.assertEqual(result_neg, [])
        MockGraphModel.objects.select_related.assert_not_called()
        MockRI.objects.bulk_create.assert_not_called()

    # -----------------------------------------------------------------------
    # A.8 — returned ids are UUID4s; single bulk_create with n instances
    # -----------------------------------------------------------------------
    @patch(PATCH_GRAPHMODEL)
    @patch(PATCH_RI)
    def test_ids_are_uuid4_and_single_bulk_create(self, MockRI, MockGraphModel):
        """_bulk_create_resources must return n UUIDs and call bulk_create once."""
        n = 5
        mock_graph, _, _ = _make_mock_graph()
        _setup_graphmodel_mock(MockGraphModel, mock_graph)

        # bulk_create does not return the instances; instances are already
        # in-memory and we just read .resourceinstanceid from them.
        # Make sure the mock instances carry a UUID as resourceinstanceid.
        def make_instance(**kwargs):
            inst = MagicMock()
            inst.resourceinstanceid = kwargs.get("resourceinstanceid", uuid.uuid4())
            # Store kwargs so callers can inspect them.
            inst._init_kwargs = kwargs
            return inst

        MockRI.side_effect = make_instance
        MockRI.objects.bulk_create.return_value = []

        view = _make_view()
        ids = view._bulk_create_resources(GRAPH_ID, n, MagicMock(id=1))

        # One bulk_create call containing n instances
        MockRI.objects.bulk_create.assert_called_once()
        bulk_args = MockRI.objects.bulk_create.call_args[0][0]
        self.assertEqual(len(bulk_args), n)

        # Returned list has n elements, all UUIDs (uuid.UUID objects or strings)
        self.assertEqual(len(ids), n)
        for rid in ids:
            # Must be parseable as UUID4
            parsed = uuid.UUID(str(rid))
            self.assertEqual(parsed.version, 4)


# ===========================================================================
# Group B — _link_to_project_batch
# ===========================================================================


class LinkToProjectBatchTests(TestCase):
    """Group B: unit tests for BiblissimaCreateResourceView._link_to_project_batch."""

    # -----------------------------------------------------------------------
    # Helper: make a mock existing tile
    # -----------------------------------------------------------------------
    def _existing_tile(self, existing_ids=None):
        """Return a mock Tile that already has existing_ids in studied_objects."""
        tile = MagicMock()
        current = [
            {
                "resourceId": str(rid),
                "ontologyProperty": "",
                "inverseOntologyProperty": "",
                "resourceXresourceId": "",
            }
            for rid in (existing_ids or [])
        ]
        tile.data = {PROJECT_STUDIED_OBJECTS_NODE: current}
        tile.save.return_value = None
        return tile

    def _setup_tile_query(self, MockTile, existing_tile):
        """Wire MockTile.objects.select_for_update().filter().first() → existing_tile."""
        (
            MockTile.objects
            .select_for_update.return_value
            .filter.return_value
            .first.return_value
        ) = existing_tile

    # -----------------------------------------------------------------------
    # B.1 — select_for_update is invoked
    # -----------------------------------------------------------------------
    @patch(PATCH_TILE)
    def test_uses_select_for_update(self, MockTile):
        """Tile.objects.select_for_update() must be called to acquire a row lock."""
        self._setup_tile_query(MockTile, self._existing_tile())

        view = _make_view()
        view._link_to_project_batch([uuid.uuid4()], PROJECT_ID, TX_ID)

        MockTile.objects.select_for_update.assert_called()

    # -----------------------------------------------------------------------
    # B.2 — idempotent: already-present id is not appended twice
    # -----------------------------------------------------------------------
    @patch(PATCH_TILE)
    def test_idempotent_no_duplicate(self, MockTile):
        """A resource id already in the tile must NOT be appended again."""
        pre_existing_id = str(uuid.uuid4())
        existing = self._existing_tile(existing_ids=[pre_existing_id])
        self._setup_tile_query(MockTile, existing)

        view = _make_view()
        view._link_to_project_batch([pre_existing_id], PROJECT_ID, TX_ID)

        saved_data = existing.data[PROJECT_STUDIED_OBJECTS_NODE]
        ids_in_tile = [ref["resourceId"] for ref in saved_data]
        self.assertEqual(ids_in_tile.count(pre_existing_id), 1)

    # -----------------------------------------------------------------------
    # B.3 — all new ids are appended
    # -----------------------------------------------------------------------
    @patch(PATCH_TILE)
    def test_appends_all_new_ids(self, MockTile):
        """All ids in created_ids that are not already present must be appended."""
        pre_existing_id = str(uuid.uuid4())
        new_id_a = str(uuid.uuid4())
        new_id_b = str(uuid.uuid4())
        existing = self._existing_tile(existing_ids=[pre_existing_id])
        self._setup_tile_query(MockTile, existing)

        view = _make_view()
        view._link_to_project_batch([new_id_a, new_id_b], PROJECT_ID, TX_ID)

        saved_data = existing.data[PROJECT_STUDIED_OBJECTS_NODE]
        ids_in_tile = {ref["resourceId"] for ref in saved_data}
        self.assertIn(new_id_a, ids_in_tile)
        self.assertIn(new_id_b, ids_in_tile)

    # -----------------------------------------------------------------------
    # B.4 — save is called exactly once with index=False
    # -----------------------------------------------------------------------
    @patch(PATCH_TILE)
    def test_saves_once_with_index_false(self, MockTile):
        """Tile.save(index=False, transaction_id=tx_id) must be called once."""
        existing = self._existing_tile()
        self._setup_tile_query(MockTile, existing)

        view = _make_view()
        view._link_to_project_batch([str(uuid.uuid4())], PROJECT_ID, TX_ID)

        existing.save.assert_called_once_with(index=False, transaction_id=TX_ID)

    # -----------------------------------------------------------------------
    # B.5 — transaction id is threaded INTO save (FIX I-1)
    # -----------------------------------------------------------------------
    @patch(PATCH_TILE)
    def test_tags_transaction(self, MockTile):
        """FIX I-1: tx_id must be passed as the ``transaction_id`` kwarg of
        ``Tile.save`` (Arches reads it only from the kwarg — setting it as an
        inert attribute leaves the project's EditLog with a random tx, so the
        project is never re-indexed by index_resources_by_transaction)."""
        tx = str(uuid.uuid4())
        existing = self._existing_tile()
        self._setup_tile_query(MockTile, existing)

        view = _make_view()
        view._link_to_project_batch([str(uuid.uuid4())], PROJECT_ID, tx)

        existing.save.assert_called_once_with(index=False, transaction_id=tx)
        # The inert attribute assignment must be gone (it was the bug).
        self.assertNotIn("transaction_id", existing.__dict__)

    # -----------------------------------------------------------------------
    # B.6 — no existing tile: new Tile is created and saved with index=False
    # -----------------------------------------------------------------------
    @patch(PATCH_TILE)
    def test_creates_new_tile_when_none_exists(self, MockTile):
        """When no project tile exists, a new Tile must be constructed and saved."""
        self._setup_tile_query(MockTile, None)
        new_tile_mock = MagicMock()
        MockTile.return_value = new_tile_mock

        rid = str(uuid.uuid4())
        view = _make_view()
        view._link_to_project_batch([rid], PROJECT_ID, TX_ID)

        MockTile.assert_called_once()
        new_tile_mock.save.assert_called_once_with(index=False, transaction_id=TX_ID)

    # -----------------------------------------------------------------------
    # B.7 — mixed: pre-existing + new ids, only new appended
    # -----------------------------------------------------------------------
    @patch(PATCH_TILE)
    def test_mixed_existing_and_new_ids(self, MockTile):
        """With mixed ids, only the new ones are appended; duplicates are skipped."""
        old_id = str(uuid.uuid4())
        new_id = str(uuid.uuid4())
        existing = self._existing_tile(existing_ids=[old_id])
        self._setup_tile_query(MockTile, existing)

        view = _make_view()
        view._link_to_project_batch([old_id, new_id], PROJECT_ID, TX_ID)

        saved_data = existing.data[PROJECT_STUDIED_OBJECTS_NODE]
        ids_in_tile = [ref["resourceId"] for ref in saved_data]
        self.assertEqual(ids_in_tile.count(old_id), 1, "old_id must appear exactly once")
        self.assertEqual(ids_in_tile.count(new_id), 1, "new_id must appear exactly once")

    # -----------------------------------------------------------------------
    # B.8 — tx_id=None: existing tile NOT tagged, save still called
    # -----------------------------------------------------------------------
    @patch(PATCH_TILE)
    def test_tx_id_none_passes_none_transaction(self, MockTile):
        """When tx_id=None on an existing tile, save is still called once with
        ``transaction_id=None`` (Arches then assigns a default uuid), and the
        inert attribute is never set on the tile."""
        existing = self._existing_tile()
        self._setup_tile_query(MockTile, existing)

        view = _make_view()
        view._link_to_project_batch([str(uuid.uuid4())], PROJECT_ID, tx_id=None)

        # The inert `existing.transaction_id = tx_id` assignment is gone, so
        # "transaction_id" must not appear in the mock's __dict__.
        self.assertNotIn(
            "transaction_id",
            existing.__dict__,
            msg="transaction_id must not be assigned as an attribute",
        )
        existing.save.assert_called_once_with(index=False, transaction_id=None)

    # -----------------------------------------------------------------------
    # B.9 — new tile (no existing): tagged with tx_id
    # -----------------------------------------------------------------------
    @patch(PATCH_TILE)
    def test_new_tile_tagged_with_tx_id(self, MockTile):
        """When no project tile exists, the newly constructed Tile must be saved
        with ``transaction_id=tx_id`` as a save kwarg (FIX I-1), not as an inert
        attribute; save(index=False, ...) called once."""
        self._setup_tile_query(MockTile, None)
        new_tile_mock = MagicMock()
        MockTile.return_value = new_tile_mock

        view = _make_view()
        view._link_to_project_batch([str(uuid.uuid4())], PROJECT_ID, TX_ID)

        new_tile_mock.save.assert_called_once_with(index=False, transaction_id=TX_ID)
        # The inert attribute assignment must be gone (it was the bug).
        self.assertNotIn("transaction_id", new_tile_mock.__dict__)

    # -----------------------------------------------------------------------
    # B.10 — ref dict has the exact 4-key Arches shape
    # -----------------------------------------------------------------------
    @patch(PATCH_TILE)
    def test_project_ref_structure(self, MockTile):
        """The appended ref dict must match the exact 4-key shape expected by Arches:
        resourceId, ontologyProperty, inverseOntologyProperty, resourceXresourceId."""
        new_id = str(uuid.uuid4())
        existing = self._existing_tile(existing_ids=[])
        self._setup_tile_query(MockTile, existing)

        view = _make_view()
        view._link_to_project_batch([new_id], PROJECT_ID, TX_ID)

        saved_data = existing.data[PROJECT_STUDIED_OBJECTS_NODE]
        self.assertEqual(len(saved_data), 1)
        ref = saved_data[0]
        self.assertEqual(ref["resourceId"], new_id)
        self.assertEqual(ref["ontologyProperty"], "")
        self.assertEqual(ref["inverseOntologyProperty"], "")
        self.assertEqual(ref["resourceXresourceId"], "")
