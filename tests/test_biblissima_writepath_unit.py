"""Unit tests for the concept-batch validate-net in
``BiblissimaCreateResourceView._flush_tile_buffer``.

These tests cover the Tier-2 safety net at biblissima_proxy.py:2687-2755:
- One batched ``Value.objects.filter(valueid__in=…)`` pre-confirms concept
  valueids.
- Arches ``datatype.validate`` is SKIPPED for confirmed valueids.
- Arches ``datatype.validate`` is CALLED for malformed (non-UUID) valueids
  and for well-formed but absent valueids.
- A well-formed but absent valueid whose ``datatype.validate`` returns an
  ERROR causes ``TileValidationError`` to be raised.

Patching strategy
-----------------
``_flush_tile_buffer`` uses local imports for ``DataTypeFactory``, ``EditLog``,
and ``TileValidationError`` (inside the method body), so we patch them at their
canonical source modules:

- ``arches.app.datatypes.datatypes.DataTypeFactory``
- ``arches.app.models.models.EditLog``

``Value`` and ``TileModel`` are imported at module level in ``biblissima_proxy``
so they are patched as ``manuspectrum.views.biblissima_proxy.Value`` /
``manuspectrum.views.biblissima_proxy.TileModel``.

No DB writes happen.  The resource mock returns a controlled serialized graph
containing concept and concept-list nodes so the code under test can look up
datatypes.

Run:
    /home/rayondemiel/venv/bin/python manage.py test \\
        tests.test_biblissima_writepath_unit --settings="tests.test_settings"
"""

import uuid
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from django.core.cache import cache
from django.test import TestCase

# ---------------------------------------------------------------------------
# UUIDs used consistently across tests
# ---------------------------------------------------------------------------

CONCEPT_NODE_ID = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
CONCEPT_LIST_NODE_ID = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"
TEXT_NODE_ID = "cccccccc-cccc-cccc-cccc-cccccccccccc"
RESOURCE_ID = "dddddddd-dddd-dddd-dddd-dddddddddddd"
NODEGROUP_ID = "eeeeeeee-eeee-eeee-eeee-eeeeeeeeeeee"
TILE_ID = "ffffffff-ffff-ffff-ffff-ffffffffffff"

VALID_CONCEPT_UUID = "11111111-1111-1111-1111-111111111111"
ABSENT_CONCEPT_UUID = "22222222-2222-2222-2222-222222222222"

MALFORMED_CONCEPT_VALUE = "not-a-uuid"

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

SERIALIZED_GRAPH = {
    "nodes": [
        {"nodeid": CONCEPT_NODE_ID, "datatype": "concept"},
        {"nodeid": CONCEPT_LIST_NODE_ID, "datatype": "concept-list"},
        {"nodeid": TEXT_NODE_ID, "datatype": "string"},
    ]
}


def _make_tile(data, tile_id=None, nodegroup_id=None, resource_id=None):
    """Return a minimal tile-like object (not a real ORM instance)."""
    tile = SimpleNamespace(
        tileid=tile_id or uuid.uuid4(),
        nodegroup_id=nodegroup_id or NODEGROUP_ID,
        resourceinstance_id=resource_id or RESOURCE_ID,
        data=data,
        parenttile=None,
        _mspectrum_transaction_id=None,
    )
    return tile


def _make_resource(serialized_graph=None):
    """Return a mock resource whose get_serialized_graph() is controlled."""
    resource = MagicMock()
    resource.get_serialized_graph.return_value = serialized_graph or SERIALIZED_GRAPH
    resource.graph_id = "graph-id-fake"
    resource.save_descriptors.return_value = None
    resource.displayname.return_value = "Test Resource"
    return resource


def _make_view_with_tiles(tiles):
    """Return a BiblissimaCreateResourceView with ``_tile_buffer`` pre-filled."""
    from manuspectrum.views.biblissima_proxy import BiblissimaCreateResourceView

    view = BiblissimaCreateResourceView()
    view._tile_buffer = list(tiles)
    return view


def _concept_dt_mock():
    """Return a mock datatype for concept / concept-list nodes."""
    dt = MagicMock()
    dt.validate.return_value = []
    dt.pre_tile_save.return_value = None
    dt.post_tile_save.return_value = None
    return dt


