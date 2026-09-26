"""The Explorer's IIIF Presentation 3 manifest of a scope (spec §11.1).

The building blocks work without database access: minted ids, selectors and
targets, source canvases (v2 or v3) as v3 canvases, and the data annotations
of an analysis. Annotations keep the shape of the project's v3 annotation
serializer (``supplementing``, ``Dataset`` bodies, ``seeAlso`` report) so
IIIF clients reading those read these the same way. ``build_manifest``
assembles the manifest of an ``ExportScope`` per request; nothing is
memoised.
"""

import functools
import hashlib
import re
from collections import defaultdict
from dataclasses import dataclass
from urllib.parse import quote, urlencode

from django.conf import settings
from django.urls import reverse
from django.utils import translation
from django.utils.translation import gettext as _
from django.utils.translation import ngettext

from manuspectrum.constants.licenses import iiif_rights
from manuspectrum.utils.iiif_tools import CanvasIIIF
from manuspectrum.utils.role_links import role_node
from manuspectrum.views.explorer_conditions import conditions_of
from manuspectrum.views.explorer_service import (
    ROLES,
    Values,
    _annotations,
    analysis_files,
    canvas_index,
    canvases_of,
    characterization_summaries,
    dataset_of,
    document_characterizations,
    imaging_entries,
    manifest_json,
    names,
    permalink,
    plain_text,
    product_url,
    renderer_configs,
)
from manuspectrum.views.explorer_scopes import kept_files
from manuspectrum.views.explorer_values import rewrite_legacy_url
from manuspectrum.views.summary_service import _date

PRESENTATION_3 = "http://iiif.io/api/presentation/3/context.json"
MEDIA_FRAGMENTS = "http://www.w3.org/TR/media-frags/"
SVG_NAMESPACE = "http://www.w3.org/2000/svg"
OCTET_STREAM = "application/octet-stream"
ANALYSIS_KEYS = [
    "files",
    "micro",
    "imaging",
    "dataset",
    "end",
    "statement_type",
    "statement_content",
]
_LEVEL = re.compile(r"level([0-2])")
_MIME = re.compile(r"^[a-z][a-z0-9.+-]*/[a-z0-9.+-]+$")


class ManifestTooLarge(Exception):
    """The manifest would hold more than ``EXPLORER_MANIFEST_MAX_CANVASES`` canvases."""


def mint(scope_digest, *parts):
    """Absolute id of a resource the manifest of *scope_digest* creates; it need not dereference."""
    path = reverse("iiif-v3-explorer-manifest").lstrip("/")
    tail = "".join(f"/{quote(str(part), safe='')}" for part in parts)
    return f"{settings.PUBLIC_SERVER_ADDRESS}{path}/{scope_digest}{tail}"


def selector(shape):
    """IIIF selector of a contract ``Shape`` in canvas pixels.

    A point is a ``PointSelector``, a rectangle a media-fragment ``xywh``
    ``FragmentSelector``, a polygon an ``SvgSelector`` with integer points.
    """
    if shape["type"] == "point":
        return {"type": "PointSelector", "x": int(shape["x"]), "y": int(shape["y"])}
    if shape["type"] == "rect":
        box = ",".join(str(int(shape[k])) for k in ("x", "y", "w", "h"))
        return {
            "type": "FragmentSelector",
            "conformsTo": MEDIA_FRAGMENTS,
            "value": f"xywh={box}",
        }
    points = " ".join(f"{int(x)},{int(y)}" for x, y in shape["points"])
    return {
        "type": "SvgSelector",
        "value": f'<svg xmlns="{SVG_NAMESPACE}"><polygon points="{points}"/></svg>',
    }


def target(canvas_id, manifest_url, shape):
    """Target of an annotation on *canvas_id*: the canvas itself without *shape*, else a ``SpecificResource`` on it."""
    if shape is None:
        return canvas_id
    return {
        "type": "SpecificResource",
        "source": {
            "id": canvas_id,
            "type": "Canvas",
            "partOf": [{"id": manifest_url, "type": "Manifest"}],
        },
        "selector": selector(shape),
    }


