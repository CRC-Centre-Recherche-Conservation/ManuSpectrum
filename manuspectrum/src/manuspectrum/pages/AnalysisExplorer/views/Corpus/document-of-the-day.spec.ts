// @vitest-environment node
//
// The shared vectors are read from the file system; jsdom's URL would not
// convert to a path (see api/types.spec.ts).
import fs from "fs";
import { fileURLToPath } from "url";
import { describe, expect, it } from "vitest";

import {
    dayIndex,
    localDay,
} from "@/manuspectrum/pages/AnalysisExplorer/views/Corpus/document-of-the-day.ts";

const VECTORS = fileURLToPath(
    new URL(
        "../../../../../../../tests/fixtures/explorer_day_index.json",
        import.meta.url,
    ),
);

describe("document of the day", () => {
    it("follows the vectors the server's day_index shares", () => {
        const vectors = JSON.parse(fs.readFileSync(VECTORS, "utf-8")) as {
            day: string;
            count: number;
            index: number;
        }[];
        expect(vectors.length).toBeGreaterThan(0);
        for (const { day, count, index } of vectors) {
            const [year, month, date] = day.split("-").map(Number);
            expect(dayIndex(new Date(year, month - 1, date), count)).toBe(
                index,
            );
        }
    });

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
