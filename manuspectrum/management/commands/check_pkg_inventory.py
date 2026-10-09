"""
CHECK PKG INVENTORY

Compares the database with the `expected-inventory.json` that `export_pkg`
writes into the data package, after the package was loaded:

    manage.py check_pkg_inventory <expected-inventory.json>

The database is only read, inside a read-only transaction that is rolled back.
Every difference is listed and the command exits 1; warnings go to stdout and
do not change the exit status.

Compared: graphs (file names, cards with help, and the current publication of
each graph per language; older publications are history and not counted),
the widgets the graphs reference (each registered, the same set, and the
number of card-node-widget rows per graph), controlled lists (counts,
`searchable`, and per list the item, value and sort-order digests of
`export_pkg`; the item digest is always compared), map layers and sources, resource constraints, functions, plugins, renderer
configurations, and that the Mapbox key of the System Settings is empty.

The loader reads each item's sort order under `ARCHES_NAMESPACE_FOR_DATA_EXPORT`.
When the inventory's `public_origin` differs from it (a rehearsal host, for
instance) the sort orders were not loaded and the lists show alphabetically: the
per-list `digest_sibling_rank` comparison is skipped with a warning and every
other comparison is still made.
"""

import json

from arches.app.models import models
from arches.app.models.system_settings import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import connection, transaction

from arches_controlled_lists.models import List, ListItem, ListItemValue

from manuspectrum.management.commands.export_pkg import (
    items_digest,
    list_digests,
    published_pairs,
    values_digest,
    widget_usage,
)
from manuspectrum.models import RendererConfig


def _diff(label, expected, actual, problems):
    if expected != actual:
        problems.append(f"{label}: expected {expected!r}, found {actual!r}")


def _diff_sets(label, expected, actual, problems):
    missing = sorted(set(expected) - set(actual))
    extra = sorted(set(actual) - set(expected))
    if missing or extra:
        problems.append(f"{label}: missing {missing}, unexpected {extra}")


def mapbox_key_values():
    """Every non-empty value of the Mapbox key node in the System Settings tiles."""
    node = models.Node.objects.filter(
        graph_id=settings.SYSTEM_SETTINGS_RESOURCE_MODEL_ID, alias="mapbox_api_key"
    ).first()
    if node is None:
        return ["(node mapbox_api_key not found)"]
    values = []
    for tile in models.TileModel.objects.filter(
        resourceinstance_id=settings.SYSTEM_SETTINGS_RESOURCE_ID
    ):
        value = (tile.data or {}).get(str(node.nodeid))
        if isinstance(value, dict):
            value = [
                v.get("value") if isinstance(v, dict) else v for v in value.values()
            ]
        elif value is not None:
            value = [value]
        values += [v for v in value or [] if v]
    return values


