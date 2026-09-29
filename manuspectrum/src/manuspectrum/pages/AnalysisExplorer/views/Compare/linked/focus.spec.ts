import { describe, expect, it } from "vitest";

import { buildGraph } from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/linked/graph.ts";
import {
    circled,
    focusHue,
    focusRelations,
    focusRim,
    focusRing,
    focusStripe,
    gainedSlots,
    mergeRelations,
    nextFreeSlot,
    pinInSlots,
    pinnedOf,
    unpinFromSlots,
} from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/linked/focus.ts";
import {
    analysisNode,
    elementNode,
    materialNode,
} from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/linked/node-id.ts";
import {
    AN1,
    AN2,
    BASKET,
    BY_KEY,
    CH1,
    CH3,
    SYNTHESIS,
} from "@/manuspectrum/pages/AnalysisExplorer/testing/linked.ts";

const GRAPH = buildGraph({
    basket: BASKET,
    byKey: BY_KEY,
    synthesis: SYNTHESIS,
});

describe("focus slots", () => {
    it("pins in the lowest hole, leaves a hole on unpin and trims trailing holes", () => {
        let slots = pinInSlots([], "a");
        slots = pinInSlots(slots, "b");
        slots = pinInSlots(slots, "c");
        slots = unpinFromSlots(slots, (id) => id === "b");
        expect(slots).toEqual(["a", null, "c"]);
        expect(nextFreeSlot(slots)).toBe(2);
        expect(pinnedOf(slots)).toEqual([
            { id: "a", slot: 1 },
            { id: "c", slot: 3 },
        ]);
        slots = pinInSlots(slots, "d");
        expect(slots).toEqual(["a", "d", "c"]);
        expect(nextFreeSlot(slots)).toBe(4);
        expect(unpinFromSlots(slots, (id) => id !== "a")).toEqual(["a"]);
        expect(unpinFromSlots(["a", null, "c"], (id) => id === "c")).toEqual([
            "a",
        ]);
    });
});

describe("focusRelations", () => {
    it("gives each node its slots, its own first, then in slot order, and its best level", () => {
        const relations = focusRelations(
            GRAPH,
            [
                { id: elementNode("Cu"), slot: 1 },
                { id: materialNode(CH1), slot: 2 },
            ],
            "any",
        );
        expect(relations.get(materialNode(CH1))).toEqual({
            best: "self",
            slots: [
                { slot: 2, level: "self" },
                { slot: 1, level: "direct" },
            ],
        });
        expect(relations.get(analysisNode(AN1))).toEqual({
            best: "evidence",
            slots: [
                { slot: 1, level: "evidence" },
                { slot: 2, level: "evidence" },
            ],
        });
        expect(relations.has(analysisNode(AN2))).toBe(false);
    });

    it("keeps under « all » only what relates to every pinned node, and ignores it with one", () => {
        const pinned = [
            { id: elementNode("Cu"), slot: 1 },
            { id: elementNode("Ca"), slot: 3 },
        ];
        const any = focusRelations(GRAPH, pinned, "any");
        const all = focusRelations(GRAPH, pinned, "all");
        expect(any.has(materialNode(CH3))).toBe(true);
        expect(all.has(materialNode(CH3))).toBe(false);
        expect(
            focusRelations(GRAPH, [pinned[0]], "all").has(elementNode("Cu")),
        ).toBe(true);
    });

    it("keeps each pinned node under « all » at its own slot, even when it relates to no other pin", () => {
        const pinned = [
            { id: elementNode("Cu"), slot: 1 },
            { id: elementNode("Ca"), slot: 3 },
        ];
        const all = focusRelations(GRAPH, pinned, "all");
        expect(all.get(elementNode("Cu"))).toEqual({
            best: "self",
            slots: [{ slot: 1, level: "self" }],
        });
        expect(all.get(elementNode("Ca"))).toEqual({
            best: "self",
            slots: [{ slot: 3, level: "self" }],
        });
        const linkedPins = [
            { id: elementNode("Cu"), slot: 1 },
            { id: materialNode(CH1), slot: 2 },
        ];
        expect(
            focusRelations(GRAPH, linkedPins, "all").get(materialNode(CH1)),
        ).toEqual({
            best: "self",
            slots: [
                { slot: 2, level: "self" },
                { slot: 1, level: "direct" },
            ],
        });
    });

    it("merges the relations of several ids and says which gained a slot", () => {
        const one = focusRelations(
            GRAPH,
            [{ id: elementNode("Cu"), slot: 1 }],
            "any",
        );
        const two = focusRelations(
            GRAPH,
            [
                { id: elementNode("Cu"), slot: 1 },
                { id: analysisNode(AN2), slot: 2 },
            ],
            "any",
        );
        expect(
            mergeRelations(two, [materialNode(CH1), analysisNode(AN2)]),
        ).toEqual({
            best: "self",
            slots: [
                { slot: 2, level: "self" },
                { slot: 1, level: "direct" },
            ],
        });
        expect(mergeRelations(two, "nothing")).toBeNull();
        const gained = gainedSlots(one, two);
        expect(gained.has(analysisNode(AN2))).toBe(true);
        expect(gained.has(materialNode(CH1))).toBe(false);
    });
});

describe("circled", () => {
    it("names slots 1 to 20 by a circled digit, the others by their number", () => {
        expect(circled(1)).toBe("①");
        expect(circled(3)).toBe("③");
        expect(circled(20)).toBe("⑳");
        expect(circled(21)).toBe("21");
        expect(circled(0)).toBe("0");
    });
});

describe("focus colours", () => {
    it("gives slots 1 to 4 their hue and the others the shared one", () => {
        expect(focusHue(1)).toBe("var(--focus-1)");
        expect(focusHue(4)).toBe("var(--focus-4)");
        expect(focusHue(5)).toBe("var(--focus-more)");
    });

    it("segments a ring, a stripe and a rim by slot", () => {
        expect(focusRing([2])).toBe("var(--focus-2)");
        expect(focusRing([1, 3])).toBe(
            "conic-gradient(from -90deg, var(--focus-1) 0.0% 50.0%, var(--focus-3) 50.0% 100.0%)",
        );
        expect(focusStripe(["var(--focus-1)"])).toBe(
            "linear-gradient(var(--focus-1), var(--focus-1))",
        );
        expect(
            focusRim(
                new Map([
                    [3, 1],
                    [1, 3],
                ]),
            ),
        ).toBe(
            "linear-gradient(90deg, var(--focus-1) 0.0% 75.0%, var(--focus-3) 75.0% 100.0%)",
        );
        expect(focusRim(new Map())).toBe("");
    });
});
