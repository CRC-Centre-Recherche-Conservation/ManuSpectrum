import { describe, expect, it } from "vitest";

import {
    meetsTrack,
    parseTrack,
    serializeTrack,
    slotOf,
    toggleTracked,
    trackedOf,
} from "@/manuspectrum/pages/AnalysisExplorer/views/Map/tracking.ts";

describe("tracked materials", () => {
    it("fills the lowest hole and refuses a fifth", () => {
        let slots: (string | null)[] = [];
        for (const uri of ["a", "b", "c", "d"]) {
            slots = toggleTracked(slots, uri).slots;
        }
        expect(toggleTracked(slots, "e")).toEqual({ slots, result: "refused" });
        const freed = toggleTracked(slots, "b");
        expect(freed).toEqual({
            slots: ["a", null, "c", "d"],
            result: "unpinned",
        });
        expect(toggleTracked(freed.slots, "e")).toEqual({
            slots: ["a", "e", "c", "d"],
            result: "pinned",
        });
        expect(slotOf(["a", null, "c"], "c")).toBe(3);
        expect(slotOf(["a"], "z")).toBeNull();
        expect(trackedOf(["a", null, "c"])).toEqual([
            { uri: "a", slot: 1 },
            { uri: "c", slot: 3 },
        ]);
    });

    it("parseTrack keeps slot order and holes, drops duplicates and trailing holes", () => {
        expect(parseTrack(["x", "-", "x", "y", "z", "w"])).toEqual([
            "x",
            null,
            null,
            "y",
        ]);
        expect(parseTrack(["a", "-", ""])).toEqual(["a"]);
        expect(serializeTrack(["a", null, "c"])).toEqual(["a", "-", "c"]);
    });

    it("meetsTrack reads any and all", () => {
        const tracked = [
            { uri: "a", slot: 1 },
            { uri: "b", slot: 2 },
        ];
        expect(meetsTrack(new Set(["a"]), tracked, "any")).toBe(true);
        expect(meetsTrack(new Set(["a"]), tracked, "all")).toBe(false);
        expect(meetsTrack(new Set(["a", "b"]), tracked, "all")).toBe(true);
        expect(meetsTrack(new Set(), [], "all")).toBe(true);
    });

    it("meetsTrack matches the exact uri, never a parent", () => {
        const tracked = [{ uri: "http://x/lead", slot: 1 }];
        expect(
            meetsTrack(new Set(["http://x/lead-white"]), tracked, "any"),
        ).toBe(false);
    });
});
