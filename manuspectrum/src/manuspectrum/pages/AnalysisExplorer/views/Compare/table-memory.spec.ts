import { describe, expect, it } from "vitest";

import {
    defaultState,
    place,
} from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/light-table.ts";
import {
    restoreState,
    storedOf,
} from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/table-memory.ts";
import {
    analysisHit,
    imagingEntry,
    layerOf,
} from "@/manuspectrum/pages/AnalysisExplorer/testing/fixtures.ts";

import type { MapLine } from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/windows.ts";

function line(n: number, count: number): MapLine {
    const analysis = analysisHit(n);
    return {
        key: `an:${analysis.id}:-`,
        slot: n,
        analysis,
        file: imagingEntry({
            id: `${analysis.id}:imaging:0`,
            layers: Array.from({ length: count }, (_, index) =>
                layerOf({
                    index,
                    id: `c${n}-${index}`,
                    label: `L${n}.${index}`,
                }),
            ),
        }),
        named: null,
    };
}

const MAPS = [line(1, 3), line(2, 2)];

describe("storedOf", () => {
    it("keeps what the browser remembers and not the target pane", () => {
        const stored = storedOf(place(defaultState(MAPS), "c1-2", 1));
        expect(Object.keys(stored).sort()).toEqual([
            "filters",
            "grouping",
            "layout",
            "panes",
            "stack",
            "syncViews",
        ]);
        expect(stored.panes[1]).toBe("c1-2");
    });

    it("adds the choice about the gallery only once the reader made one", () => {
        const state = defaultState(MAPS);
        expect(storedOf(state)).not.toHaveProperty("gallery");
        expect(storedOf(state, false).gallery).toBe(false);
        expect(storedOf(state, true).gallery).toBe(true);
    });
});

describe("restoreState", () => {
    it("takes the stored table, minus what the Selection no longer holds", () => {
        const stored = storedOf({
            ...defaultState(MAPS),
            layout: "grid2",
            panes: ["c1-2", "gone", null, null],
        });
        const state = restoreState(stored, MAPS);
        expect(state.layout).toBe("grid2");
        expect(state.panes[0]).toBe("c1-2");
        expect(state.panes[1]).not.toBe("gone");
        expect(state.active).toBe(0);
    });

    it("starts again from the default when nothing stored is held", () => {
        const stored = storedOf({
            ...defaultState(MAPS),
            layout: "grid4",
            panes: ["a", "b", "c", "d"],
        });
        expect(restoreState(stored, MAPS)).toEqual(defaultState(MAPS));
    });

    it("starts from the default without a record", () => {
        expect(restoreState(undefined, MAPS)).toEqual(defaultState(MAPS));
    });

    it("keeps a stack whose layers are held", () => {
        const stored = {
            ...storedOf(defaultState(MAPS)),
            layout: "stack" as const,
            panes: [null, null, null, null],
            stack: {
                analysis: analysisHit(1).id,
                layers: [{ canvas: "c1-1", opacity: 80, on: true, tint: null }],
            },
        };
        const state = restoreState(stored, MAPS);
        expect(state.layout).toBe("stack");
        expect(state.stack.layers).toHaveLength(1);
    });
});
