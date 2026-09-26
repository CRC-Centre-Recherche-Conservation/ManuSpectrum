"""``GET /api/explorer/series.csv``: the Selection's spectra in long format (spec §11.2).

One row per point, ``curve,analysis,file,x,y``, after ``#`` comment lines
that name the Selection, its drafts and restricted data, each analysis's
permalink and, per curve, its licence, attribution, renderer configuration
and raw file. The curve is the one the XY reader draws: the file's renderer
configuration decides its columns and normalisation; it is never decimated.
"""

import csv
import datetime
import os
import re

from django.conf import settings
from django.http import HttpResponseBadRequest, StreamingHttpResponse
from django.utils import translation
from django.utils.http import content_disposition_header
from django.utils.translation import gettext as _
from django.views import View

from manuspectrum.utils.spectrum_preview import is_supported, read_series
from manuspectrum.views.explorer.api import _not_found
from manuspectrum.views.explorer.manifest import absolute_url
from manuspectrum.views.explorer.scopes import (
    ScopeError,
    export_language,
    kept_files,
    resolve_scope,
    scope_files,
)
from manuspectrum.views.explorer.service import (
    Values,
    analysis_files,
    permalink,
    renderer_configs,
)

HEADER = ("curve", "analysis", "file", "x", "y")
ROWS_PER_CHUNK = 2000
_CONTROL = re.compile(r"[\x00-\x1f\x7f]+")
_FORMULA_CELL = re.compile(r",(?=[=+\-@])")


class _Line:
    """A file-like object whose ``write`` returns what ``csv.writer`` wrote."""

    def write(self, value):
        return value


def _clean(text):
    """Curator text on one line: control characters and line breaks become spaces."""
    return _CONTROL.sub(" ", str(text or "")).strip()


def _comment(text):
    """One ``#`` comment line; a comma never opens a spreadsheet cell with a formula character."""
    return _FORMULA_CELL.sub(", ", f"# {_clean(text)}") + "\r\n"


def _file_url(entry, entries):
    """Absolute URL of the raw file paired with *entry*, else of *entry* itself."""
    paired = next((e for e in entries if e.get("id") == entry.get("pairedWith")), None)
    return absolute_url((paired or entry).get("downloadUrl")) or ""


def _curve_line(number, name, entry, entries, config, config_id):
    licence = entry.get("license") or {}
    parts = [f"c{number}: {name} — {entry.get('name') or ''}"]
    if licence:
        text = licence["label"]["value"]
        if licence.get("url"):
            text += f" ({licence['url']})"
        parts.append(_("licence %(licence)s") % {"licence": text})
    if licence.get("attribution"):
        parts.append(_("attribution %(text)s") % {"text": licence["attribution"]})
    parts.append(
        _("configuration %(name)s")
        % {"name": (config or {}).get("presetKey") or config_id or "-"}
    )
    parts.append(_("raw file %(url)s") % {"url": _file_url(entry, entries)})
    return "; ".join(parts)


