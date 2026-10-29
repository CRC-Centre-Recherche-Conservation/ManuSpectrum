import {
    linkedGroups,
    type TableState,
} from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/light-table.ts";

import type { MapLine } from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/windows.ts";

/** A canvas size as the image service serves it, in pixels. */
export interface ServedSize {
    w: number;
    h: number;
}

/** « Not the same scale »: `canvas` is served at `size`, `against` at `againstSize`. */
export interface ScaleNote {
    canvas: string;
    size: ServedSize;
    against: string;
    againstSize: ServedSize;
}

export function sameSize(a: ServedSize, b: ServedSize): boolean {
    return a.w === b.w && a.h === b.h;
}

/**
 * The canvases shown together that are not served at the same size, by
 * canvas id: the panes of the synced group (`syncViews`, against its first),
 * the two sides of a curtain (against pane A) and the layers of a stack
 * (against the first shown). Nothing is said while a size of the pair is not
 * read.
 */
export function scaleNotes(
    state: TableState,
    maps: readonly MapLine[],
    sizes: ReadonlyMap<string, ServedSize | null>,
): Map<string, ScaleNote> {
    const notes = new Map<string, ScaleNote>();
    const compare = (reference: string, canvas: string): void => {
        const against = sizes.get(reference);
        const size = sizes.get(canvas);
        if (!against || !size || sameSize(size, against)) return;
        notes.set(canvas, {
            canvas,
            size,
            against: reference,
            againstSize: against,
        });
    };
    if (state.layout === "curtain") {
        const [a, b] = state.panes;
        if (a !== null && b !== null) compare(a, b);
    } else if (state.layout === "stack") {
        const shown = state.stack.layers.filter((layer) => layer.on);
        for (const layer of shown.slice(1)) {
            compare(shown[0].canvas, layer.canvas);
        }
    } else {
        for (const group of linkedGroups(state, maps)) {
            const [first, ...rest] = group.map((pane) => state.panes[pane]);
            for (const canvas of rest) {
                if (first !== null && canvas !== null) compare(first, canvas);
            }
        }
    }
    return notes;
}
