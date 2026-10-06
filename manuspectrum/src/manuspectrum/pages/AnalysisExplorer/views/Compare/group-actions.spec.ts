import { describe, expect, it } from "vitest";

import { layGroup } from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/group-actions.ts";
import {
    defaultState,
    setLayout,
} from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/light-table.ts";
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
                layerOf({ index, id: `c${n}-${index}` }),
            ),
        }),
        named: null,
    };
}

const MAPS = [line(1, 5), line(2, 3)];

describe("layGroup", () => {
    it("lays one canvas in the target pane", () => {
        const next = layGroup(defaultState(MAPS), ["c1-3"], MAPS);
        expect(next.panes[next.active]).toBe("c1-3");
        expect(next.layout).toBe(defaultState(MAPS).layout);
    });

    it("lays two canvases on a grid of two", () => {
        const next = layGroup(defaultState(MAPS), ["c2-1", "c2-2"], MAPS);
        expect(next.layout).toBe("grid2");
        expect(next.panes.slice(0, 2)).toEqual(["c2-1", "c2-2"]);
    });

    it("lays three or four on a grid of four, never twice the same canvas", () => {
        const next = layGroup(
            setLayout(defaultState(MAPS), "grid2", MAPS),
            ["c1-2", "c1-3", "c2-0"],
            MAPS,
        );
        expect(next.layout).toBe("grid4");
        expect(next.panes.slice(0, 3)).toEqual(["c1-2", "c1-3", "c2-0"]);
        const placed = next.panes.filter((pane) => pane !== null);
        expect(new Set(placed).size).toBe(placed.length);
    });

    it("lays at most four", () => {
        const next = layGroup(
            defaultState(MAPS),
            ["c1-0", "c1-1", "c1-2", "c1-3", "c1-4"],
            MAPS,
        );
        expect(next.panes).toEqual(["c1-0", "c1-1", "c1-2", "c1-3"]);
    });

    it("returns the state when there is nothing to lay", () => {
        const state = defaultState(MAPS);
        expect(layGroup(state, [], MAPS)).toBe(state);
    });
});
