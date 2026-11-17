"""Register the remote IIIF manifests that existing annotations reference.

Dry run by default; ``--apply`` fetches and stores. Covers annotations written
without a Python save hook (ETL, bulk import). Always exits 0: it is a report.
"""

from collections import defaultdict

from django.core.management.base import BaseCommand

from arches.app.models.models import VwAnnotation

from manuspectrum.utils import manifest_registry


def referenced_manifests():
    """``{manifest URL: [annotation count, [canvas ids]]}`` of every http(s) manifest named by a stored annotation.

    Reads Arches' annotation view: the approved features of every annotation
    node. One canvas per URL: the first seen.
    """
    found = defaultdict(lambda: [0, []])
    for feature in VwAnnotation.objects.values_list("feature", flat=True).iterator():
        named = manifest_registry.feature_manifest(feature)
        if named is None:
            continue
        url, canvas = named
        entry = found[url]
        entry[0] += 1
        if canvas and not entry[1]:
            entry[1].append(canvas)
    return dict(found)


class Command(BaseCommand):
    help = "Register the remote IIIF manifests referenced by annotations (dry run unless --apply)."

    def add_arguments(self, parser):
        parser.add_argument("--apply", action="store_true", help="Fetch and store.")

    def handle(self, *args, apply=False, **options):
        counts = defaultdict(int)
        for url, (annotations, canvases) in sorted(referenced_manifests().items()):
            if apply:
                try:
                    _row, outcome = manifest_registry.register_remote_manifest(
                        url,
                        expected_service=canvases[0] if canvases else None,
                        use_memo=False,
                    )
                except manifest_registry.ManifestRegistrationError as exc:
                    outcome = f"FAILED {exc.reason}"
            else:
                _row, outcome = manifest_registry.find_registered(url)
                outcome = outcome or "would register"
            counts[outcome] += 1
            self.stdout.write(f"{outcome}\t{annotations}\t{url}")
        summary = ", ".join(f"{n} {name}" for name, n in sorted(counts.items()))
        mode = "applied" if apply else "dry run"
        self.stdout.write(f"{mode}: {summary or 'no manifest referenced'}")
