import { describe, expect, it } from "vitest";

import {
    analysisHit,
    imagingEntry,
    layerOf,
    valueRef,
} from "@/manuspectrum/pages/AnalysisExplorer/testing/fixtures.ts";
import {
    CAPTURE_PREFIX,
    NEUTRAL_FILTERS,
    canStack,
    captureLayer,
    defaultState,
    linkedGroups,
    setSyncViews,
    moveInStack,
    pairsOf,
    place,
    layerById,
    reconcile,
    setLayout,
    setOpacity,
    setTint,
    stepPane,
    swap,
    toggleInStack,
} from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/light-table.ts";

import type { TableState } from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/light-table.ts";
import type { FileLayer } from "@/manuspectrum/pages/AnalysisExplorer/api/types.ts";
import type { MapLine } from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/windows.ts";

const ELEMENT_MAP = valueRef("http://example.org/element-map", "Element map");

function cu(n: number, symbol = "Cu"): Partial<FileLayer> {
    return {
        content: ELEMENT_MAP,
        elements: [
            {
                value: valueRef(`http://example.org/el-${symbol}`, symbol),
                symbol,
            },
        ],
        label: `${symbol} ${n}`,
    };
}

/** A map of analysis `n` whose layers are `layers`, canvas ids `c<n>-<index>`. */
function line(
    n: number,
    layers: Partial<FileLayer>[] = [{}, {}],
    named: number | null = null,
): MapLine {
    const analysis = analysisHit(n);
    return {
        key: `an:${analysis.id}:-`,
        slot: n,
        analysis,
        file: imagingEntry({
            id: `${analysis.id}:imaging:0`,
            layers: layers.map((overrides, index) =>
                layerOf({
                    index,
                    id: `c${n}-${index}`,
                    label: `L${n}.${index}`,
                    ...overrides,
                }),
            ),
        }),
        named,
    };
}

describe("defaultState", () => {
    it("is a single empty pane without any map", () => {
        const state = defaultState([]);
        expect(state.layout).toBe("single");
        expect(state.panes).toEqual([null, null, null, null]);
        expect(state.filters).toHaveLength(5);
        expect(state.filters.every((f) => f === NEUTRAL_FILTERS)).toBe(false);
        expect(state.filters[0]).toEqual(NEUTRAL_FILTERS);
        expect(state.syncViews).toBe(false);
        expect(state.stack).toEqual({ analysis: null, layers: [] });
        expect(state.grouping).toBe("analysis");
    });

    it("lays a curtain between the first two layers of a lone analysis", () => {
        const state = defaultState([line(1, [{}, {}, {}])]);
        expect(state.layout).toBe("curtain");
        expect(state.panes).toEqual(["c1-0", "c1-1", null, null]);
    });

    it("shows a lone one-layer analysis in a single pane", () => {
        const state = defaultState([line(1, [{}])]);
        expect(state.layout).toBe("single");
        expect(state.panes[0]).toBe("c1-0");
    });

    it("puts the first layer of each of two analyses side by side, in slot order", () => {
        const state = defaultState([line(2), line(1)]);
        expect(state.layout).toBe("grid2");
        expect(state.panes).toEqual(["c1-0", "c2-0", null, null]);
    });

    it("uses the layer a one-layer key names", () => {
        const state = defaultState([line(1, [{}, {}, {}], 2), line(2)]);
        expect(state.panes.slice(0, 2)).toEqual(["c1-2", "c2-0"]);
    });

    it("fills a 2 by 2 grid with 3 or 4 analyses and keeps the first four of 5", () => {
        expect(defaultState([line(1), line(2), line(3)]).layout).toBe("grid4");
        const five = defaultState([1, 2, 3, 4, 5].map((n) => line(n)));
        expect(five.layout).toBe("grid4");
        expect(five.panes).toEqual(["c1-0", "c2-0", "c3-0", "c4-0"]);
    });

    it("groups by tag as soon as two analyses share a family, else by analysis", () => {
        const shared = defaultState([
            line(1, [cu(1), {}]),
            line(2, [cu(2), {}]),
        ]);
        expect(shared.grouping).toBe("tag");
        const alone = defaultState([line(1, [cu(1), {}]), line(2, [{}, {}])]);
        expect(alone.grouping).toBe("analysis");
    });
});

