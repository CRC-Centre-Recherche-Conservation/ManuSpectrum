"""Per-language serialisations of the graph publications, rebuilt from the graph tables.

Arches 8.1 keeps, for every graph publication (``graphs_x_published_graphs``),
one serialised graph per language of ``settings.LANGUAGES``
(``published_graphs``). The resource editor, the reports and every card-based
page read the row of the active language.

``Graph.update_published_graphs()`` writes those rows wrongly. It serialises a
``Graph`` loaded through the ORM, and ``Graph.__init__`` fills ``cards`` and
``widgets`` of a published graph from the publication of the language active at
load time, as plain strings instead of ``I18n_String``. Each language row then
receives that one language: the ``fr`` rows hold the English card names, help
texts and widget labels, although the ``cards`` and ``cards_x_nodes_x_widgets``
tables hold the French ones. It runs through
``LanguageSynchronizer.synchronize_settings_with_db()``: ``manage.py i18n
synclanguages``, and ``packages`` before each graph import (``load_package``
imports the branches, then the resource models). ``Graph.publish()`` reads the
tables first and writes correct rows, but it creates a new publication, which
the existing resources (``resource_instances.graphpublicationid``) no longer
match: Arches then opens them read-only.

``rebuild()`` serialises a graph from its tables the way ``Graph.publish()``
does, one language at a time, so that the rows of the CURRENT publication can
be rewritten in place. ``translation_drift()`` is the cheap comparison behind
the ``manuspectrum.W006`` system check.
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


def rebuild(graph_id, codes, load_language):
    """``{code: serialised graph}`` of ``graph_id``, read from the graph tables.

    ``load_language`` must have a row in the graph's current publication:
    loading a published graph, ``refresh_from_db()`` included, reads the row of
    the active language (``Graph.__init__``), although nothing of it survives
    ``refresh_from_database()``. As ``Graph.publish()`` does, the graph is
    reloaded from its tables, then serialised under each language; the tables'
    strings are ``I18n_String`` and resolve at serialisation. The reload is
    repeated for each language, so no string resolved for one language
    reaches the next.
    """
    with translation.override(load_language):
        graph = Graph.objects.get(pk=graph_id)
    has_unpublished_changes = graph.has_unpublished_changes
    rebuilt = {}
    for code in codes:
        with translation.override(load_language):
            graph.refresh_from_database()
        # refresh_from_database() goes through add_node() and add_card(), which
        # raise this flag in memory; Graph.publish() lowers it before it
        # serialises. The serialisation carries the stored value.
        graph.has_unpublished_changes = has_unpublished_changes
        with translation.override(code):
            rebuilt[code] = JSONDeserializer().deserialize(
                JSONSerializer().serialize(graph, force_recalculation=True)
            )
    return rebuilt


def _raw(value):
    """The ``{language: text}`` of an I18n value; ``{}`` when it holds none."""
    raw = getattr(value, "raw_value", value)
    return raw if isinstance(raw, dict) else {}


def _differs(published, expected, key, code):
    """True when a published item shows another text than its table row in ``code``.

    ``published`` is a card or widget of a serialised graph, ``expected`` the
    ``{key: {language: text}}`` of its table row (``{}`` when it has none). An
    item without a table row, or a text without a value in ``code``, is not
    compared.
    """
    wanted = expected.get(key, {}).get(code)
    return bool(wanted) and published.get(key) != wanted


def translation_drift(codes=None):
    """``{code: [graph names]}``: publications whose texts are not those of the tables.

    For each published graph without unpublished changes, and each language,
    the card names, card help texts and widget labels of the ``cards`` and
    ``cards_x_nodes_x_widgets`` tables that have a value in that language must
    be those of the language's row of the current publication. A branch's root
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
            "name": _raw(card.graph.name if is_branch_root else card.name),
            "helptext": _raw(card.helptext),
        }
    widgets = {
        str(widget_id): {"label": _raw(label)}
        for widget_id, label in models.CardXNodeXWidget.objects.filter(
            **{f"card__{key}": value for key, value in in_graphs.items()}
        ).values_list("id", "label")
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
            _differs(card, cards.get(str(card.get("cardid")), {}), key, code)
            for card in published_cards or []
            for key in ("name", "helptext")
        ) or any(
            _differs(widget, widgets.get(str(widget.get("id")), {}), "label", code)
            for widget in published_widgets or []
        ):
            drift.setdefault(code, []).append(str(graphs[publication_id].name))
    return {code: sorted(found) for code, found in sorted(drift.items())}