def _plan(scope):
    """``(comment lines, curves)`` of *scope*; each curve is ``(label, analysis id, file id, path, config)``.

    A readable XY entry ``scope_files`` refuses is left out without a line.
    One under a no-derivatives licence, one outside ``XY_TEXT_FILE_FORMATS``
    or over ``SPECTRUM_PREVIEW_MAX_BYTES`` gets a comment line naming its
    file and is never read.
    """
    values = Values(list(scope.analyses), ["files", "micro", "imaging"], scope.reader)
    configs = renderer_configs(values, scope.analyses)
    comments = [
        _("%(site)s: spectra of a Selection") % {"site": settings.APP_TITLE},
        _("Generated on %(date)s") % {"date": datetime.date.today().isoformat()},
    ]
    if scope.drafts:
        comments.append(_("Contains drafts"))
    if scope.restricted:
        comments.append(_("Contains restricted-access data"))
    curves, per_analysis, per_curve = [], [], []
    entries_of = {
        analysis_id: kept_files(
            scope,
            analysis_id,
            analysis_files(
                analysis_id,
                scope.reader,
                scope.language,
                values=values,
                configs=configs,
            ),
        )
        for analysis_id in scope.analyses
    }
    readable_of = {
        analysis_id: [
            e
            for e in entries
            if e.get("dataKind") == "xy" and e.get("role") == "readable"
        ]
        for analysis_id, entries in entries_of.items()
    }
    paths = scope_files(
        scope,
        [(a, e.get("id")) for a, readable in readable_of.items() for e in readable],
    )
    for analysis_id in scope.analyses:
        name = scope.bundle.by_id[analysis_id]["name"]["value"]
        entries, readable = entries_of[analysis_id], readable_of[analysis_id]
        listed = False
        for entry in readable:
            path = paths.get((analysis_id, entry.get("id")))
            if path is None:
                continue
            listed = True
            licence = entry.get("license") or {}
            if licence.get("noDerivatives"):
                per_curve.append(
                    _(
                        "excluded: %(file)s — licence %(licence)s forbids derivatives; raw file: %(url)s"
                    )
                    % {
                        "file": entry.get("name") or "",
                        "licence": licence.get("url") or licence["label"]["value"],
                        "url": _file_url(entry, entries),
                    }
                )
                continue
            try:
                too_large = os.path.getsize(path) > settings.SPECTRUM_PREVIEW_MAX_BYTES
            except OSError:
                continue
            if too_large or not is_supported(path):
                per_curve.append(
                    _("not in the CSV: %(file)s; file: %(url)s")
                    % {
                        "file": entry.get("name") or "",
                        "url": absolute_url(entry.get("downloadUrl")) or "",
                    }
                )
                continue
            config_id = (entry.get("viewer") or {}).get("rendererConfigId")
            config = configs.get(config_id) or {}
            number = len(curves) + 1
            per_curve.append(
                _curve_line(number, name, entry, entries, config, config_id)
            )
            curves.append((f"c{number}", analysis_id, entry["id"], path, config))
        if listed:
            per_analysis.append(f"{name}: {permalink(analysis_id)}")
    return comments + per_analysis + per_curve, curves


def _rows(curves):
    writer = csv.writer(_Line(), lineterminator="\r\n")
    yield writer.writerow(HEADER)
    for label, analysis_id, file_id, path, config in curves:
        try:
            series = read_series(path, config)
        except OSError:
            series = None
        if not series:
            continue
        chunk = []
        for x, y in zip(series["x"], series["y"]):
            chunk.append(
                writer.writerow((label, analysis_id, file_id, repr(x), repr(y)))
            )
            if len(chunk) == ROWS_PER_CHUNK:
                yield "".join(chunk)
                chunk = []
        if chunk:
            yield "".join(chunk)


def series_lines(scope):
    """The body of ``series.csv`` for an ``ids`` *scope*, as an iterator of text chunks.

    The comment lines are built at once, in ``scope.language``, with every
    database read; the iterator then reads one file at a time, whole
    (``read_series``), and writes its points with ``repr(float)``.
    """
    with translation.override(scope.language):
        comments, curves = _plan(scope)
    head = "".join(_comment(line) for line in comments)

    def body():
        yield head
        yield from _rows(curves)

    return body()


class ExplorerSeriesView(View):
    """``GET /api/explorer/series.csv?ids=…[&restricted=1][&lang=]``: the Selection's spectra, a private download.

    Only an ``ids`` scope; any other scope, malformed parameters or an
    unknown language answer a bodyless 400, a Selection with nothing visible
    the bodyless 404. The body streams uncompressed.
    """

    def get(self, request):
        if "ids" not in request.GET:
            return HttpResponseBadRequest()
        try:
            language = export_language(request.GET)
            scope = resolve_scope(request.GET, request.user, language)
        except ScopeError:
            return HttpResponseBadRequest()
        if scope is None:
            return _not_found()
        response = StreamingHttpResponse(
            series_lines(scope), content_type="text/csv; charset=utf-8"
        )
        response["Content-Disposition"] = content_disposition_header(
            True, f"manuspectrum-series-{scope.digest}.csv"
        )
        response["Cache-Control"] = "private, no-store"
        return response
