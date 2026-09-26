"""``GET /api/explorer/export``: the data package of a scope (spec §11.4) as a stored ZIP.

``package`` lists every member of the archive but ``ro-crate-metadata.json``,
whose checksums are only known once the files have streamed. Data files are
read through ``scope_file`` (the ``File`` row joined to the analysis's tile),
never from a path found in tile data. Everything else is built in memory in
``scope.language``. ``stream`` sends the members as a stored ZIP whose length
is announced before the first byte, ``ro-crate-metadata.json`` last. Nothing
is memoised.
"""

import datetime
import hashlib
import io
import mimetypes
import os
import posixpath
import re
from dataclasses import dataclass

import orjson
from defusedcsv import csv
from django.conf import settings
from django.http import HttpResponse, HttpResponseBadRequest, StreamingHttpResponse
from django.template.loader import render_to_string
from django.utils import translation
from django.utils.http import content_disposition_header
from django.utils.text import slugify
from django.utils.translation import gettext as _
from django.utils.translation import ngettext
from django.views import View
from zipstream import ZIP_STORED, ZipStream

from manuspectrum.utils.public_visibility import readable_nodegroup_ids
from manuspectrum.utils.role_links import role_node
from manuspectrum.views.explorer_api import _not_found
from manuspectrum.views.explorer_citations import (
    availability,
    citation_entries,
    parse_dataverse,
)
from manuspectrum.views.explorer_conditions import conditions_of
from manuspectrum.views.explorer_manifest import ManifestTooLarge, build_manifest
from manuspectrum.views.explorer_scopes import (
    ScopeError,
    export_language,
    resolve_scope,
    scope_content,
    scope_file,
    share_link,
)
from manuspectrum.views.explorer_service import (
    ROLES,
    Values,
    _annotations,
    canvas_index,
    canvases_of,
    characterization_summaries,
    dataset_of,
    manifest_json,
    names,
    permalink,
    plain_text,
)
from manuspectrum.views.explorer_values import rewrite_legacy_url
from manuspectrum.views.summary_service import _date

CRATE_NAME = "ro-crate-metadata.json"
CHUNK_SIZE = 1024 * 1024
RO_CRATE_CONTEXT = "https://w3id.org/ro/crate/1.1/context"
RO_CRATE_PROFILE = "https://w3id.org/ro/crate/1.1"
SHA256_SLOT = "0" * 64
LICENCES_PER_FILE = "#licences-per-file"
OCTET_STREAM = "application/octet-stream"
TEXT_LENGTH = 100_000
UNLOCATED = "unlocated"
_MIME = re.compile(r"^[a-z][a-z0-9.+-]*/[a-z0-9.+-]+$")
_UNSAFE = re.compile(r"[\x00-\x1f\x7f/\\]")
_MARKDOWN_BREAK = re.compile(r"[\r\n\x00-\x1f\x7f]+")


@dataclass(frozen=True)
class Member:
    """One entry of the archive.

    A data file has its stored path in ``source`` and its size on disk; built
    bytes (metadata, README, citations, manifests) are in ``data``.
    ``licence`` is the ``effective_license`` of a data file or of an imaging
    manifest, ``analysis`` the analysis it belongs to.
    """

    arcname: str
    size: int
    source: str | None
    data: bytes | None
    media_type: str
    licence: dict | None
    analysis: str | None


def _segment(name, identifier):
    """A directory name: the slug of *name* and the first 8 characters of *identifier*."""
    stem = slugify(str(name or ""))[:60].strip("-")
    return f"{stem}-{identifier[:8]}" if stem else identifier[:8]


def arcname(parts, file_name, taken, fallback):
    """The archive name of *file_name* under the directories *parts*, unique in *taken*.

    The file name is reduced to its last path component; control characters,
    NUL and path separators are removed and leading dots stripped. An empty
    result is *fallback*. *taken* holds the case-folded names already given
    and gets the new one; a name already there gets ``-2``, ``-3``… before
    its extension.
    """
    leaf = re.split(r"[/\\]", str(file_name or ""))[-1]
    leaf = _UNSAFE.sub("", leaf).strip().lstrip(".").strip() or fallback
    stem, extension = os.path.splitext(leaf)
    if not stem:
        stem, extension = leaf, ""
    candidate, number = posixpath.join(*parts, leaf), 1
    while candidate.casefold() in taken:
        number += 1
        candidate = posixpath.join(*parts, f"{stem}-{number}{extension}")
    taken.add(candidate.casefold())
    return candidate


