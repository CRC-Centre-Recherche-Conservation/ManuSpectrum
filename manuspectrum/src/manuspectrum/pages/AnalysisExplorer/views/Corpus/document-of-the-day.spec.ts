import { describe, expect, it } from "vitest";

import {
    dayIndex,
    localDay,
} from "@/manuspectrum/pages/AnalysisExplorer/views/Corpus/document-of-the-day.ts";

describe("document of the day", () => {
    it("names the local day", () => {
        expect(localDay(new Date(2026, 8, 5, 23, 59))).toBe("2026-09-05");
    });

    it("picks the same position all day, within the count", () => {
        const morning = new Date(2026, 8, 25, 0, 1);
        const evening = new Date(2026, 8, 25, 23, 59);
        expect(dayIndex(morning, 55)).toBe(dayIndex(evening, 55));
        expect(dayIndex(morning, 55)).toBe(34);
        for (let day = 1; day <= 30; day += 1) {
            const index = dayIndex(new Date(2026, 8, day), 7);
            expect(index).toBeGreaterThanOrEqual(0);
            expect(index).toBeLessThan(7);
        }
    });

    it("moves on from one day to the next", () => {
        const picks = new Set(
            Array.from({ length: 10 }, (_, day) =>
                dayIndex(new Date(2026, 8, day + 1), 55),
            ),
        );
        expect(picks.size).toBeGreaterThan(5);
    });

    it("has nothing to pick among no document", () => {
        expect(dayIndex(new Date(2026, 8, 25), 0)).toBeNull();
    });
});