def _other_dt_mock():
    """Return a mock datatype for non-concept nodes."""
    dt = MagicMock()
    dt.validate.return_value = []
    dt.pre_tile_save.return_value = None
    dt.post_tile_save.return_value = None
    return dt


def _patch_factory(mock_factory_cls, concept_dt, other_dt):
    """Wire a MockFactory instance so get_instance dispatches to the right dt."""
    mock_factory_cls.return_value.get_instance.side_effect = (
        lambda dt: concept_dt if dt in ("concept", "concept-list") else other_dt
    )


# ---------------------------------------------------------------------------
# Common patch targets
# ---------------------------------------------------------------------------
# DataTypeFactory is imported locally inside _flush_tile_buffer, so we patch
# it at its canonical module path; the local `from ... import DataTypeFactory`
# fetches it from sys.modules at call time, which the patch replaces.
PATCH_FACTORY = "arches.app.datatypes.datatypes.DataTypeFactory"
# EditLog is also a local import inside the method; patch at source module.
PATCH_EDITLOG = "arches.app.models.models.EditLog"
# Value and TileModel are module-level imports in biblissima_proxy, so patch
# via the proxy module namespace.
PATCH_VALUE = "manuspectrum.views.biblissima_proxy.Value"
PATCH_TILEMODEL = "manuspectrum.views.biblissima_proxy.TileModel"


# ---------------------------------------------------------------------------
# Case 1 — all concept valueids present → datatype.validate NOT called
# ---------------------------------------------------------------------------


class ConceptBatchAllPresentTests(TestCase):
    """When every concept valueid is confirmed by the batched filter,
    ``datatype.validate`` must NOT be called for those concept nodes."""

    def setUp(self):
        cache.clear()

    def tearDown(self):
        cache.clear()

    @patch(PATCH_EDITLOG)
    @patch(PATCH_TILEMODEL)
    @patch(PATCH_VALUE)
    @patch(PATCH_FACTORY)
    def test_concept_validate_not_called_when_all_present(
        self, MockFactory, MockValue, MockTileModel, MockEditLog
    ):
        MockValue.objects.filter.return_value.values_list.return_value = [
            VALID_CONCEPT_UUID
        ]

        concept_dt = _concept_dt_mock()
        other_dt = _other_dt_mock()
        _patch_factory(MockFactory, concept_dt, other_dt)

        MockTileModel.objects.bulk_create.return_value = []
        MockEditLog.objects.bulk_create.return_value = []

        tile = _make_tile(
            data={
                CONCEPT_NODE_ID: VALID_CONCEPT_UUID,
                TEXT_NODE_ID: {"en": "hello"},
            }
        )
        view = _make_view_with_tiles([tile])
        resource = _make_resource()

        view._flush_tile_buffer(resource, user=None, default_transaction_id=None)

        # validate must NOT have been called for the concept node
        concept_dt.validate.assert_not_called()

    @patch(PATCH_EDITLOG)
    @patch(PATCH_TILEMODEL)
    @patch(PATCH_VALUE)
    @patch(PATCH_FACTORY)
    def test_concept_list_validate_not_called_when_all_present(
        self, MockFactory, MockValue, MockTileModel, MockEditLog
    ):
        """concept-list node with multiple confirmed values: no validate call."""
        uuid_a = "33333333-3333-3333-3333-333333333333"
        uuid_b = "44444444-4444-4444-4444-444444444444"

        MockValue.objects.filter.return_value.values_list.return_value = [
            uuid_a,
            uuid_b,
        ]

        concept_dt = _concept_dt_mock()
        other_dt = _other_dt_mock()
        _patch_factory(MockFactory, concept_dt, other_dt)

        MockTileModel.objects.bulk_create.return_value = []
        MockEditLog.objects.bulk_create.return_value = []

        tile = _make_tile(data={CONCEPT_LIST_NODE_ID: [uuid_a, uuid_b]})
        view = _make_view_with_tiles([tile])
        resource = _make_resource()

        view._flush_tile_buffer(resource, user=None, default_transaction_id=None)

        concept_dt.validate.assert_not_called()


# ---------------------------------------------------------------------------
# Case 2 — malformed (non-UUID) valueid → datatype.validate IS called
# ---------------------------------------------------------------------------


