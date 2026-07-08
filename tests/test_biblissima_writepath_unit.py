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


# ---------------------------------------------------------------------------
# Task 1.3 — sortorder + nested-tile FK ordering
# ---------------------------------------------------------------------------
#
# AUDIT FINDINGS (as of commit f8bc498, builders in biblissima_proxy.py):
#
# _create_document_tiles multi-sibling nodegroups (cardinality-n):
#   - DOC_NAME_NG:       called 1× always (label) + 1× conditional (shelfmark)
#     → max 2 siblings; all got sortorder=0 before the fix.
#   - DOC_IDENTIFIER_NG: called up to 4× (ark, qid, aem, mandragore)
#     → up to 4 siblings; all got sortorder=0 before the fix.
#   No nested/parent tiles in _create_document_tiles.
#
# _create_component_tiles multi-sibling nodegroups:
#   - COMP_IDENTIFIER_NG:  called up to 2× (ark + mandragore_ark)
#   - COMP_STATEMENT_NG:   called up to 2× (text + rubric)
#   - COMP_ICONOGRAPHIC_NG: called N× (one per descriptorLinks entry)
#   All got sortorder=0 for every sibling before the fix.
#
# Parent-before-child ordering (FK resolution at bulk_create time):
#   - COMP_PARENT_DOC_NG (item_feature_tile) is created FIRST.
#   - COMP_PRODUCTION_NG (production_tile, parenttile=item_feature_tile) is
#     created AFTER item_feature_tile.
#   - COMP_PERIOD_NG (parenttile=production_tile) is created AFTER
#     production_tile.
#   - COMP_LOCATION_DOC_NG (parenttile=item_feature_tile) is created last.
#   → Parent-before-child ordering is already CORRECT in the builder;
#     no reorder was needed. Assertion (a) is characterization-only.
#
# Fix applied: _create_tile now counts existing tiles for (resource_id,
# nodegroup_id) in self._tile_buffer and assigns sortorder = that count,
# giving 0, 1, 2, … for successive siblings.


def _make_minimal_document_data(**extra):
    """Return a minimal bbma_data dict for _create_document_tiles.

    Includes shelfmark (triggers 2nd DOC_NAME_NG tile) and all four
    identifier fields (triggers 4 DOC_IDENTIFIER_NG tiles) to exercise
    the maximum number of siblings.
    """
    data = {
        "label": "Test Manuscript",
        "shelfmark": "Ms. 42",
        "arkId": "ark:/43093/testark",
        "biblissimaQid": "Q12345",
        "aemId": "cc12345",
        "mandragoreId": "9999",
    }
    data.update(extra)
    return data


def _make_minimal_component_data(**extra):
    """Return a minimal bbma_data dict for _create_component_tiles.

    Includes both identifier fields (ark + mandragore_ark), both statement
    fields (text + rubric), two descriptorLinks, and canvas data to trigger
    the Location in Document tile (nested under item_feature).
    """
    data = {
        "label": "Test Illumination",
        "arkId": "ark:/43093/comptest",
        "mandragoreArk": "ark:/12148/mm12345",
        "text": "Text content",
        "rubric": "Rubric content",
        "descriptorLinks": [
            {"uri": "ark:/43093/desc1", "label": "Descriptor one"},
            {"uri": "ark:/43093/desc2", "label": "Descriptor two"},
            {"uri": "ark:/43093/desc3", "label": "Descriptor three"},
        ],
        "imageServiceUrl": "https://example.com/iiif/image",
        "manifestUrl": "https://example.com/iiif/manifest",
        "canvasWidth": "800",
        "canvasHeight": "1000",
        "dateStart": "1200",
        "dateEnd": "1300",
    }
    data.update(extra)
    return data


def _make_builder_view():
    """Return a BiblissimaCreateResourceView with empty _tile_buffer."""
    from manuspectrum.views.biblissima_proxy import BiblissimaCreateResourceView

    view = BiblissimaCreateResourceView()
    view._tile_buffer = []
    return view


class SortorderSiblingTests(TestCase):
    """_create_tile must assign distinct sortorder values for same-nodegroup
    sibling tiles of a cardinality-n card.

    Before the fix, all siblings received sortorder=0 because bulk_create
    bypasses TileModel.save()'s set_next_sort_order().  The fix increments
    a counter per (resource_id, nodegroup_id) inside _create_tile.
    """

    def setUp(self):
        cache.clear()

    def tearDown(self):
        cache.clear()

    def test_document_name_siblings_have_distinct_sortorder(self):
        """DOC_NAME_NG gets 2 sibling tiles (label + shelfmark); they must
        have sortorder 0 and 1 respectively."""
        from manuspectrum.views.biblissima_proxy import (
            DOC_NAME_NG,
            BiblissimaCreateResourceView,
        )

        view = _make_builder_view()
        resource_id = str(uuid.uuid4())
        tx = str(uuid.uuid4())

        view._create_document_tiles(
            resource_id,
            tx,
            _make_minimal_document_data(),
            deps={},
            concepts={},
            created_deps={},
        )

        name_tiles = [
            t for t in view._tile_buffer if str(t.nodegroup_id) == DOC_NAME_NG
        ]
        self.assertEqual(len(name_tiles), 2, "expected 2 DOC_NAME_NG tiles")
        sortorders = {t.sortorder for t in name_tiles}
        self.assertEqual(sortorders, {0, 1}, f"expected {{0, 1}}, got {sortorders}")

    def test_document_identifier_siblings_have_distinct_sortorder(self):
        """DOC_IDENTIFIER_NG gets up to 4 sibling tiles (ark, qid, aem,
        mandragore); each must have a unique sortorder."""
        from manuspectrum.views.biblissima_proxy import DOC_IDENTIFIER_NG

        view = _make_builder_view()
        resource_id = str(uuid.uuid4())
        tx = str(uuid.uuid4())

        view._create_document_tiles(
            resource_id,
            tx,
            _make_minimal_document_data(),
            deps={},
            concepts={},
            created_deps={},
        )

        id_tiles = [
            t for t in view._tile_buffer if str(t.nodegroup_id) == DOC_IDENTIFIER_NG
        ]
        self.assertEqual(
            len(id_tiles),
            4,
            "expected exactly 4 DOC_IDENTIFIER_NG tiles (ark, qid, aem, mandragore)",
        )
        sortorders = [t.sortorder for t in id_tiles]
        self.assertEqual(
            len(sortorders),
            len(set(sortorders)),
            f"duplicate sortorders in DOC_IDENTIFIER_NG siblings: {sortorders}",
        )

    def test_component_identifier_siblings_have_distinct_sortorder(self):
        """COMP_IDENTIFIER_NG gets 2 sibling tiles (ark + mandragore_ark);
        they must have sortorder 0 and 1."""
        from manuspectrum.views.biblissima_proxy import COMP_IDENTIFIER_NG

        view = _make_builder_view()
        resource_id = str(uuid.uuid4())
        tx = str(uuid.uuid4())
        parent_doc_id = str(uuid.uuid4())

        view._create_component_tiles(
            resource_id,
            tx,
            _make_minimal_component_data(),
            deps={"parentDocument": parent_doc_id},
            concepts={},
            created_deps={},
        )

        id_tiles = [
            t for t in view._tile_buffer if str(t.nodegroup_id) == COMP_IDENTIFIER_NG
        ]
        self.assertEqual(len(id_tiles), 2, "expected 2 COMP_IDENTIFIER_NG tiles")
        sortorders = {t.sortorder for t in id_tiles}
        self.assertEqual(sortorders, {0, 1}, f"expected {{0, 1}}, got {sortorders}")

    def test_component_statement_siblings_have_distinct_sortorder(self):
        """COMP_STATEMENT_NG gets 2 sibling tiles (text + rubric); they must
        have distinct sortorders."""
        from manuspectrum.views.biblissima_proxy import COMP_STATEMENT_NG

        view = _make_builder_view()
        resource_id = str(uuid.uuid4())
        tx = str(uuid.uuid4())
        parent_doc_id = str(uuid.uuid4())

        view._create_component_tiles(
            resource_id,
            tx,
            _make_minimal_component_data(),
            deps={"parentDocument": parent_doc_id},
            concepts={},
            created_deps={},
        )

        stmt_tiles = [
            t for t in view._tile_buffer if str(t.nodegroup_id) == COMP_STATEMENT_NG
        ]
        self.assertEqual(len(stmt_tiles), 2, "expected 2 COMP_STATEMENT_NG tiles")
        sortorders = {t.sortorder for t in stmt_tiles}
        self.assertEqual(
            len(sortorders), 2, f"duplicate sortorders in COMP_STATEMENT_NG: {sortorders}"
        )

    def test_component_iconographic_multi_siblings_have_distinct_sortorder(self):
        """COMP_ICONOGRAPHIC_NG gets N sibling tiles (one per descriptorLink);
        each must have a unique, incrementing sortorder."""
        from manuspectrum.views.biblissima_proxy import COMP_ICONOGRAPHIC_NG

        view = _make_builder_view()
        resource_id = str(uuid.uuid4())
        tx = str(uuid.uuid4())
        parent_doc_id = str(uuid.uuid4())

        view._create_component_tiles(
            resource_id,
            tx,
            _make_minimal_component_data(),
            deps={"parentDocument": parent_doc_id},
            concepts={},
            created_deps={},
        )

        icon_tiles = [
            t for t in view._tile_buffer if str(t.nodegroup_id) == COMP_ICONOGRAPHIC_NG
        ]
        self.assertEqual(len(icon_tiles), 3, "expected 3 COMP_ICONOGRAPHIC_NG tiles")
        sortorders = [t.sortorder for t in icon_tiles]
        self.assertEqual(
            sortorders,
            list(range(len(icon_tiles))),
            f"expected [0, 1, 2], got {sortorders}",
        )

    def test_create_tile_direct_increments_sortorder(self):
        """Direct unit test of _create_tile: calling it twice with the same
        nodegroup and resource must yield sortorder 0 then 1."""
        from manuspectrum.views.biblissima_proxy import BiblissimaCreateResourceView

        view = BiblissimaCreateResourceView()
        view._tile_buffer = []
        ng = "aaaa0000-0000-0000-0000-000000000000"
        rid = str(uuid.uuid4())

        t0 = view._create_tile(ng, rid, {})
        t1 = view._create_tile(ng, rid, {})
        t2 = view._create_tile(ng, rid, {})

        self.assertEqual(t0.sortorder, 0)
        self.assertEqual(t1.sortorder, 1)
        self.assertEqual(t2.sortorder, 2)

    def test_create_tile_different_nodegroups_each_start_at_zero(self):
        """Different nodegroups on the same resource must each get their own
        counter starting at 0."""
        from manuspectrum.views.biblissima_proxy import BiblissimaCreateResourceView

        view = BiblissimaCreateResourceView()
        view._tile_buffer = []
        ng_a = "aaaa0000-0000-0000-0000-000000000001"
        ng_b = "bbbb0000-0000-0000-0000-000000000002"
        rid = str(uuid.uuid4())

        ta0 = view._create_tile(ng_a, rid, {})
        tb0 = view._create_tile(ng_b, rid, {})
        ta1 = view._create_tile(ng_a, rid, {})
        tb1 = view._create_tile(ng_b, rid, {})

        self.assertEqual(ta0.sortorder, 0)
        self.assertEqual(ta1.sortorder, 1)
        self.assertEqual(tb0.sortorder, 0)
        self.assertEqual(tb1.sortorder, 1)


