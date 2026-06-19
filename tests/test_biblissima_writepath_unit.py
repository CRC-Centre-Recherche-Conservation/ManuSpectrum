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
        self.assertGreaterEqual(len(id_tiles), 2, "expected ≥2 DOC_IDENTIFIER_NG tiles")
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