def _rewritten(value):
    """*value* with a legacy host rewritten in every ``id`` and ``@id``."""
    if isinstance(value, list):
        return [_rewritten(item) for item in value]
    if isinstance(value, dict):
        return {
            key: (
                rewrite_legacy_url(item)
                if key in ("id", "@id") and isinstance(item, str)
                else _rewritten(item)
            )
            for key, item in value.items()
        }
    return value


def _text(value):
    """Plain text of a v2 string value: a string, a ``{"@value"}`` object or a list of them."""
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, dict):
        return _text(value.get("@value"))
    if isinstance(value, list):
        return " ; ".join(t for t in (_text(v) for v in value) if t)
    return ""


def _rights(value):
    rights = value[0] if isinstance(value, list) and value else value
    return iiif_rights({"url": rights}) if isinstance(rights, str) else None


def _v2_painting(canvas, canvas_id, mint_id):
    key = hashlib.sha1(canvas_id.encode(), usedforsecurity=False).hexdigest()[:12]
    image = ((canvas.get("images") or [{}])[0] or {}).get("resource") or {}
    service = image.get("service") or {}
    if isinstance(service, list):
        service = service[0] if service else {}
    service_id = service.get("@id") or service.get("id")
    body = {
        "id": image.get("@id")
        or (f"{service_id.rstrip('/')}/full/full/0/default.jpg" if service_id else ""),
        "type": "Image",
        "format": image.get("format") or "image/jpeg",
    }
    width, height = image.get("width"), image.get("height")
    if isinstance(width, int) and isinstance(height, int):
        body.update(width=width, height=height)
    if service_id:
        level = _LEVEL.search(str(service.get("profile") or ""))
        body["service"] = [
            {
                "id": service_id,
                "type": "ImageService2",
                "profile": f"level{level[1] if level else 0}",
            }
        ]
    return [
        {
            "id": mint_id("painting", key),
            "type": "AnnotationPage",
            "items": [
                {
                    "id": mint_id("painting", key, "image"),
                    "type": "Annotation",
                    "motivation": "painting",
                    "target": canvas_id,
                    "body": body,
                }
            ],
        }
    ]


def v3_canvas(source_canvas, source_manifest, manifest_url, mint_id):
    """*source_canvas* of *source_manifest* (v2 or v3) as a v3 canvas, part of *manifest_url*.

    A v3 canvas keeps its ``id``, ``label``, size and ``items``; ``rights``
    and ``requiredStatement`` are its own, else the manifest's; its own
    ``annotations`` are dropped. A v2 canvas gets one minted painting page
    whose image carries an ``ImageService2``; the manifest's ``license``
    becomes ``rights`` and its ``attribution`` a ``requiredStatement``.
    ``rights`` is kept only in the ``http://`` form of a rights registry
    (``iiif_rights``). Legacy hosts are rewritten in every id.
    """
    source_canvas = _rewritten(source_canvas)
    source_manifest = source_manifest or {}
    width, height = CanvasIIIF.get_canvas_dimensions(source_canvas)
    if CanvasIIIF.detect_version(source_manifest) == 3:
        canvas_id = source_canvas["id"]
        canvas = {
            "id": canvas_id,
            "type": "Canvas",
            "label": source_canvas.get("label") or {"none": [""]},
            "width": int(width),
            "height": int(height),
            "items": source_canvas.get("items") or [],
        }
        rights = _rights(source_canvas.get("rights") or source_manifest.get("rights"))
        statement = source_canvas.get("requiredStatement") or source_manifest.get(
            "requiredStatement"
        )
    else:
        canvas_id = source_canvas["@id"]
        canvas = {
            "id": canvas_id,
            "type": "Canvas",
            "label": {"none": [_text(source_canvas.get("label"))]},
            "width": int(width),
            "height": int(height),
            "items": _v2_painting(source_canvas, canvas_id, mint_id),
        }
        rights = _rights(source_manifest.get("license"))
        attribution = _text(source_manifest.get("attribution"))
        statement = (
            {"label": {"none": [_("Attribution")]}, "value": {"none": [attribution]}}
            if attribution
            else None
        )
    if rights:
        canvas["rights"] = rights
    if statement:
        canvas["requiredStatement"] = statement
    canvas["partOf"] = [{"id": manifest_url, "type": "Manifest"}]
    return canvas