class NestedTileFKOrderingTests(TestCase):
    """Parent tiles must appear BEFORE their children in self._tile_buffer so
    that PostgreSQL can resolve the FK from child.parenttile_id to a row that
    already exists (bulk_create inserts rows in buffer order).

    Audit result: the builder already maintains correct parent-before-child
    ordering, so these are characterization tests — they document the contract
    and will catch any future reorder of the builder logic.
    """

    def setUp(self):
        cache.clear()

    def tearDown(self):
        cache.clear()

    def test_document_builder_no_parenttile_used(self):
        """_create_document_tiles does not use parenttile (flat structure).
        All tiles must have parenttile=None."""
        view = _make_builder_view()
        resource_id = str(uuid.uuid4())
        tx = str(uuid.uuid4())

        view._create_document_tiles(
            resource_id,
            tx,
            _make_minimal_document_data(),
            deps={},
            concepts={},
            created_deps={},
        )

        child_tiles = [t for t in view._tile_buffer if getattr(t, "parenttile", None)]
        self.assertEqual(
            child_tiles,
            [],
            "document builder must not produce any nested (parenttile!=None) tiles",
        )

    def test_component_builder_parents_before_children(self):
        """Every child tile in _create_component_tiles must have its parent
        appearing at an earlier index in self._tile_buffer.

        Chain: COMP_PARENT_DOC_NG (item_feature) → COMP_PRODUCTION_NG
        → COMP_PERIOD_NG; also COMP_PARENT_DOC_NG → COMP_LOCATION_DOC_NG.
        """
        view = _make_builder_view()
        resource_id = str(uuid.uuid4())
        tx = str(uuid.uuid4())
        parent_doc_id = str(uuid.uuid4())

        view._create_component_tiles(
            resource_id,
            tx,
            _make_minimal_component_data(),
            deps={"parentDocument": parent_doc_id},
            concepts={},
            created_deps={},
        )

        buffer = view._tile_buffer
        tile_index = {t.tileid: i for i, t in enumerate(buffer)}

        for tile in buffer:
            parent = getattr(tile, "parenttile", None)
            if parent is None:
                continue
            parent_idx = tile_index.get(parent.tileid)
            self.assertIsNotNone(
                parent_idx,
                f"parent tile {parent.tileid} of {tile.tileid} not found in buffer",
            )
            child_idx = tile_index[tile.tileid]
            self.assertLess(
                parent_idx,
                child_idx,
                f"parent tile (idx={parent_idx}) must come BEFORE child tile "
                f"(idx={child_idx}) in buffer; nodegroup={tile.nodegroup_id}",
            )


# ---------------------------------------------------------------------------
# Task 1.4 — Buffer isolation + EditLog row construction (incl. user=None)
# + single-tx_id invariant
# ---------------------------------------------------------------------------
#
# DESIGN NOTES
#
# Buffer isolation:
#   _create_resource (line 2519) and _create_dependency_resource (line 2429)
#   both start with ``self._tile_buffer = []``.  _flush_tile_buffer (line
#   2659-2660) does ``tiles = self._tile_buffer; self._tile_buffer = []``
#   before any processing, so stale tiles from a prior (possibly failed)
#   request can never leak into a new one.
#
# EditLog construction / single-tx_id invariant:
#   fallback_tx = default_transaction_id or uuid.uuid4()
#   Each EditLog row uses:
#       transactionid = getattr(t, "_mspectrum_transaction_id", None) or fallback_tx
#   Because ``_create_tile`` initialises ``t._mspectrum_transaction_id =
#   transaction_id`` (passed explicitly) and the normal bulk path passes
#   transaction_id=None, all tiles built by the standard builders have
#   _mspectrum_transaction_id=None.  With ``None or fallback_tx`` every row
#   unconditionally uses ``fallback_tx = default_transaction_id`` when one is
#   supplied — the single-tx_id invariant is therefore a characterization of
#   current behaviour: no code change is required.


class BufferIsolationTests(TestCase):
    """The tile buffer must be reset to [] at entry of _create_resource /
    _create_dependency_resource and after _flush_tile_buffer, so stale tiles
    from a prior (possibly failed) request never leak into a new one.

    These tests verify the reset semantics directly on _flush_tile_buffer
    (because _create_resource/_create_dependency_resource need a real DB and
    cannot be called without a live graph), and indirectly via a direct call
    to _flush_tile_buffer with a pre-filled buffer.
    """

    def setUp(self):
        cache.clear()

    def tearDown(self):
        cache.clear()

    @patch(PATCH_EDITLOG)
    @patch(PATCH_TILEMODEL)
    @patch(PATCH_VALUE)
    @patch(PATCH_FACTORY)
    def test_flush_resets_buffer_to_empty(
        self, MockFactory, MockValue, MockTileModel, MockEditLog
    ):
        """After _flush_tile_buffer returns, self._tile_buffer must be []."""
        MockValue.objects.filter.return_value.values_list.return_value = []
        concept_dt = _concept_dt_mock()
        other_dt = _other_dt_mock()
        _patch_factory(MockFactory, concept_dt, other_dt)
        MockTileModel.objects.bulk_create.return_value = []
        MockEditLog.objects.bulk_create.return_value = []

        tile = _make_tile(data={TEXT_NODE_ID: {"en": "hello"}})
        view = _make_view_with_tiles([tile])
        resource = _make_resource()

        self.assertEqual(len(view._tile_buffer), 1, "pre-condition: buffer has 1 tile")
        view._flush_tile_buffer(resource, user=None, default_transaction_id=None)
        self.assertEqual(
            view._tile_buffer,
            [],
            "_tile_buffer must be [] after _flush_tile_buffer",
        )

    @patch(PATCH_EDITLOG)
    @patch(PATCH_TILEMODEL)
    @patch(PATCH_VALUE)
    @patch(PATCH_FACTORY)
    def test_flush_resets_buffer_before_validation(
        self, MockFactory, MockValue, MockTileModel, MockEditLog
    ):
        """Even when _flush_tile_buffer raises (e.g. TileValidationError),
        the buffer is already reset at the very start of the method, so
        a subsequent call on the same view sees an empty buffer."""
        from arches.app.models.tile import TileValidationError

        MockValue.objects.filter.return_value.values_list.return_value = []

        concept_dt = _concept_dt_mock()
        concept_dt.validate.return_value = [{"type": "ERROR", "message": "bad"}]
        other_dt = _other_dt_mock()
        _patch_factory(MockFactory, concept_dt, other_dt)
        MockTileModel.objects.bulk_create.return_value = []
        MockEditLog.objects.bulk_create.return_value = []

        # Seed garbage from a prior "request"
        stale_tile = _make_tile(data={CONCEPT_NODE_ID: ABSENT_CONCEPT_UUID})
        view = _make_view_with_tiles([stale_tile])
        resource = _make_resource()

        with self.assertRaises(TileValidationError):
            view._flush_tile_buffer(resource, user=None, default_transaction_id=None)

        # After the exception, the buffer must still be empty — stale tiles
        # cannot survive into a future call.
        self.assertEqual(
            view._tile_buffer,
            [],
            "_tile_buffer must be [] even after _flush_tile_buffer raises",
        )

    def test_create_resource_resets_buffer_documented_contract(self):
        """Characterization: the source of _create_resource at line 2519
        performs ``self._tile_buffer = []`` before any tile building.

        This test verifies the contract by reading the source directly —
        checking the reset is present before we can run ORM-heavy paths.
        """
        import inspect
        from manuspectrum.views.biblissima_proxy import BiblissimaCreateResourceView

        src = inspect.getsource(BiblissimaCreateResourceView._create_resource)
        # The very first statement inside ``with transaction.atomic():``
        # must be the buffer reset.
        self.assertIn(
            "self._tile_buffer = []",
            src,
            "_create_resource must reset self._tile_buffer = [] at entry",
        )

    def test_create_dependency_resource_resets_buffer_documented_contract(self):
        """Characterization: the source of _create_dependency_resource at
        line 2429 performs ``self._tile_buffer = []`` before any tile
        building."""
        import inspect
        from manuspectrum.views.biblissima_proxy import BiblissimaCreateResourceView

        src = inspect.getsource(
            BiblissimaCreateResourceView._create_dependency_resource
        )
        self.assertIn(
            "self._tile_buffer = []",
            src,
            "_create_dependency_resource must reset self._tile_buffer = [] at entry",
        )


# ---------------------------------------------------------------------------
# UUIDs and tiles for EditLog tests
# ---------------------------------------------------------------------------

EDITLOG_TX_ID = "cccccccc-1111-1111-1111-cccccccccccc"
EDITLOG_TILE_ID_A = "dddddddd-2222-2222-2222-dddddddddddd"
EDITLOG_TILE_ID_B = "eeeeeeee-3333-3333-3333-eeeeeeeeeeee"
EDITLOG_TILE_ID_C = "ffffffff-4444-4444-4444-ffffffffffff"


def _make_tile_for_editlog(tile_id, mspectrum_tx=None):
    """Return a tile-like object with no per-tile _mspectrum_transaction_id
    (simulating tiles created via the standard builder path)."""
    tile = SimpleNamespace(
        tileid=uuid.UUID(tile_id),
        nodegroup_id=NODEGROUP_ID,
        resourceinstance_id=RESOURCE_ID,
        data={TEXT_NODE_ID: {"en": "value"}},
        parenttile=None,
        _mspectrum_transaction_id=mspectrum_tx,  # None on the normal path
    )
    return tile


