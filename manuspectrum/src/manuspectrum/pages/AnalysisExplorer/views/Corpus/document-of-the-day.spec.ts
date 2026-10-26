import { describe, expect, it } from "vitest";

import { localDay } from "@/manuspectrum/pages/AnalysisExplorer/views/Corpus/document-of-the-day.ts";

describe("document of the day", () => {
    it("names the local day", () => {
        expect(localDay(new Date(2026, 8, 5, 23, 59))).toBe("2026-09-05");
        expect(localDay(new Date(2026, 11, 31, 0, 1))).toBe("2026-12-31");
    });
});
