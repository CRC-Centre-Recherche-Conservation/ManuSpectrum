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
  (``iiif.facts.CharacterizationZones``). A canvas is labelled once
  (``_canvas_labels``) for every part of the payload naming it. A canvas is
  ``selected`` when an item of the Selection itself (one of its analyses or
  ``ch:`` materials) is placed on it; a canvas carrying only materials that
  cite its analyses is not.
- Every aggregate names the ids it gathers (canvases, pairs, elements,
  ``materials``), so the client links them without another request.
"""

import dataclasses
from collections import Counter, defaultdict

from django.utils import translation
from django.utils.translation import gettext as _

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


def _canvas_labels(rows, bundle):
    """``{(document, canvas): label}`` of the ``(document, canvas, placement)`` *rows*: the one rule naming a canvas in the payload.

    A canvas takes its manifest label, prefixed with its document's name
    when *rows* span several documents; a label that several rows share is
    followed by the canvas's 1-based position in its document's manifest
    (« f. · view 23 »), in the active language.
    """
    several = len({row[0] for row in rows}) > 1
    named = {
        (document, canvas): (
            f"{bundle.label_of[document]['value']} — {placement.position[canvas]['label']}"
            if several
            else placement.position[canvas]["label"]
        )
        for document, canvas, placement in rows
    }
    shared = Counter(named.values())
    return {
        (document, canvas): (
            _("%(label)s · view %(number)s")
            % {
                "label": named[document, canvas],
                "number": placement.number[canvas],
            }
            if shared[named[document, canvas]] > 1
            else named[document, canvas]
        )
        for document, canvas, placement in rows
    }


def _canvases(placements, bundle, own):
    """Every canvas an item of the synthesis is placed on, as ``SynthesisCanvas``, in document then page order.

    ``document`` is the id of the document whose manifest lists the canvas;
    ``analyses`` and ``materials`` are the ids of the analyses (all of the
    scope) and identified materials the placements put on it; ``selected``
    is true when one of those analyses or one of the identified materials
    *own* (the Selection's ``ch:`` keys) is among them.
    """
    rows = [
        (placement.document, canvas, placement)
        for placement in placements
        for canvas in placement.kept
    ]
    labels = _canvas_labels(rows, bundle)
    canvases = []
    for document, canvas, placement in rows:
        analyses = sorted(placement.analyses.get(canvas, ()))
        materials = sorted(placement.materials.get(canvas, ()))
        canvases.append(
            {
                "canvas": canvas,
                "document": str(document),
                "label": labels[document, canvas],
                "selected": bool(analyses) or not own.isdisjoint(materials),
                "analyses": analyses,
                "materials": materials,
            }
        )
    return canvases


def _coverage(placements, canvases, bundle):
    """``(coverage rows, techniques)``: analyses per canvas and technique, in the order of *canvases*.

    A canvas is a row when an analysis with a technique is placed on it; it
    keeps the canvas, label and document of its entry of *canvases*
    (``_canvases``) with the counts.
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
        {
            "canvas": entry["canvas"],
            "label": entry["label"],
            "document": entry["document"],
            "counts": counted[entry["document"], entry["canvas"]],
        }
        for entry in canvases
        if (entry["document"], entry["canvas"]) in counted
    ]
    return coverage, _by_label(techniques.values())


def _by_label(techniques):
    """*techniques* sorted by label, then id."""
    return sorted(techniques, key=lambda t: (t["label"]["value"].casefold(), t["id"]))


def _material_evidence(materials, scope):
    """``{identified material: [analysis id, …]}``: its evidence analyses in *scope*, sorted."""
    evidence, analyses = scope.bundle.visible.evidence, set(scope.analyses)
    return {c: sorted(analyses.intersection(evidence.get(c, ()))) for c in materials}


def _material_cells(materials, evidence_of, canvases_of, bundle):
    """``{identified material: {(canvas, technique id): technique}}``: its canvases × the techniques of its evidence *evidence_of*."""
    cells = {}
    for c in materials:
        techniques = {}
        for a in evidence_of[c]:
            technique = bundle.by_id[a]["technique"]
            if technique:
                techniques.setdefault(technique["id"], technique)
        cells[c] = {
            (canvas, technique_id): technique
            for canvas in canvases_of.get(c, ())
            for technique_id, technique in techniques.items()
        }
    return cells


