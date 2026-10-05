import { describe, expect, it } from "vitest";

import {
    analysisHit,
    imagingEntry,
    layerOf,
} from "@/manuspectrum/pages/AnalysisExplorer/testing/fixtures.ts";
import {
    defaultState,
    place,
    toggleInStack,
} from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/light-table.ts";
import {
    sameSize,
    scaleNotes,
} from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/scale-notes.ts";

import type { TableState } from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/light-table.ts";
import type { MapLine } from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/windows.ts";

function line(n: number, count = 2): MapLine {
    const analysis = analysisHit(n);
    return {
        key: `an:${analysis.id}:-`,
        slot: n,
        analysis,
        file: imagingEntry({
            layers: Array.from({ length: count }, (_, index) =>
                layerOf({ index, id: `c${n}-${index}` }),
            ),
        }),
        named: null,
    };
}

const BIG = { w: 1529, h: 2405 };
const SMALL = { w: 600, h: 1202 };

function sizes(entries: Record<string, { w: number; h: number } | null>) {
    return new Map(Object.entries(entries));
}

describe("sameSize", () => {
    it("compares width and height", () => {
        expect(sameSize(BIG, { ...BIG })).toBe(true);
        expect(sameSize(BIG, SMALL)).toBe(false);
        expect(sameSize(BIG, { w: 1529, h: 1 })).toBe(false);
    });
});

describe("scaleNotes", () => {
    const maps = [line(1), line(2)];

    it("says nothing for equal sizes", () => {
        const state = defaultState(maps);
        expect(
            scaleNotes(state, maps, sizes({ "c1-0": BIG, "c2-0": { ...BIG } })),
        ).toEqual(new Map());
    });

    it("says nothing while a size is not read", () => {
        const state = defaultState(maps);
        expect(scaleNotes(state, maps, sizes({ "c1-0": BIG }))).toEqual(
            new Map(),
        );
        expect(
            scaleNotes(state, maps, sizes({ "c1-0": BIG, "c2-0": null })),
        ).toEqual(new Map());
    });

    it("notes the curtain's B side with both served sizes", () => {
        const state: TableState = {
            ...place(defaultState(maps), "c2-0", 1),
            layout: "curtain",
        };
        const notes = scaleNotes(
            state,
            maps,
            sizes({ "c1-0": BIG, "c2-0": SMALL }),
        );
        expect([...notes.keys()]).toEqual(["c2-0"]);
        expect(notes.get("c2-0")).toEqual({
            canvas: "c2-0",
            size: SMALL,
            against: "c1-0",
            againstSize: BIG,
        });
    });

    it("notes a linked pane whose size differs from the first of its group", () => {
        const one = [line(1, 3)];
        const state: TableState = {
            ...defaultState(one),
            layout: "grid4",
            panes: ["c1-0", "c1-1", "c1-2", null],
        };
        const notes = scaleNotes(
            state,
            one,
            sizes({ "c1-0": BIG, "c1-1": SMALL, "c1-2": BIG }),
        );
        expect([...notes.keys()]).toEqual(["c1-1"]);
        const unlinked: TableState = {
            ...state,
            panes: ["c1-0", "c1-1", null, null],
            layout: "grid2",
        };
        expect(
            scaleNotes(unlinked, one, sizes({ "c1-0": BIG, "c1-1": SMALL }))
                .size,
        ).toBe(1);
    });

    it("does not note panes of two analyses unless linked on demand", () => {
        const state: TableState = { ...defaultState(maps), layout: "grid2" };
        const all = sizes({ "c1-0": BIG, "c2-0": SMALL });
        expect(scaleNotes(state, maps, all).size).toBe(0);
        expect(scaleNotes({ ...state, linkAll: true }, maps, all).size).toBe(1);
    });

    it("notes each stack layer whose size differs from the first shown", () => {
        let state: TableState = {
            ...defaultState([line(1, 3)]),
            layout: "stack",
        };
        const one = [line(1, 3)];
        for (const canvas of ["c1-0", "c1-1", "c1-2"]) {
            state = toggleInStack(state, canvas, one);
        }
        const notes = scaleNotes(
            state,
            one,
            sizes({ "c1-0": BIG, "c1-1": SMALL, "c1-2": { ...BIG } }),
        );
        expect([...notes.keys()]).toEqual(["c1-1"]);
        expect(notes.get("c1-1")?.againstSize).toEqual(BIG);
    });
});
