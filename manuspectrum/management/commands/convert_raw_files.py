"""Convert local raw instrument files to bare CSV, for inspection.

Reads files and directories (walked recursively, sorted, symlinks skipped) and
prints one tab-separated line per file: relative path, format, outcome (`csv`,
`raw-only`, `unreadable:<code>`, `unsupported`), rows, columns, content preset,
warnings. With `--out`, a converted file `<rel>/<name>` is written as
`<out>/<rel>/<csv name>` with its `.description.<lang>.txt` files. The command
never touches the database and never writes inside an input tree; `--out` may
not lie inside an input nor contain one. A file that fails is a report line,
not a failure: the exit status stays 0.
"""

import hashlib
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from manuspectrum.measurement_files.converters import (
    UnreadableFile,
    UnsupportedFormat,
    convert,
    csv_name,
    write_csv,
)
from manuspectrum.measurement_files.converters.metadata import describe


def _walk(root: Path):
    """Yield the files under `root` in sorted order, symlinks skipped."""
    for entry in sorted(root.iterdir()):
        if entry.is_symlink():
            continue
        if entry.is_dir():
            yield from _walk(entry)
        elif entry.is_file():
            yield entry


def _within(path: Path, parent: Path) -> bool:
    return path == parent or parent in path.parents


class Command(BaseCommand):
    help = "Convert local raw instrument files to CSV (dry run, no database)."

    def add_arguments(self, parser):
        parser.add_argument("paths", nargs="+", metavar="PATH")
        parser.add_argument(
            "--out", help="Directory receiving the CSV and descriptions."
        )

    def handle(self, *args, paths, out=None, **options):
        inputs = []
        for raw in paths:
            path = Path(raw)
            if not path.exists():
                raise CommandError(f"No such file or directory: {raw}")
            inputs.append(path.resolve())
        out_dir = Path(out).resolve() if out else None
        if out_dir is not None:
            for path in inputs:
                if _within(out_dir, path) or _within(path, out_dir):
                    raise CommandError(
                        f"--out {out_dir} and the input {path} may not contain each other."
                    )
        for root in inputs:
            if root.is_file():
                items = [(root, Path(root.name))]
            else:
                items = [(f, f.relative_to(root)) for f in _walk(root)]
            for file, rel in items:
                self._report(file, rel, out_dir)

    def _report(self, file: Path, rel: Path, out_dir):
        data = file.read_bytes()
        fmt, outcome = "-", "unsupported"
        rows = columns = preset = warnings = ""
        reading = None
        try:
            reading = convert(data)
        except UnsupportedFormat as exc:
            fmt = f"unsupported:{exc.format or 'unknown'}"
        except UnreadableFile as exc:
            fmt = exc.format or "-"
            outcome = f"unreadable:{exc.code}"
        if reading is not None:
            fmt = reading.format
            outcome = "csv" if reading.series is not None else "raw-only"
            if reading.series is not None:
                rows = str(len(reading.series.rows))
                columns = str(len(reading.series.columns))
            preset = reading.content_preset or ""
            warnings = ",".join(reading.warnings)
            if out_dir is not None and reading.series is not None:
                self._write(reading, data, file, rel, out_dir)
        self.stdout.write(
            "\t".join([rel.as_posix(), fmt, outcome, rows, columns, preset, warnings])
        )

    def _write(self, reading, data, file, rel, out_dir):
        target = out_dir / rel.parent / csv_name(rel.name)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(write_csv(reading.series))
        texts = describe(
            reading, source_name=file.name, sha256=hashlib.sha256(data).hexdigest()
        )
        for lang, _name in settings.LANGUAGES:
            if lang in texts:
                path = target.with_name(f"{target.name}.description.{lang}.txt")
                path.write_text(texts[lang], encoding="utf-8")