def _media_type(entry):
    fmt = str(entry.get("format") or "").lower()
    if _MIME.match(fmt):
        return fmt
    return mimetypes.guess_type(entry.get("name") or "")[0] or OCTET_STREAM


def _flat(value):
    """A cell of a CSV row: a list joined by ``; ``, a boolean as ``true``/``false``, a dict as JSON."""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (list, tuple)):
        return "; ".join(str(v) for v in value)
    if isinstance(value, dict):
        return orjson.dumps(value).decode()
    return "" if value is None else value


def csv_bytes(columns, rows):
    """*rows* (dicts) as UTF-8 CSV with a byte order mark; ``defusedcsv`` neutralises a cell that opens a formula."""
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\r\n")
    writer.writerow(columns)
    for row in rows:
        writer.writerow([_flat(row.get(column)) for column in columns])
    return buffer.getvalue().encode("utf-8-sig")


def _json_bytes(value):
    return orjson.dumps(value, option=orjson.OPT_INDENT_2)


def _dataset_url(dataset):
    url = (dataset or {}).get("url") or ""
    return f"https://doi.org/{url}" if url.startswith("10.") else url or None


def analysis_zones(scope):
    """``{analysis id: {"canvas", "label", "shape"}}``: the first zone of each analysis on a canvas of its document's manifest.

    Zones are read from the nodegroup both the reader and the viewer may
    read; the canvas is resolved as ``build_manifest`` resolves it.
    """
    bundle = scope.bundle
    readable = readable_nodegroup_ids(scope.reader) & readable_nodegroup_ids(
        scope.viewer
    )
    doc_values = Values(list(scope.documents), ["doc_manifest"], scope.reader)
    zone_node = role_node(*ROLES["zone"])
    zones = {}
    for document in scope.documents:
        url = rewrite_legacy_url(doc_values.first(document, "doc_manifest") or "")
        listed = canvases_of(manifest_json(url)) if url else []
        labels = {c["id"]: c["label"] for c in listed}
        analyses = [
            a for a in scope.analyses if bundle.chains.get(a, (None,))[0] == document
        ]
        for rid, _, canvas, shape in _annotations(
            zone_node, analyses, canvas_index(listed), readable
        ):
            if canvas in labels:
                zones.setdefault(
                    rid, {"canvas": canvas, "label": labels[canvas], "shape": shape}
                )
    return zones


def _unique(values):
    return list(dict.fromkeys(v for v in values if v))


ANALYSIS_COLUMNS = [
    "id",
    "name",
    "technique",
    "technique_uri",
    "document",
    "document_id",
    "component",
    "component_id",
    "zone_canvas",
    "zone_shape",
    "operators",
    "date_start",
    "date_end",
    "instrument",
    "projects",
]
ANALYSIS_TAIL = ["licences", "attributions", "dataset", "permalink", "draft"]