class ConceptBatchMalformedTests(TestCase):
    """A non-UUID string in a concept node must fall through to
    ``datatype.validate`` (the batch filter is bypassed for malformed ids)."""

    def setUp(self):
        cache.clear()

    def tearDown(self):
        cache.clear()

    @patch(PATCH_EDITLOG)
    @patch(PATCH_TILEMODEL)
    @patch(PATCH_VALUE)
    @patch(PATCH_FACTORY)
    def test_malformed_uuid_triggers_validate(
        self, MockFactory, MockValue, MockTileModel, MockEditLog
    ):
        # Malformed IDs are never sent to the filter; it gets an empty set
        # of well-formed ids and returns nothing.
        MockValue.objects.filter.return_value.values_list.return_value = []

        concept_dt = _concept_dt_mock()
        other_dt = _other_dt_mock()
        _patch_factory(MockFactory, concept_dt, other_dt)

        MockTileModel.objects.bulk_create.return_value = []
        MockEditLog.objects.bulk_create.return_value = []

        tile = _make_tile(data={CONCEPT_NODE_ID: MALFORMED_CONCEPT_VALUE})
        view = _make_view_with_tiles([tile])
        resource = _make_resource()

        view._flush_tile_buffer(resource, user=None, default_transaction_id=None)

        # validate MUST have been called for the malformed value
        concept_dt.validate.assert_called_once()
        call_args = concept_dt.validate.call_args
        self.assertEqual(call_args[0][0], MALFORMED_CONCEPT_VALUE)

    @patch(PATCH_EDITLOG)
    @patch(PATCH_TILEMODEL)
    @patch(PATCH_VALUE)
    @patch(PATCH_FACTORY)
    def test_mixed_list_with_malformed_triggers_validate(
        self, MockFactory, MockValue, MockTileModel, MockEditLog
    ):
        """A concept-list where one value is valid and one malformed must
        fall through — the guard requires ALL values to be confirmed."""
        valid_id = "55555555-5555-5555-5555-555555555555"
        # Only the well-formed uuid is returned by the batched filter
        MockValue.objects.filter.return_value.values_list.return_value = [valid_id]

        concept_dt = _concept_dt_mock()
        other_dt = _other_dt_mock()
        _patch_factory(MockFactory, concept_dt, other_dt)

        MockTileModel.objects.bulk_create.return_value = []
        MockEditLog.objects.bulk_create.return_value = []

        tile = _make_tile(
            data={CONCEPT_LIST_NODE_ID: [valid_id, MALFORMED_CONCEPT_VALUE]}
        )
        view = _make_view_with_tiles([tile])
        resource = _make_resource()

        view._flush_tile_buffer(resource, user=None, default_transaction_id=None)

        # validate must be called because not ALL values are confirmed
        concept_dt.validate.assert_called_once()


# ---------------------------------------------------------------------------
# Case 3 — well-formed but absent valueid → validate IS called, ERROR → raises
# ---------------------------------------------------------------------------


