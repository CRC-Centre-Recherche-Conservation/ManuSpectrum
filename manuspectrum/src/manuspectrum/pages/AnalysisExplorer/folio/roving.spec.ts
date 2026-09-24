import { describe, expect, it } from "vitest";

import {
    nextId,
    readingOrder,
} from "@/manuspectrum/pages/AnalysisExplorer/folio/roving.ts";

describe("roving order", () => {
    it("reads top to bottom, then left to right within a band", () => {
        const order = readingOrder([
            { id: "low", lat: -10, lng: 0 },
            { id: "right", lat: -1.2, lng: 5 },
            { id: "left", lat: -1, lng: 1 },
        ]);
        expect(order).toEqual(["left", "right", "low"]);
    });

    it("moves with the arrows and stops at the ends", () => {
        const order = ["a", "b", "c"];
        expect(nextId(order, "a", "ArrowRight")).toBe("b");
        expect(nextId(order, "a", "ArrowDown")).toBe("b");
        expect(nextId(order, "b", "ArrowLeft")).toBe("a");
        expect(nextId(order, "c", "ArrowRight")).toBe("c");
        expect(nextId(order, "b", "Home")).toBe("a");
        expect(nextId(order, "a", "End")).toBe("c");
        expect(nextId(order, null, "ArrowRight")).toBe("a");
        expect(nextId(order, "a", "Tab")).toBeNull();
        expect(nextId([], null, "ArrowRight")).toBeNull();
    });
});