def _sorted_cells(cells, order):
    """The ``{(canvas, technique id): technique}`` *cells* as ``[canvas, technique id]``, by canvas *order*, then technique label."""
    return [
        [canvas, technique_id]
        for (canvas, technique_id), _technique in sorted(
            cells.items(),
            key=lambda cell: (
                order[cell[0][0]],
                cell[1]["label"]["value"].casefold(),
                cell[0][1],
            ),
        )
    ]


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


def _pairs_and_elements(materials, canvases_of, cells_of, order, reader, language):
    """``(pairs, elements)`` of the identified materials *materials*.

    A pair is one colour (None for a material without colour) × one
    material value; it gathers the identified materials carrying both (their
    ids and number), the union of their elements (with their symbol), their
    canvases, their cells (the union of each material's *cells_of*; by
    canvas, then technique label) and the best certainty of that material
    value. An element is counted once per identified material naming its
    symbol, with the best level it is given and those materials' ids; an
    element without a symbol is left out of ``elements`` (it stays in its
    pairs, ``symbol`` None).
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
                            "cells": {},
                            "confidences": [],
                            "materials": set(),
                        },
                    )
                    pair["confidences"].append(confidence)
                    pair["materials"].add(c)
                    pair["canvases"].update(canvases_of.get(c, ()))
                    pair["cells"].update(cells_of[c])
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
            "cells": _sorted_cells(pair["cells"], order),
            "materials": sorted(pair["materials"]),
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
                "materials": sorted(entry["materials"]),
            }
            for symbol, entry in symbols.items()
        ),
        key=lambda e: (-e["count"], e["symbol"]),
    )
    return shown_pairs, shown_elements


def _material_entries(materials, evidence_of, canvases_of, cells_of, order, bundle):
    """``SynthesisMaterial`` of each identified material of *materials*, in their order.

    ``objects`` are its visible objects observed (documents and components).
    """
    shown = bundle.visible.documents | bundle.visible.components
    objects_of = bundle.links["objects"]
    return [
        {
            "id": c,
            "evidence": evidence_of[c],
            "canvases": canvases_of.get(c, []),
            "cells": _sorted_cells(cells_of[c], order),
            "objects": sorted(shown.intersection(objects_of.get(c, ()))),
        }
        for c in materials
    ]


def synthesis_payload(scope):
    """``SynthesisResponse`` of the Selection *scope* (an ``ids`` scope from ``resolve_scope``).

    ``canvases`` lists every canvas an analysis (with or without technique)
    or identified material of the synthesis is placed on, marked
    ``selected`` when an item of the Selection itself is, ``coverage``
    counts the scope's analyses per canvas and technique, ``techniques``
    lists the techniques it counts by label, ``pairs`` and
    ``elements`` describe the identified materials of ``synthesis_materials``
    (most frequent first), ``materials`` lists those materials with the ids
    they link, ``unpublishedCount`` counts the analyses and identified
    materials in a Draft state. Labels are in ``scope.language``.
    """
    bundle = scope.bundle
    materials = synthesis_materials(scope)
    placed = dataclasses.replace(
        scope,
        characterizations=materials,
        documents=_documents(bundle, scope.analyses, materials),
    )
    placements = list(_placements(placed, bounded=False))
    with translation.override(scope.language):
        canvases = _canvases(placements, bundle, set(scope.characterizations))
    coverage, techniques = _coverage(placements, canvases, bundle)
    canvases_of, order = _material_canvases(placements)
    evidence_of = _material_evidence(materials, scope)
    cells_of = _material_cells(materials, evidence_of, canvases_of, bundle)
    pairs, elements = _pairs_and_elements(
        materials, canvases_of, cells_of, order, scope.reader, scope.language
    )
    return {
        "coverage": coverage,
        "canvases": canvases,
        "techniques": techniques,
        "pairs": pairs,
        "elements": elements,
        "materials": _material_entries(
            materials, evidence_of, canvases_of, cells_of, order, bundle
        ),
        "unpublishedCount": len(
            (set(scope.analyses) | set(materials)) & bundle.visible.unpublished
        ),
    }
