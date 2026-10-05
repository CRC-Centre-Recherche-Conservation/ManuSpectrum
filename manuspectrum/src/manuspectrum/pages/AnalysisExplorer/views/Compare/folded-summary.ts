import type {
    AutoWindow,
    MapLine,
} from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/windows.ts";

/**
 * What a folded window says under its header: how many spectra or maps it
 * holds, the slots they come from (in order, once each) and the names that
 * tell them apart: the technique codes of the spectra, every distinct layer
 * label met across the maps, in the order met.
 */
export interface FoldedSummary {
    kind: "xy" | "maps";
    count: number;
    slots: number[];
    names: string[];
}

function sortedSlots(slots: readonly number[]): number[] {
    return [...new Set(slots)].sort((a, b) => a - b);
}

/** Every distinct layer label of `maps`, in the order first met. */
function layerNames(maps: readonly MapLine[]): string[] {
    const seen = new Set<string>();
    for (const line of maps) {
        for (const layer of line.file.layers) seen.add(layer.label);
    }
    return [...seen];
}

/** The summary of a window that folds; null for the others. */
export function foldedSummary(window: AutoWindow): FoldedSummary | null {
    if (window.kind === "xy") {
        const codes = window.curves.flatMap((curve) =>
            curve.analysis.technique ? [curve.analysis.technique.code] : [],
        );
        return {
            kind: "xy",
            count: window.curves.length,
            slots: sortedSlots(window.curves.map((curve) => curve.slot)),
            names: [...new Set(codes)],
        };
    }
    if (window.kind === "chemical-imaging") {
        return {
            kind: "maps",
            count: window.maps.length,
            slots: sortedSlots(window.maps.map((line) => line.slot)),
            names: layerNames(window.maps),
        };
    }
    return null;
}
