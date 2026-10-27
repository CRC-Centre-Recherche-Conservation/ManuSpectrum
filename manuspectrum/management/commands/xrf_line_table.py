"""Generate or verify the versioned XRF line table (``xray-lines.json``)."""

from django.core.management.base import BaseCommand, CommandError

from manuspectrum.utils import xrf_line_table as table


class Command(BaseCommand):
    help = (
        "Build the XRF line table from XrayDB. --write rewrites the versioned "
        "file, --check compares bytes. xraydb is not a project dependency: "
        + table.INSTALL_HINT
    )

    def add_arguments(self, parser):
        mode = parser.add_mutually_exclusive_group(required=True)
        mode.add_argument("--write", action="store_true")
        mode.add_argument("--check", action="store_true")

    def handle(self, *args, **options):
        try:
            source = table.xraydb_source()
        except ImportError as error:
            raise CommandError(
                f"xraydb is not installed. {table.INSTALL_HINT}"
            ) from error
        text = table.dumps(table.build_table(source))
        path = table.TABLE_PATH
        if options["write"]:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(text.encode("utf-8"))
            self.stdout.write(f"Wrote {path} ({len(text.encode('utf-8'))} bytes)")
            return
        if not path.exists() or path.read_bytes() != text.encode("utf-8"):
            raise CommandError(f"{path} differs from the XrayDB {source.version} table")
        self.stdout.write("xray-lines.json is up to date")