def layer_canvas(source_canvas, imaging_manifest, imaging_url, label, mint_id):
    """One image layer of an imaging manifest as a v3 canvas: its source id, the lngString *label*, part of *imaging_url*."""
    canvas = v3_canvas(source_canvas, imaging_manifest, imaging_url, mint_id)
    canvas["label"] = label
    return canvas


def absolute_url(url):
    """*url* as an absolute URL: a site path is prefixed with ``PUBLIC_SERVER_ADDRESS``; None when it is neither."""
    url = str(url or "")
    if url.startswith(("http://", "https://")):
        return url
    if url.startswith("/") and not url.startswith("//"):
        return f"{settings.PUBLIC_SERVER_ADDRESS}{url.lstrip('/')}"
    return None


def _dataset_url(dataset):
    url = (dataset or {}).get("url") or ""
    if url.startswith("10."):
        return f"https://doi.org/{url}"
    return url if url.startswith(("http://", "https://")) else None


def _body(entry, language):
    """Annotation body of one ``FileEntry``: a ``Dataset``, or the ``Manifest`` of an imaging entry; None without a URL."""
    url = absolute_url(entry.get("downloadUrl"))
    if url is None:
        return None
    if entry.get("dataKind") == "chemical-imaging":
        return {"id": url, "type": "Manifest"}
    fmt = str(entry.get("format") or "").lower()
    body = {
        "id": url,
        "type": "Dataset",
        "format": fmt if _MIME.match(fmt) else OCTET_STREAM,
        "label": {language: [entry.get("name") or ""]},
    }
    licence = entry.get("license")
    rights = iiif_rights(licence)
    if rights:
        body["rights"] = rights
    if licence and not rights:
        text = " — ".join(
            t for t in (licence["label"]["value"], licence.get("attribution")) if t
        )
        body["requiredStatement"] = {
            "label": {language: [_("Licence")]},
            "value": {language: [text]},
        }
    elif licence and licence.get("attribution"):
        body["requiredStatement"] = {
            "label": {language: [_("Attribution")]},
            "value": {language: [licence["attribution"]]},
        }
    return body


def data_annotation(annotation_id, analysis, files, target, language):
    """The ``supplementing`` annotation of one analysis on *target*, its files as bodies.

    *analysis* holds ``name``, ``permalink``, ``dataset`` (``dataset_of``)
    and the plain-text metadata ``technique``, ``dates``, ``operators``,
    ``conditions``, ``document`` and ``component`` (empty ones are left
    out). Each file is a ``Dataset`` body: its absolute download URL, its
    MIME type (``application/octet-stream`` when the entry has none),
    ``rights`` when its licence is in a rights registry, else a
    ``requiredStatement`` naming the licence and its attribution; an
    attribution under a registry licence is a ``requiredStatement`` too. An
    imaging manifest is a ``Manifest`` body. ``seeAlso`` links the report
    and the dataset.
    """
    with translation.override(language):
        name = {language: [analysis["name"]]}
        see_also = [
            {
                "id": analysis["permalink"],
                "type": "Text",
                "format": "text/html",
                "label": name,
            }
        ]
        dataset = analysis.get("dataset")
        dataset_url = _dataset_url(dataset)
        if dataset_url:
            link = {"id": dataset_url, "type": "Dataset", "format": "text/html"}
            if dataset.get("label"):
                link["label"] = {language: [dataset["label"]]}
            see_also.append(link)
        metadata = []
        for label, value in (
            (_("Technique"), analysis.get("technique")),
            (_("Dates"), analysis.get("dates")),
            (_("Operators"), analysis.get("operators")),
            (_("Conditions"), analysis.get("conditions")),
            (_("Document"), analysis.get("document")),
            (_("Component"), analysis.get("component")),
        ):
            values = [value] if isinstance(value, str) else list(value or ())
            values = [v for v in values if v]
            if values:
                metadata.append(
                    {"label": {language: [label]}, "value": {language: values}}
                )
        return {
            "id": annotation_id,
            "type": "Annotation",
            "motivation": "supplementing",
            "label": name,
            "body": [b for b in (_body(f, language) for f in files) if b],
            "target": target,
            "seeAlso": see_also,
            "metadata": metadata,
        }