def analyses_table(scope, content, zones):
    """``(columns, rows)`` of ``metadata/analyses.csv``, one row per analysis of *scope*.

    *content* is the scope's ``ScopeContent`` (read with the statement and
    instrument roles), *zones* its ``analysis_zones``. Measurement conditions
    take one column per statement type label (``conditions: <label>``),
    untyped statements the column ``conditions``, as plain text. Operators,
    projects and instruments are named only when both the reader and the
    viewer may name them.
    """
    bundle, language = scope.bundle, scope.language
    values = content.values
    type_node = values.node("statement_type")
    content_node = values.node("statement_content")
    instruments_of = {a: bundle.links["instruments"].get(a, ()) for a in scope.analyses}
    shown_instruments = set(
        scope.names_visible({i for ids in instruments_of.values() for i in ids})
    )
    label_of = dict(bundle.label_of)
    label_of.update(content.label_of)
    label_of.update(names(shown_instruments, language, scope.reader))
    condition_columns, rows = [], []
    for row in content.rows:
        analysis_id = row["id"]
        document, component = bundle.chains.get(analysis_id, (None, None))
        conditions = {}
        if content_node:
            for condition in conditions_of(
                values.tiles(analysis_id, "statement_content"),
                type_node.nodeid if type_node else "",
                content_node.nodeid,
                language,
            ):
                column = (
                    f"conditions: {condition['type']['label']['value']}"
                    if condition["type"]
                    else "conditions"
                )
                conditions.setdefault(column, []).append(
                    plain_text(condition["html"], TEXT_LENGTH)
                )
        for column in conditions:
            if column not in condition_columns:
                condition_columns.append(column)
        end = values.first(analysis_id, "end")
        zone = zones.get(analysis_id)
        technique = row["technique"]
        files = content.files[analysis_id]
        rows.append(
            {
                "id": analysis_id,
                "name": row["name"]["value"],
                "technique": technique["label"]["value"] if technique else None,
                "technique_uri": (technique["uri"] or None) if technique else None,
                "document": (label_of.get(document) or {}).get("value"),
                "document_id": document,
                "component": (label_of.get(component) or {}).get("value"),
                "component_id": component,
                "zone_canvas": zone["label"] if zone else None,
                "zone_shape": zone["shape"] if zone else None,
                "operators": [
                    label_of[o]["value"]
                    for o in row["operators"]
                    if o in content.named and o in label_of
                ],
                "date_start": row["date"],
                "date_end": _date(end) if isinstance(end, str) else None,
                "instrument": [
                    label_of[i]["value"]
                    for i in sorted(instruments_of[analysis_id])
                    if i in shown_instruments and i in label_of
                ],
                "projects": [
                    label_of[p]["value"]
                    for p in content.projects[analysis_id]
                    if p in content.named and p in label_of
                ],
                **{column: "; ".join(texts) for column, texts in conditions.items()},
                "licences": _unique(
                    (f.get("license") or {}).get("label", {}).get("value")
                    for f in files
                ),
                "attributions": _unique(
                    (f.get("license") or {}).get("attribution") for f in files
                ),
                "dataset": _dataset_url(
                    dataset_of(values.first(analysis_id, "dataset"))
                ),
                "permalink": permalink(analysis_id),
                "draft": bool(row["unpublished"]),
            }
        )
    typed = sorted(c for c in condition_columns if c != "conditions")
    untyped = ["conditions"] if "conditions" in condition_columns else []
    return ANALYSIS_COLUMNS + typed + untyped + ANALYSIS_TAIL, rows


CHARACTERIZATION_COLUMNS = [
    "id",
    "name",
    "materials",
    "colours",
    "layers",
    "elements",
    "evidence",
    "note",
    "permalink",
    "draft",
]


def characterizations_table(scope):
    """``(columns, rows)`` of ``metadata/characterizations.csv``, one row per identified material of *scope*.

    Materials carry their certainty, elements their level; ``evidence``
    lists the ids of the cited analyses that are in the scope; the note is
    plain text.
    """
    bundle = scope.bundle
    kept = set(scope.analyses)
    rows = []
    for summary in characterization_summaries(
        scope.characterizations,
        bundle.visible,
        scope.reader,
        scope.language,
        {},
        objects_of=bundle.links["objects"],
        analysis_rows=bundle.by_id,
    ):
        materials = []
        for material in summary["materials"]:
            text = material["value"]["label"]["value"]
            if material["confidence"]:
                text += f" ({material['confidence']['label']['value']})"
            materials.append(text)
        elements = []
        for group in summary["elements"]:
            found = ", ".join(v["label"]["value"] for v in group["values"])
            level = group["level"]
            elements.append(f"{level['label']['value']}: {found}" if level else found)
        note = summary["note"]
        rows.append(
            {
                "id": summary["id"],
                "name": summary["name"]["value"],
                "materials": materials,
                "colours": [c["label"]["value"] for c in summary["colours"]],
                "layers": [c["label"]["value"] for c in summary["layers"]],
                "elements": elements,
                "evidence": [e["id"] for e in summary["evidence"] if e["id"] in kept],
                "note": plain_text(note["html"], TEXT_LENGTH) if note else None,
                "permalink": permalink(summary["id"]),
                "draft": bool(summary["unpublished"]),
            }
        )
    return CHARACTERIZATION_COLUMNS, rows


