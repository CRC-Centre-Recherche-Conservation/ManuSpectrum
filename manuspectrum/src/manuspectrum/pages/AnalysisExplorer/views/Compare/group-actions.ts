import {
    PANE_COUNT,
    place,
    setLayout,
} from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/light-table.ts";

import type { TableState } from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/light-table.ts";
import type { MapLine } from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/windows.ts";

/**
 * Lays the first canvases of a gallery group (at most `PANE_COUNT`) in the
 * panes from A: one in the target pane, two on a grid of two, three or four
 * on a grid of four. Panes left over are filled from the Selection, never
 * with a canvas already laid.
 */
export function layGroup(
    state: TableState,
    canvases: readonly string[],
    maps: readonly MapLine[],
): TableState {
    const ids = canvases.slice(0, PANE_COUNT);
    if (ids.length === 0) return state;
    if (ids.length === 1) return place(state, ids[0]);
    const panes: (string | null)[] = Array(PANE_COUNT).fill(null);
    ids.forEach((canvas, pane) => {
        panes[pane] = canvas;
    });
    return {
        ...setLayout(
            { ...state, panes, active: 0 },
            ids.length === 2 ? "grid2" : "grid4",
            maps,
        ),
    };
}
