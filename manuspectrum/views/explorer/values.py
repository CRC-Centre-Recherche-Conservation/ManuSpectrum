"""Tile values turned into the objects of the Explorer's JSON contract (spec §5).

Pure functions over what Arches stores in ``tiles.tiledata``; none of them
queries the database.

``label()`` duplicates the language-fallback bucketing that ``localized()``
(``views/graph_nodes.py``, used throughout ``summary_service``) already does,
because the Explorer contract needs the language a name actually resolved to
(``Label.lang``, shown in the UI when it falls back to another language) and
``localized()`` only returns the text.
"""

import os
import re
from urllib.parse import urlsplit

from django.conf import settings
from django.urls import reverse

from manuspectrum.constants.licenses import effective_license
from manuspectrum.constants.xy_presets import XY_PRESETS
from manuspectrum.utils.iiif_tools import BBoxCalculator

FALLBACK_LANGUAGE = "en"


def label(texts, language):
    """``{"value", "lang"}`` from ``{lang: text}``: *language*, English, then the first language; None when all are empty."""
    texts = {
        lang: text.strip()
        for lang, text in (texts or {}).items()
        if isinstance(text, str) and text.strip()
    }
    if not texts:
        return None
    for lang in (language, FALLBACK_LANGUAGE):
        if lang in texts:
            return {"value": texts[lang], "lang": lang}
    lang = sorted(texts)[0]
    return {"value": texts[lang], "lang": lang}


def string_texts(value):
    """``{lang: text}`` of a localized string value; a plain string counts as English."""
    if isinstance(value, str):
        return {FALLBACK_LANGUAGE: value}
    if not isinstance(value, dict):
        return {}
    texts = {}
    for lang, entry in value.items():
        text = entry.get("value") if isinstance(entry, dict) else entry
        if isinstance(text, str):
            texts[lang] = text
    return texts


def name_of(values, model_name, resource_id, language):
    """Name of a resource from its ``label_of_name`` values, else « model name + short id »."""
    for value in values or []:
        found = label(string_texts(value), language)
        if found:
            return found
    model = label(model_name or {}, language) or {"value": "", "lang": language}
    return {
        "value": f"{model['value']} {str(resource_id)[:4]}…".strip(),
        "lang": model["lang"],
    }


def _reference_items(value):
    items = value if isinstance(value, list) else [value]
    return [item for item in items if isinstance(item, dict) and item.get("uri")]


def value_refs(value, language):
    """``ValueRef`` list of a ``reference`` value: list item id, uri, and its prefLabel, else altLabel, else the uri."""
    refs = []
    for item in _reference_items(value):
        preferred, other, item_id = {}, {}, None
        for entry in item.get("labels") or []:
            if not isinstance(entry, dict) or not isinstance(entry.get("value"), str):
                continue
            item_id = item_id or entry.get("list_item_id")
            bucket = preferred if entry.get("valuetype_id") == "prefLabel" else other
            bucket.setdefault(entry.get("language_id"), entry["value"])
        text = (
            label(preferred, language)
            or label(other, language)
            or {"value": item["uri"], "lang": language}
        )
        refs.append(
            {"id": str(item_id or item["uri"]), "uri": item["uri"], "label": text}
        )
    return refs


ACRONYM = re.compile(r"^\S{1,12}$")


def acronym(value):
    """Short code of a ``reference`` value from its alternative labels, the same in every language.

    Candidates are the alternative labels without whitespace of at most 12
    characters. The first candidate of the first language (by code) that every
    language carries wins, else the first English candidate, else the first
    candidate of the first language; None without candidates.
    """
    found = {}
    for item in _reference_items(value)[:1]:
        for entry in item.get("labels") or []:
            if not isinstance(entry, dict) or entry.get("valuetype_id") != "altLabel":
                continue
            text = entry.get("value")
            text = text.strip() if isinstance(text, str) else ""
            if ACRONYM.match(text):
                candidates = found.setdefault(entry.get("language_id") or "", [])
                if text not in candidates:
                    candidates.append(text)
    if not found:
        return None
    first = found[sorted(found)[0]]
    shared = [t for t in first if all(t in texts for texts in found.values())]
    return (shared or found.get(FALLBACK_LANGUAGE) or first)[0]