def _title(scope):
    """The name of the package: its project, its document, else its Selection."""
    if scope.kind in ("project", "document"):
        subject = scope.bundle.label_of.get(scope.subject) or names(
            {scope.subject}, scope.language, scope.reader
        ).get(scope.subject)
        return f"{settings.APP_TITLE} — {(subject or {}).get('value', scope.subject)}"
    count = len(scope.analyses) + len(scope.characterizations)
    return f"{settings.APP_TITLE} — " + ngettext(
        "Selection of %(count)d item", "Selection of %(count)d items", count
    ) % {"count": count}


def _marks(scope):
    marks = []
    if scope.drafts:
        marks.append(_("Contains drafts"))
    if scope.restricted:
        marks.append(_("Contains restricted-access data"))
    return marks


def _markdown_cell(text):
    return _MARKDOWN_BREAK.sub(" ", str(text or "")).replace("|", "\\|").strip()


def readme(
    scope, members, citations, availability_text, *, exported_at, datasets=(), notes=()
):
    """``README.md`` of the package in ``scope.language``: contents, how to cite, licences per file, availability.

    It names the datasets the data come from (*datasets*, ``dataset_of``
    values) by their identifier and never invites to deposit the package
    again. *notes* are extra paragraphs (a manifest left out, imaging given
    as manifests).
    """
    files = [
        {
            "path": _markdown_cell(m.arcname),
            "size": m.size,
            "licence": _markdown_cell(m.licence["label"]["value"]),
            "attribution": _markdown_cell(m.licence.get("attribution")),
        }
        for m in members
        if m.licence
    ]
    with translation.override(scope.language):
        text = render_to_string(
            "explorer/export_readme.md",
            {
                "title": _title(scope),
                "site": settings.APP_TITLE,
                "date": exported_at.isoformat(),
                "marks": _marks(scope),
                "files": files,
                "has_manifest": any(m.arcname == "manifest.json" for m in members),
                "notes": list(notes),
                "citations": [c["recommended"] for c in citations],
                "availability": availability_text,
                "datasets": _readme_datasets(datasets),
            },
        )
    return text.encode("utf-8")


def _readme_datasets(datasets):
    found = {}
    for dataset in datasets:
        url = _dataset_url(dataset)
        if url and url not in found:
            parsed = parse_dataverse(dataset.get("label"))
            title = parsed.title if parsed else dataset.get("label")
            found[url] = {"title": _markdown_cell(title or url), "url": url}
    return list(found.values())


def _file_entity(member, licence_id):
    entity = {
        "@id": member.arcname,
        "@type": "File",
        "name": posixpath.basename(member.arcname),
        "contentSize": str(member.size),
        "encodingFormat": member.media_type,
        "sha256": SHA256_SLOT,
    }
    if licence_id:
        entity["license"] = {"@id": licence_id}
    return entity


def _licence_id(licence):
    return licence.get("url") or f"#licence-{slugify(licence['id'])}"


