import type {
    AutoWindow,
    FileLine,
    MapLine,
} from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/windows.ts";

/**
 * What a folded window says under its header: how many spectra or maps it
 * holds, the slots they come from (in order, once each), the colour index of
 * each slot (`colours`, parallel to `slots`: the order of its first drawn
 * curve in the window for spectra, so the chip matches the workshop; the slot
 * itself for maps) and the names that
 * tell them apart: the technique codes of the spectra, every distinct layer
 * label met across the maps, in the order met.
 */
export interface FoldedSummary {
    kind: "xy" | "maps";
    count: number;
    slots: number[];
    colours: number[];
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

/**
 * The colour index of each slot of `curves` (sorted), as `XyWorkshop` orders
 * them: the position of the slot's first curve with a preview among the
 * curves with a preview, else the count of those met before its first curve.
 */
function spectraColours(
    curves: readonly FileLine[],
    slots: readonly number[],
): number[] {
    const first = new Map<number, { order: number; drawn: boolean }>();
    let drawn = 0;
    for (const curve of curves) {
        const readable = curve.file.previewUrl !== null;
        const known = first.get(curve.slot);
        if (!known || (readable && !known.drawn)) {
            first.set(curve.slot, { order: drawn, drawn: readable });
        }
        if (readable) drawn += 1;
    }
    return slots.map((slot) => first.get(slot)?.order ?? 0);
}

/** The summary of a window that folds; null for the others. */
export function foldedSummary(window: AutoWindow): FoldedSummary | null {
    if (window.kind === "xy") {
        const codes = window.curves.flatMap((curve) =>
            curve.analysis.technique ? [curve.analysis.technique.code] : [],
        );
        const slots = sortedSlots(window.curves.map((curve) => curve.slot));
        return {
            kind: "xy",
            count: window.curves.length,
            slots,
            colours: spectraColours(window.curves, slots),
            names: [...new Set(codes)],
        };
    }
    if (window.kind === "chemical-imaging") {
        const slots = sortedSlots(window.maps.map((line) => line.slot));
        return {
            kind: "maps",
            count: window.maps.length,
            slots,
            colours: slots,
            names: layerNames(window.maps),
        };
    }
    return null;
}
