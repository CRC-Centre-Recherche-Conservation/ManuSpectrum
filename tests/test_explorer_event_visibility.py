"""visible_set gains Places and the carriers of the map's events (spec 2026-10-09 §2.1).

Usage:
    python manage.py test tests.test_explorer_event_visibility --settings="tests.test_settings"
"""

from manuspectrum.utils.public_visibility import visible_set
from tests.explorer_fixtures import DRAFT, ExplorerCase


class EventCarrierVisibilityTests(ExplorerCase):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.modification = cls.new_resource("modification", "Repainting")
        cls.tile(
            cls.modification, "document_modified", cls.refs(cls.components["open"])
        )
        cls.on_embargoed = cls.new_resource("modification", "Repair")
        cls.tile(
            cls.on_embargoed, "document_modified", cls.refs(cls.documents["embargoed"])
        )
        cls.alteration = cls.new_resource("alteration", "Darkening", state=DRAFT)
        cls.tile(cls.alteration, "object_altered", cls.refs(cls.documents["open"]))
        cls.dangling = cls.new_resource("alteration", "No object")

    def test_places_are_visible_unless_restricted_and_a_draft_place_is_unpublished(
        self,
    ):
        self.embargo(self.places["hidden"])
        visible = visible_set(self.anonymous)
        self.assertIn(str(self.places["paris"].pk), visible.places)
        self.assertNotIn(str(self.places["hidden"].pk), visible.places)
        self.assertIn(str(self.places["france"].pk), visible.unpublished)
        self.assertIn(str(self.places["paris"].pk), visible)

    def test_a_carrier_needs_a_visible_object(self):
        self.embargo(self.documents["embargoed"])
        visible = visible_set(self.anonymous)
        self.assertIn(str(self.modification.pk), visible.modifications)
        self.assertNotIn(str(self.on_embargoed.pk), visible.modifications)
        self.assertIn(str(self.alteration.pk), visible.alterations)
        self.assertNotIn(str(self.dangling.pk), visible.alterations)

    def test_a_draft_carrier_stays_visible_marked_unpublished(self):
        visible = visible_set(self.anonymous)
        self.assertIn(str(self.alteration.pk), visible.alterations)
        self.assertIn(str(self.alteration.pk), visible.unpublished)

    def test_an_unreadable_object_link_hides_the_carrier(self):
        node = self.nodes[("modification", "document_modified")]
        self.restrict_nodegroup(node.nodegroup_id, self.editor)
        self.assertNotIn(
            str(self.modification.pk), visible_set(self.anonymous).modifications
        )

    def test_a_restricted_carrier_is_hidden(self):
        self.embargo(self.modification)
        self.assertNotIn(
            str(self.modification.pk), visible_set(self.anonymous).modifications
        )
