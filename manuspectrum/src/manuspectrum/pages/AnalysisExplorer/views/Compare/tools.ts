import type {
    DocumentPayload,
    Label,
    Shape,
    SynthesisCoverage,
    SynthesisElement,
    SynthesisPair,
    SynthesisResponse,
    Technique,
} from "@/manuspectrum/pages/AnalysisExplorer/api/types.ts";
import type {
    BasketItem,
    ToolFilters,
    ToolKind,
} from "@/manuspectrum/pages/AnalysisExplorer/store/types.ts";

/** The tools « + Tool » offers, in its order. */
export type OfferedTool = Exclude<ToolKind, "analysis-list">;

export const OFFERED_TOOLS: readonly OfferedTool[] = [
    "coverage",
    "colour-material",
    "periodic",
    "folio",
];

export type FilterKey = keyof ToolFilters;

/** The filter each cross-filtered tool sets. */
export const OWN_FILTER: Partial<Record<ToolKind, FilterKey>> = {
    coverage: "cell",
    "colour-material": "pair",
    periodic: "element",
};

const FILTER_ORDER: readonly FilterKey[] = ["element", "cell", "pair"];

/** What a tool shows of the synthesis. */
export interface ToolView {
    coverage: SynthesisCoverage[];
    pairs: SynthesisPair[];
    elements: SynthesisElement[];
}

/** The tools the synthesis has something for: the coverage matrix and the folio image need a canvas, the others a pair or an element. */
export function offeredTools(synthesis: SynthesisResponse): OfferedTool[] {
    const holds: Record<OfferedTool, boolean> = {
        coverage: synthesis.coverage.length > 0,
        "colour-material": synthesis.pairs.length > 0,
        periodic: synthesis.elements.length > 0,
        folio: synthesis.coverage.length > 0,
    };
    return OFFERED_TOOLS.filter((kind) => holds[kind]);
}

/** The filters set by the other cross-filtered tools, which restrict `kind`; none for a tool outside the three. */
export function restrictingFilters(
    kind: ToolKind,
    filters: ToolFilters,
): FilterKey[] {
    const own = OWN_FILTER[kind];
    if (!own) return [];
    return FILTER_ORDER.filter((key) => key !== own && filters[key] !== null);
}

function isPair(
    pair: SynthesisPair,
    [colour, material]: [string | null, string],
): boolean {
    return (
        (pair.colour?.id ?? null) === colour && pair.material.id === material
    );
}

/** The pairs the filters `keys` of `filters` keep: naming the element, on the cell's canvas, the pair itself. */
function pairsKept(
    pairs: readonly SynthesisPair[],
    filters: ToolFilters,
    keys: readonly FilterKey[],
): SynthesisPair[] {
    const { element, cell, pair: chosen } = filters;
    return pairs.filter(
        (pair) =>
            (!keys.includes("element") ||
                element === null ||
                pair.elements.some((entry) => entry.symbol === element)) &&
            (!keys.includes("cell") ||
                cell === null ||
                pair.canvases.includes(cell[0])) &&
            (!keys.includes("pair") || chosen === null || isPair(pair, chosen)),
    );
}

/**
 * What `kind` shows under the filters of the other two tools, never its
 * own. The filters restrict through the identified materials: an element
 * keeps the pairs naming it, a cell the pairs placed on its canvas (the
 * technique of the cell names the cell only), a pair itself. The coverage
 * matrix keeps the canvases of the pairs kept, the periodic table their
 * elements.
 */
export function toolView(
    synthesis: SynthesisResponse,
    filters: ToolFilters,
    kind: ToolKind,
): ToolView {
    const keys = restrictingFilters(kind, filters);
    const all: ToolView = {
        coverage: synthesis.coverage,
        pairs: synthesis.pairs,
        elements: synthesis.elements,
    };
    if (keys.length === 0) return all;
    const kept = pairsKept(synthesis.pairs, filters, keys);
    if (kind === "coverage") {
        const canvases = new Set(kept.flatMap((pair) => pair.canvases));
        return {
            ...all,
            coverage: synthesis.coverage.filter((row) =>
                canvases.has(row.canvas),
            ),
        };
    }
    if (kind === "periodic") {
        const symbols = new Set(
            kept.flatMap((pair) => pair.elements.map((entry) => entry.symbol)),
        );
        return {
            ...all,
            elements: synthesis.elements.filter((entry) =>
                symbols.has(entry.symbol),
            ),
        };
    }
    return { ...all, pairs: kept };
}