def reference_terms(value):
    """Every label of a ``reference`` value, preferred and alternative, in every language."""
    return {
        entry["value"]
        for item in _reference_items(value)
        for entry in item.get("labels") or []
        if isinstance(entry, dict)
        and isinstance(entry.get("value"), str)
        and entry["value"]
    }


def dataset_of(value):
    """``{"url", "isDoi", "label"}`` of a ``url`` value, trailing punctuation removed; None when empty."""
    if not isinstance(value, dict):
        return None
    url = (value.get("url") or "").strip().rstrip(".,;: ").strip()
    if not url:
        return None
    text = (value.get("url_label") or "").strip() or None
    return {
        "url": url,
        "isDoi": "doi.org/10." in url or url.startswith("10."),
        "label": text,
    }


DOI = re.compile(r"(10\.\d{4,9}/\S+)", re.IGNORECASE)


def doi_of(url):
    """The DOI *url* names (``10.…``, trailing punctuation removed), as written; None when it names none."""
    match = DOI.search(url or "")
    return match[1].rstrip(".,;:") if match else None


def dataset_url(dataset):
    """The one web address of *dataset* (a ``dataset_of`` value): ``https://doi.org/<doi>`` when it names a DOI, else its http(s) URL; None otherwise.

    Citations, the IIIF manifest and the data package read a dataset's
    address through this function alone.
    """
    url = (dataset or {}).get("url") or ""
    doi = doi_of(url)
    if doi:
        return f"https://doi.org/{doi}"
    return url if url.startswith(("http://", "https://")) else None


def rewrite_legacy_url(url):
    """*url* with a host of ``EXPLORER_LEGACY_HOSTS`` replaced by ``PUBLIC_SERVER_ADDRESS``."""
    for host in getattr(settings, "EXPLORER_LEGACY_HOSTS", ()):
        pattern = re.compile(rf"^https?://{re.escape(host)}(?::\d+)?/")
        if pattern.match(url or ""):
            return pattern.sub(settings.PUBLIC_SERVER_ADDRESS, url, count=1)
    return url


def _display(config):
    config = config or {}
    display = dict(config.get("display") or {})
    preset = XY_PRESETS.get(config.get("presetKey") or "")
    if preset:
        display.update((preset.get("config") or {}).get("display") or {})
    return display


def axis_key(config):
    """Comparison group of a renderer configuration (D8): canonical labels of its preset, else its own, and the direction of x."""
    display = _display(config)
    x = " ".join(str(display.get("xAxisLabel") or "").split()).casefold()
    y = " ".join(str(display.get("yAxisLabel") or "").split()).casefold()
    if not x and not y:
        return None
    return f"{y}|{x}|{'desc' if display.get('xReversed') else 'asc'}"


def axis_title(config):
    """``{"value", "lang"}`` naming the axes of a configuration (preset labels are English)."""
    display = _display(config)
    x, y = display.get("xAxisLabel"), display.get("yAxisLabel")
    if not x and not y:
        return None
    return {"value": " · ".join(t for t in (y, x) if t), "lang": FALLBACK_LANGUAGE}


_SCHEME = re.compile(r"^[a-z][a-z0-9+.-]*:", re.IGNORECASE)
_WEB_SCHEMES = ("http", "https")


def site_path(url):
    """*url* as a path on this site when it is local, an http(s) URL when it is external, else None.

    Local is a path, or an absolute URL on ``PUBLIC_SERVER_ADDRESS`` or on a
    host of ``EXPLORER_LEGACY_HOSTS``; a path without its leading slash gets
    one. Any other scheme (``javascript:``, ``data:``, ``ftp:``), a
    protocol-relative URL and a path a browser reads as another host
    (``/\\host``) give None.
    """
    url = rewrite_legacy_url(str(url or "").strip())
    if not url or url.startswith(("//", "\\", "/\\")):
        return None
    if not _SCHEME.match(url):
        return _local_path(url)
    public = settings.PUBLIC_SERVER_ADDRESS.rstrip("/")
    if public and (url == public or url.startswith(public + "/")):
        return _local_path(url[len(public) :])
    return url if urlsplit(url).scheme.lower() in _WEB_SCHEMES else None


