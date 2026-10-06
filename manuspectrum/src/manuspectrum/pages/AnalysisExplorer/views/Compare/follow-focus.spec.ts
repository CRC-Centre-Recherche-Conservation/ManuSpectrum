import { describe, expect, it } from "vitest";

import { followElement } from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/follow-focus.ts";
import {
    defaultState,
    place,
} from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/light-table.ts";
import {
    analysisHit,
    imagingEntry,
    layerOf,
    valueRef,
} from "@/manuspectrum/pages/AnalysisExplorer/testing/fixtures.ts";

import type { FileLayer } from "@/manuspectrum/pages/AnalysisExplorer/api/types.ts";
import type { MapLine } from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/windows.ts";

function element(symbol: string): Partial<FileLayer> {
    return {
        content: valueRef("http://example.org/element-map", "Element map"),
        elements: [
            {
                value: valueRef(`http://example.org/el-${symbol}`, symbol),
                symbol,
            },
        ],
    };
}

function line(n: number, layers: Partial<FileLayer>[]): MapLine {
    const analysis = analysisHit(n);
    return {
        key: `an:${analysis.id}:-`,
        slot: n,
        analysis,
        file: imagingEntry({
            id: `${analysis.id}:imaging:0`,
            layers: layers.map((overrides, index) =>
                layerOf({ index, id: `c${n}-${index}`, ...overrides }),
            ),
        }),
        named: null,
    };
}

const MAPS = [
    line(1, [element("Pb"), element("Cu")]),
    line(2, [element("Fe"), element("Cu")]),
];

describe("followElement", () => {
    it("moves each pane to its own analysis's layer of the element", () => {
        const state = defaultState(MAPS);
        expect(state.panes.slice(0, 2)).toEqual(["c1-0", "c2-0"]);
        const next = followElement(state, "Cu", MAPS);
        expect(next.panes.slice(0, 2)).toEqual(["c1-1", "c2-1"]);
    });

    it("leaves a pane that already shows the element", () => {
        const state = place(defaultState(MAPS), "c1-1", 0);
        const next = followElement(state, "Cu", MAPS);
        expect(next.panes[0]).toBe("c1-1");
    });

    it("leaves a pane whose analysis has no layer of the element", () => {
        const state = defaultState(MAPS);
        expect(followElement(state, "Hg", MAPS)).toBe(state);
    });

    it("moves only the panes the layout shows", () => {
        const state = {
            ...defaultState(MAPS),
            layout: "single" as const,
            panes: ["c1-0", "c2-0", null, null],
        };
        const next = followElement(state, "Cu", MAPS);
        expect(next.panes).toEqual(["c1-1", "c2-0", null, null]);
    });

    it("does nothing in a stack, which holds layers rather than panes", () => {
        const state = { ...defaultState(MAPS), layout: "stack" as const };
        expect(followElement(state, "Cu", MAPS)).toBe(state);
    });
});