describe("place, stepPane, swap", () => {
    const maps = [line(1, [{}, {}, {}]), line(2)];

    it("places a canvas in the target pane, then makes it the target", () => {
        const state = { ...defaultState(maps), active: 1 };
        const next = place(state, "c2-1");
        expect(next.panes[1]).toBe("c2-1");
        expect(next.active).toBe(1);
        expect(place(state, "c1-2", 3)).toMatchObject({
            active: 3,
            panes: [state.panes[0], state.panes[1], null, "c1-2"],
        });
    });

    it("does not mutate the state it was given", () => {
        const state = defaultState(maps);
        const before = JSON.stringify(state);
        place(state, "c2-1", 0);
        swap(state);
        expect(JSON.stringify(state)).toBe(before);
    });

    it("steps to the next layer of the same manifest and stops at its ends", () => {
        const state = place(defaultState(maps), "c1-1", 0);
        expect(stepPane(state, 0, 1, maps).panes[0]).toBe("c1-2");
        expect(stepPane(state, 0, -1, maps).panes[0]).toBe("c1-0");
        const last = place(state, "c1-2", 0);
        expect(stepPane(last, 0, 1, maps)).toBe(last);
        expect(stepPane(state, 3, 1, maps)).toBe(state);
    });

    it("swaps A and B and leaves the others", () => {
        const state = defaultState([1, 2, 3].map((n) => line(n)));
        const next = swap(state);
        expect(next.panes).toEqual([
            state.panes[1],
            state.panes[0],
            state.panes[2],
            state.panes[3],
        ]);
    });
});

describe("setLayout", () => {
    it("fills the panes a layout needs and keeps what was placed", () => {
        const maps = [line(1, [{}, {}, {}, {}, {}])];
        const single = { ...defaultState(maps), layout: "single" as const };
        const grid = setLayout(
            { ...single, panes: ["c1-3", null, null, null] },
            "grid4",
            maps,
        );
        expect(grid.layout).toBe("grid4");
        expect(grid.panes[0]).toBe("c1-3");
        expect(grid.panes.every((pane) => pane !== null)).toBe(true);
        expect(new Set(grid.panes).size).toBe(4);
    });

    it("lets a curtain take two canvases of two analyses", () => {
        const maps = [line(1), line(2)];
        const state = setLayout(defaultState(maps), "curtain", maps);
        expect(state.layout).toBe("curtain");
        expect(state.panes.slice(0, 2)).toEqual(["c1-0", "c2-0"]);
        const mixed = place(place(state, "c1-1", 0), "c2-1", 1);
        expect(mixed.panes.slice(0, 2)).toEqual(["c1-1", "c2-1"]);
    });
});

describe("the stack", () => {
    const maps = [line(1, [{}, {}, {}]), line(2)];
    const start = { ...defaultState(maps), layout: "stack" as const };

    it("is fixed to the analysis of its first layer and refuses another", () => {
        const one = toggleInStack(start, "c1-0", maps);
        expect(one.stack.analysis).toBe(maps[0].analysis.id);
        expect(one.stack.layers).toEqual([
            { canvas: "c1-0", opacity: 100, on: true, tint: null },
        ]);
        expect(canStack(one, "c1-1", maps)).toBe(true);
        expect(canStack(one, "c2-0", maps)).toBe(false);
        expect(toggleInStack(one, "c2-0", maps)).toBe(one);
        expect(canStack(one, "unknown", maps)).toBe(false);
    });

    it("frees the analysis when the last layer leaves", () => {
        const one = toggleInStack(start, "c1-0", maps);
        const empty = toggleInStack(one, "c1-0", maps);
        expect(empty.stack).toEqual({ analysis: null, layers: [] });
        expect(toggleInStack(empty, "c2-0", maps).stack.analysis).toBe(
            maps[1].analysis.id,
        );
    });

    it("orders, fades and tints its layers", () => {
        let state = toggleInStack(start, "c1-0", maps);
        state = toggleInStack(state, "c1-1", maps);
        state = moveInStack(state, "c1-1", -1);
        expect(state.stack.layers.map((l) => l.canvas)).toEqual([
            "c1-1",
            "c1-0",
        ]);
        expect(moveInStack(state, "c1-1", -1)).toBe(state);
        state = setOpacity(state, "c1-0", 140);
        expect(state.stack.layers[1].opacity).toBe(100);
        state = setOpacity(state, "c1-0", 35);
        expect(state.stack.layers[1].opacity).toBe(35);
        state = setTint(state, "c1-0", "cyan");
        expect(state.stack.layers[1].tint).toBe("cyan");
    });
});

describe("reconcile", () => {
    it("empties the panes of an analysis left out of the Selection and refills them", () => {
        const maps = [line(1), line(2)];
        const state = defaultState(maps);
        const next = reconcile(state, [maps[0]]);
        expect(next.panes[1]).not.toBe("c2-0");
        expect(next.panes.every((p) => p === null || p.startsWith("c1"))).toBe(
            true,
        );
        expect(next.panes[0]).toBe("c1-0");
    });

    it("leaves nothing when no map is left", () => {
        const state = defaultState([line(1), line(2)]);
        const next = reconcile(state, []);
        expect(next.panes).toEqual([null, null, null, null]);
        expect(next.stack).toEqual({ analysis: null, layers: [] });
    });

    it("drops stack layers that are gone and frees the analysis", () => {
        const maps = [line(1, [{}, {}]), line(2)];
        let state: TableState = { ...defaultState(maps), layout: "stack" };
        state = toggleInStack(state, "c1-0", maps);
        expect(reconcile(state, [maps[1]]).stack).toEqual({
            analysis: null,
            layers: [],
        });
        expect(reconcile(state, maps)).toEqual(state);
    });

    it("keeps a valid state as it is", () => {
        const maps = [line(1), line(2)];
        const state = defaultState(maps);
        expect(reconcile(state, maps)).toEqual(state);
    });
});