def ro_crate(scope, members, exported_at, content=None):
    """The RO-Crate 1.1 metadata of the package, as a dict; every ``sha256`` is a 64-character placeholder.

    The descriptor ``ro-crate-metadata.json`` is about the root ``Dataset``
    ``./``, which has every member as ``hasPart``, the export day as
    ``datePublished``, the licence common to all licensed members (else a
    ``CreativeWork`` « Licences per file ») and the datasets the data come
    from as ``isBasedOn``. Each member is a ``File`` with its size, media
    type and licence. Each analysis is a ``CreateAction`` identified by its
    permalink: operators as ``Person`` agents, dates, the document and
    component as ``object``, its files as ``result``, its technique as a
    ``DefinedTerm`` in ``additionalType``. No instrument and no place are
    described.
    """
    content = content or scope_content(scope)
    bundle, language = scope.bundle, scope.language
    graph, contextual = [], {}

    def describe(entity):
        contextual.setdefault(entity["@id"], entity)

    licences = {}
    for member in members:
        if member.licence:
            licence_id = _licence_id(member.licence)
            licences[licence_id] = member.licence
    with translation.override(language):
        if len(licences) == 1:
            root_licence = next(iter(licences))
        else:
            root_licence = LICENCES_PER_FILE
            describe(
                {
                    "@id": LICENCES_PER_FILE,
                    "@type": "CreativeWork",
                    "name": _("Licences per file"),
                    "description": _(
                        "Each file carries its own licence, given with the file."
                    ),
                }
            )
        title = _title(scope)
        description = " ".join(
            [
                *_marks(scope),
                availability(
                    content.datasets,
                    licences=content.licences,
                    permalink=share_link(scope),
                    language=language,
                ),
            ]
        )
    for licence_id, licence in licences.items():
        entity = {
            "@id": licence_id,
            "@type": "CreativeWork",
            "name": licence["label"]["value"],
        }
        if licence.get("url"):
            entity["url"] = licence["url"]
        describe(entity)
    based_on = []
    for dataset in content.datasets:
        url = _dataset_url(dataset)
        if url and url not in based_on:
            based_on.append(url)
            describe(
                {
                    "@id": url,
                    "@type": "Dataset",
                    "name": dataset.get("label") or url,
                    "url": url,
                }
            )
    root = {
        "@id": "./",
        "@type": "Dataset",
        "name": title,
        "description": description,
        "datePublished": exported_at.isoformat(),
        "publisher": settings.APP_TITLE,
        "license": {"@id": root_licence},
        "hasPart": [{"@id": m.arcname} for m in members],
    }
    if based_on:
        root["isBasedOn"] = [{"@id": url} for url in based_on]
    graph.append(
        {
            "@id": CRATE_NAME,
            "@type": "CreativeWork",
            "conformsTo": {"@id": RO_CRATE_PROFILE},
            "about": {"@id": "./"},
        }
    )
    graph.append(root)
    graph += [
        _file_entity(m, _licence_id(m.licence) if m.licence else None) for m in members
    ]
    label_of = dict(bundle.label_of)
    label_of.update(content.label_of)
    for row in content.rows:
        analysis_id = row["id"]
        action = {
            "@id": permalink(analysis_id),
            "@type": "CreateAction",
            "name": row["name"]["value"],
        }
        agents = [o for o in row["operators"] if o in content.named and o in label_of]
        if agents:
            action["agent"] = [{"@id": permalink(o)} for o in agents]
            for o in agents:
                describe(
                    {
                        "@id": permalink(o),
                        "@type": "Person",
                        "name": label_of[o]["value"],
                    }
                )
        end = content.values.first(analysis_id, "end")
        if row["date"]:
            action["startTime"] = row["date"]
        if isinstance(end, str):
            action["endTime"] = _date(end)
        objects = [
            r for r in bundle.chains.get(analysis_id, (None, None)) if r in label_of
        ]
        if objects:
            action["object"] = [{"@id": permalink(r)} for r in objects]
            for r in objects:
                describe(
                    {
                        "@id": permalink(r),
                        "@type": "CreativeWork",
                        "name": label_of[r]["value"],
                    }
                )
        results = [m.arcname for m in members if m.analysis == analysis_id]
        if results:
            action["result"] = [{"@id": name} for name in results]
        technique = row["technique"]
        if technique:
            term = technique["uri"] or f"#technique-{technique['id']}"
            action["additionalType"] = {"@id": term}
            describe(
                {
                    "@id": term,
                    "@type": "DefinedTerm",
                    "name": technique["label"]["value"],
                }
            )
        graph.append(action)
    graph += list(contextual.values())
    return {"@context": RO_CRATE_CONTEXT, "@graph": graph}


def _built(name, data, media_type):
    return Member(name, len(data), None, data, media_type, None, None)


def _data_members(scope, content, zones):
    """The data files and imaging manifests of *scope*, laid out ``data/<document>/<folio>/<analysis>/<file>``."""
    bundle = scope.bundle
    taken, members = set(), []
    for row in content.rows:
        analysis_id = row["id"]
        document = bundle.chains.get(analysis_id, (None, None))[0]
        zone = zones.get(analysis_id)
        folio = (
            _segment(
                zone["label"],
                hashlib.sha1(
                    zone["canvas"].encode(), usedforsecurity=False
                ).hexdigest(),
            )
            if zone
            else UNLOCATED
        )
        parts = [
            "data",
            (
                _segment((bundle.label_of.get(document) or {}).get("value"), document)
                if document
                else UNLOCATED
            ),
            folio,
            _segment(row["name"]["value"], analysis_id),
        ]
        imaging = 0
        for entry in content.files[analysis_id]:
            if entry.get("dataKind") == "chemical-imaging":
                manifest = manifest_json(entry.get("downloadUrl"))
                if not isinstance(manifest, dict):
                    continue
                imaging += 1
                data = _json_bytes(manifest)
                name = arcname(parts, f"imaging-{imaging}.json", taken, "imaging")
                members.append(
                    Member(
                        name,
                        len(data),
                        None,
                        data,
                        "application/ld+json",
                        entry.get("license"),
                        analysis_id,
                    )
                )
                continue
            path = scope_file(scope, analysis_id, entry.get("id"))
            if path is None:
                continue
            try:
                size = os.path.getsize(path)
            except OSError:
                continue
            members.append(
                Member(
                    arcname(
                        parts,
                        entry.get("name"),
                        taken,
                        f"file-{str(entry.get('id'))[:8]}",
                    ),
                    size,
                    path,
                    None,
                    _media_type(entry),
                    entry.get("license"),
                    analysis_id,
                )
            )
    return members


