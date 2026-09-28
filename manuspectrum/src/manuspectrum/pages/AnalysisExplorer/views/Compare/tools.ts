import type {
    DocumentPayload,
    Label,
    Shape,
    SynthesisCanvas,
    SynthesisResponse,
    Technique,
} from "@/manuspectrum/pages/AnalysisExplorer/api/types.ts";
import type {
    BasketItem,
    ToolKind,
} from "@/manuspectrum/pages/AnalysisExplorer/store/types.ts";

/** The tools « + Tool » offers, in its order. */
export const OFFERED_TOOLS: readonly ToolKind[] = [
    "coverage",
    "colour-material",
    "periodic",
    "folio",
];

/** The canvases the folio image offers: those an item of the Selection itself is placed on. */
export function folioCanvases(synthesis: SynthesisResponse): SynthesisCanvas[] {
    return synthesis.canvases.filter((entry) => entry.selected);
}

/** The tools the synthesis has something for: the coverage matrix a counted canvas, the folio image a canvas holding a Selection item, the others a pair or an element. */
export function offeredTools(synthesis: SynthesisResponse): ToolKind[] {
    const holds: Record<ToolKind, boolean> = {
        coverage: synthesis.coverage.length > 0,
        "colour-material": synthesis.pairs.length > 0,
        periodic: synthesis.elements.length > 0,
        folio: folioCanvases(synthesis).length > 0,
    };
    return OFFERED_TOOLS.filter((kind) => holds[kind]);
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
