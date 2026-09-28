"""The synthesis of a Selection for the Compare tools (spec §5 ``SynthesisResponse``, §9, D60).

The coverage matrix, the colours × materials table and the periodic table
are computed on the Selection's ``ExportScope`` (``resolve_scope``), with
the visitor's rights (D59), per request; nothing is memoised.

- The analyses are those of the scope (``an:``, ``af:`` and ``im:`` keys, an
  analysis once whatever its keys). The identified materials are those of
  its ``ch:`` keys plus the visible ones citing one of its analyses in
  evidence: a Selection of measurements brings the materials they support.
- Canvases are placed by the manifest's rule (``manifest._placements``):
  an analysis on every canvas of its document carrying one of its zones,
  an identified material on the canvas of its first zone
  (``iiif.facts.CharacterizationZones``). A canvas is labelled the same way
  wherever it appears: prefixed with its document's name when the placed
  canvases span several documents.
"""

import dataclasses
from collections import defaultdict

from manuspectrum.views.explorer.manifest import _placements
from manuspectrum.views.explorer.scopes import _documents
from manuspectrum.views.explorer.service import Values, qualified_values
from manuspectrum.views.explorer.values import element_symbols, value_refs

SYNTHESIS_ROLES = ["material", "confidence", "colour", "elements", "element_level"]


def synthesis_materials(scope):
    """The identified materials of *scope*'s synthesis, sorted: its own and the visible ones citing one of its analyses."""
    visible = scope.bundle.visible
    analyses = set(scope.analyses)
    citing = {
        c
        for c in visible.characterizations
        if analyses.intersection(visible.evidence.get(c, ()))
    }
    return tuple(sorted(set(scope.characterizations) | citing))


def _best(ranked):
    """The value of lowest rank among *ranked* (``RankedValue`` or None), else None."""
    found = [r for r in ranked if r]
    return min(found, key=lambda r: (r["rank"], r["id"])) if found else None


def _canvases(placements, bundle):
    """Every canvas an item of the scope is placed on, as ``{canvas, document, label}``, in document then page order.

    ``document`` is the id of the document whose manifest lists the canvas.
    """
    rows = [
        (placement.document, canvas, placement.position[canvas]["label"])
        for placement in placements
        for canvas in placement.kept
    ]
    several = len({document for document, *_ in rows}) > 1
    return [
        {
            "canvas": canvas,
            "document": str(document),
            "label": (
                f"{bundle.label_of[document]['value']} — {label}" if several else label
            ),
        }
        for document, canvas, label in rows
    ]


def _coverage(placements, canvases, bundle):
    """``(coverage rows, techniques)``: analyses per canvas and technique, in the order of *canvases*.

    A canvas is a row when an analysis with a technique is placed on it; it
    keeps its entry of *canvases* (``_canvases``) with the counts.
    """
    counted, techniques = {}, {}
    for placement in placements:
        for canvas in placement.kept:
            counts = defaultdict(int)
            for analysis_id in placement.analyses.get(canvas, ()):
                technique = bundle.by_id[analysis_id]["technique"]
                if technique:
                    counts[technique["id"]] += 1
                    techniques.setdefault(technique["id"], technique)
            if counts:
                counted[str(placement.document), canvas] = dict(counts)
    coverage = [
        {**entry, "counts": counted[entry["document"], entry["canvas"]]}
        for entry in canvases
        if (entry["document"], entry["canvas"]) in counted
    ]
    return coverage, _by_label(techniques.values())


def _by_label(techniques):
    """*techniques* sorted by label, then id."""
    return sorted(techniques, key=lambda t: (t["label"]["value"].casefold(), t["id"]))


def _material_techniques(materials, scope):
    """``{identified material: {technique id: technique}}``: the techniques of its evidence analyses in *scope*."""
    bundle, analyses = scope.bundle, set(scope.analyses)
    found = {}
    for c in materials:
        techniques = {}
        for a in analyses.intersection(bundle.visible.evidence.get(c, ())):
            technique = bundle.by_id[a]["technique"]
            if technique:
                techniques.setdefault(technique["id"], technique)
        found[c] = techniques
    return found


def _material_canvases(placements):
    """``({identified material: [canvas, …]}, {canvas: order})`` of the materials the placements put on a canvas."""
    canvases, order = defaultdict(list), {}
    for placement in placements:
        for canvas in placement.kept:
            order.setdefault(canvas, len(order))
            for c in placement.materials.get(canvas, ()):
                if canvas not in canvases[c]:
                    canvases[c].append(canvas)
    return canvases, order


