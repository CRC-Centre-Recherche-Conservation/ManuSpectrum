"""The summary fields of a Document as IIIF metadata (``iiif.record``), on real fixtures.

Usage:
    python manage.py test tests.test_iiif_record --settings=tests.test_settings
"""

import uuid
from unittest import mock

from manuspectrum.iiif import ids
from manuspectrum.iiif.record import record_metadata
from tests.explorer_fixtures import ExplorerCase

CONFIG = "manuspectrum.iiif.record.load_summary_config"


def field(alias, style="text", label=None):
    entry = {"alias": alias, "style": style}
    if label:
        entry["label"] = label
    return entry


class RecordCase(ExplorerCase):
    def metadata(self, fields, document="open", reader=None):
        subject = self.documents[document]
        with mock.patch(CONFIG, return_value={"fields": fields}):
            return record_metadata(
                subject.pk, subject.graph_id, reader or self.anonymous
            )


class RecordTests(RecordCase):
    def test_record_fields_in_configuration_order(self):
        doc = self.documents["embargoed"]
        self.tile(doc, "content_of_statement", self.string_value("A codex", "Un codex"))
        self.tile(doc, "type", self.reference_value("urn:t:book", "Book", "Livre"))
        entries = self.metadata(
            [
                field("content_of_statement", label={"en": "Note", "fr": "Notice"}),
                field("type", "chip", label={"en": "Kind", "fr": "Genre"}),
            ],
            "embargoed",
        )
        self.assertEqual(
            [
                {
                    "label": {"en": ["Note"], "fr": ["Notice"]},
                    "value": {"en": ["A codex"], "fr": ["Un codex"]},
                },
                {
                    "label": {"en": ["Kind"], "fr": ["Genre"]},
                    "value": {"en": ["Book"], "fr": ["Livre"]},
                },
            ],
            entries,
        )

    def test_record_text_drops_markup(self):
        doc = self.documents["embargoed"]
        self.tile(
            doc,
            "content_of_statement",
            self.string_value("<p>A <b>codex</b></p>", "<p>Un codex</p>"),
        )
        entries = self.metadata([field("content_of_statement")], "embargoed")
        self.assertEqual(
            [{"en": ["A codex"], "fr": ["Un codex"]}], [e["value"] for e in entries]
        )

    def test_record_identical_values_go_under_none(self):
        self.tile(
            self.documents["embargoed"], "date_start_of_production_time", "2019-01-22"
        )
        entries = self.metadata(
            [field("date_start_of_production_time", "date")], "embargoed"
        )
        self.assertEqual([{"none": ["2019-01-22"]}], [e["value"] for e in entries])

    def test_record_link_field_links_visible_resource_only(self):
        doc = self.documents["embargoed"]
        self.tile(
            doc,
            "production_at_place",
            self.refs(self.places["paris"], self.places["hidden"]),
        )
        self.embargo(self.places["hidden"])
        entries = self.metadata([field("production_at_place", "link")], "embargoed")
        href = ids.report(self.places["paris"].pk)
        self.assertEqual(1, len(entries))
        self.assertEqual({"en": [f'<a href="{href}">Paris</a>']}, entries[0]["value"])

    def test_record_skips_unreadable_nodegroup(self):
        self.tile(
            self.documents["embargoed"], "content_of_statement", self.string_value("X")
        )
        node = self.nodes[("document", "content_of_statement")]
        self.restrict_nodegroup(node.nodegroup_id, self.editor)
        fields = [field("content_of_statement")]
        self.assertEqual([], self.metadata(fields, "embargoed"))
        self.assertEqual(1, len(self.metadata(fields, "embargoed", self.editor)))

    def test_record_number_style_is_a_string(self):
        self.tile(self.documents["embargoed"], "content_of_statement", "12")
        entries = self.metadata([field("content_of_statement", "number")], "embargoed")
        self.assertEqual({"none": ["12"]}, entries[0]["value"])

    def test_record_image_style_yields_nothing(self):
        self.assertEqual([], self.metadata([field("facsimiles", "image")]))

    def test_record_without_config_is_empty(self):
        subject = self.documents["open"]
        with mock.patch(CONFIG, return_value=None):
            self.assertEqual(
                [], record_metadata(subject.pk, subject.graph_id, self.anonymous)
            )

    def test_record_unknown_graph_is_empty(self):
        with mock.patch(CONFIG, return_value={"fields": [field("x")]}):
            self.assertEqual(
                [],
                record_metadata(
                    self.documents["open"].pk, uuid.uuid4(), self.anonymous
                ),
            )