def _source_canvases(manifest):
    """``{canvas id: raw canvas}`` of a v2 or v3 manifest, in manifest order, ids with legacy hosts rewritten."""
    if not isinstance(manifest, dict):
        return {}
    if CanvasIIIF.detect_version(manifest) == 3:
        raw = manifest.get("items") or []
    else:
        raw = ((manifest.get("sequences") or [{}])[0] or {}).get("canvases") or []
    found = {}
    for canvas in raw:
        canvas_id = canvas.get("id") or canvas.get("@id")
        if canvas_id:
            found.setdefault(rewrite_legacy_url(canvas_id), canvas)
    return found


def _key(text):
    return hashlib.sha1(str(text).encode(), usedforsecurity=False).hexdigest()[:12]


class _Canvases:
    """The manifest's canvases in order, each id once, bounded by ``EXPLORER_MANIFEST_MAX_CANVASES``."""

    def __init__(self):
        self.items, self.ids = [], set()
        self.limit = settings.EXPLORER_MANIFEST_MAX_CANVASES

    def add(self, canvas):
        if canvas["id"] in self.ids:
            return
        if len(self.items) >= self.limit:
            raise ManifestTooLarge()
        self.items.append(canvas)
        self.ids.add(canvas["id"])


def _material_text(summary):
    """Material names of an identified material summary, each with its certainty."""
    texts = []
    for material in summary["materials"]:
        text = material["value"]["label"]["value"]
        if material["confidence"]:
            text += f" ({material['confidence']['label']['value']})"
        texts.append(text)
    return "; ".join(texts) or summary["name"]["value"]


def _facts(scope, row, values, label_of, named):
    """What ``data_annotation`` says of one analysis *row*."""
    end = values.first(row["id"], "end")
    end = _date(end) if isinstance(end, str) else None
    dates = " – ".join(dict.fromkeys(d for d in (row["date"], end) if d))
    type_node = values.node("statement_type")
    content_node = values.node("statement_content")
    conditions = (
        conditions_of(
            values.tiles(row["id"], "statement_content"),
            type_node.nodeid if type_node else "",
            content_node.nodeid,
            scope.language,
        )
        if content_node
        else []
    )
    document, component = scope.bundle.chains.get(row["id"], (None, None))
    technique = row["technique"]
    return {
        "name": row["name"]["value"],
        "permalink": permalink(row["id"]),
        "dataset": dataset_of(values.first(row["id"], "dataset")),
        "technique": technique["label"]["value"] if technique else None,
        "dates": dates or None,
        "operators": [
            label_of[o]["value"]
            for o in row["operators"]
            if o in named and o in label_of
        ],
        "conditions": [plain_text(c["html"]) for c in conditions],
        "document": label_of[document]["value"] if document in label_of else None,
        "component": label_of[component]["value"] if component in label_of else None,
    }


def _layers(entry, folio_label, mint_id, read=manifest_json):
    """Layer canvases of one kept imaging entry, labelled « <folio> — <layer> »; *read* reads its manifest."""
    url = entry.get("downloadUrl") or ""
    imaging = read(url) or {}
    part_of = _absolute_or_self(url)
    layers = []
    for canvas, raw in zip(canvases_of(imaging), _source_canvases(imaging).values()):
        label = " — ".join(t for t in (folio_label, canvas["label"]) if t)
        layers.append(layer_canvas(raw, imaging, part_of, {"none": [label]}, mint_id))
    return layers


