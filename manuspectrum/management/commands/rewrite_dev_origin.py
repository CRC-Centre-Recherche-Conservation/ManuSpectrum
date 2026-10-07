"""Replace development origins by the public address in every stored URL.

Arches writes the host of the request, or a setting of the development
host, into the data it creates: concept ``legacyoid`` and ``identifier``
values (``ARCHES_NAMESPACE_FOR_DATA_EXPORT``), controlled list item URIs and
their copies in tiles (``PUBLIC_SERVER_ADDRESS``), IIIF manifests and the
canvases they mint (``manifest_manager.py``: image URLs from the request,
canvas and sequence ids from ``CANTALOUPE_HTTP_ENDPOINT``). Run this once on
a database taken from a development host, before it serves a public address.

Each ``--from`` is an origin (``http://host:port``); ``--to`` is the new base
URL (default ``settings.PUBLIC_SERVER_ADDRESS``, ending with ``/``). A string
is rewritten only when it starts with ``<origin>/``; a value that merely
contains an origin, an external URL and a value that is not a URL are never
touched. The mapping is the same in every family:

- ``<origin>/iiif/manifest/<rest>`` becomes ``<to>iiifserver/iiif/manifest/<rest>``
  (the canvas and sequence ids; set ``CANTALOUPE_HTTP_ENDPOINT`` to
  ``<to>iiifserver/`` so ids minted later have the same form);
- ``<origin>/<rest>`` becomes ``<to><rest>`` for everything else.

Families (``--family``, repeatable, default all):

``concepts``
    ``concepts.legacyoid`` and ``values.value`` of type ``identifier``.
``lists``
    ``arches_controlled_lists_listitem.uri``. The reference datatype copies
    the URI into tiles and the search compares the two, so run ``lists``
    together with ``tiles``.
``manifests``
    every string of ``IIIFManifest.manifest``.
``tiles``
    every string of ``tiles.tiledata``: list item URIs and canvas ids that
    annotation and imaging layer tiles reference. A canvas id becomes the
    same string in a manifest and in a tile, so references keep resolving.

History and staging tables, views and strings that are not at the start of
a value are not read. ``blob:<origin>/...`` URLs in tiles (anywhere in a
string) are dead browser object URLs: they are counted as an anomaly and
never rewritten.

Rows are written with ``QuerySet.update`` in one transaction: no ``save()``,
no Arches function and no signal runs. ``--dry-run`` reports and writes
nothing. A second run changes nothing. The output holds counts only.

Elasticsearch keeps copies of tiles and concepts, and the command does not
touch it: after a real run, ``python manage.py es reindex_database``.
"""

import re

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.db.models import Q, TextField
from django.db.models.functions import Cast

from arches.app.models.models import Concept, IIIFManifest, TileModel, Value
from arches_controlled_lists.models import ListItem

ORIGIN = re.compile(r"^https?://[^/\s?#]+$")
FAMILIES = ("concepts", "lists", "manifests", "tiles")
CANVAS_PATH = "iiif/manifest/"
BATCH = 500


class OriginMap:
    """The rewrite rule, and the counters of what it saw."""

    def __init__(self, origins, target):
        self.prefixes = [f"{origin}/" for origin in origins]
        self.blob_prefixes = [f"blob:{prefix}" for prefix in self.prefixes]
        self.target = target
        self.blobs = 0

    def map(self, value):
        """The new string, or None when *value* does not start with an origin."""
        for prefix in self.prefixes:
            if value.startswith(prefix):
                rest = value[len(prefix) :]
                if rest.startswith(CANVAS_PATH):
                    rest = f"iiifserver/{rest}"
                return self.target + rest
        self.blobs += sum(value.count(prefix) for prefix in self.blob_prefixes)
        return None

    def rewrite(self, value):
        """Return ``(new_value, number_of_rewritten_strings)`` for a JSON value."""
        if isinstance(value, str):
            new = self.map(value)
            return (value, 0) if new is None else (new, 1)
        if isinstance(value, list):
            pairs = [self.rewrite(item) for item in value]
            return [new for new, _ in pairs], sum(n for _, n in pairs)
        if isinstance(value, dict):
            pairs = {key: self.rewrite(item) for key, item in value.items()}
            return (
                {key: new for key, (new, _) in pairs.items()},
                sum(n for _, n in pairs.values()),
            )
        return value, 0


