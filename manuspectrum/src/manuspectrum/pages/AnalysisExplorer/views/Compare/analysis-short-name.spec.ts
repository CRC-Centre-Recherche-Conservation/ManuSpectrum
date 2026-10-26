import { describe, expect, it } from "vitest";

import { shortAnalysisName } from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/analysis-short-name.ts";

describe("shortAnalysisName", () => {
    it("keeps the first segment of a name with spaced dashes", () => {
        expect(
            shortAnalysisName(
                "MAN12-MA-XRF-0031 — MA-XRF — parchemin — 61v — Manchester",
            ),
        ).toBe("MAN12-MA-XRF-0031");
    });

    it("returns a name with no separator whole", () => {
        expect(shortAnalysisName('maXRF - "C" initial - f13v')).toBe(
            'maXRF - "C" initial - f13v',
        );
    });

    it("returns the name whole when its first segment is empty", () => {
        expect(shortAnalysisName(" —  — tail")).toBe(" —  — tail");
    });

    it("does not split a hyphen without spaces", () => {
        expect(shortAnalysisName("MON9720-HSI-0596")).toBe("MON9720-HSI-0596");
    });
});