def _pairs_and_elements(materials, canvases_of, techniques_of, order, reader, language):
    """``(pairs, elements)`` of the identified materials *materials*.

    A pair is one colour (None for a material without colour) × one
    material value; it gathers the identified materials carrying both, the
    union of their elements (with their symbol), their canvases, the
    techniques of their evidence analyses in scope (*techniques_of*), the
    best certainty of that material value and their number. An element is
    counted once per identified material naming its symbol, with the best
    level it is given; an element without a symbol is left out of
    ``elements`` (it stays in its pairs, ``symbol`` None).
    """
    values = Values(list(materials), SYNTHESIS_ROLES, reader)
    qualified = qualified_values(values, materials, language)
    pairs, symbols = {}, {}
    for c in materials:
        colours = {}
        for stored in values.get(c, "colour"):
            for ref in value_refs(stored, language):
                colours.setdefault(ref["id"], ref)
        elements = {}
        for refs, stored, level in qualified[c]["elements"]:
            for ref, symbol in zip(refs, element_symbols(stored)):
                elements.setdefault(ref["id"], {**ref, "symbol": symbol})
                if symbol:
                    entry = symbols.setdefault(
                        symbol, {"levels": [], "materials": set()}
                    )
                    entry["levels"].append(level)
                    entry["materials"].add(c)
        for refs, _, confidence in qualified[c]["material"]:
            for material in refs:
                for colour in list(colours.values()) or [None]:
                    key = (colour["id"] if colour else None, material["id"])
                    pair = pairs.setdefault(
                        key,
                        {
                            "colour": colour,
                            "material": material,
                            "elements": {},
                            "canvases": set(),
                            "techniques": {},
                            "confidences": [],
                            "materials": set(),
                        },
                    )
                    pair["confidences"].append(confidence)
                    pair["materials"].add(c)
                    pair["canvases"].update(canvases_of.get(c, ()))
                    pair["techniques"].update(techniques_of[c])
                    for element_id, element in elements.items():
                        pair["elements"].setdefault(element_id, element)
    shown_pairs = [
        {
            "colour": pair["colour"],
            "material": pair["material"],
            "elements": sorted(
                pair["elements"].values(),
                key=lambda e: (e["label"]["value"].casefold(), e["id"]),
            ),
            "canvases": sorted(pair["canvases"], key=order.__getitem__),
            "confidenceBest": _best(pair["confidences"]),
            "count": len(pair["materials"]),
            "techniques": [t["id"] for t in _by_label(pair["techniques"].values())],
        }
        for pair in pairs.values()
    ]
    shown_pairs.sort(
        key=lambda p: (
            -p["count"],
            p["material"]["label"]["value"].casefold(),
            p["colour"] is None,
            p["colour"]["label"]["value"].casefold() if p["colour"] else "",
            p["material"]["id"],
            p["colour"]["id"] if p["colour"] else "",
        )
    )
    shown_elements = sorted(
        (
            {
                "symbol": symbol,
                "level": _best(entry["levels"]),
                "count": len(entry["materials"]),
            }
            for symbol, entry in symbols.items()
        ),
        key=lambda e: (-e["count"], e["symbol"]),
    )
    return shown_pairs, shown_elements


def synthesis_payload(scope):
    """``SynthesisResponse`` of the Selection *scope* (an ``ids`` scope from ``resolve_scope``).

    ``canvases`` lists every canvas an analysis (with or without technique)
    or identified material of the synthesis is placed on, ``coverage``
    counts the scope's analyses per canvas and technique, ``techniques``
    lists the techniques it counts by label, ``pairs`` and
    ``elements`` describe the identified materials of ``synthesis_materials``
    (most frequent first), ``unpublishedCount`` counts the analyses and
    identified materials in a Draft state.
    """
    bundle = scope.bundle
    materials = synthesis_materials(scope)
    placed = dataclasses.replace(
        scope,
        characterizations=materials,
        documents=_documents(bundle, scope.analyses, materials),
    )
    placements = list(_placements(placed, bounded=False))
    canvases = _canvases(placements, bundle)
    coverage, techniques = _coverage(placements, canvases, bundle)
    canvases_of, order = _material_canvases(placements)
    pairs, elements = _pairs_and_elements(
        materials,
        canvases_of,
        _material_techniques(materials, scope),
        order,
        scope.reader,
        scope.language,
    )
    return {
        "coverage": coverage,
        "canvases": canvases,
        "techniques": techniques,
        "pairs": pairs,
        "elements": elements,
        "unpublishedCount": len(
            (set(scope.analyses) | set(materials)) & bundle.visible.unpublished
        ),
    }