class ExportTooLarge(Exception):
    """The data files of the scope exceed ``EXPLORER_EXPORT_MAX_FILES`` or ``EXPLORER_EXPORT_MAX_BYTES``."""


def package(scope, exported_at=None):
    """Every member of the data package of *scope* but ``ro-crate-metadata.json``, README first.

    *exported_at* (``datetime.date``, default today) is the export day and
    the day of consultation of the citations. A manifest over
    ``EXPLORER_MANIFEST_MAX_CANVASES`` canvases is left out and the README
    says why; imaging manifests go in as JSON, the README saying their images
    are served by IIIF. More data files than ``EXPLORER_EXPORT_MAX_FILES``,
    or more of their bytes than ``EXPLORER_EXPORT_MAX_BYTES``, raise
    ``ExportTooLarge`` before anything else is built and before any file is
    opened.
    """
    return _assemble(scope, exported_at or datetime.date.today())[0]


def _assemble(scope, exported_at):
    """``(members, content)`` of ``package``; *content* is the ``ScopeContent`` the RO-Crate reads."""
    language = scope.language
    content = scope_content(scope, ("statement_type", "statement_content"))
    zones = analysis_zones(scope)
    data = _data_members(scope, content, zones)
    files = [m for m in data if m.source is not None]
    if (
        len(files) > settings.EXPLORER_EXPORT_MAX_FILES
        or sum(m.size for m in files) > settings.EXPLORER_EXPORT_MAX_BYTES
    ):
        raise ExportTooLarge()
    citations = citation_entries(
        content.groups, language=language, accessed=exported_at
    )
    availability_text = availability(
        content.datasets,
        licences=content.licences,
        permalink=share_link(scope),
        language=language,
    )
    built = [
        _built(
            "citations.bib",
            "\n".join(c["bibtex"].strip() + "\n" for c in citations).encode(),
            "application/x-bibtex",
        ),
        _built(
            "citations.ris",
            "".join(c["ris"] for c in citations).encode(),
            "application/x-research-info-systems",
        ),
        _built(
            "citations.json",
            _json_bytes([c["csl"] for c in citations]),
            "application/vnd.citationstyles.csl+json",
        ),
    ]
    notes = []
    with translation.override(language):
        try:
            built.append(
                _built(
                    "manifest.json",
                    _json_bytes(build_manifest(scope)),
                    "application/ld+json",
                )
            )
        except ManifestTooLarge:
            notes.append(
                _(
                    "The IIIF manifest of this scope is too large to be included "
                    "(more than %(count)d canvases): open it by document."
                )
                % {"count": settings.EXPLORER_MANIFEST_MAX_CANVASES}
            )
        if any(
            m.media_type == "application/ld+json" and m.source is None for m in data
        ):
            notes.append(
                _(
                    "Chemical imaging is given as IIIF manifests (imaging-<n>.json); "
                    "their images are served by IIIF image servers and are not in the package."
                )
            )
    columns, rows = analyses_table(scope, content, zones)
    built += [
        _built("metadata/analyses.csv", csv_bytes(columns, rows), "text/csv"),
        _built("metadata/analyses.json", _json_bytes(rows), "application/json"),
    ]
    columns, rows = characterizations_table(scope)
    built += [
        _built("metadata/characterizations.csv", csv_bytes(columns, rows), "text/csv"),
        _built(
            "metadata/characterizations.json", _json_bytes(rows), "application/json"
        ),
    ]
    members = built + data
    text = readme(
        scope,
        members,
        citations,
        availability_text,
        exported_at=exported_at,
        datasets=content.datasets,
        notes=notes,
    )
    return [_built("README.md", text, "text/markdown"), *members], content


