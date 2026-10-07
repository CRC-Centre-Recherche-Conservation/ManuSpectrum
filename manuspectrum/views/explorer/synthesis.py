"""The synthesis of a Selection for the Compare tools (spec §5 ``SynthesisResponse``, §9, D60).

The coverage matrix, the colour × material groups of the Materials window,
the periodic table and the linked selection's graph are computed on the
Selection's ``ExportScope`` (``resolve_scope``), with the visitor's rights
(D59), per request; nothing is memoised.

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
- A coverage row is split by the component its analyses observe; each
  identified material carries its ``CharacterizationSummary``
  (``characterization_summaries``, one call for all of them).
"""

import dataclasses
from collections import Counter, defaultdict

from django.utils import translation
from django.utils.translation import gettext as _

from manuspectrum.views.explorer.manifest import _placements
from manuspectrum.views.explorer.scopes import _documents
from manuspectrum.views.explorer.service import (
    Values,
    _ref,
    characterization_summaries,
    fold,
    qualified_values,
)
from manuspectrum.views.explorer.swatches import colour_refs
from manuspectrum.views.explorer.values import element_symbols

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
    (``_canvases``) with the counts. ``components`` splits those counts by
    the component each analysis observes (its corpus row's ``component``,
    None for an analysis of the folio itself); their counts sum to the
    row's. Within a row, None comes first, then the components by the first
    row of the payload they appear in, then name and id.
    """
    counted, techniques = {}, {}
    for placement in placements:
        for canvas in placement.kept:
            counts = defaultdict(lambda: defaultdict(int))
            for analysis_id in placement.analyses.get(canvas, ()):
                row = bundle.by_id[analysis_id]
                technique = row["technique"]
                if technique:
                    counts[row["component"]][technique["id"]] += 1
                    techniques.setdefault(technique["id"], technique)
            if counts:
                counted[str(placement.document), canvas] = counts
    rows = [
        (entry, counted[entry["document"], entry["canvas"]])
        for entry in canvases
        if (entry["document"], entry["canvas"]) in counted
    ]
    first = {}
    for index, (_entry, by_component) in enumerate(rows):
        for component in by_component:
            first.setdefault(component, index)

    def component_order(component):
        if component is None:
            return (0, 0, "", "")
        name = bundle.label_of[component]["value"]
        return (1, first[component], fold(name), component)

    coverage = []
    for entry, by_component in rows:
        total = Counter()
        for counts in by_component.values():
            total.update(counts)
        coverage.append(
            {
                "canvas": entry["canvas"],
                "label": entry["label"],
                "document": entry["document"],
                "counts": dict(total),
                "components": [
                    {
                        "component": (
                            _ref(component, "component", bundle.label_of)
                            if component
                            else None
                        ),
                        "counts": dict(by_component[component]),
                    }
                    for component in sorted(by_component, key=component_order)
                ],
            }
        )
    return coverage, _by_label(techniques.values())


def _by_label(techniques):
    """*techniques* sorted by label, then id."""
    return sorted(techniques, key=lambda t: (t["label"]["value"].casefold(), t["id"]))


def _material_evidence(materials, scope):
    """``{identified material: [analysis id, …]}``: its evidence analyses in *scope*, sorted."""
    evidence, analyses = scope.bundle.visible.evidence, set(scope.analyses)
    return {c: sorted(analyses.intersection(evidence.get(c, ()))) for c in materials}


def _material_canvases(placements):
    """``{identified material: [canvas, …]}``: the canvases the placements put each material on, in their order."""
    canvases = defaultdict(list)
    for placement in placements:
        for canvas in placement.kept:
            for c in placement.materials.get(canvas, ()):
                if canvas not in canvases[c]:
                    canvases[c].append(canvas)
    return canvases


def _pairs_and_elements(materials, reader, language):
    """``(pairs, elements)`` of the identified materials *materials*.

    A pair is one colour (None for a material without colour) × one
    material value; it gathers the identified materials carrying both (their
    ids and number) and the union of their elements (with their symbol).
    An element is counted once per identified material naming its symbol, with the best level it is given and those materials' ids; an
    element without a symbol is left out of ``elements`` (it stays in its
    pairs, ``symbol`` None).
    """
    values = Values(list(materials), SYNTHESIS_ROLES, reader)
    qualified = qualified_values(values, materials, language)
    pairs, symbols = {}, {}
    for c in materials:
        colours = {}
        for stored in values.get(c, "colour"):
            for ref in colour_refs(stored, language):
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
        for refs, _, _confidence in qualified[c]["material"]:
            for material in refs:
                for colour in list(colours.values()) or [None]:
                    key = (colour["id"] if colour else None, material["id"])
                    pair = pairs.setdefault(
                        key,
                        {
                            "colour": colour,
                            "material": material,
                            "elements": {},
                            "materials": set(),
                        },
                    )
                    pair["materials"].add(c)
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
            "count": len(pair["materials"]),
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


def _material_entries(scope, materials, evidence_of, canvases_of):
    """``SynthesisMaterial`` of each identified material of *materials*, in their order.

    ``objects`` are its visible objects observed (documents and components).
    ``summary`` is its ``CharacterizationSummary`` as the items payload gives
    it for a ``ch:`` key (``zone`` None), read with the scope's reader in one
    ``characterization_summaries`` call; ``selected`` says it is a ``ch:``
    item of the Selection itself rather than only citing one of its analyses.
    """
    bundle = scope.bundle
    shown = bundle.visible.documents | bundle.visible.components
    objects_of = bundle.links["objects"]
    own = set(scope.characterizations)
    summary_of = {
        s["id"]: s
        for s in characterization_summaries(
            materials,
            bundle.visible,
            scope.reader,
            scope.language,
            objects_of=objects_of,
            analysis_rows=bundle.by_id,
        )
    }
    return [
        {
            "id": c,
            "evidence": evidence_of[c],
            "canvases": canvases_of.get(c, []),
            "objects": sorted(shown.intersection(objects_of.get(c, ()))),
            "summary": summary_of[c],
            "selected": c in own,
        }
        for c in materials
    ]


def synthesis_payload(scope):
    """``SynthesisResponse`` of the Selection *scope* (an ``ids`` scope from ``resolve_scope``).

    ``canvases`` lists every canvas an analysis (with or without technique)
    or identified material of the synthesis is placed on, marked
    ``selected`` when an item of the Selection itself is, ``coverage``
    counts the scope's analyses per canvas and technique, split by
    component, ``techniques`` lists the techniques it counts by label,
    ``pairs`` and
    ``elements`` describe the identified materials of ``synthesis_materials``
    (most frequent first), ``materials`` lists those materials with the ids
    they link and their summary, ``unpublishedCount`` counts the analyses and identified
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
    canvases_of = _material_canvases(placements)
    evidence_of = _material_evidence(materials, scope)
    pairs, elements = _pairs_and_elements(materials, scope.reader, scope.language)
    return {
        "coverage": coverage,
        "canvases": canvases,
        "techniques": techniques,
        "pairs": pairs,
        "elements": elements,
        "materials": _material_entries(scope, materials, evidence_of, canvases_of),
        "unpublishedCount": len(
            (set(scope.analyses) | set(materials)) & bundle.visible.unpublished
        ),
    }