class EditLogConstructionTests(TestCase):
    """_flush_tile_buffer must build one EditLog row per tile with:
    - edittype == "tile create"
    - note == "resource creation"
    - userid is None when user=None
    - user_username, user_firstname, user_lastname, user_email all == ""
    - every row's transactionid equals the passed default_transaction_id
      (single-tx_id invariant).

    Characterization note: current behaviour already satisfies the invariant
    because _create_tile sets _mspectrum_transaction_id=None by default and
    ``None or fallback_tx`` unconditionally uses fallback_tx, which is
    default_transaction_id when one is supplied.  No fix was needed.
    """

    def setUp(self):
        cache.clear()

    def tearDown(self):
        cache.clear()

    def _run_flush(self, tiles, user, tx_id):
        """Helper: run _flush_tile_buffer with patches and return the
        list passed to EditLog.objects.bulk_create.

        EditLog is patched so that ``EditLog(**kwargs)`` returns a
        ``SimpleNamespace(**kwargs)`` — this lets us assert on the fields
        actually passed to the constructor (transactionid, edittype, etc.)
        rather than getting opaque MagicMock objects back.
        """
        captured = {}

        with patch(PATCH_FACTORY) as MockFactory, \
             patch(PATCH_VALUE) as MockValue, \
             patch(PATCH_TILEMODEL) as MockTileModel, \
             patch(PATCH_EDITLOG) as MockEditLog:

            MockValue.objects.filter.return_value.values_list.return_value = []
            concept_dt = _concept_dt_mock()
            other_dt = _other_dt_mock()
            _patch_factory(MockFactory, concept_dt, other_dt)
            MockTileModel.objects.bulk_create.return_value = []

            # Make EditLog(**kwargs) return a SimpleNamespace so field
            # access on the returned objects works correctly.
            MockEditLog.side_effect = lambda **kwargs: SimpleNamespace(**kwargs)

            def capture_edits(edits):
                captured["edits"] = list(edits)
                return []

            MockEditLog.objects.bulk_create.side_effect = capture_edits

            view = _make_view_with_tiles(tiles)
            resource = _make_resource()
            view._flush_tile_buffer(resource, user=user, default_transaction_id=tx_id)

        return captured.get("edits", [])

    def test_one_editlog_row_per_tile(self):
        """One EditLog row must be created for each tile in the buffer."""
        tiles = [
            _make_tile_for_editlog(EDITLOG_TILE_ID_A),
            _make_tile_for_editlog(EDITLOG_TILE_ID_B),
            _make_tile_for_editlog(EDITLOG_TILE_ID_C),
        ]
        edits = self._run_flush(tiles, user=None, tx_id=EDITLOG_TX_ID)
        self.assertEqual(
            len(edits), 3, f"expected 3 EditLog rows, got {len(edits)}"
        )

    def test_edittype_is_tile_create(self):
        """Every EditLog row must have edittype == 'tile create'."""
        tiles = [
            _make_tile_for_editlog(EDITLOG_TILE_ID_A),
            _make_tile_for_editlog(EDITLOG_TILE_ID_B),
        ]
        edits = self._run_flush(tiles, user=None, tx_id=EDITLOG_TX_ID)
        for row in edits:
            self.assertEqual(
                row.edittype,
                "tile create",
                f"expected edittype='tile create', got {row.edittype!r}",
            )

    def test_note_is_resource_creation(self):
        """Every EditLog row must have note == 'resource creation'."""
        tiles = [_make_tile_for_editlog(EDITLOG_TILE_ID_A)]
        edits = self._run_flush(tiles, user=None, tx_id=EDITLOG_TX_ID)
        for row in edits:
            self.assertEqual(
                row.note,
                "resource creation",
                f"expected note='resource creation', got {row.note!r}",
            )

    def test_user_none_yields_null_userid_and_empty_user_fields(self):
        """When user=None, userid must be None and all user string fields ""."""
        tiles = [_make_tile_for_editlog(EDITLOG_TILE_ID_A)]
        edits = self._run_flush(tiles, user=None, tx_id=EDITLOG_TX_ID)
        self.assertEqual(len(edits), 1)
        row = edits[0]
        self.assertIsNone(row.userid, f"userid must be None when user=None, got {row.userid!r}")
        self.assertEqual(row.user_username, "", f"user_username must be '' when user=None")
        self.assertEqual(row.user_firstname, "", f"user_firstname must be '' when user=None")
        self.assertEqual(row.user_lastname, "", f"user_lastname must be '' when user=None")
        self.assertEqual(row.user_email, "", f"user_email must be '' when user=None")

    def test_single_tx_id_invariant_all_rows_use_default_tx(self):
        """CHARACTERIZATION: when a default_transaction_id is provided and
        tiles have _mspectrum_transaction_id=None (the normal builder path),
        every EditLog row must carry that exact transactionid.

        The invariant is maintained by:
            fallback_tx = default_transaction_id or uuid.uuid4()
            transactionid = getattr(t, "_mspectrum_transaction_id", None) or fallback_tx
        Since _mspectrum_transaction_id is None → None or fallback_tx →
        fallback_tx = default_transaction_id for every tile.

        This is a characterization test; no code change was required.
        """
        tiles = [
            _make_tile_for_editlog(EDITLOG_TILE_ID_A),  # _mspectrum_transaction_id=None
            _make_tile_for_editlog(EDITLOG_TILE_ID_B),  # _mspectrum_transaction_id=None
            _make_tile_for_editlog(EDITLOG_TILE_ID_C),  # _mspectrum_transaction_id=None
        ]
        edits = self._run_flush(tiles, user=None, tx_id=EDITLOG_TX_ID)
        self.assertEqual(len(edits), 3)
        tx_ids = {str(row.transactionid) for row in edits}
        self.assertEqual(
            tx_ids,
            {EDITLOG_TX_ID},
            f"all rows must share transactionid={EDITLOG_TX_ID!r}, got {tx_ids}",
        )

    def test_no_tx_scatter_with_mixed_per_tile_ids(self):
        """When tiles DO carry a per-tile _mspectrum_transaction_id (explicit
        override), that tile's tx wins over the default.  This test documents
        the current override semantics and prevents silent regressions.

        Per-tile override is a P3 / future concern; the primary path always
        leaves _mspectrum_transaction_id=None, so the default_transaction_id
        is used for all tiles.
        """
        per_tile_tx = "aaaaaaaa-5555-5555-5555-aaaaaaaaaaaa"
        tiles = [
            _make_tile_for_editlog(EDITLOG_TILE_ID_A, mspectrum_tx=None),
            _make_tile_for_editlog(EDITLOG_TILE_ID_B, mspectrum_tx=per_tile_tx),
        ]
        edits = self._run_flush(tiles, user=None, tx_id=EDITLOG_TX_ID)
        self.assertEqual(len(edits), 2)

        tx_by_tile = {str(row.tileinstanceid): str(row.transactionid) for row in edits}
        # Tile A has no per-tile tx → uses default
        self.assertEqual(
            tx_by_tile[EDITLOG_TILE_ID_A],
            EDITLOG_TX_ID,
            "tile without per-tile tx must use default_transaction_id",
        )
        # Tile B has a per-tile tx → uses its own
        self.assertEqual(
            tx_by_tile[EDITLOG_TILE_ID_B],
            per_tile_tx,
            "tile with per-tile _mspectrum_transaction_id must use its own tx id",
        )

    def test_empty_buffer_produces_no_editlog_rows(self):
        """When the tile buffer is empty, _flush_tile_buffer returns early and
        EditLog.objects.bulk_create must NOT be called."""
        with patch(PATCH_FACTORY) as MockFactory, \
             patch(PATCH_VALUE) as MockValue, \
             patch(PATCH_TILEMODEL) as MockTileModel, \
             patch(PATCH_EDITLOG) as MockEditLog:

            MockValue.objects.filter.return_value.values_list.return_value = []
            _patch_factory(MockFactory, _concept_dt_mock(), _other_dt_mock())
            MockTileModel.objects.bulk_create.return_value = []
            MockEditLog.objects.bulk_create.return_value = []

            view = _make_view_with_tiles([])  # empty buffer
            resource = _make_resource()
            view._flush_tile_buffer(resource, user=None, default_transaction_id=EDITLOG_TX_ID)

            MockEditLog.objects.bulk_create.assert_not_called()


# ---------------------------------------------------------------------------
# Task 2.1 — _extract_tile_value and _displayname_from_i18n pure helpers
# ---------------------------------------------------------------------------


class ExtractTileValueTests(TestCase):
    """Unit tests for BiblissimaCheckDuplicatesView._extract_tile_value.

    Mirrors the inline i18n block at biblissima_proxy.py ~1551-1559:
    - dict: return first non-empty ``value`` among en → fr → de → es → it
    - plain string: return str(raw_value).strip() if truthy else ""
    - falsy / empty dict: return ""
    """

    @classmethod
    def _fn(cls, raw_value):
        from manuspectrum.views.biblissima_proxy import BiblissimaCheckDuplicatesView

        return BiblissimaCheckDuplicatesView._extract_tile_value(raw_value)

    # -- dict branch: language priority -----------------------------------------

    def test_dict_picks_en_first(self):
        raw = {
            "en": {"value": "English title"},
            "fr": {"value": "Titre français"},
        }
        self.assertEqual(self._fn(raw), "English title")

    def test_dict_falls_to_fr_when_en_absent(self):
        raw = {
            "fr": {"value": "Titre français"},
            "de": {"value": "Deutsches Titel"},
        }
        self.assertEqual(self._fn(raw), "Titre français")

    def test_dict_falls_to_de(self):
        raw = {
            "de": {"value": "Deutsches Titel"},
            "es": {"value": "Título español"},
        }
        self.assertEqual(self._fn(raw), "Deutsches Titel")

    def test_dict_falls_to_es(self):
        raw = {"es": {"value": "Título español"}, "it": {"value": "Titolo italiano"}}
        self.assertEqual(self._fn(raw), "Título español")

    def test_dict_falls_to_it(self):
        raw = {"it": {"value": "Titolo italiano"}}
        self.assertEqual(self._fn(raw), "Titolo italiano")

    def test_dict_en_empty_value_falls_to_fr(self):
        """An en entry whose ``value`` is '' or missing is skipped."""
        raw = {
            "en": {"value": ""},
            "fr": {"value": "Titre français"},
        }
        self.assertEqual(self._fn(raw), "Titre français")

    def test_dict_en_missing_value_key_falls_to_fr(self):
        """An en entry that has no ``value`` key is skipped."""
        raw = {
            "en": {},
            "fr": {"value": "Titre français"},
        }
        self.assertEqual(self._fn(raw), "Titre français")

    def test_dict_en_not_a_dict_falls_to_fr(self):
        """An en entry that is not a dict (e.g. a plain string) is skipped."""
        raw = {
            "en": "not-a-dict",
            "fr": {"value": "Titre français"},
        }
        self.assertEqual(self._fn(raw), "Titre français")

    def test_dict_all_empty_returns_empty_string(self):
        """No language has a usable value → ""."""
        raw = {
            "en": {"value": ""},
            "fr": {},
            "de": "bad",
            "es": {"value": ""},
            "it": {"value": ""},
        }
        self.assertEqual(self._fn(raw), "")

    def test_empty_dict_returns_empty_string(self):
        self.assertEqual(self._fn({}), "")

    def test_dict_strips_whitespace(self):
        raw = {"en": {"value": "  padded  "}}
        self.assertEqual(self._fn(raw), "padded")

    # -- plain string / scalar branch -------------------------------------------

    def test_plain_string_returned_stripped(self):
        self.assertEqual(self._fn("  Hello  "), "Hello")

    def test_plain_string_no_whitespace(self):
        self.assertEqual(self._fn("Hello"), "Hello")

    def test_empty_string_returns_empty_string(self):
        self.assertEqual(self._fn(""), "")

    def test_none_returns_empty_string(self):
        self.assertEqual(self._fn(None), "")

    def test_zero_returns_empty_string(self):
        """0 is falsy → ""."""
        self.assertEqual(self._fn(0), "")

    def test_integer_nonzero_returns_str(self):
        """A truthy non-string scalar is coerced via str()."""
        self.assertEqual(self._fn(42), "42")