def _absolute_or_self(url):
    return absolute_url(url) or url


def _label(scope, folios, label_of):
    if scope.kind == "project":
        return names({scope.subject}, scope.language, scope.reader)[scope.subject][
            "value"
        ]
    if len(scope.documents) == 1:
        return ngettext(
            "Selection of %(count)d page of %(document)s",
            "Selection of %(count)d pages of %(document)s",
            folios,
        ) % {"count": folios, "document": label_of[scope.documents[0]]["value"]}
    return ngettext(
        "Selection of %(count)d page of %(documents)d documents",
        "Selection of %(count)d pages of %(documents)d documents",
        folios,
    ) % {"count": folios, "documents": len(scope.documents)}


def _homepage(scope):
    """The Explorer page of the scope: its document, its project filter or its Selection."""
    with translation.override(scope.language):
        page = reverse("analysis-explorer").lstrip("/")
    if scope.kind == "document":
        query = urlencode({"doc": scope.subject})
    elif scope.kind == "project":
        query = urlencode({"project": scope.subject})
    else:
        query = f"sel={scope.key.split('&')[0].removeprefix('ids=')}"
    return [
        {
            "id": f"{settings.PUBLIC_SERVER_ADDRESS}{page}?{query}",
            "type": "Text",
            "format": "text/html",
            "label": {scope.language: [settings.APP_TITLE]},
        }
    ]


@dataclass(frozen=True)
class _Placement:
    """Where the elements of a scope fall on one document's manifest (``_placements``)."""

    document: str
    url: str
    source: object
    raw: dict
    position: dict
    analyses: list
    zones: dict
    first: dict
    materials: dict
    kept: list


def _placements(scope):
    """One ``_Placement`` per document of *scope*, in order: its source manifest, zones, material zones and kept canvases.

    Zones are read from ``scope.nodegroups``. The kept canvases are those
    carrying a zone of a kept analysis or of a kept identified material, or
    every canvas with ``canvases_all``. ``ManifestTooLarge`` is raised as
    soon as the kept canvases of the documents placed so far exceed
    ``EXPLORER_MANIFEST_MAX_CANVASES``.
    """
    bundle, language, reader = scope.bundle, scope.language, scope.reader
    readable = scope.nodegroups
    doc_values = Values(list(scope.documents), ["doc_manifest"], reader)
    zone_node = role_node(*ROLES["zone"])
    material_nodegroups = {
        "own": getattr(role_node(*ROLES["ch_zone"]), "nodegroup_id", None),
        "component": getattr(role_node(*ROLES["comp_zone"]), "nodegroup_id", None),
    }
    chosen_characterizations = set(scope.characterizations)
    limit = settings.EXPLORER_MANIFEST_MAX_CANVASES
    plans, planned = [], set()
    for document in scope.documents:
        url = rewrite_legacy_url(doc_values.first(document, "doc_manifest") or "")
        source = manifest_json(url) if url else None
        listed = canvases_of(source)
        position = {c["id"]: c for c in listed}
        dims = canvas_index(listed)
        analyses = [
            a for a in scope.analyses if bundle.chains.get(a, (None,))[0] == document
        ]
        zones, first = defaultdict(list), {}
        for rid, feature, canvas, shape in _annotations(
            zone_node, analyses, dims, readable
        ):
            if canvas in position:
                zones[canvas].append((rid, feature, shape))
                first.setdefault(rid, canvas)
        materials = defaultdict(list)
        chosen = [
            c
            for c in document_characterizations(bundle, document)
            if c in chosen_characterizations
        ]
        for summary in characterization_summaries(
            chosen,
            bundle.visible,
            reader,
            language,
            dims,
            objects_of=bundle.links["objects"],
            analysis_rows=bundle.by_id,
        ):
            zone = summary["zone"]
            if (
                zone
                and zone["canvas"] in position
                and material_nodegroups[zone["source"]] in readable
            ):
                materials[zone["canvas"]].append((summary, zone["shape"]))
        if scope.canvases_all:
            kept = [c["id"] for c in listed]
        else:
            kept = [c["id"] for c in listed if c["id"] in zones or c["id"] in materials]
        raw = _source_canvases(source)
        planned.update(c for c in kept if c in raw)
        if len(planned) > limit:
            raise ManifestTooLarge()
        plans.append(
            _Placement(
                document=document,
                url=url,
                source=source,
                raw=raw,
                position=position,
                analyses=analyses,
                zones=zones,
                first=first,
                materials=materials,
                kept=kept,
            )
        )
    return plans


