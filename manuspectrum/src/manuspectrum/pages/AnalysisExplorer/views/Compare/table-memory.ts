import {
    defaultState,
    reconcile,
} from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/light-table.ts";

import type {
    StoredImaging,
    TableState,
} from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/light-table.ts";
import type { MapLine } from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/windows.ts";

/**
 * What of the table the browser keeps: not the target pane, nor zoom, pan or
 * the curtain's position; the reader's choice about the gallery (`gallery`)
 * only once made.
 */
export function storedOf(
    state: TableState,
    gallery: boolean | null = null,
): StoredImaging {
    const { layout, panes, syncViews, filters, stack, grouping } = state;
    return {
        layout,
        panes,
        syncViews,
        filters,
        stack,
        grouping,
        ...(gallery === null ? {} : { gallery }),
    };
}

/**
 * The table a reader left, reconciled with the Selection (canvases no longer
 * held are dropped, empty panes refilled). The default table when nothing
 * was stored or none of the stored canvases is still held.
 */
export function restoreState(
    stored: StoredImaging | undefined,
    maps: readonly MapLine[],
): TableState {
    if (!stored) return defaultState(maps);
    const held = new Set(
        maps.flatMap((line) => line.file.layers.map((layer) => layer.id)),
    );
    const survives =
        stored.panes.some((pane) => pane !== null && held.has(pane)) ||
        stored.stack.layers.some((layer) => held.has(layer.canvas));
    if (!survives) return defaultState(maps);
    return reconcile({ ...stored, active: 0 }, maps);
}