class DisplaynameFromI18nTests(TestCase):
    """Unit tests for BiblissimaCheckDuplicatesView._displayname_from_i18n.

    Mirrors ``str(ri.name) if ri.name else ""`` from _get_resource_name.
    """

    @classmethod
    def _fn(cls, name):
        from manuspectrum.views.biblissima_proxy import BiblissimaCheckDuplicatesView

        return BiblissimaCheckDuplicatesView._displayname_from_i18n(name)

    def test_truthy_string_returned_as_str(self):
        self.assertEqual(self._fn("Some Title"), "Some Title")

    def test_truthy_dict_stringified(self):
        """A raw I18n dict is passed to str() — the exact repr doesn't matter
        as long as it's a non-empty string."""
        d = {"en": {"value": "Title"}}
        result = self._fn(d)
        self.assertIsInstance(result, str)
        self.assertTrue(result, "expected non-empty string for truthy dict")

    def test_none_returns_empty_string(self):
        self.assertEqual(self._fn(None), "")

    def test_empty_string_returns_empty_string(self):
        self.assertEqual(self._fn(""), "")

    def test_zero_returns_empty_string(self):
        """0 is falsy → ""."""
        self.assertEqual(self._fn(0), "")

    def test_integer_nonzero_returns_str(self):
        self.assertEqual(self._fn(42), "42")


# ---------------------------------------------------------------------------
# Tasks 2.2 + 2.3 — CheckDuplicates N×M hoist: parity + scaling tests
# ---------------------------------------------------------------------------
#
# DESIGN: BiblissimaCheckDuplicatesView.post() previously called
# Tile.objects.filter(...) once PER ITEM inside the items loop (O(N×M) where
# N=items, M=corpus).  The rewrite hoists the corpus load to ONCE before the
# loop and resolves all matched resource names in a single batched
# ResourceInstance.objects.filter(...__in=...) call after the loop.
#
# Patch targets
# -------------
# Tile and ResourceInstance are imported at module level in biblissima_proxy,
# so we patch them via the proxy module namespace.
PATCH_TILE = "manuspectrum.views.biblissima_proxy.Tile"
PATCH_RESOURCE_INSTANCE = "manuspectrum.views.biblissima_proxy.ResourceInstance"

# Fixed UUIDs for corpus/name data
_RID_A = "aaaaaaaa-0001-0001-0001-aaaaaaaaaaaa"
_RID_B = "bbbbbbbb-0002-0002-0002-bbbbbbbbbbbb"
_RID_C = "cccccccc-0003-0003-0003-cccccccccccc"

# Corpus: two tiles whose values match specific ark tokens.
# _RID_A's tile value IS the ark token directly; _RID_B's value contains it.
_CORPUS_ARK_A = "ark:/43093/ifdataA001"
_CORPUS_ARK_B = "ark:/43093/ifdataB002"

def _make_corpus_tile(tile_value, rid, id_node=None):
    """Return a minimal tile-like object for the corpus (tile_index building).

    *id_node* must be the same key the view will use to look up the value in
    tile.data (i.e. DOC_IDENTIFIER_VALUE or COMP_IDENTIFIER_VALUE).  Pass it
    explicitly from the test so the corpus tiles match the view's lookup key.
    """
    key = id_node or "00000000-0000-0000-0000-000000000002"
    tile = SimpleNamespace(
        data={key: tile_value},
        resourceinstance_id=rid,
    )
    return tile


def _build_mock_tile(corpus_tiles):
    """Return a patcher context for Tile that yields corpus_tiles on filter()."""
    # filter() returns an iterable; we patch it as a list so the for-loop works.
    mock_tile_cls = MagicMock()
    mock_tile_cls.objects.filter.return_value = corpus_tiles
    return mock_tile_cls


def _build_mock_ri(names_by_rid):
    """Return a patcher context for ResourceInstance that yields (rid, name) pairs
    from values_list() on filter(resourceinstanceid__in=...)."""
    mock_ri_cls = MagicMock()
    mock_ri_cls.objects.filter.return_value.values_list.return_value = list(
        names_by_rid.items()
    )
    return mock_ri_cls


def _post_check_duplicates(items, graph_id, mock_tile_cls, mock_ri_cls):
    """Drive BiblissimaCheckDuplicatesView.post() with mocked ORM.

    Returns the parsed JSON response dict.
    """
    import json as _json
    from django.test import RequestFactory
    from manuspectrum.views.biblissima_proxy import BiblissimaCheckDuplicatesView

    rf = RequestFactory()
    body = _json.dumps({"graphId": graph_id, "items": items})
    req = rf.post(
        "/api/biblissima/check-duplicates",
        data=body,
        content_type="application/json",
    )
    view = BiblissimaCheckDuplicatesView()

    with patch(PATCH_TILE, mock_tile_cls), patch(PATCH_RESOURCE_INSTANCE, mock_ri_cls):
        # Also stub out ES strategies so they don't hit a real cluster.
        with patch.object(view, "_es_string_search"):
            response = view.post(req)

    return _json.loads(response.content)


class CheckDuplicatesParityTests(TestCase):
    """Task 2.2 — parity: the per-item identifier suggestions are IDENTICAL
    whether the batch has 1 item or 25 items (with overlapping tokens)."""

    def setUp(self):
        cache.clear()

    def tearDown(self):
        cache.clear()

    def _build_corpus(self):
        """Return the fixed corpus tiles and names used across parity tests."""
        from manuspectrum.constants.biblissima import DOC_IDENTIFIER_VALUE

        corpus_tiles = [
            _make_corpus_tile(_CORPUS_ARK_A, _RID_A, id_node=DOC_IDENTIFIER_VALUE),
            _make_corpus_tile(_CORPUS_ARK_B, _RID_B, id_node=DOC_IDENTIFIER_VALUE),
        ]
        names_by_rid = {
            _RID_A: "Manuscript Alpha",
            _RID_B: "Manuscript Beta",
        }
        return corpus_tiles, names_by_rid

    def _item_matching_a(self, suffix=""):
        """An item whose arkId token matches _RID_A's tile value exactly."""
        return {
            "arkId": _CORPUS_ARK_A,
            "label": f"Label A{suffix}",
            "shelfmark": "",
            "biblissimaQid": "",
            "portalHash": "",
            "manifestUrl": "",
        }

    def _item_matching_b(self, suffix=""):
        """An item whose arkId token matches _RID_B's tile value exactly."""
        return {
            "arkId": _CORPUS_ARK_B,
            "label": f"Label B{suffix}",
            "shelfmark": "",
            "biblissimaQid": "",
            "portalHash": "",
            "manifestUrl": "",
        }

    def _item_no_match(self, suffix=""):
        """An item with no matching tokens."""
        return {
            "arkId": "ark:/43093/noMatch999",
            "label": f"No Match{suffix}",
            "shelfmark": "",
            "biblissimaQid": "",
            "portalHash": "",
            "manifestUrl": "",
        }

    def test_single_item_returns_expected_suggestion(self):
        """A single-item request must yield the expected identifier suggestion."""
        from manuspectrum.views.biblissima_proxy import DOCUMENT_GRAPH_ID

        corpus_tiles, names_by_rid = self._build_corpus()
        mock_tile = _build_mock_tile(corpus_tiles)
        mock_ri = _build_mock_ri(names_by_rid)

        data = _post_check_duplicates(
            items=[self._item_matching_a()],
            graph_id=DOCUMENT_GRAPH_ID,
            mock_tile_cls=mock_tile,
            mock_ri_cls=mock_ri,
        )

        self.assertEqual(len(data["results"]), 1)
        suggestions = data["results"][0]["suggestions"]
        self.assertEqual(len(suggestions), 1)
        self.assertEqual(suggestions[0]["resourceId"], _RID_A)
        self.assertEqual(suggestions[0]["displayname"], "Manuscript Alpha")
        self.assertEqual(suggestions[0]["matchType"], "identifier")
        self.assertEqual(suggestions[0]["confidence"], "high")

    def test_parity_1_vs_25_items_same_suggestion_for_first_item(self):
        """The suggestion list for item[0] must be IDENTICAL whether the batch
        has 1 item or 25 items (overlapping tokens across items)."""
        from manuspectrum.views.biblissima_proxy import DOCUMENT_GRAPH_ID

        corpus_tiles, names_by_rid = self._build_corpus()

        # --- 1-item batch ---
        mock_tile_1 = _build_mock_tile(corpus_tiles)
        mock_ri_1 = _build_mock_ri(names_by_rid)
        data_1 = _post_check_duplicates(
            items=[self._item_matching_a()],
            graph_id=DOCUMENT_GRAPH_ID,
            mock_tile_cls=mock_tile_1,
            mock_ri_cls=mock_ri_1,
        )
        sugg_1 = data_1["results"][0]["suggestions"]

        # --- 25-item batch: item[0] is the same; rest alternate A/B/no-match ---
        items_25 = [self._item_matching_a()]
        for i in range(1, 25):
            if i % 3 == 0:
                items_25.append(self._item_matching_a(suffix=f"_{i}"))
            elif i % 3 == 1:
                items_25.append(self._item_matching_b(suffix=f"_{i}"))
            else:
                items_25.append(self._item_no_match(suffix=f"_{i}"))

        mock_tile_25 = _build_mock_tile(corpus_tiles)
        mock_ri_25 = _build_mock_ri(names_by_rid)
        data_25 = _post_check_duplicates(
            items=items_25,
            graph_id=DOCUMENT_GRAPH_ID,
            mock_tile_cls=mock_tile_25,
            mock_ri_cls=mock_ri_25,
        )
        sugg_25 = data_25["results"][0]["suggestions"]

        self.assertEqual(
            sugg_1,
            sugg_25,
            f"Suggestion for item[0] differs between 1-item and 25-item batch:\n"
            f"  1-item:  {sugg_1}\n"
            f"  25-item: {sugg_25}",
        )

    def test_parity_no_match_item_yields_empty_suggestions(self):
        """An item with no matching token must yield no identifier suggestions."""
        from manuspectrum.views.biblissima_proxy import DOCUMENT_GRAPH_ID

        corpus_tiles, names_by_rid = self._build_corpus()
        mock_tile = _build_mock_tile(corpus_tiles)
        mock_ri = _build_mock_ri(names_by_rid)

        data = _post_check_duplicates(
            items=[self._item_no_match()],
            graph_id=DOCUMENT_GRAPH_ID,
            mock_tile_cls=mock_tile,
            mock_ri_cls=mock_ri,
        )

        suggestions = data["results"][0]["suggestions"]
        identifier_hits = [s for s in suggestions if s["matchType"] == "identifier"]
        self.assertEqual(
            identifier_hits,
            [],
            f"Expected no identifier suggestions for no-match item; got {identifier_hits}",
        )


