import { describe, expect, it } from "vitest";

import { firstStoredTitle } from "@/manuspectrum/pages/AnalysisExplorer/xy/axis-titles.ts";

describe("firstStoredTitle", () => {
    it("takes the first title that holds text, trimmed", () => {
        expect(
            firstStoredTitle([null, "  ", undefined, " Counts ", "Net"]),
        ).toBe("Counts");
    });

    it("is null when no title holds text", () => {
        expect(firstStoredTitle([null, "", " "])).toBeNull();
        expect(firstStoredTitle([])).toBeNull();
    });
});
