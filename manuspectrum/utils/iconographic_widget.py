"""The Biblissima concept widget on the Component node « Iconographic representation » (#289).

The data package gives this node (`COMP_ICONOGRAPHIC_NODE`, a `url` node) the
generic URL widget of Arches (`urldatatype`). The project's
`biblissima-concept-widget` (the Biblissima autocomplete with its provenance
badge, `manuspectrum/widgets/biblissima-concept-widget.json`) is registered but
no node uses it. `repair()` assigns it in place, in one transaction:

- the card-node-widget row of the node, and the row of the node's copy in the
  graph's draft (the copy the Graph Designer edits and publishes from), when
  they still hold the URL widget: widget `biblissima-concept-widget`, config
  = the widget's default config plus the row's `label` key. The row's own
  label (en/fr) is kept. The URL widget's placeholders go: the new widget
  does not read them, and its empty `placeholder` shows its own translated
  prompt;
- in every language of the graph's CURRENT publication (`published_graphs`,
  what the resource editor and the reports read), the entry of that row gets
  the row's widget and config. Only that entry changes: the strings of a
  publication are per language and stay as they are. As
  `Graph.update_published_graphs()` does, the in-place edit is recorded in
  `published_graph_edits`.

No new publication: Arches 8.1 ties each resource instance to a publication
(`resource_instances.graphpublicationid`) and the resource editor sends a
resource whose publication is not the graph's current one to its report.
`graphs.publicationid` and the resource instances are not touched. Both
widgets edit the `url` datatype, so the tiles stay valid as they are.

A row holding a third widget (chosen in the Graph Designer) is left alone,
and so is its publication. A second run changes nothing; on a database
without the node (before the data package is loaded) nothing is done. When
the widget is not registered (`manage.py project update` registers the
project's widgets; `packages -o load_package` runs it) nothing is done either.

Raw SQL on the connection it is given, so that migration
`0017_iconographic_widget` runs it on the schema of its time. The values are
frozen here for that migration: a later change of this node's widget is a new
migration, not an edit of this module (`tests/test_iconographic_widget.py`
fails when the widget's id or default config no longer match them).

Callers: migration `0017_iconographic_widget` (existing databases: `migrate`
on update) and `manage.py repair_iconographic_widget` (`init`, after the
package is loaded; at any time, since it is idempotent).
"""

import json
import uuid
from dataclasses import dataclass, field

from arches.app.models.fields.i18n import I18n_JSON
from django.utils import translation

# `COMP_ICONOGRAPHIC_NODE` of `manuspectrum/constants/biblissima.py`.
NODE_ID = "56018940-ee09-11ef-9a8f-89acc4447d22"
# Arches' `urldatatype` widget (migration `models.7224_url_datatype`).
URL_WIDGET_ID = "ca0c43ff-af73-4349-bafd-53ff9f22eebd"
# `widgetid` and `defaultconfig` of `manuspectrum/widgets/biblissima-concept-widget.json`.
CONCEPT_WIDGET_ID = "29905551-a4a5-428c-bf82-2eb0ec464bab"
CONCEPT_WIDGET_CONFIG = {
    "entityType": "descriptor",
    "placeholder": "",
    "link_color": "#0055a0",
}
EDIT_NOTES = (
    "Iconographic representation: biblissima-concept-widget instead of the "
    "URL widget, in place (ManuSpectrum #289)"
)

# The node's own row (a source graph's row has no source_identifier) and the
# current publication of its graph.
SOURCE_ROW = """
    SELECT x.id, x.widgetid, g.publicationid
    FROM cards_x_nodes_x_widgets x
    JOIN nodes n ON n.nodeid = x.nodeid
    JOIN graphs g ON g.graphid = n.graphid
    WHERE x.nodeid = %(node)s AND x.source_identifier IS NULL
"""