class CheckDuplicatesScalingTests(TestCase):
    """Task 2.3 — scaling: Tile.objects.filter call_count == 1 regardless
    of the number of items (proves O(1) corpus load)."""

    def setUp(self):
        cache.clear()

    def tearDown(self):
        cache.clear()

    def _run_and_count(self, n_items, graph_id):
        """Submit n_items and return (tile_filter_call_count, ri_filter_call_count)."""
        import json as _json
        from django.test import RequestFactory
        from manuspectrum.views.biblissima_proxy import BiblissimaCheckDuplicatesView
        from manuspectrum.constants.biblissima import DOC_IDENTIFIER_VALUE

        corpus_tiles = [
            _make_corpus_tile(_CORPUS_ARK_A, _RID_A, id_node=DOC_IDENTIFIER_VALUE),
        ]
        names_by_rid = {_RID_A: "Alpha"}

        mock_tile_cls = MagicMock()
        mock_tile_cls.objects.filter.return_value = corpus_tiles

        mock_ri_cls = MagicMock()
        mock_ri_cls.objects.filter.return_value.values_list.return_value = list(
            names_by_rid.items()
        )

        items = [
            {
                "arkId": _CORPUS_ARK_A,
                "label": f"Item {i}",
                "shelfmark": "",
                "biblissimaQid": "",
                "portalHash": "",
                "manifestUrl": "",
            }
            for i in range(n_items)
        ]

        rf = RequestFactory()
        body = _json.dumps({"graphId": graph_id, "items": items})
        req = rf.post(
            "/api/biblissima/check-duplicates",
            data=body,
            content_type="application/json",
        )
        view = BiblissimaCheckDuplicatesView()

        with patch(PATCH_TILE, mock_tile_cls), patch(
            PATCH_RESOURCE_INSTANCE, mock_ri_cls
        ):
            with patch.object(view, "_es_string_search"):
                view.post(req)

        return (
            mock_tile_cls.objects.filter.call_count,
            mock_ri_cls.objects.filter.call_count,
        )

    def test_tile_filter_called_once_for_1_item(self):
        """Tile.objects.filter must be called exactly once for a 1-item request."""
        from manuspectrum.views.biblissima_proxy import DOCUMENT_GRAPH_ID

        tile_calls, _ = self._run_and_count(1, DOCUMENT_GRAPH_ID)
        self.assertEqual(
            tile_calls,
            1,
            f"Tile.objects.filter must be called once for 1 item, got {tile_calls}",
        )

    def test_tile_filter_called_once_for_25_items(self):
        """Tile.objects.filter must be called exactly once for a 25-item request
        (same as 1 item — proves O(1) in len(items))."""
        from manuspectrum.views.biblissima_proxy import DOCUMENT_GRAPH_ID

        tile_calls, _ = self._run_and_count(25, DOCUMENT_GRAPH_ID)
        self.assertEqual(
            tile_calls,
            1,
            f"Tile.objects.filter must be called once for 25 items, got {tile_calls}",
        )

    def test_tile_filter_call_count_equal_for_1_and_25_items(self):
        """call_count for Tile.objects.filter must be identical (both 1) for
        1-item and 25-item requests — confirming O(1) scaling."""
        from manuspectrum.views.biblissima_proxy import DOCUMENT_GRAPH_ID

        tile_1, _ = self._run_and_count(1, DOCUMENT_GRAPH_ID)
        tile_25, _ = self._run_and_count(25, DOCUMENT_GRAPH_ID)
        self.assertEqual(
            tile_1,
            tile_25,
            f"Tile filter call_count must be equal for 1 vs 25 items "
            f"(got {tile_1} vs {tile_25})",
        )
        self.assertEqual(tile_1, 1, "Expected constant call_count of 1")

    def test_name_batching_single_ri_filter_call(self):
        """ResourceInstance.objects.filter must be called at most once (batched),
        not once per match."""
        from manuspectrum.views.biblissima_proxy import DOCUMENT_GRAPH_ID

        _, ri_calls = self._run_and_count(25, DOCUMENT_GRAPH_ID)
        self.assertEqual(
            ri_calls,
            1,
            f"ResourceInstance.objects.filter must be called exactly once "
            f"(batched name resolution), got {ri_calls}",
        )


# ---------------------------------------------------------------------------
# Task 3.1 — _flush_tile_buffer refactored into 4 reusable primitives
# ---------------------------------------------------------------------------
#
# Groups A–F verify the extraction is behavior-preserving and that the 4
# primitives are independently callable with the correct signatures.
#
# A  OrchestratorDelegationTests — exact call ORDER + argument threading
# B  CollectValidConceptsTests   — _collect_valid_concepts in isolation
# C  ValidateTilesTests          — _validate_tiles in isolation
# D  RunHookTests                — _run_hook in isolation
# E  WriteEditlogTests           — _write_editlog in isolation
# F  FlushGoldenSnapshotTests    — behavior-preservation end-to-end


# ---------------------------------------------------------------------------
# A — Orchestrator delegation
# ---------------------------------------------------------------------------


class OrchestratorDelegationTests(TestCase):
    """_flush_tile_buffer must delegate to the 4 primitives in the exact order
    specified and thread arguments correctly between them."""

    def setUp(self):
        cache.clear()

    def tearDown(self):
        cache.clear()

    @patch(PATCH_TILEMODEL)
    @patch(PATCH_FACTORY)
    def test_delegation_order_and_argument_threading(
        self, MockFactory, MockTileModel
    ):
        """Exact call order: collect → validate → run_hook(pre) →
        bulk_create → run_hook(post) → save_descriptors → write_editlog.
        The set returned by _collect_valid_concepts flows into _validate_tiles;
        the same nodes_by_id and factory go to both _run_hook calls;
        default_transaction_id is forwarded to _write_editlog as tx_id."""
        from unittest.mock import MagicMock

        from manuspectrum.views.biblissima_proxy import BiblissimaCreateResourceView

        CONCEPT_SET = frozenset({"valid-concept-uuid"})
        mock_factory_inst = MagicMock(name="factory_inst")
        MockFactory.return_value = mock_factory_inst
        MockTileModel.objects.bulk_create.return_value = []

        tile = _make_tile(data={TEXT_NODE_ID: {"en": "hello"}})
        view = BiblissimaCreateResourceView()
        view._tile_buffer = [tile]
        resource = _make_resource()
        tx_id = EDITLOG_TX_ID

        # Build a shared manager so mock_calls records cross-primitive order
        mgr = MagicMock(name="mgr")
        collect_mock = MagicMock(return_value=CONCEPT_SET)
        validate_mock = MagicMock()
        run_hook_mock = MagicMock()
        write_mock = MagicMock()
        mgr.attach_mock(collect_mock, "collect")
        mgr.attach_mock(validate_mock, "validate")
        mgr.attach_mock(run_hook_mock, "run_hook")
        mgr.attach_mock(write_mock, "write_editlog")

        with patch.object(view, "_collect_valid_concepts", collect_mock), patch.object(
            view, "_validate_tiles", validate_mock
        ), patch.object(view, "_run_hook", run_hook_mock), patch.object(
            view, "_write_editlog", write_mock
        ):
            view._flush_tile_buffer(resource, user=None, default_transaction_id=tx_id)

        # 1 — Call order (5 entries: collect, validate, run_hook×2, write_editlog)
        call_names = [c[0] for c in mgr.mock_calls]
        self.assertEqual(
            call_names,
            ["collect", "validate", "run_hook", "run_hook", "write_editlog"],
            f"Unexpected call order: {call_names}",
        )

        # 2 — _collect_valid_concepts receives (tiles, nodes_by_id)
        collect_args = collect_mock.call_args[0]
        tiles_arg, nodes_by_id_arg = collect_args[0], collect_args[1]
        self.assertEqual(tiles_arg, [tile])
        self.assertIsInstance(nodes_by_id_arg, dict)

        # 3 — The SAME nodes_by_id object flows from collect to validate and hooks
        validate_args = validate_mock.call_args[0]
        self.assertIs(validate_args[1], nodes_by_id_arg, "nodes_by_id must be threaded")
        run_hook_calls = run_hook_mock.call_args_list
        self.assertIs(run_hook_calls[0][0][1], nodes_by_id_arg, "pre_tile_save nodes_by_id")
        self.assertIs(run_hook_calls[1][0][1], nodes_by_id_arg, "post_tile_save nodes_by_id")

        # 4 — The factory instance returned by DataTypeFactory() is threaded
        self.assertIs(validate_args[2], mock_factory_inst, "factory threaded to validate")
        self.assertIs(run_hook_calls[0][0][2], mock_factory_inst, "factory to pre_tile_save")
        self.assertIs(run_hook_calls[1][0][2], mock_factory_inst, "factory to post_tile_save")

        # 5 — The CONCEPT_SET returned by collect flows into validate
        self.assertIs(validate_args[3], CONCEPT_SET, "valid_concept_ids threaded")

        # 6 — _run_hook receives correct method_name as last arg
        self.assertEqual(run_hook_calls[0][0][3], "pre_tile_save")
        self.assertEqual(run_hook_calls[1][0][3], "post_tile_save")

        # 7 — _write_editlog receives (tiles, resource, user, default_transaction_id)
        write_args = write_mock.call_args[0]
        self.assertEqual(write_args[0], [tile])
        self.assertIs(write_args[1], resource)
        self.assertIsNone(write_args[2])  # user=None
        self.assertEqual(str(write_args[3]), tx_id)

        # 8 — resource.save_descriptors is invoked exactly once by the
        # orchestrator (between run_hook(post) and write_editlog per the
        # documented order); pin it so a regression that drops or duplicates
        # the per-resource descriptor refresh is caught.
        resource.save_descriptors.assert_called_once()

    @patch(PATCH_TILEMODEL)
    @patch(PATCH_FACTORY)
    def test_empty_buffer_no_primitive_called(self, MockFactory, MockTileModel):
        """When the buffer is empty, _flush_tile_buffer returns early and
        none of the 4 primitives must be called."""
        from unittest.mock import MagicMock

        from manuspectrum.views.biblissima_proxy import BiblissimaCreateResourceView

        view = BiblissimaCreateResourceView()
        view._tile_buffer = []
        resource = _make_resource()

        collect_mock = MagicMock()
        validate_mock = MagicMock()
        run_hook_mock = MagicMock()
        write_mock = MagicMock()

        with patch.object(view, "_collect_valid_concepts", collect_mock), patch.object(
            view, "_validate_tiles", validate_mock
        ), patch.object(view, "_run_hook", run_hook_mock), patch.object(
            view, "_write_editlog", write_mock
        ):
            view._flush_tile_buffer(resource, user=None, default_transaction_id=None)

        collect_mock.assert_not_called()
        validate_mock.assert_not_called()
        run_hook_mock.assert_not_called()
        write_mock.assert_not_called()