/** The filters naming what the synthesis no longer holds (the Selection changed). */
export function staleToolFilters(
    synthesis: SynthesisResponse,
    filters: ToolFilters,
): FilterKey[] {
    const { element, cell, pair } = filters;
    const stale: FilterKey[] = [];
    if (
        element !== null &&
        !synthesis.elements.some((entry) => entry.symbol === element)
    ) {
        stale.push("element");
    }
    if (
        cell !== null &&
        !synthesis.coverage.some(
            (row) => row.canvas === cell[0] && (row.counts[cell[1]] ?? 0) > 0,
        )
    ) {
        stale.push("cell");
    }
    if (
        pair !== null &&
        !synthesis.pairs.some((entry) => isPair(entry, pair))
    ) {
        stale.push("pair");
    }
    return stale;
}

/** The labels a filter is named by: an element's symbol; a cell's canvas and technique; a pair's colour (when stated) and material. */
export function filterParts(
    synthesis: SynthesisResponse,
    filters: ToolFilters,
    key: FilterKey,
): string[] {
    if (key === "element") return filters.element ? [filters.element] : [];
    if (key === "cell") {
        if (!filters.cell) return [];
        const [canvas, technique] = filters.cell;
        return [
            synthesis.coverage.find((row) => row.canvas === canvas)?.label ??
                canvas,
            synthesis.techniques.find((entry) => entry.id === technique)?.label
                .value ?? technique,
        ];
    }
    const chosen = filters.pair;
    if (!chosen) return [];
    const found = synthesis.pairs.find((entry) => isPair(entry, chosen));
    if (!found) return [];
    return found.colour
        ? [found.colour.label.value, found.material.label.value]
        : [found.material.label.value];
}

/** The slots (0-based, in order) of each analysis and identified material of the Selection, by resource id. */
export function selectionSlots(
    basket: readonly BasketItem[],
): Map<string, number[]> {
    const slots = new Map<string, number[]>();
    for (const { key, slot } of basket) {
        const id = key.split(":")[1];
        slots.set(id, [...(slots.get(id) ?? []), slot]);
    }
    for (const [id, list] of slots)
        slots.set(
            id,
            list.sort((a, b) => a - b),
        );
    return slots;
}

/** A Selection item placed on the folio image: its zones on the canvas shown. */
export interface FolioMark {
    id: string;
    kind: "analysis" | "characterization";
    slots: number[];
    name: Label;
    technique: Technique | null;
    shapes: Shape[];
}

/**
 * The analyses and identified materials of the Selection (`slots`, by id)
 * that `payload` places on `canvas`: an analysis by its zones on that page,
 * an identified material by its zone; by first slot.
 */
export function folioMarks(
    payload: DocumentPayload,
    canvas: string,
    slots: ReadonlyMap<string, readonly number[]>,
): FolioMark[] {
    const position = payload.canvases.findIndex((entry) => entry.id === canvas);
    if (position < 0) return [];
    const marks: FolioMark[] = [];
    for (const analysis of payload.analyses) {
        const held = slots.get(analysis.id);
        const shapes = analysis.zones
            .filter((zone) => zone.canvas === position)
            .map((zone) => zone.shape);
        if (!held || shapes.length === 0) continue;
        marks.push({
            id: analysis.id,
            kind: "analysis",
            slots: [...held],
            name: analysis.name,
            technique:
                analysis.technique === null
                    ? null
                    : payload.techniques[analysis.technique] ?? null,
            shapes,
        });
    }
    for (const summary of payload.characterizations) {
        const held = slots.get(summary.id);
        if (!held || summary.zone?.canvas !== canvas) continue;
        marks.push({
            id: summary.id,
            kind: "characterization",
            slots: [...held],
            name: summary.name,
            technique: null,
            shapes: [summary.zone.shape],
        });
    }
    return marks.sort((a, b) => a.slots[0] - b.slots[0]);
}