# The node's row and its draft copies, while they hold the URL widget. A
# draft row points to the source row (`source_identifier`), its node to the
# source node.
ASSIGN_WIDGET = """
    UPDATE cards_x_nodes_x_widgets
    SET widgetid = %(concept)s,
        config = %(config)s::jsonb
            || jsonb_strip_nulls(jsonb_build_object('label', config -> 'label'))
    WHERE widgetid = %(url)s
      AND (
        id = %(row)s
        OR source_identifier = %(row)s
        OR nodeid IN (SELECT nodeid FROM nodes WHERE source_identifier = %(node)s)
      )
"""

RECORD_EDIT = """
    INSERT INTO published_graph_edits (edit_id, edit_time, publicationid, notes)
    VALUES (%s, now(), %s, %s)
"""


@dataclass
class Outcome:
    """What `repair()` found and wrote.

    `status`: `absent` (the node is not in the database), `other` (the
    node's row holds `widget_id`, neither of the two: nothing is written),
    `unregistered` (the widget is not registered: nothing is written) or
    `done`. `rows`: card-node-widget rows changed;
    `languages`: languages of `publication_id` whose entry changed.
    """

    status: str
    rows: int = 0
    languages: list = field(default_factory=list)
    publication_id: str | None = None
    widget_id: str | None = None

    @property
    def changed(self):
        return bool(self.rows or self.languages)


def _json(value):
    # Django hands jsonb to Python as text on a raw cursor.
    return json.loads(value) if isinstance(value, str) else value


def _published_config(config, language):
    """`config` as Arches publishes it in `language` (`I18n_JSON.serialize`)."""
    with translation.override(language):
        return I18n_JSON(json.loads(json.dumps(config))).serialize()


def repair(connection):
    """Assign the Biblissima concept widget to the node, in place; see the module docstring."""
    with connection.cursor() as cursor:
        cursor.execute(SOURCE_ROW, {"node": NODE_ID})
        found = cursor.fetchone()
        if found is None:
            return Outcome("absent")
        row_id, widget_id, publication_id = found
        publication_id = str(publication_id) if publication_id else None
        if str(widget_id) not in (URL_WIDGET_ID, CONCEPT_WIDGET_ID):
            return Outcome(
                "other", publication_id=publication_id, widget_id=str(widget_id)
            )

        cursor.execute("SELECT 1 FROM widgets WHERE widgetid = %s", [CONCEPT_WIDGET_ID])
        if cursor.fetchone() is None:
            return Outcome("unregistered", publication_id=publication_id)

        cursor.execute(
            ASSIGN_WIDGET,
            {
                "concept": CONCEPT_WIDGET_ID,
                "config": json.dumps(CONCEPT_WIDGET_CONFIG),
                "url": URL_WIDGET_ID,
                "row": row_id,
                "node": NODE_ID,
            },
        )
        rows = cursor.rowcount
        cursor.execute(
            "SELECT config FROM cards_x_nodes_x_widgets WHERE id = %s", [row_id]
        )
        config = _json(cursor.fetchone()[0]) or {}

        languages = []
        if publication_id:
            cursor.execute(
                "SELECT id, languageid, serialized_graph FROM published_graphs "
                "WHERE publicationid = %s ORDER BY languageid FOR UPDATE",
                [publication_id],
            )
            for pk, language, serialized_graph in cursor.fetchall():
                serialized_graph = _json(serialized_graph) or {}
                changed = False
                for entry in serialized_graph.get("cards_x_nodes_x_widgets") or []:
                    if (
                        entry.get("node_id") == NODE_ID
                        and entry.get("widget_id") != CONCEPT_WIDGET_ID
                    ):
                        entry["widget_id"] = CONCEPT_WIDGET_ID
                        entry["config"] = _published_config(config, language)
                        changed = True
                if changed:
                    cursor.execute(
                        "UPDATE published_graphs SET serialized_graph = %s::jsonb "
                        "WHERE id = %s",
                        [json.dumps(serialized_graph), pk],
                    )
                    languages.append(language)
            if languages:
                cursor.execute(
                    RECORD_EDIT, [str(uuid.uuid4()), publication_id, EDIT_NOTES]
                )

    return Outcome(
        "done", rows=rows, languages=languages, publication_id=publication_id
    )