# ---------------------------------------------------------------------------
# B — _collect_valid_concepts in isolation
# ---------------------------------------------------------------------------


class CollectValidConceptsTests(TestCase):
    """_collect_valid_concepts must issue ONE batched Value.objects.filter for
    well-formed concept UUIDs and return the confirmed set."""

    def setUp(self):
        cache.clear()

    def tearDown(self):
        cache.clear()

    def _call(self, tiles, nodes_by_id, mock_value_return=None):
        from manuspectrum.views.biblissima_proxy import BiblissimaCreateResourceView

        view = BiblissimaCreateResourceView()
        with patch(PATCH_VALUE) as MockValue:
            MockValue.objects.filter.return_value.values_list.return_value = (
                mock_value_return or []
            )
            result = view._collect_valid_concepts(tiles, nodes_by_id)
        return result, MockValue

    def test_returns_confirmed_ids_as_strings(self):
        """IDs returned by Value.filter must appear in the result set as strings."""
        tile = _make_tile(data={CONCEPT_NODE_ID: VALID_CONCEPT_UUID})
        nodes = {CONCEPT_NODE_ID: {"nodeid": CONCEPT_NODE_ID, "datatype": "concept"}}
        from manuspectrum.views.biblissima_proxy import BiblissimaCreateResourceView

        view = BiblissimaCreateResourceView()
        with patch(PATCH_VALUE) as MockValue:
            MockValue.objects.filter.return_value.values_list.return_value = [
                VALID_CONCEPT_UUID
            ]
            result = view._collect_valid_concepts([tile], nodes)
        self.assertIn(VALID_CONCEPT_UUID, result)

    def test_value_filter_called_once(self):
        """Only ONE Value.objects.filter must be issued for any batch size."""
        tiles = [
            _make_tile(data={CONCEPT_NODE_ID: VALID_CONCEPT_UUID}),
            _make_tile(data={CONCEPT_LIST_NODE_ID: [VALID_CONCEPT_UUID]}),
        ]
        nodes = {
            CONCEPT_NODE_ID: {"nodeid": CONCEPT_NODE_ID, "datatype": "concept"},
            CONCEPT_LIST_NODE_ID: {"nodeid": CONCEPT_LIST_NODE_ID, "datatype": "concept-list"},
        }
        from manuspectrum.views.biblissima_proxy import BiblissimaCreateResourceView

        view = BiblissimaCreateResourceView()
        with patch(PATCH_VALUE) as MockValue:
            MockValue.objects.filter.return_value.values_list.return_value = [
                VALID_CONCEPT_UUID
            ]
            view._collect_valid_concepts(tiles, nodes)
        self.assertEqual(
            MockValue.objects.filter.call_count, 1, "Value.filter must be called once"
        )

    def test_empty_tiles_returns_empty_set(self):
        """No tiles → empty result, no DB call."""
        from manuspectrum.views.biblissima_proxy import BiblissimaCreateResourceView

        view = BiblissimaCreateResourceView()
        with patch(PATCH_VALUE) as MockValue:
            MockValue.objects.filter.return_value.values_list.return_value = []
            result = view._collect_valid_concepts([], {})
        self.assertEqual(result, set())
        MockValue.objects.filter.assert_not_called()

    def test_malformed_uuid_excluded_from_filter(self):
        """Malformed (non-UUID) values must NOT be sent to Value.objects.filter."""
        tile = _make_tile(data={CONCEPT_NODE_ID: "not-a-uuid"})
        nodes = {CONCEPT_NODE_ID: {"nodeid": CONCEPT_NODE_ID, "datatype": "concept"}}
        from manuspectrum.views.biblissima_proxy import BiblissimaCreateResourceView

        view = BiblissimaCreateResourceView()
        with patch(PATCH_VALUE) as MockValue:
            MockValue.objects.filter.return_value.values_list.return_value = []
            view._collect_valid_concepts([tile], nodes)
        # well_formed is empty → filter never called
        MockValue.objects.filter.assert_not_called()

    def test_none_value_skipped(self):
        """None concept values must not be added to concept_ids (skip guard)."""
        tile = _make_tile(data={CONCEPT_NODE_ID: None})
        nodes = {CONCEPT_NODE_ID: {"nodeid": CONCEPT_NODE_ID, "datatype": "concept"}}
        from manuspectrum.views.biblissima_proxy import BiblissimaCreateResourceView

        view = BiblissimaCreateResourceView()
        with patch(PATCH_VALUE) as MockValue:
            MockValue.objects.filter.return_value.values_list.return_value = []
            result = view._collect_valid_concepts([tile], nodes)
        self.assertEqual(result, set())
        MockValue.objects.filter.assert_not_called()

    def test_non_concept_node_ignored(self):
        """Nodes with datatype 'string' must not trigger a Value filter."""
        tile = _make_tile(data={TEXT_NODE_ID: {"en": "hello"}})
        nodes = {TEXT_NODE_ID: {"nodeid": TEXT_NODE_ID, "datatype": "string"}}
        from manuspectrum.views.biblissima_proxy import BiblissimaCreateResourceView

        view = BiblissimaCreateResourceView()
        with patch(PATCH_VALUE) as MockValue:
            MockValue.objects.filter.return_value.values_list.return_value = []
            result = view._collect_valid_concepts([tile], nodes)
        self.assertEqual(result, set())
        MockValue.objects.filter.assert_not_called()


# ---------------------------------------------------------------------------
# C — _validate_tiles in isolation
# ---------------------------------------------------------------------------


class ValidateTilesTests(TestCase):
    """_validate_tiles must short-circuit confirmed concepts, fall through for
    unconfirmed ones, and raise TileValidationError on ERROR."""

    def setUp(self):
        cache.clear()

    def tearDown(self):
        cache.clear()

    def _nodes(self):
        return {
            CONCEPT_NODE_ID: {"nodeid": CONCEPT_NODE_ID, "datatype": "concept"},
            TEXT_NODE_ID: {"nodeid": TEXT_NODE_ID, "datatype": "string"},
        }

    def test_confirmed_concept_skips_validate(self):
        """A concept value in valid_concept_ids must NOT call datatype.validate."""
        from manuspectrum.views.biblissima_proxy import BiblissimaCreateResourceView

        concept_dt = _concept_dt_mock()
        other_dt = _other_dt_mock()
        factory = MagicMock()
        factory.get_instance.side_effect = (
            lambda dt: concept_dt if dt in ("concept", "concept-list") else other_dt
        )
        tile = _make_tile(data={CONCEPT_NODE_ID: VALID_CONCEPT_UUID})
        view = BiblissimaCreateResourceView()

        view._validate_tiles(
            [tile],
            self._nodes(),
            factory,
            valid_concept_ids={VALID_CONCEPT_UUID},
        )

        concept_dt.validate.assert_not_called()

    def test_unconfirmed_concept_triggers_validate(self):
        """A concept value NOT in valid_concept_ids must call datatype.validate."""
        from manuspectrum.views.biblissima_proxy import BiblissimaCreateResourceView

        concept_dt = _concept_dt_mock()
        concept_dt.validate.return_value = []
        other_dt = _other_dt_mock()
        factory = MagicMock()
        factory.get_instance.side_effect = (
            lambda dt: concept_dt if dt in ("concept", "concept-list") else other_dt
        )
        tile = _make_tile(data={CONCEPT_NODE_ID: ABSENT_CONCEPT_UUID})
        view = BiblissimaCreateResourceView()

        view._validate_tiles([tile], self._nodes(), factory, valid_concept_ids=set())

        concept_dt.validate.assert_called_once()

    def test_error_level_raises_tile_validation_error(self):
        """An ERROR from datatype.validate must raise TileValidationError."""
        from arches.app.models.tile import TileValidationError

        from manuspectrum.views.biblissima_proxy import BiblissimaCreateResourceView

        concept_dt = _concept_dt_mock()
        concept_dt.validate.return_value = [{"type": "ERROR", "message": "bad value"}]
        factory = MagicMock()
        factory.get_instance.return_value = concept_dt
        tile = _make_tile(data={CONCEPT_NODE_ID: ABSENT_CONCEPT_UUID})
        view = BiblissimaCreateResourceView()

        with self.assertRaises(TileValidationError):
            view._validate_tiles(
                [tile],
                self._nodes(),
                factory,
                valid_concept_ids=set(),
            )

    def test_warning_level_does_not_raise(self):
        """A WARNING from datatype.validate must NOT raise."""
        from manuspectrum.views.biblissima_proxy import BiblissimaCreateResourceView

        concept_dt = _concept_dt_mock()
        concept_dt.validate.return_value = [{"type": "WARNING", "message": "advisory"}]
        factory = MagicMock()
        factory.get_instance.return_value = concept_dt
        tile = _make_tile(data={CONCEPT_NODE_ID: ABSENT_CONCEPT_UUID})
        view = BiblissimaCreateResourceView()

        # Must not raise
        view._validate_tiles(
            [tile],
            self._nodes(),
            factory,
            valid_concept_ids=set(),
        )

    def test_unknown_node_skipped(self):
        """A nodeid not in nodes_by_id must be silently skipped."""
        from manuspectrum.views.biblissima_proxy import BiblissimaCreateResourceView

        factory = MagicMock()
        tile = _make_tile(data={"unknown-node-id": "value"})
        view = BiblissimaCreateResourceView()

        # Must not raise, factory.get_instance must not be called
        view._validate_tiles([tile], {}, factory, valid_concept_ids=set())
        factory.get_instance.assert_not_called()