def compare(expected, warnings):
    """The differences between the database and `expected`, as sentences."""
    problems = []
    origin = expected.get("public_origin")
    namespace = settings.ARCHES_NAMESPACE_FOR_DATA_EXPORT
    compare_order = origin is None or origin == namespace
    if not compare_order:
        warnings.append(
            "WARNING: list sort orders were not loaded (the lists show "
            f"alphabetically): the package origin {origin} differs from "
            f"ARCHES_NAMESPACE_FOR_DATA_EXPORT {namespace}; the "
            "digest_sibling_rank comparison is skipped"
        )

    graphs = expected["graphs"]
    for is_resource, key in ((True, "resource_models"), (False, "branches")):
        names = sorted(
            f"{str(graph.name).replace('/', '-')}.json"
            for graph in models.GraphModel.objects.filter(
                isresource=is_resource, source_identifier__isnull=True
            ).exclude(pk=settings.SYSTEM_SETTINGS_RESOURCE_MODEL_ID)
        )
        _diff_sets(f"graphs.{key}", graphs[key], names, problems)

    help_cards = 0
    for card in models.CardModel.objects.filter(
        graph__source_identifier__isnull=True
    ).exclude(graph_id=settings.SYSTEM_SETTINGS_RESOURCE_MODEL_ID):
        helptext = getattr(card.helptext, "raw_value", card.helptext)
        values = helptext.values() if isinstance(helptext, dict) else [helptext]
        if any(values):
            help_cards += 1
    _diff("graphs.cards_with_help", graphs["cards_with_help"], help_cards, problems)
    _diff_sets("graphs.published", graphs["published"], published_pairs(), problems)

    widgets, widget_rows = widget_usage()
    registered = {
        str(pk) for pk in models.Widget.objects.values_list("widgetid", flat=True)
    }
    unregistered = sorted(set(expected["widgets"]) - registered)
    if unregistered:
        problems.append(f"widgets: not registered in the database {unregistered}")
    _diff_sets(
        "widgets referenced by the graphs", expected["widgets"], widgets, problems
    )
    _diff(
        "widget_rows (card-node-widget rows per graph)",
        expected["widget_rows"],
        widget_rows,
        problems,
    )

    wanted = expected["controlled_lists"]
    lists = list(List.objects.all())
    _diff("controlled_lists.lists", wanted["lists"], len(lists), problems)
    _diff("controlled_lists.items", wanted["items"], ListItem.objects.count(), problems)
    _diff(
        "controlled_lists.values",
        wanted["values"],
        ListItemValue.objects.count(),
        problems,
    )
    _diff(
        "controlled_lists.searchable",
        wanted["searchable"],
        sum(1 for lst in lists if lst.searchable),
        problems,
    )
    by_id = {str(lst.id): lst for lst in lists}
    _diff_sets("controlled_lists.per_list ids", wanted["per_list"], by_id, problems)
    for list_id, want in wanted["per_list"].items():
        lst = by_id.get(list_id)
        if lst is None:
            continue
        where = f"list {want['name']} ({list_id})"
        rows = list(
            ListItem.objects.filter(list=lst).values_list(
                "id", "parent_id", "sortorder"
            )
        )
        value_rows = list(
            ListItemValue.objects.filter(list_item__list=lst).values_list(
                "list_item_id", "valuetype_id", "language_id", "value"
            )
        )
        _diff(f"{where} name", want["name"], lst.name, problems)
        _diff(f"{where} searchable", want["searchable"], lst.searchable, problems)
        _diff(f"{where} items", want["items"], len(rows), problems)
        _diff(f"{where} values", want["values"], len(value_rows), problems)
        _diff(
            f"{where} digest_values",
            want["digest_values"],
            values_digest(value_rows),
            problems,
        )
        _diff(
            f"{where} digest_items", want["digest_items"], items_digest(rows), problems
        )
        if compare_order:
            _diff(
                f"{where} digest_sibling_rank",
                want["digest_sibling_rank"],
                list_digests(rows)[1],
                problems,
            )

    _diff(
        "map_layers", expected["map_layers"], models.MapLayer.objects.count(), problems
    )
    _diff(
        "map_sources",
        expected["map_sources"],
        models.MapSource.objects.count(),
        problems,
    )
    _diff(
        "resource_to_resource_constraints",
        expected["resource_to_resource_constraints"],
        models.Resource2ResourceConstraint.objects.count(),
        problems,
    )
    actual = {
        "functions": models.Function.objects.count(),
        "functions_x_graphs": models.FunctionXGraph.objects.count(),
        "plugins": models.Plugin.objects.count(),
        "renderer_config": RendererConfig.objects.count(),
    }
    for key, value in expected["database"].items():
        _diff(f"database.{key}", value, actual.get(key), problems)

    if mapbox_key_values():
        problems.append("System Settings: the Mapbox key is not empty")
    return problems


class Command(BaseCommand):
    help = "Compare the database with a data package's expected-inventory.json"

    def add_arguments(self, parser):
        parser.add_argument("inventory", help="Path of expected-inventory.json")

    def handle(self, *args, **options):
        try:
            with open(options["inventory"], encoding="utf-8") as handle:
                expected = json.load(handle)
        except (OSError, ValueError) as error:
            raise CommandError(f"Cannot read {options['inventory']}: {error}")

        warnings = []
        try:
            with transaction.atomic():
                with connection.cursor() as cursor:
                    cursor.execute("SET LOCAL transaction_read_only = on")
                try:
                    problems = compare(expected, warnings)
                finally:
                    transaction.set_rollback(True)
        except KeyError as error:
            raise CommandError(f"expected-inventory.json lacks {error}")

        for warning in warnings:
            self.stdout.write(warning)
        if problems:
            raise CommandError(
                f"Inventory check FAILED: {len(problems)} difference(s)\n"
                + "\n".join(f"  - {problem}" for problem in problems)
            )
        self.stdout.write(
            "Inventory check passed: the database matches expected-inventory.json"
        )