class ConceptBatchAbsentTests(TestCase):
    """A well-formed UUID not in the DB must fall through to
    ``datatype.validate``.  If validate returns an ERROR, TileValidationError
    is raised."""

    def setUp(self):
        cache.clear()

    def tearDown(self):
        cache.clear()

    @patch(PATCH_EDITLOG)
    @patch(PATCH_TILEMODEL)
    @patch(PATCH_VALUE)
    @patch(PATCH_FACTORY)
    def test_absent_uuid_triggers_validate(
        self, MockFactory, MockValue, MockTileModel, MockEditLog
    ):
        # Filter returns nothing → ABSENT_CONCEPT_UUID not confirmed
        MockValue.objects.filter.return_value.values_list.return_value = []

        concept_dt = _concept_dt_mock()
        # validate returns no error — we just verify the call happens
        concept_dt.validate.return_value = []
        other_dt = _other_dt_mock()
        _patch_factory(MockFactory, concept_dt, other_dt)

        MockTileModel.objects.bulk_create.return_value = []
        MockEditLog.objects.bulk_create.return_value = []

        tile = _make_tile(data={CONCEPT_NODE_ID: ABSENT_CONCEPT_UUID})
        view = _make_view_with_tiles([tile])
        resource = _make_resource()

        view._flush_tile_buffer(resource, user=None, default_transaction_id=None)

        concept_dt.validate.assert_called_once()
        call_args = concept_dt.validate.call_args
        self.assertEqual(call_args[0][0], ABSENT_CONCEPT_UUID)

    @patch(PATCH_EDITLOG)
    @patch(PATCH_TILEMODEL)
    @patch(PATCH_VALUE)
    @patch(PATCH_FACTORY)
    def test_absent_uuid_with_error_raises_tile_validation_error(
        self, MockFactory, MockValue, MockTileModel, MockEditLog
    ):
        """If validate returns an ERROR for an absent valueid, TileValidationError
        must be raised before any bulk_create occurs."""
        from arches.app.models.tile import TileValidationError

        MockValue.objects.filter.return_value.values_list.return_value = []

        concept_dt = _concept_dt_mock()
        concept_dt.validate.return_value = [
            {"type": "ERROR", "message": "Concept value not found"}
        ]
        other_dt = _other_dt_mock()
        _patch_factory(MockFactory, concept_dt, other_dt)

        MockTileModel.objects.bulk_create.return_value = []
        MockEditLog.objects.bulk_create.return_value = []

        tile = _make_tile(data={CONCEPT_NODE_ID: ABSENT_CONCEPT_UUID})
        view = _make_view_with_tiles([tile])
        resource = _make_resource()

        with self.assertRaises(TileValidationError):
            view._flush_tile_buffer(resource, user=None, default_transaction_id=None)

        # bulk_create must NOT have been called — error surfaces before DB writes
        MockTileModel.objects.bulk_create.assert_not_called()

    @patch(PATCH_EDITLOG)
    @patch(PATCH_TILEMODEL)
    @patch(PATCH_VALUE)
    @patch(PATCH_FACTORY)
    def test_absent_uuid_with_warning_does_not_raise(
        self, MockFactory, MockValue, MockTileModel, MockEditLog
    ):
        """A WARNING-level validate result must NOT raise — only ERROR does."""
        MockValue.objects.filter.return_value.values_list.return_value = []

        concept_dt = _concept_dt_mock()
        concept_dt.validate.return_value = [
            {"type": "WARNING", "message": "Concept value advisory"}
        ]
        other_dt = _other_dt_mock()
        _patch_factory(MockFactory, concept_dt, other_dt)

        MockTileModel.objects.bulk_create.return_value = []
        MockEditLog.objects.bulk_create.return_value = []

        tile = _make_tile(data={CONCEPT_NODE_ID: ABSENT_CONCEPT_UUID})
        view = _make_view_with_tiles([tile])
        resource = _make_resource()

        # Must NOT raise
        view._flush_tile_buffer(resource, user=None, default_transaction_id=None)

        MockTileModel.objects.bulk_create.assert_called_once()


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