# ---------------------------------------------------------------------------
# D — _run_hook in isolation
# ---------------------------------------------------------------------------


class RunHookTests(TestCase):
    """_run_hook must dispatch pre_tile_save (no request) and post_tile_save
    (request=None) correctly, skipping unknown nodes."""

    def setUp(self):
        cache.clear()

    def tearDown(self):
        cache.clear()

    def _nodes(self):
        return {TEXT_NODE_ID: {"nodeid": TEXT_NODE_ID, "datatype": "string"}}

    def test_pre_tile_save_called_without_request(self):
        """pre_tile_save must be called as method(tile, nodeid) — no request kwarg."""
        from manuspectrum.views.biblissima_proxy import BiblissimaCreateResourceView

        dt = _other_dt_mock()
        factory = MagicMock()
        factory.get_instance.return_value = dt
        tile = _make_tile(data={TEXT_NODE_ID: {"en": "hi"}})
        view = BiblissimaCreateResourceView()

        view._run_hook([tile], self._nodes(), factory, "pre_tile_save")

        dt.pre_tile_save.assert_called_once_with(tile, TEXT_NODE_ID)

    def test_post_tile_save_called_with_request_none(self):
        """post_tile_save must be called as method(tile, nodeid, request=None)."""
        from manuspectrum.views.biblissima_proxy import BiblissimaCreateResourceView

        dt = _other_dt_mock()
        factory = MagicMock()
        factory.get_instance.return_value = dt
        tile = _make_tile(data={TEXT_NODE_ID: {"en": "hi"}})
        view = BiblissimaCreateResourceView()

        view._run_hook([tile], self._nodes(), factory, "post_tile_save")

        dt.post_tile_save.assert_called_once_with(tile, TEXT_NODE_ID, request=None)

    def test_unknown_node_skipped(self):
        """A nodeid not in nodes_by_id must not trigger any datatype call."""
        from manuspectrum.views.biblissima_proxy import BiblissimaCreateResourceView

        factory = MagicMock()
        tile = _make_tile(data={"unknown-node-id": "value"})
        view = BiblissimaCreateResourceView()

        view._run_hook([tile], {}, factory, "pre_tile_save")

        factory.get_instance.assert_not_called()

    def test_multiple_tiles_all_called(self):
        """All tiles in the batch must have the hook dispatched."""
        from manuspectrum.views.biblissima_proxy import BiblissimaCreateResourceView

        dt = _other_dt_mock()
        factory = MagicMock()
        factory.get_instance.return_value = dt
        tiles = [
            _make_tile(data={TEXT_NODE_ID: {"en": "a"}}),
            _make_tile(data={TEXT_NODE_ID: {"en": "b"}}),
        ]
        view = BiblissimaCreateResourceView()

        view._run_hook(tiles, self._nodes(), factory, "pre_tile_save")

        self.assertEqual(dt.pre_tile_save.call_count, 2)


# ---------------------------------------------------------------------------
# E — _write_editlog in isolation
# ---------------------------------------------------------------------------


class WriteEditlogTests(TestCase):
    """_write_editlog must compute displayname from resource.displayname(),
    build one row per tile, and bulk-insert them."""

    def setUp(self):
        cache.clear()

    def tearDown(self):
        cache.clear()

    def _run(self, tiles, user=None, tx_id=None, displayname="Test Resource"):
        """Call _write_editlog with mocked EditLog; return the list of row objects."""
        from manuspectrum.views.biblissima_proxy import BiblissimaCreateResourceView

        captured = {}
        resource = _make_resource()
        resource.displayname.return_value = displayname

        with patch(PATCH_EDITLOG) as MockEditLog:
            MockEditLog.side_effect = lambda **kw: SimpleNamespace(**kw)

            def capture(rows):
                captured["rows"] = list(rows)
                return []

            MockEditLog.objects.bulk_create.side_effect = capture

            view = BiblissimaCreateResourceView()
            view._write_editlog(tiles, resource, user, tx_id)

        return captured.get("rows", [])

    def test_one_row_per_tile(self):
        """One EditLog row must be produced for each tile in the list."""
        tiles = [
            _make_tile_for_editlog(EDITLOG_TILE_ID_A),
            _make_tile_for_editlog(EDITLOG_TILE_ID_B),
        ]
        rows = self._run(tiles)
        self.assertEqual(len(rows), 2)

    def test_displayname_from_resource(self):
        """resourcedisplayname must equal resource.displayname()."""
        tile = _make_tile_for_editlog(EDITLOG_TILE_ID_A)
        rows = self._run([tile], displayname="My Resource Name")
        self.assertEqual(rows[0].resourcedisplayname, "My Resource Name")

    def test_tx_id_used_as_fallback(self):
        """When tiles have _mspectrum_transaction_id=None, the tx_id arg must
        be used for every row (single-tx invariant)."""
        tiles = [
            _make_tile_for_editlog(EDITLOG_TILE_ID_A),
            _make_tile_for_editlog(EDITLOG_TILE_ID_B),
        ]
        rows = self._run(tiles, tx_id=EDITLOG_TX_ID)
        tx_ids = {str(r.transactionid) for r in rows}
        self.assertEqual(tx_ids, {EDITLOG_TX_ID})

    def test_user_none_yields_null_userid_empty_fields(self):
        """user=None must produce userid=None and empty user string fields."""
        tile = _make_tile_for_editlog(EDITLOG_TILE_ID_A)
        rows = self._run([tile], user=None)
        row = rows[0]
        self.assertIsNone(row.userid)
        self.assertEqual(row.user_username, "")
        self.assertEqual(row.user_firstname, "")
        self.assertEqual(row.user_lastname, "")
        self.assertEqual(row.user_email, "")

    def test_edittype_and_note(self):
        """edittype must be 'tile create' and note must be 'resource creation'."""
        tile = _make_tile_for_editlog(EDITLOG_TILE_ID_A)
        rows = self._run([tile])
        self.assertEqual(rows[0].edittype, "tile create")
        self.assertEqual(rows[0].note, "resource creation")

    def test_displayname_called_on_resource(self):
        """resource.displayname() must be called exactly once (after save_descriptors
        has been called by the orchestrator)."""
        from manuspectrum.views.biblissima_proxy import BiblissimaCreateResourceView

        resource = _make_resource()
        resource.displayname.return_value = "Name"
        tile = _make_tile_for_editlog(EDITLOG_TILE_ID_A)

        with patch(PATCH_EDITLOG) as MockEditLog:
            MockEditLog.side_effect = lambda **kw: SimpleNamespace(**kw)
            MockEditLog.objects.bulk_create.return_value = []
            view = BiblissimaCreateResourceView()
            view._write_editlog([tile], resource, None, None)

        resource.displayname.assert_called_once()


# ---------------------------------------------------------------------------
# F — FlushGoldenSnapshotTests (behavior preservation)
# ---------------------------------------------------------------------------


class FlushGoldenSnapshotTests(TestCase):
    """End-to-end: _flush_tile_buffer (now a thin orchestrator) must produce
    the same EditLog rows and call pattern as the pre-refactor monolith."""

    def setUp(self):
        cache.clear()

    def tearDown(self):
        cache.clear()

    def _run_full_flush(self, tiles, user=None, tx_id=None):
        """Run _flush_tile_buffer with all ORM mocked; return captured EditLog rows."""
        captured = {}

        with patch(PATCH_FACTORY) as MockFactory, patch(
            PATCH_VALUE
        ) as MockValue, patch(PATCH_TILEMODEL) as MockTileModel, patch(
            PATCH_EDITLOG
        ) as MockEditLog:

            MockValue.objects.filter.return_value.values_list.return_value = [
                VALID_CONCEPT_UUID
            ]
            concept_dt = _concept_dt_mock()
            other_dt = _other_dt_mock()
            _patch_factory(MockFactory, concept_dt, other_dt)
            MockTileModel.objects.bulk_create.return_value = []

            MockEditLog.side_effect = lambda **kw: SimpleNamespace(**kw)

            def capture_bulk(rows):
                captured["rows"] = list(rows)
                return []

            MockEditLog.objects.bulk_create.side_effect = capture_bulk

            view = _make_view_with_tiles(tiles)
            resource = _make_resource()
            view._flush_tile_buffer(resource, user=user, default_transaction_id=tx_id)

        return captured.get("rows", [])

    def test_editlog_rows_match_expected_fields(self):
        """A buffer with 2 tiles must produce 2 EditLog rows with the correct
        edittype, note, and transactionid (same output as the pre-refactor path)."""
        tiles = [
            _make_tile_for_editlog(EDITLOG_TILE_ID_A),
            _make_tile_for_editlog(EDITLOG_TILE_ID_B),
        ]
        rows = self._run_full_flush(tiles, tx_id=EDITLOG_TX_ID)

        self.assertEqual(len(rows), 2, "expected 2 EditLog rows")
        for row in rows:
            self.assertEqual(row.edittype, "tile create")
            self.assertEqual(row.note, "resource creation")
            self.assertEqual(str(row.transactionid), EDITLOG_TX_ID)

    def test_empty_buffer_produces_no_editlog_rows(self):
        """Empty buffer must not call EditLog.bulk_create (early return)."""
        with patch(PATCH_FACTORY), patch(PATCH_VALUE), patch(
            PATCH_TILEMODEL
        ), patch(PATCH_EDITLOG) as MockEditLog:
            MockEditLog.objects.bulk_create.return_value = []
            view = _make_view_with_tiles([])
            resource = _make_resource()
            view._flush_tile_buffer(
                resource, user=None, default_transaction_id=EDITLOG_TX_ID
            )
            MockEditLog.objects.bulk_create.assert_not_called()

    def test_confirmed_concept_skips_validate_in_full_flush(self):
        """A confirmed concept value must not call datatype.validate (behavior
        preservation of the concept-batch short-circuit)."""
        with patch(PATCH_FACTORY) as MockFactory, patch(
            PATCH_VALUE
        ) as MockValue, patch(PATCH_TILEMODEL) as MockTileModel, patch(
            PATCH_EDITLOG
        ) as MockEditLog:

            MockValue.objects.filter.return_value.values_list.return_value = [
                VALID_CONCEPT_UUID
            ]
            concept_dt = _concept_dt_mock()
            other_dt = _other_dt_mock()
            _patch_factory(MockFactory, concept_dt, other_dt)
            MockTileModel.objects.bulk_create.return_value = []
            MockEditLog.objects.bulk_create.return_value = []
            MockEditLog.side_effect = lambda **kw: SimpleNamespace(**kw)

            tile = _make_tile(data={CONCEPT_NODE_ID: VALID_CONCEPT_UUID})
            view = _make_view_with_tiles([tile])
            resource = _make_resource()
            view._flush_tile_buffer(
                resource, user=None, default_transaction_id=EDITLOG_TX_ID
            )

        concept_dt.validate.assert_not_called()

    def test_tile_model_bulk_create_called_once(self):
        """TileModel.objects.bulk_create must be called exactly once (the single
        INSERT that replaces the per-tile Tile.save() chain)."""
        with patch(PATCH_FACTORY) as MockFactory, patch(
            PATCH_VALUE
        ) as MockValue, patch(PATCH_TILEMODEL) as MockTileModel, patch(
            PATCH_EDITLOG
        ) as MockEditLog:

            MockValue.objects.filter.return_value.values_list.return_value = []
            _patch_factory(MockFactory, _concept_dt_mock(), _other_dt_mock())
            MockTileModel.objects.bulk_create.return_value = []
            MockEditLog.objects.bulk_create.return_value = []
            MockEditLog.side_effect = lambda **kw: SimpleNamespace(**kw)

            tiles = [
                _make_tile(data={TEXT_NODE_ID: {"en": "a"}}),
                _make_tile(data={TEXT_NODE_ID: {"en": "b"}}),
            ]
            view = _make_view_with_tiles(tiles)
            resource = _make_resource()
            view._flush_tile_buffer(
                resource, user=None, default_transaction_id=EDITLOG_TX_ID
            )

        MockTileModel.objects.bulk_create.assert_called_once()


