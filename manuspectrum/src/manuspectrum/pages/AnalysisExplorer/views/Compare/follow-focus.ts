import { PANES_SHOWN } from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/light-table.ts";

import type { FileLayer } from "@/manuspectrum/pages/AnalysisExplorer/api/types.ts";
import type { TableState } from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/light-table.ts";
import type { MapLine } from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/windows.ts";

function carries(layer: FileLayer, symbol: string): boolean {
    return layer.elements.some((item) => item.symbol === symbol);
}

/**
 * « Follow the focus »: each pane showing no layer of `symbol` moves to the
 * first layer of that element in its own analysis; a pane whose analysis has
 * none stays. Only the panes the layout shows move, and a stack, which holds
 * layers rather than panes, is left alone. The state is returned as is when
 * nothing moves.
 */
export function followElement(
    state: TableState,
    symbol: string,
    maps: readonly MapLine[],
): TableState {
    if (state.layout === "stack") return state;
    const panes = [...state.panes];
    let moved = false;
    for (let pane = 0; pane < PANES_SHOWN[state.layout]; pane++) {
        const canvas = panes[pane];
        if (canvas === null) continue;
        const line = maps.find((entry) =>
            entry.file.layers.some((layer) => layer.id === canvas),
        );
        if (!line) continue;
        const layers = line.file.layers;
        if (
            layers.some(
                (layer) => layer.id === canvas && carries(layer, symbol),
            )
        ) {
            continue;
        }
        const target = layers.find((layer) => carries(layer, symbol));
        if (target) {
            panes[pane] = target.id;
            moved = true;
        }
    }
    return moved ? { ...state, panes } : state;
}
