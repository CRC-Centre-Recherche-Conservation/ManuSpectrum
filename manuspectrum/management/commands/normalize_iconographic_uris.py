"""Normalize manually-entered Iconographic representation URIs.

Converts Wikibase entity URIs (https://data.biblissima.fr/entity/Qxxx) to
the canonical portal ARK (settings.BIBLISSIMA_PORTAL_URL + "/" + P129) on
tiles of the Iconographic representation node, and trims stray whitespace.
Labels are left untouched (human choices). Dry-run by default.

Uses the arches Tile proxy so every write gets validation, an edit-log
entry and ES reindexing (resources + terms) for free.
"""

import re
import uuid
from collections import Counter

from django.core.management.base import BaseCommand
from django.db import transaction

from arches.app.models.tile import Tile
from manuspectrum.constants.biblissima import (
    COMP_ICONOGRAPHIC_NG,
    COMP_ICONOGRAPHIC_NODE,
    P129,
)
from manuspectrum.views import biblissima_proxy as bp

QID_RE = re.compile(r"/entity/(Q\d+)\s*$")


class Command(BaseCommand):
    help = (
        "Normalize Iconographic representation URLs to canonical Biblissima "
        "portal ARKs (dry-run by default, pass --apply to write)."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--apply",
            action="store_true",
            help="Write the changes (default is a dry-run report).",
        )
        parser.add_argument(
            "--user",
            default=None,
            help="Username recorded in the edit log (default: none).",
        )

    def handle(self, *args, **options):
        apply_changes = options["apply"]
        user = None
        if options["user"]:
            from django.contrib.auth.models import User

            user = User.objects.get(username=options["user"])

        tiles = list(Tile.objects.filter(nodegroup_id=COMP_ICONOGRAPHIC_NG))
        session = bp._build_biblissima_session()
        planned = []  # (tile, old_url, new_url)
        final_urls = Counter()  # (resource_id, final_url) → count

        try:
            for tile in tiles:
                value = (tile.data or {}).get(COMP_ICONOGRAPHIC_NODE)
                if not value or not value.get("url"):
                    continue
                if tile.provisionaledits:
                    self.stdout.write(
                        self.style.WARNING(
                            f"skip {tile.tileid}: provisional edits present"
                        )
                    )
                    continue

                old_url = value["url"]
                new_url = old_url.strip()
                if not new_url.startswith(bp.BIBLISSIMA_PORTAL):
                    match = QID_RE.search(new_url)
                    if match:
                        p129 = self._lookup_p129(session, match.group(1))
                        if p129:
                            new_url = f"{bp.BIBLISSIMA_PORTAL}/{p129}"
                        # else: keep the (trimmed) entity URI — P129 absent
                    else:
                        self.stdout.write(
                            self.style.WARNING(
                                f"skip {tile.tileid}: no parsable QID in {old_url!r}"
                            )
                        )
                        final_urls[(str(tile.resourceinstance_id), new_url)] += 1
                        continue

                final_urls[(str(tile.resourceinstance_id), new_url)] += 1
                if new_url != old_url:
                    planned.append((tile, old_url, new_url))
        finally:
            session.close()

        for (resource_id, url), count in sorted(final_urls.items()):
            if count > 1:
                self.stdout.write(
                    self.style.WARNING(
                        f"collision: resource {resource_id} would hold "
                        f"{count} tiles with url {url}"
                    )
                )

        for tile, old_url, new_url in planned:
            self.stdout.write(f"{tile.tileid}: {old_url!r} -> {new_url!r}")
        if not planned:
            self.stdout.write("Nothing to change.")

        if not apply_changes:
            self.stdout.write("dry-run: pass --apply to write.")
            return

        transaction_id = uuid.uuid4()
        with transaction.atomic():
            for tile, _old_url, new_url in planned:
                tile.data[COMP_ICONOGRAPHIC_NODE]["url"] = new_url
                # Tile proxy save = validation + edit log + ES reindex.
                tile.save(user=user, transaction_id=transaction_id)
        self.stdout.write(
            self.style.SUCCESS(
                f"Updated {len(planned)} tile(s) (transaction {transaction_id})."
            )
        )

    def _lookup_p129(self, session, qid):
        try:
            resp = bp._bib_request(
                session,
                bp.BIBLISSIMA_WIKIBASE,
                params={
                    "action": "wbgetentities",
                    "ids": qid,
                    "format": "json",
                    "props": "claims",
                },
                timeout=bp.REQUEST_TIMEOUT,
            )
            resp.raise_for_status()
            claims = resp.json().get("entities", {}).get(qid, {}).get("claims", {})
            for claim in claims.get(P129, []):
                value = claim.get("mainsnak", {}).get("datavalue", {}).get("value")
                if isinstance(value, str) and re.fullmatch(
                    r"desc[0-9a-f]{40}", value.strip()
                ):
                    return value.strip()
        except Exception as exc:
            self.stdout.write(
                self.style.WARNING(f"P129 lookup failed for {qid}: {exc}")
            )
        return None