# ---------------------------------------------------------------------------
# Task 3.2 — _batch_save_descriptors (partition-by-graph) +
#            prefetch-aware MultiDescriptor
# ---------------------------------------------------------------------------

PATCH_NODE = "arches.app.models.models.Node"
PATCH_FXG = "arches.app.models.models.FunctionXGraph"


def _make_mock_resource_for_batch(graph_id):
    """Return a mock resource suitable for _batch_save_descriptors tests."""
    r = MagicMock()
    r.graph_id = graph_id
    r.descriptor_function = None
    r.save_descriptors = MagicMock()
    return r


class BatchSaveDescriptorsTests(TestCase):
    """Task 3.2 — _batch_save_descriptors must hoist Node and FunctionXGraph
    fetches once per graph and call the UNMODIFIED resource.save_descriptors
    per resource with a context containing '_prefetched_graph_nodes'."""

    def setUp(self):
        cache.clear()

    def tearDown(self):
        cache.clear()

    def _get_view(self):
        from manuspectrum.views.biblissima_proxy import BiblissimaCreateResourceView

        view = BiblissimaCreateResourceView()
        view._tile_buffer = []
        return view

    @patch(PATCH_FXG)
    @patch(PATCH_NODE)
    def test_nodes_fetched_once_per_graph(self, MockNode, MockFxg):
        """25 same-graph resources → Node.objects.filter called once AND
        FunctionXGraph.objects.filter called once (hoist proven)."""
        gid = "graph-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
        resources = [_make_mock_resource_for_batch(gid) for _ in range(25)]

        MockNode.objects.filter.return_value = []
        MockFxg.objects.filter.return_value.select_related.return_value = []

        view = self._get_view()
        view._batch_save_descriptors(resources)

        self.assertEqual(
            MockNode.objects.filter.call_count,
            1,
            f"Node.objects.filter must be called once for a same-graph batch; "
            f"got {MockNode.objects.filter.call_count}",
        )
        self.assertEqual(
            MockFxg.objects.filter.call_count,
            1,
            f"FunctionXGraph.objects.filter must be called once; "
            f"got {MockFxg.objects.filter.call_count}",
        )
        # save_descriptors called once per resource
        for r in resources:
            r.save_descriptors.assert_called_once()

    @patch(PATCH_FXG)
    @patch(PATCH_NODE)
    def test_partitions_by_graph_id(self, MockNode, MockFxg):
        """Resources across 2 graph_ids → Node.objects.filter called twice;
        each resource's save_descriptors received the nodes for ITS graph only
        (no cross-contamination)."""
        gid_a = "graph-aaaa-0000-0000-0000-aaaaaaaaaaaa"
        gid_b = "graph-bbbb-0000-0000-0000-bbbbbbbbbbbb"

        node_a = MagicMock(alias="node_alias_a")
        node_b = MagicMock(alias="node_alias_b")
        nodes_a = [node_a]
        nodes_b = [node_b]

        def node_filter_side_effect(**kwargs):
            return nodes_a if kwargs.get("graph_id") == gid_a else nodes_b

        def fxg_filter_side_effect(**kwargs):
            m = MagicMock()
            m.select_related.return_value = []
            return m

        MockNode.objects.filter.side_effect = node_filter_side_effect
        MockFxg.objects.filter.side_effect = fxg_filter_side_effect

        r_a1 = _make_mock_resource_for_batch(gid_a)
        r_a2 = _make_mock_resource_for_batch(gid_a)
        r_b1 = _make_mock_resource_for_batch(gid_b)

        view = self._get_view()
        view._batch_save_descriptors([r_a1, r_a2, r_b1])

        self.assertEqual(
            MockNode.objects.filter.call_count,
            2,
            f"Node.objects.filter must be called twice (once per graph); "
            f"got {MockNode.objects.filter.call_count}",
        )

        # No cross-contamination: graph-A nodes must appear only in graph-A
        # resources' context, and graph-B nodes only in graph-B resources.
        for r in [r_a1, r_a2]:
            ctx = r.save_descriptors.call_args[1]["context"]
            batch_nodes = ctx["_prefetched_graph_nodes"]
            self.assertIn(node_a, batch_nodes, "r_aX must receive node_a")
            self.assertNotIn(node_b, batch_nodes, "r_aX must NOT receive node_b")

        ctx_b = r_b1.save_descriptors.call_args[1]["context"]
        batch_nodes_b = ctx_b["_prefetched_graph_nodes"]
        self.assertIn(node_b, batch_nodes_b, "r_b1 must receive node_b")
        self.assertNotIn(node_a, batch_nodes_b, "r_b1 must NOT receive node_a")

    @patch(PATCH_FXG)
    @patch(PATCH_NODE)
    def test_save_descriptors_called_per_resource(self, MockNode, MockFxg):
        """The UNMODIFIED resource.save_descriptors is called once per resource
        with a context kwarg containing '_prefetched_graph_nodes' (proves value
        logic is NOT re-implemented in the batch helper)."""
        gid = "graph-cccc-0000-0000-0000-cccccccccccc"
        resources = [_make_mock_resource_for_batch(gid) for _ in range(3)]

        MockNode.objects.filter.return_value = []
        MockFxg.objects.filter.return_value.select_related.return_value = []

        view = self._get_view()
        view._batch_save_descriptors(resources)

        for i, r in enumerate(resources):
            r.save_descriptors.assert_called_once()
            call_kwargs = r.save_descriptors.call_args[1]
            self.assertIn(
                "context",
                call_kwargs,
                f"resource[{i}].save_descriptors must receive 'context' kwarg",
            )
            self.assertIn(
                "_prefetched_graph_nodes",
                call_kwargs["context"],
                f"resource[{i}].save_descriptors context must contain "
                "'_prefetched_graph_nodes'",
            )


class MultiDescriptorPrefetchTests(TestCase):
    """Task 3.2 — pins the prefetch / fallback contract on
    MultiDescriptor.get_primary_descriptor_from_nodes.

    When '_prefetched_graph_nodes' is present in context, the ORM query
    Node.objects.filter must NOT fire (prefetch consumed).
    When absent, Node.objects.filter MUST fire (byte-identical fallback).
    """

    def setUp(self):
        cache.clear()

    def tearDown(self):
        cache.clear()

    def _make_resource(self):
        resource = MagicMock()
        resource.graph = MagicMock()
        resource.resourceinstanceid = str(uuid.uuid4())
        resource.descriptors = {}
        return resource

    @patch(PATCH_NODE)
    def test_multidescriptor_uses_prefetched_nodes(self, MockNode):
        """When context['_prefetched_graph_nodes'] is set, MultiDescriptor must
        NOT call Node.objects.filter — it uses the provided list."""
        from manuspectrum.functions.multi_descriptor import MultiDescriptor

        prefetched_nodes = [MagicMock(alias="some_alias")]

        func = MultiDescriptor()
        config = {
            "nodegroup_id": str(uuid.uuid4()),
            "string_template": "no-alias-template",  # no <alias> → no tile query
        }
        resource = self._make_resource()

        func.get_primary_descriptor_from_nodes(
            resource,
            config,
            context={"_prefetched_graph_nodes": prefetched_nodes},
            descriptor="name",
        )

        MockNode.objects.filter.assert_not_called()

    @patch(PATCH_NODE)
    def test_multidescriptor_fallback_queries_when_no_prefetch(self, MockNode):
        """When context has no '_prefetched_graph_nodes' (None or missing),
        MultiDescriptor MUST call Node.objects.filter (byte-identical fallback)."""
        from manuspectrum.functions.multi_descriptor import MultiDescriptor

        MockNode.objects.filter.return_value = []

        func = MultiDescriptor()
        config = {
            "nodegroup_id": str(uuid.uuid4()),
            "string_template": "no-alias-template",  # no <alias> → no tile query
        }
        resource = self._make_resource()

        func.get_primary_descriptor_from_nodes(
            resource,
            config,
            context=None,  # no prefetch → must fall back to DB query
            descriptor="name",
        )

        MockNode.objects.filter.assert_called_once()