def _local_path(path):
    path = "/" + path.lstrip("/")
    return None if path.startswith("/\\") else path


def file_entries(entries, *, language, configs, kind):
    """``FileEntry`` list of one file-list value (D39).

    A file with a renderer configuration is ``readable`` (a spectrum when
    *kind* is ``"measurement"``); an extension of ``RAW_INSTRUMENT_EXTENSIONS``
    is ``raw`` and is never parsed; anything else is ``other``. A raw file and
    a readable one sharing a base name (case ignored) point at each other.
    Micro-imaging files (*kind* ``"micro-imaging"``) carry that data kind.
    """
    raw_extensions = {e.lower() for e in settings.RAW_INSTRUMENT_EXTENSIONS}
    items = []
    for entry in entries if isinstance(entries, list) else []:
        if not isinstance(entry, dict) or not entry.get("file_id"):
            continue
        name = str(entry.get("name") or "")
        base, extension = os.path.splitext(name)
        config_id = entry.get("rendererConfig") or None
        role = (
            "readable"
            if config_id
            else "raw" if extension.lower() in raw_extensions else "other"
        )
        config = configs.get(config_id) if config_id else None
        if kind == "micro-imaging":
            data_kind = "micro-imaging"
        else:
            data_kind = "xy" if role == "readable" else "file"
        file_id = str(entry["file_id"])
        items.append(
            {
                "id": file_id,
                "name": name,
                "size": (
                    entry.get("size") if isinstance(entry.get("size"), int) else None
                ),
                "format": entry.get("type") or extension.lstrip(".").lower(),
                "role": role,
                "pairedWith": None,
                "dataKind": data_kind,
                "viewer": {
                    "rendererConfigId": config_id,
                    "xLabel": (
                        _display(config).get("xAxisLabel") or None if config else None
                    ),
                    "yLabel": (
                        _display(config).get("yAxisLabel") or None if config else None
                    ),
                    "axisKey": axis_key(config) if config else None,
                    "axisTitle": axis_title(config) if config else None,
                    "points": None,
                    "decimated": False,
                },
                "layers": [],
                "license": effective_license(entry, language),
                "downloadUrl": site_path(entry.get("url")) or "",
                "previewUrl": (
                    reverse("api-spectrum-preview", kwargs={"file_id": file_id})
                    if data_kind == "xy"
                    else None
                ),
                "zone": None,
                "_base": base.casefold(),
            }
        )
    readable = {i["_base"]: i for i in items if i["role"] == "readable"}
    raw = {i["_base"]: i for i in items if i["role"] == "raw"}
    for base in readable.keys() & raw.keys():
        readable[base]["pairedWith"] = raw[base]["id"]
        raw[base]["pairedWith"] = readable[base]["id"]
    for item in items:
        del item["_base"]
    return items


def _pixel(coordinate, width, height):
    box = BBoxCalculator.point_bbox(coordinate, width, height, radius=0)
    return (int(box[0]), int(box[1])) if box else None


def shape_of(geometry, width, height):
    """Contract ``Shape`` of an annotation geometry, in canvas pixels; None for an unknown or empty geometry.

    Coordinates are Arches' annotation space, converted by the project's
    ``BBoxCalculator``. A polygon of four axis-aligned corners is a ``rect``.
    """
    kind = (geometry or {}).get("type")
    coordinates = (geometry or {}).get("coordinates")
    if kind == "Point" and coordinates:
        point = _pixel(coordinates, width, height)
        return {"type": "point", "x": point[0], "y": point[1]} if point else None
    if kind == "Polygon" and coordinates and coordinates[0]:
        points = [p for p in (_pixel(c, width, height) for c in coordinates[0]) if p]
        if points and points[0] == points[-1]:
            points = points[:-1]
        xs, ys = {p[0] for p in points}, {p[1] for p in points}
        if len(points) == 4 and len(xs) == 2 and len(ys) == 2:
            return {
                "type": "rect",
                "x": min(xs),
                "y": min(ys),
                "w": max(xs) - min(xs),
                "h": max(ys) - min(ys),
            }
        return (
            {"type": "polygon", "points": [list(p) for p in points]} if points else None
        )
    return None
