import { describe, expect, it } from "vitest";

import {
    aoristic,
    binStart,
    binYearsFor,
    intervalOf,
} from "@/manuspectrum/pages/AnalysisExplorer/views/Map/aoristic.ts";

describe("aoristic histogram", () => {
    it("spreads an event dated 1301–1400 as a quarter in each of its four bins", () => {
        const histogram = aoristic([
            {
                interval: [1301, 1400],
                approximate: false,
                keys: ["production"],
            },
        ]);
        expect(histogram?.binYears).toBe(25);
        const bins =
            histogram?.segments.flatMap((s) =>
                s.kind === "bins" ? s.bins : [],
            ) ?? [];
        expect(bins.map((b) => [b.from, b.to, b.firm.production])).toEqual([
            [1301, 1325, 0.25],
            [1326, 1350, 0.25],
            [1351, 1375, 0.25],
            [1376, 1400, 0.25],
        ]);
    });

    it("puts an approximate event in the lighter band and counts it once per key", () => {
        const histogram = aoristic([
            {
                interval: [1310, 1310],
                approximate: true,
                keys: ["slot:1", "slot:2"],
            },
        ]);
        const [bin] =
            histogram?.segments[0].kind === "bins"
                ? histogram.segments[0].bins
                : [];
        expect(bin.approx).toEqual({ "slot:1": 1, "slot:2": 1 });
        expect(bin.total).toBe(2);
    });

    it("uses 50-year bins beyond 800 years", () => {
        expect(binYearsFor(801)).toBe(50);
        expect(binYearsFor(800)).toBe(25);
        expect(binStart(1349, 50)).toBe(1301);
    });

    it("folds the empty centuries between a 1300 production and a 2024 analysis", () => {
        const histogram = aoristic([
            {
                interval: [1301, 1310],
                approximate: false,
                keys: ["production"],
            },
            { interval: [2024, 2024], approximate: false, keys: ["analysis"] },
        ]);
        expect(histogram?.binYears).toBe(25);
        expect(histogram?.segments.map((s) => s.kind)).toEqual([
            "bins",
            "fold",
            "bins",
        ]);
        expect(histogram?.segments[1]).toEqual({
            kind: "fold",
            from: 1401,
            to: 2000,
        });
    });

    it("reads a single bound as both and leaves an undated event out", () => {
        expect(
            intervalOf({ start: 1300, end: null, approximate: false }),
        ).toEqual([1300, 1300]);
        expect(
            intervalOf({ start: null, end: null, approximate: false }),
        ).toBeNull();
        expect(
            intervalOf({ start: 1400, end: 1300, approximate: false }),
        ).toEqual([1300, 1400]);
        expect(aoristic([])).toBeNull();
    });
});
