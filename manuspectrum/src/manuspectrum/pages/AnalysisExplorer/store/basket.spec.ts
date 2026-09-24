import { describe, expect, it } from "vitest";

import {
    BASKET_LIMIT,
    freeSlots,
    kindOf,
    normalizeItemKey,
    slotLabel,
    uniqueKeys,
} from "@/manuspectrum/pages/AnalysisExplorer/store/basket.ts";

const A = "0b3c6f4e-6a39-4e3c-9f7e-1d2c3b4a5f60";
const F = "7d1e2f3a-4b5c-4d6e-8f70-819203a4b5c6";

describe("item keys", () => {
    it("accepts the three key shapes, trimmed and lower-cased", () => {
        expect(normalizeItemKey(` af:${A.toUpperCase()}:${F} `)).toBe(
            `af:${A}:${F}`,
        );
        expect(normalizeItemKey(`im:${A}:3`)).toBe(`im:${A}:3`);
        expect(normalizeItemKey(`ch:${A}:-`)).toBe(`ch:${A}:-`);
    });

    it("rejects anything else", () => {
        for (const raw of [
            "",
            "af:1:2",
            `af:${A}`,
            `ch:${A}:${F}`,
            `im:${A}:x`,
            `im:${A}:12345`,
            `zz:${A}:-`,
            `af:${A}:${F}:extra`,
        ]) {
            expect(normalizeItemKey(raw)).toBeNull();
        }
    });

    it("derives the kind from the prefix", () => {
        expect(kindOf(`af:${A}:${F}`)).toBe("analysis-file");
        expect(kindOf(`im:${A}:0`)).toBe("imaging");
        expect(kindOf(`ch:${A}:-`)).toBe("characterization");
    });

    it("dedupes and counts invalid keys, keeping the first order", () => {
        expect(
            uniqueKeys([`ch:${A}:-`, "bad", `CH:${A}:-`, `im:${A}:1`]),
        ).toEqual({
            keys: [`ch:${A}:-`, `im:${A}:1`],
            invalid: 1,
        });
    });
});

describe("slots", () => {
    it("hands out the lowest free slots", () => {
        const items = [
            { key: "a", kind: "imaging" as const, slot: 0 },
            { key: "b", kind: "imaging" as const, slot: 2 },
        ];
        expect(freeSlots(items, 3)).toEqual([1, 3, 4]);
    });

    it("never goes past the limit", () => {
        expect(freeSlots([], BASKET_LIMIT + 5)).toHaveLength(BASKET_LIMIT);
    });

    it("labels slots A1…A30", () => {
        expect(slotLabel(0)).toBe("A1");
        expect(slotLabel(29)).toBe("A30");
    });
});