class Command(BaseCommand):
    help = (
        "Replace development origins by the public address in stored URLs "
        "(--dry-run reports counts only)."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--from",
            dest="origins",
            action="append",
            required=True,
            help="Origin to replace, e.g. http://host:8000 (repeatable; no path, no trailing slash).",
        )
        parser.add_argument(
            "--to",
            dest="target",
            default=None,
            help="New base URL ending with a slash (default: PUBLIC_SERVER_ADDRESS).",
        )
        parser.add_argument(
            "--family",
            dest="families",
            action="append",
            default=None,
            help=f"Family to rewrite, one of {', '.join(FAMILIES)} (repeatable; default: all).",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Report the counts and write nothing.",
        )

    def handle(self, *args, **options):
        origins = list(dict.fromkeys(options["origins"]))
        for origin in origins:
            if not ORIGIN.match(origin):
                raise CommandError("--from must be an origin: http(s)://host[:port]")
        target = options["target"]
        if target is None:
            target = settings.PUBLIC_SERVER_ADDRESS
        if not target.endswith("/"):
            raise CommandError("--to must end with a slash")
        if target[:-1] in origins:
            raise CommandError("--to must differ from every --from origin")
        families = options["families"] or list(FAMILIES)
        for family in families:
            if family not in FAMILIES:
                raise CommandError(f"--family must be one of: {', '.join(FAMILIES)}")

        self.dry_run = options["dry_run"]
        self.mapping = OriginMap(origins, target)
        self.origins = origins
        verb = "would rewrite" if self.dry_run else "rewrote"
        changed = 0
        with transaction.atomic():
            for family in FAMILIES:
                if family not in families:
                    continue
                rows, strings = getattr(self, f"do_{family}")()
                changed += rows
                self.stdout.write(
                    f"{family}: {verb} {strings} string(s) in {rows} row(s)"
                )
        if "tiles" in families:
            self.stdout.write(
                f"anomaly: {self.mapping.blobs} blob: URL(s) with a development "
                "origin left untouched in tiles"
            )
        if "lists" in families and "tiles" not in families:
            self.stdout.write(
                "warning: tiles copy list item URIs; run the tiles family too"
            )
        if changed and not self.dry_run:
            self.stdout.write(
                "Follow-up: python manage.py es reindex_database "
                "(Elasticsearch still holds the old URLs)"
            )

    def starts_with_origin(self, field):
        query = Q()
        for origin in self.origins:
            query |= Q(**{f"{field}__startswith": f"{origin}/"})
        return query

    def update_column(self, queryset, field):
        """Rewrite one text column; returns ``(rows, strings)``."""
        rows = 0
        for pk, value in list(queryset.values_list("pk", field)):
            new = self.mapping.map(value)
            if new is None:
                continue
            rows += 1
            if not self.dry_run:
                queryset.model.objects.filter(pk=pk).update(**{field: new})
        return rows, rows

    def update_json(self, queryset, field):
        """Rewrite the strings of one JSON column; returns ``(rows, strings)``."""
        rows = strings = 0
        pks = list(queryset.values_list("pk", flat=True))
        for start in range(0, len(pks), BATCH):
            chunk = pks[start : start + BATCH]
            for pk, data in queryset.model.objects.filter(pk__in=chunk).values_list(
                "pk", field
            ):
                new, count = self.mapping.rewrite(data)
                if not count:
                    continue
                rows += 1
                strings += count
                if not self.dry_run:
                    queryset.model.objects.filter(pk=pk).update(**{field: new})
        return rows, strings

    def containing_origin(self, model, field):
        """Rows whose JSON column mentions an origin: a cheap text pre-filter."""
        query = Q()
        for origin in self.origins:
            query |= Q(text__contains=f"{origin}/")
        return model.objects.annotate(text=Cast(field, TextField())).filter(query)

    def do_concepts(self):
        rows, strings = self.update_column(
            Concept.objects.filter(self.starts_with_origin("legacyoid")), "legacyoid"
        )
        identifiers = Value.objects.filter(
            self.starts_with_origin("value"), valuetype_id="identifier"
        )
        more, _ = self.update_column(identifiers, "value")
        return rows + more, strings + more

    def do_lists(self):
        return self.update_column(
            ListItem.objects.filter(self.starts_with_origin("uri")), "uri"
        )

    def do_manifests(self):
        return self.update_json(
            self.containing_origin(IIIFManifest, "manifest"), "manifest"
        )

    def do_tiles(self):
        self.mapping.blobs = 0
        return self.update_json(self.containing_origin(TileModel, "data"), "data")