def _layer_ids(entry, read=manifest_json):
    """The canvas ids ``_layers`` gives one kept imaging entry; *read* reads its manifest."""
    imaging = read(entry.get("downloadUrl") or "") or {}
    return list(_source_canvases(imaging))[: len(canvases_of(imaging))]


def build_manifest(scope):
    """The IIIF Presentation 3 manifest of *scope*, in ``scope.language``.

    ``id`` is the manifest's own URL (``product_url``), ``homepage`` the
    Explorer page of the scope. The label names the project of a project
    scope, else the Selection (« Selection of n pages of <document> » or
    « … of k documents »). The manifest carries no ``rights``; ``summary``
    says when the scope holds drafts or restricted-access data.

    Per document, in ``scope.documents`` order, its manifest (the
    ``doc_manifest`` role, read by ``manifest_json``) gives the canvases:
    those carrying a zone of a kept analysis or of a kept identified
    material, or all of them with ``canvases_all``, each converted by
    ``v3_canvas``. A canvas's ``annotations`` hold one ``data_annotation``
    per analysis zone and one ``describing`` annotation per material zone
    (a plain-text ``TextualBody`` naming the materials and their certainty).
    Zones are read from the nodegroups both the reader and the viewer may
    read. The layers of each kept imaging entry follow the canvas of the
    analysis's first zone, labelled « <folio> — <layer> »; the layers of an
    analysis without a zone follow the canvases of its document (or come
    last). ``structures`` holds one Range per document and one per analysis
    with imaging layers.

    An analysis without a zone on a canvas of its document's manifest (none,
    unreadable, or a zone on an unknown canvas) has no annotation and is
    listed in the manifest's ``metadata`` with its permalink.

    More than ``EXPLORER_MANIFEST_MAX_CANVASES`` canvases (folios and
    layers) raises ``ManifestTooLarge``, counted before anything is built:
    the folios while the zones are placed (``_placements``), before any file
    or fact is read, then the folios and layers once the imaging entries are
    read, before the other files, the facts and any canvas.
    """
    bundle, language, reader = scope.bundle, scope.language, scope.reader
    mint_id = functools.partial(mint, scope.digest)
    limit = settings.EXPLORER_MANIFEST_MAX_CANVASES
    plans = _placements(scope)
    planned = {c for plan in plans for c in plan.kept if c in plan.raw}
    values = Values(list(scope.analyses), ANALYSIS_KEYS, reader)
    read_imaging = functools.cache(manifest_json)
    imaging = {
        a: kept_files(scope, a, imaging_entries(a, values.get(a, "imaging"), language))
        for a in scope.analyses
    }
    layer_ids = {
        c
        for entries in imaging.values()
        for e in entries
        for c in _layer_ids(e, read_imaging)
    }
    if len(planned | layer_ids) > limit:
        raise ManifestTooLarge()
    rows = {a: bundle.by_id[a] for a in scope.analyses}
    configs = renderer_configs(values, scope.analyses)
    files = {
        a: kept_files(
            scope,
            a,
            analysis_files(a, reader, language, values=values, configs=configs),
        )
        for a in scope.analyses
    }
    named = set(
        scope.names_visible({o for row in rows.values() for o in row["operators"]})
    )
    label_of = dict(bundle.label_of)
    label_of.update(names(named, language, reader))
    facts = {a: _facts(scope, row, values, label_of, named) for a, row in rows.items()}
    canvases, structures, unlocated, placed = _Canvases(), [], [], set()
    layer_ranges = {}

    def add_layers(analysis_id, folio_label):
        placed.add(analysis_id)
        for entry in imaging[analysis_id]:
            for layer in _layers(entry, folio_label, mint_id, read_imaging):
                canvases.add(layer)
                layer_ranges.setdefault(analysis_id, []).append(layer["id"])

    folios = 0
    for plan in plans:
        document, url, source, raw = plan.document, plan.url, plan.source, plan.raw
        position, zones, materials = plan.position, plan.zones, plan.materials
        analyses, first, kept = plan.analyses, plan.first, plan.kept
        after = defaultdict(list)
        for analysis_id, canvas_id in first.items():
            after[canvas_id].append(analysis_id)
        folio_ids = []
        for canvas_id in kept:
            if canvas_id not in raw:
                continue
            canvas = v3_canvas(raw[canvas_id], source, url, mint_id)
            items = [
                data_annotation(
                    mint_id("annotation", rid, feature),
                    facts[rid],
                    files[rid],
                    target(canvas_id, url, shape),
                    language,
                )
                for rid, feature, shape in zones.get(canvas_id, ())
            ] + [
                {
                    "id": mint_id("material", summary["id"]),
                    "type": "Annotation",
                    "motivation": "describing",
                    "label": {language: [summary["name"]["value"]]},
                    "body": {
                        "type": "TextualBody",
                        "value": _material_text(summary),
                        "format": "text/plain",
                        "language": language,
                    },
                    "target": target(canvas_id, url, shape),
                }
                for summary, shape in materials.get(canvas_id, ())
            ]
            if items:
                canvas["annotations"] = [
                    {
                        "id": mint_id("annotations", _key(canvas_id)),
                        "type": "AnnotationPage",
                        "items": items,
                    }
                ]
            canvases.add(canvas)
            folio_ids.append(canvas_id)
            folios += 1
            for analysis_id in after.get(canvas_id, ()):
                add_layers(analysis_id, position[canvas_id]["label"])
        for analysis_id in analyses:
            if analysis_id not in first:
                unlocated.append(analysis_id)
                add_layers(analysis_id, facts[analysis_id]["name"])
        if folio_ids:
            structures.append(
                {
                    "id": mint_id("range", document),
                    "type": "Range",
                    "label": {language: [label_of[document]["value"]]},
                    "items": [{"id": c, "type": "Canvas"} for c in folio_ids],
                }
            )
    for analysis_id in scope.analyses:
        if analysis_id not in placed:
            unlocated.append(analysis_id)
            add_layers(analysis_id, facts[analysis_id]["name"])
    for analysis_id in scope.analyses:
        if analysis_id in layer_ranges:
            structures.append(
                {
                    "id": mint_id("range", analysis_id),
                    "type": "Range",
                    "label": {language: [facts[analysis_id]["name"]]},
                    "items": [
                        {"id": c, "type": "Canvas"} for c in layer_ranges[analysis_id]
                    ],
                }
            )

    manifest = {
        "@context": PRESENTATION_3,
        "id": product_url("iiif-v3-explorer-manifest", scope.key, language),
        "type": "Manifest",
        "label": {language: [_label(scope, folios, label_of)]},
    }
    summary = []
    if scope.drafts:
        summary.append(_("Contains drafts"))
    if scope.restricted:
        summary.append(_("Contains restricted-access data"))
    if summary:
        manifest["summary"] = {language: summary}
    if unlocated:
        manifest["metadata"] = [
            {
                "label": {language: [_("Without a position on the image")]},
                "value": {
                    language: [
                        f"{facts[a]['name']} — {facts[a]['permalink']}"
                        for a in unlocated
                    ]
                },
            }
        ]
    manifest["homepage"] = _homepage(scope)
    manifest["items"] = canvases.items
    if structures:
        manifest["structures"] = structures
    return manifest
