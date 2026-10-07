"""Rewrite the origin of the image service URLs stored in Arches manifests.

``IIIFManifestManagerView`` builds the image ``@id``, the ``service`` ``@id``
and the thumbnail ``@id`` of an uploaded image from the host of the request
that uploaded it (``arches/app/views/manifest_manager.py``), so a manifest
created on a development host keeps ``<dev origin>/iiifserver/iiif/2/<file>``
forever.

The command replaces ``--from`` (an origin such as ``http://host:8000``) by
``--to`` (default ``settings.PUBLIC_SERVER_ADDRESS``, ending with ``/``) in
every string of ``IIIFManifest.manifest`` that starts with
``<--from>/iiifserver/``. Nothing else is touched: canvas, sequence and
annotation ids (tiles and annotations reference the canvas ids), external
manifests, ``@context`` and strings that only contain the origin. Rows are
written with ``QuerySet.update`` in one transaction, so no model ``save()``
runs. A second run changes nothing.

Run it after loading a snapshot or restoring a migration dump taken on a
development host. ``--dry-run`` reports the counts and writes nothing. The
output holds counts only.
"""

import re

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from arches.app.models.models import IIIFManifest

ORIGIN = re.compile(r"^https?://[^/\s?#]+$")


def rewrite(value, prefix, target):
    """Return ``(new_value, number_of_rewritten_strings)`` for a JSON value."""
    if isinstance(value, str):
        if value.startswith(prefix):
            return target + value[len(prefix) :], 1
        return value, 0
    if isinstance(value, list):
        count = 0
        items = []
        for item in value:
            new, n = rewrite(item, prefix, target)
            items.append(new)
            count += n
        return items, count
    if isinstance(value, dict):
        count = 0
        mapped = {}
        for key, item in value.items():
            new, n = rewrite(item, prefix, target)
            mapped[key] = new
            count += n
        return mapped, count
    return value, 0


class Command(BaseCommand):
    help = (
        "Rewrite the development origin of stored image service URLs "
        "(--dry-run reports counts only)."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--from",
            dest="origin",
            required=True,
            help="Origin to replace, e.g. http://host:8000 (no path, no trailing slash).",
        )
        parser.add_argument(
            "--to",
            dest="target",
            default=None,
            help="New base URL ending with a slash (default: PUBLIC_SERVER_ADDRESS).",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Report the counts and write nothing.",
        )

    def handle(self, *args, **options):
        origin = options["origin"]
        if not ORIGIN.match(origin):
            raise CommandError("--from must be an origin: http(s)://host[:port]")
        target = options["target"]
        if target is None:
            target = settings.PUBLIC_SERVER_ADDRESS
        if not target.endswith("/"):
            raise CommandError("--to must end with a slash")

        prefix = f"{origin}/iiifserver/"
        target_prefix = f"{target}iiifserver/"
        rows = urls = 0
        with transaction.atomic():
            for pk, data in IIIFManifest.objects.values_list("pk", "manifest"):
                if data is None:
                    continue
                new, count = rewrite(data, prefix, target_prefix)
                if not count:
                    continue
                rows += 1
                urls += count
                if not options["dry_run"]:
                    IIIFManifest.objects.filter(pk=pk).update(manifest=new)

        verb = "would rewrite" if options["dry_run"] else "rewrote"
        self.stdout.write(f"{verb} {urls} URL(s) in {rows} manifest(s)")