class ConceptBatchEdgeCaseTests(TestCase):
    """Edge cases: None values, non-concept nodes, multiple-tile batches."""

    def setUp(self):
        cache.clear()

    def tearDown(self):
        cache.clear()

    @patch(PATCH_EDITLOG)
    @patch(PATCH_TILEMODEL)
    @patch(PATCH_VALUE)
    @patch(PATCH_FACTORY)
    def test_none_concept_value_skips_batch_lookup_but_still_validates(
        self, MockFactory, MockValue, MockTileModel, MockEditLog
    ):
        """None concept values are excluded from the batch collection, but
        validate is still called for them (matching standard Arches Tile.validate
        behaviour where None is a legitimate value to check).

        The batch optimisation is about skipping the per-value DB existence
        check — not about skipping validation entirely.  Validate receives None
        and the datatype decides whether that is an error."""
        MockValue.objects.filter.return_value.values_list.return_value = []

        concept_dt = _concept_dt_mock()
        concept_dt.validate.return_value = []  # no error
        other_dt = _other_dt_mock()
        _patch_factory(MockFactory, concept_dt, other_dt)

        MockTileModel.objects.bulk_create.return_value = []
        MockEditLog.objects.bulk_create.return_value = []

        tile = _make_tile(data={CONCEPT_NODE_ID: None})
        view = _make_view_with_tiles([tile])
        resource = _make_resource()

        view._flush_tile_buffer(resource, user=None, default_transaction_id=None)

        # None bypasses the concept-batch short-circuit (value is not None check),
        # so it falls through to the authoritative validate call.
        concept_dt.validate.assert_called_once()
        call_args = concept_dt.validate.call_args
        self.assertIsNone(call_args[0][0])

    @patch(PATCH_EDITLOG)
    @patch(PATCH_TILEMODEL)
    @patch(PATCH_VALUE)
    @patch(PATCH_FACTORY)
    def test_non_concept_node_always_validates(
        self, MockFactory, MockValue, MockTileModel, MockEditLog
    ):
        """Non-concept/string nodes always go through datatype.validate
        (the concept-batch optimisation doesn't affect them)."""
        MockValue.objects.filter.return_value.values_list.return_value = []

        string_dt = _other_dt_mock()
        concept_dt = _concept_dt_mock()

        MockFactory.return_value.get_instance.side_effect = (
            lambda dt: string_dt if dt == "string" else concept_dt
        )
        MockTileModel.objects.bulk_create.return_value = []
        MockEditLog.objects.bulk_create.return_value = []

        tile = _make_tile(data={TEXT_NODE_ID: {"en": "some text"}})
        view = _make_view_with_tiles([tile])
        resource = _make_resource()

        view._flush_tile_buffer(resource, user=None, default_transaction_id=None)

        string_dt.validate.assert_called_once()

    @patch(PATCH_EDITLOG)
    @patch(PATCH_TILEMODEL)
    @patch(PATCH_VALUE)
    @patch(PATCH_FACTORY)
    def test_two_concept_nodes_both_confirmed_no_validate(
        self, MockFactory, MockValue, MockTileModel, MockEditLog
    ):
        """Two concept nodes on the same tile, both confirmed → no validate."""
        uuid_a = "66666666-6666-6666-6666-666666666666"
        uuid_b = "77777777-7777-7777-7777-777777777777"
        MockValue.objects.filter.return_value.values_list.return_value = [uuid_a, uuid_b]

        concept_dt = _concept_dt_mock()
        other_dt = _other_dt_mock()
        _patch_factory(MockFactory, concept_dt, other_dt)

        MockTileModel.objects.bulk_create.return_value = []
        MockEditLog.objects.bulk_create.return_value = []

        tile = _make_tile(
            data={
                CONCEPT_NODE_ID: uuid_a,
                CONCEPT_LIST_NODE_ID: [uuid_b],
            }
        )
        view = _make_view_with_tiles([tile])
        resource = _make_resource()

        view._flush_tile_buffer(resource, user=None, default_transaction_id=None)

        concept_dt.validate.assert_not_called()

    @patch(PATCH_EDITLOG)
    @patch(PATCH_TILEMODEL)
    @patch(PATCH_VALUE)
    @patch(PATCH_FACTORY)
    def test_one_confirmed_one_absent_across_tiles_raises(
        self, MockFactory, MockValue, MockTileModel, MockEditLog
    ):
        """Two tiles: tile 1 has a confirmed concept, tile 2 has an absent one
        whose validate returns ERROR → TileValidationError raised."""
        from arches.app.models.tile import TileValidationError

        confirmed_id = "88888888-8888-8888-8888-888888888888"
        absent_id = "99999999-9999-9999-9999-999999999999"

        # Only confirmed_id is in the DB
        MockValue.objects.filter.return_value.values_list.return_value = [confirmed_id]

        concept_dt = _concept_dt_mock()
        # validate is called only for the absent_id tile (confirmed tile skips)
        concept_dt.validate.return_value = [{"type": "ERROR", "message": "not found"}]
        other_dt = _other_dt_mock()
        _patch_factory(MockFactory, concept_dt, other_dt)

        MockTileModel.objects.bulk_create.return_value = []
        MockEditLog.objects.bulk_create.return_value = []

        tile_ok = _make_tile(data={CONCEPT_NODE_ID: confirmed_id})
        tile_bad = _make_tile(data={CONCEPT_NODE_ID: absent_id})
        view = _make_view_with_tiles([tile_ok, tile_bad])
        resource = _make_resource()

        with self.assertRaises(TileValidationError):
            view._flush_tile_buffer(resource, user=None, default_transaction_id=None)

        MockTileModel.objects.bulk_create.assert_not_called()