def _crate_bytes(crate):
    return orjson.dumps(crate, option=orjson.OPT_SORT_KEYS | orjson.OPT_INDENT_2)


def _file_chunks(member, digests):
    """The bytes of a stored data file in ``CHUNK_SIZE`` chunks; its sha256 goes to *digests*.

    A file whose length on disk differs from ``member.size`` raises
    ``RuntimeError`` as soon as the difference shows, so a stream never ends
    with a complete-looking archive.
    """
    sha, read = hashlib.sha256(), 0
    with open(member.source, "rb") as handle:
        while chunk := handle.read(CHUNK_SIZE):
            read += len(chunk)
            if read > member.size:
                raise RuntimeError(f"{member.arcname} grew while it was exported")
            sha.update(chunk)
            yield chunk
    if read != member.size:
        raise RuntimeError(f"{member.arcname} shrank while it was exported")
    digests[member.arcname] = sha.hexdigest()


def _filled(crate, members, digests):
    """*crate* with the sha256 of every member in place of its placeholder."""
    for member in members:
        if member.source is None:
            digests[member.arcname] = hashlib.sha256(member.data).hexdigest()
    graph = [
        (
            {**entity, "sha256": digests[entity["@id"]]}
            if entity.get("@type") == "File"
            else entity
        )
        for entity in crate["@graph"]
    ]
    return {**crate, "@graph": graph}


def stream(members, crate):
    """``(length, iterator)`` of the stored ZIP of *members* followed by ``ro-crate-metadata.json``.

    Every entry is ``ZIP_STORED`` and the stream is sized, so its length is
    known before the first byte. Data files are read while they stream;
    ``ro-crate-metadata.json`` comes last, serialised with the checksums
    collected on the way in the length of its placeholder (64 hexadecimal
    characters per checksum, sorted keys). A size that does not match raises
    ``RuntimeError`` inside the iterator.
    """
    archive = ZipStream(compress_type=ZIP_STORED, sized=True)
    digests = {}
    for member in members:
        if member.source is None:
            archive.add(member.data, member.arcname)
        else:
            archive.add(_file_chunks(member, digests), member.arcname, size=member.size)
    placeholder = _crate_bytes(crate)

    def crate_chunks():
        data = _crate_bytes(_filled(crate, members, digests))
        if len(data) != len(placeholder):
            raise RuntimeError("the RO-Crate metadata changed length")
        yield data

    archive.add(crate_chunks(), CRATE_NAME, size=len(placeholder))
    return len(archive), iter(archive)


def _too_large():
    response = HttpResponse(status=413)
    response["Cache-Control"] = "private, no-store"
    return response


class ExplorerExportView(View):
    """``GET /api/explorer/export?ids=|document=|project=[&canvases=all][&restricted=1][&lang=]``: the data package, a private download.

    ``lang`` absent is ``LANGUAGE_CODE``; an unknown language or malformed
    scope parameters answer a bodyless 400, a scope with nothing visible the
    bodyless 404, a package over ``EXPLORER_EXPORT_MAX_FILES`` or
    ``EXPLORER_EXPORT_MAX_BYTES`` a bodyless 413. The archive streams
    uncompressed with its ``Content-Length``.
    """

    def get(self, request):
        try:
            language = export_language(request.GET)
        except ScopeError:
            return HttpResponseBadRequest()
        with translation.override(language):
            try:
                scope = resolve_scope(request.GET, request.user, language)
            except ScopeError:
                return HttpResponseBadRequest()
            if scope is None:
                return _not_found()
            exported_at = datetime.date.today()
            try:
                members, content = _assemble(scope, exported_at)
            except ExportTooLarge:
                return _too_large()
            crate = ro_crate(scope, members, exported_at, content)
        length, body = stream(members, crate)
        response = StreamingHttpResponse(body, content_type="application/zip")
        response["Content-Length"] = str(length)
        response["Content-Disposition"] = content_disposition_header(
            True, f"manuspectrum-{scope.kind}-{scope.digest}.zip"
        )
        response["Cache-Control"] = "private, no-store"
        return response