describe("pairsOf", () => {
    it("is empty without a mapping", () => {
        const maps = [line(1), line(2)];
        expect(pairsOf("c1-0", maps)).toEqual([]);
    });

    it("lists the layers of the same family in the other analyses, in slot order", () => {
        const maps = [
            line(3, [cu(3), {}]),
            line(1, [cu(1), {}]),
            line(2, [{}, cu(2, "Fe")]),
        ];
        expect(pairsOf("c1-0", maps).map((l) => l.id)).toEqual(["c3-0"]);
        expect(pairsOf("c1-1", maps)).toEqual([]);
        expect(pairsOf("c2-1", maps)).toEqual([]);
        expect(pairsOf("nope", maps)).toEqual([]);
    });
});

describe("linkedGroups", () => {
    it("links no pane by default, not even two of the same analysis", () => {
        const maps = [line(1, [{}, {}, {}]), line(2, [{}, {}])];
        let state = { ...defaultState(maps), layout: "grid4" as const };
        state = {
            ...state,
            panes: ["c1-0", "c2-0", "c1-1", "c2-1"],
        };
        expect(state.syncViews).toBe(false);
        expect(linkedGroups(state, maps)).toEqual([]);
        expect(linkedGroups(setSyncViews(state, true), maps)).toEqual([
            [0, 1, 2, 3],
        ]);
    });

    it("ignores empty panes, the hidden ones and layouts drawn by one map", () => {
        const maps = [line(1), line(2)];
        const grid2 = {
            ...defaultState(maps),
            layout: "grid2" as const,
            panes: ["c1-0", "c1-1", "c1-0", null],
        };
        const synced = { ...grid2, syncViews: true };
        expect(linkedGroups(synced, maps)).toEqual([[0, 1]]);
        expect(linkedGroups({ ...synced, layout: "curtain" }, maps)).toEqual(
            [],
        );
        expect(linkedGroups({ ...synced, layout: "stack" }, maps)).toEqual([]);
        expect(linkedGroups({ ...synced, layout: "single" }, maps)).toEqual([]);
        expect(
            linkedGroups(
                { ...synced, panes: ["c1-0", null, null, null] },
                maps,
            ),
        ).toEqual([]);
    });
});

describe("captures", () => {
    const capture = {
        url: "https://iiif.example/folio/full/200,/0/default.jpg",
        width: 200,
        height: 300,
        canvas: "https://iiif.example/canvas/1",
        at: 1,
    };
    const maps = [line(1, [{}, {}]), line(2, [{}])];
    const id = maps[0].analysis.id;
    const captures = { [id]: captureLayer(id, capture, "Folio photo") };

    it("builds a layer without service from the capture", () => {
        const layer = captures[id];
        expect(layer.id).toBe(CAPTURE_PREFIX + id);
        expect(layer.index).toBe(-1);
        expect(layer.image).toEqual({
            service: null,
            url: capture.url,
            width: 200,
            height: 300,
        });
        expect(layer.elements).toEqual([]);
    });

    it("resolves a capture id with the line of its analysis", () => {
        const found = layerById(CAPTURE_PREFIX + id, maps, captures);
        expect(found?.layer.label).toBe("Folio photo");
        expect(found?.line.analysis.id).toBe(id);
        expect(layerById(CAPTURE_PREFIX + id, maps)).toBeNull();
    });

    it("ignores a capture whose analysis is not among the maps", () => {
        const other = { x: captureLayer("x", capture, "Folio photo") };
        expect(layerById(CAPTURE_PREFIX + "x", maps, other)).toBeNull();
    });

    function withPane(canvas: string): TableState {
        const state = place(defaultState(maps), canvas, 0);
        return { ...state, layout: "grid2" };
    }

    it("keeps a pane and a stack layer holding a capture while its analysis is selected", () => {
        const canvas = CAPTURE_PREFIX + id;
        const state = toggleInStack(withPane(canvas), canvas, [
            {
                ...maps[0],
                file: {
                    ...maps[0].file,
                    layers: [...maps[0].file.layers, captures[id]],
                },
            },
            maps[1],
        ]);
        const next = reconcile(state, maps, captures);
        expect(next.panes[0]).toBe(canvas);
        expect(next.stack.layers.map((l) => l.canvas)).toEqual([canvas]);
    });

    it("drops it once the analysis leaves the Selection or the capture is deleted", () => {
        const canvas = CAPTURE_PREFIX + id;
        const state = withPane(canvas);
        expect(reconcile(state, [maps[1]], captures).panes[0]).not.toBe(canvas);
        expect(reconcile(state, maps, {}).panes[0]).not.toBe(canvas);
    });

    it("never lays a capture into an empty pane by itself", () => {
        const next = reconcile(
            {
                ...defaultState(maps),
                layout: "grid4",
                panes: [null, null, null, null],
            },
            maps,
            captures,
        );
        expect(next.panes.includes(CAPTURE_PREFIX + id)).toBe(false);
    });
});
