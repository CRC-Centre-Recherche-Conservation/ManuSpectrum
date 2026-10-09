import { describe, expect, it } from "vitest";

import {
    checkState,
    planToggleAll,
} from "@/manuspectrum/pages/AnalysisExplorer/selection/bulk.ts";

const KEYS = ["an:1", "an:2", "an:3"];

describe("checkState", () => {
    it("is none when no key is held", () => {
        expect(checkState(KEYS, new Set(["an:9"]))).toBe("none");
    });

    it("is some when part of the keys is held", () => {
        expect(checkState(KEYS, new Set(["an:2"]))).toBe("some");
    });

    it("is all when every key is held", () => {
        expect(checkState(KEYS, new Set(KEYS))).toBe("all");
    });

    it("is none for no key", () => {
        expect(checkState([], new Set(KEYS))).toBe("none");
    });
});

describe("planToggleAll", () => {
    it("adds every key when none is held", () => {
        expect(planToggleAll(KEYS, new Set(), 30)).toEqual({
            action: "add",
            keys: KEYS,
        });
    });

    it("adds only the missing keys when some are held", () => {
        expect(planToggleAll(KEYS, new Set(["an:2"]), 2)).toEqual({
            action: "add",
            keys: ["an:1", "an:3"],
        });
    });

    it("removes every key when all are held, whatever the free places", () => {
        expect(planToggleAll(KEYS, new Set(KEYS), 0)).toEqual({
            action: "remove",
            keys: KEYS,
        });
    });

    it("refuses when the missing keys exceed the free places", () => {
        expect(planToggleAll(KEYS, new Set(["an:1"]), 1)).toEqual({
            action: "refused",
            needed: 2,
            free: 1,
        });
    });

    it("does nothing for no key", () => {
        expect(planToggleAll([], new Set(), 30)).toEqual({
            action: "add",
            keys: [],
        });
    });
});
