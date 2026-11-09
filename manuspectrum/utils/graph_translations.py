"""Per-language serialisations of the graph publications, rebuilt from the graph tables.

Arches 8.1 keeps, for every graph publication (``graphs_x_published_graphs``),
one serialised graph per language of ``settings.LANGUAGES``
(``published_graphs``). The resource editor, the reports and every card-based
page read the row of the active language.

Arches 8.1.5 (``arches/app/models/graph.py``): ``Graph.update_published_graphs()``
serialises the ``Graph`` it is called on, and ``Graph.__init__`` fills the
``cards`` and ``widgets`` of a published graph from the publication of the
language active at load time, as plain strings instead of ``I18n_String``. Each
language row then receives that one language: the ``fr`` rows hold the English
card names, help texts and widget labels, although the ``cards`` and
``cards_x_nodes_x_widgets`` tables hold the French ones. It runs through
``LanguageSynchronizer.synchronize_settings_with_db()``: ``manage.py i18n
synclanguages``, and ``packages`` before each graph import (``load_package``
imports the branches, then the resource models). ``Graph.publish()`` reads the
tables first and writes correct rows, but it creates a new publication, which
the existing resources (``resource_instances.graphpublicationid``) no longer
match: Arches then opens them read-only.

``load_from_tables()`` loads a graph the way ``Graph.publish()`` does, so that
``update_published_graphs()`` rewrites the rows of the CURRENT publication
correctly. ``rebuild()`` serialises that graph under each language, for the
comparison behind ``--dry-run``; ``translation_drift()`` is the cheap
comparison behind the ``manuspectrum.W006`` system check. Both can be dropped
once Arches loads published graphs from their tables.
"""

from django.conf import settings
from django.utils import translation

from arches.app.models import models
from arches.app.models.graph import Graph
from arches.app.utils.betterJSONSerializer import JSONDeserializer, JSONSerializer


def language_codes():
    """The language codes of ``settings.LANGUAGES``, in their order."""
    return [code for code, _name in settings.LANGUAGES]


def published_graphs():
    """Graphs with a current publication, drafts excluded: resource models and branches."""
    return models.GraphModel.objects.filter(
        publication__isnull=False, source_identifier__isnull=True
    ).order_by("-isresource", "slug", "graphid")


def load_from_tables(graph_id, load_language):
    """The graph as ``Graph.publish()`` loads it: from its tables, flag as stored.

    ``load_language`` must have a row in the graph's current publication:
    loading a published graph reads the row of the active language
    (``Graph.__init__``), although nothing of it survives
    ``refresh_from_database()``, after which the card and widget strings are
    ``I18n_String`` and resolve at serialisation.
    """
    with translation.override(load_language):
        graph = Graph.objects.get(pk=graph_id)
    stored_flag = graph.has_unpublished_changes
    with translation.override(load_language):
        graph.refresh_from_database()
    # refresh_from_database() goes through add_node() and add_card(), which
    # raise this flag in memory; the serialisation carries the stored value.
    graph.has_unpublished_changes = stored_flag
    return graph


def rebuild(graph_id, codes, load_language):
    """``{code: serialised graph}`` of ``graph_id``, read from the graph tables.

    The graph is reloaded for each language, so no string resolved for one
    language reaches the next.
    """
    rebuilt = {}
    for code in codes:
        graph = load_from_tables(graph_id, load_language)
        with translation.override(code):
            rebuilt[code] = JSONDeserializer().deserialize(
                JSONSerializer().serialize(graph, force_recalculation=True)
            )
    return rebuilt


def _raw(value):
    """The ``{language: text}`` of an I18n value; ``{}`` when it holds none."""
    raw = getattr(value, "raw_value", value)
    return raw if isinstance(raw, dict) else {}


def _differs(published, expected, code):
    """True when a published text is not its table row's text in ``code``.

    ``expected`` is the ``{language: text}`` of the table row (``{}`` when it
    has none). A text without a value in ``code`` is not compared.
    """
    wanted = expected.get(code)
    return bool(wanted) and published != wanted


CARD_TEXTS = ("name", "description", "instructions", "helptext")


def _widget_texts(label, config):
    """``{text: {language: value}}`` of a widget row: its label and placeholder."""
    raw = _raw(config)
    placeholder = raw.get("placeholder")
    return {
        "label": _raw(label),
        "placeholder": (
            placeholder
            if "placeholder" in raw.get("i18n_properties", [])
            and isinstance(placeholder, dict)
            else {}
        ),
    }


def _published_widget_text(widget, key):
    if key == "placeholder":
        config = widget.get("config")
        return config.get("placeholder") if isinstance(config, dict) else None
    return widget.get(key)


def translation_drift(codes=None):
    """``{code: [graph names]}``: publications whose texts are not those of the tables.

    For each published graph without unpublished changes, and each language,
    the card names, descriptions, instructions and help texts, and the widget
    labels and placeholders, of the ``cards`` and ``cards_x_nodes_x_widgets``
    tables that have a value in that language must be those of the language's
    row of the current publication. A branch's root
    card is published under the graph's name (``Graph.get_cards``). Reads those
    two parts of the publications only, not the whole serialised graphs.
    """
    codes = language_codes() if codes is None else codes
    graphs = {
        graph.publication_id: graph
        for graph in published_graphs().filter(has_unpublished_changes=False)
    }
    if not graphs:
        return {}
    in_graphs = {
        "graph__publication_id__in": list(graphs),
        "graph__source_identifier__isnull": True,
    }
    cards = {}
    for card in models.CardModel.objects.filter(**in_graphs).select_related(
        "graph", "nodegroup"
    ):
        is_branch_root = (
            not card.graph.isresource and card.nodegroup.parentnodegroup_id is None
        )
        cards[str(card.cardid)] = {
            key: _raw(
                card.graph.name
                if key == "name" and is_branch_root
                else getattr(card, key)
            )
            for key in CARD_TEXTS
        }
    widgets = {
        str(widget_id): _widget_texts(label, config)
        for widget_id, label, config in models.CardXNodeXWidget.objects.filter(
            **{f"card__{key}": value for key, value in in_graphs.items()}
        ).values_list("id", "label", "config")
    }

    drift = {}
    rows = models.PublishedGraph.objects.filter(
        publication_id__in=list(graphs), language_id__in=codes
    ).values_list(
        "publication_id",
        "language_id",
        "serialized_graph__cards",
        "serialized_graph__cards_x_nodes_x_widgets",
    )
    for publication_id, code, published_cards, published_widgets in rows:
        if any(
            _differs(
                card.get(key), cards.get(str(card.get("cardid")), {}).get(key, {}), code
            )
            for card in published_cards or []
            for key in CARD_TEXTS
        ) or any(
            _differs(
                _published_widget_text(widget, key),
                widgets.get(str(widget.get("id")), {}).get(key, {}),
                code,
            )
            for widget in published_widgets or []
            for key in ("label", "placeholder")
        ):
            drift.setdefault(code, []).append(str(graphs[publication_id].name))
    return {code: sorted(found) for code, found in sorted(drift.items())}
