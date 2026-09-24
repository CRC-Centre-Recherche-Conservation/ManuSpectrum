import { describe, expect, it } from "vitest";

import { characterizationMatches } from "@/manuspectrum/pages/AnalysisExplorer/folio/matching.ts";
import { emptyFilters } from "@/manuspectrum/pages/AnalysisExplorer/store/explorer.ts";
import {
    characterization,
    valueRef,
} from "@/manuspectrum/pages/AnalysisExplorer/testing/fixtures.ts";

describe("identified material matching", () => {
    it("keeps every identified material when no material filter is set", () => {
        expect(
            characterizationMatches(characterization(1), {
                ...emptyFilters(),
                technique: ["t:xrf"],
            }),
        ).toBe(true);
    });

    it("keeps one that carries a selected material, colour, element or layer", () => {
        const summary = characterization(1, {
            elements: [{ level: null, values: [valueRef("el:Hg", "Hg")] }],
        });
        expect(
            characterizationMatches(summary, {
                ...emptyFilters(),
                material: ["http://example.org/vermilion"],
            }),
        ).toBe(true);
        expect(
            characterizationMatches(summary, {
                ...emptyFilters(),
                element: ["el:Hg"],
            }),
        ).toBe(true);
        expect(
            characterizationMatches(summary, {
                ...emptyFilters(),
                colour: ["http://example.org/blue"],
            }),
        ).toBe(false);
    });

    it("needs every material facet to agree", () => {
        const filters = {
            ...emptyFilters(),
            material: ["http://example.org/vermilion"],
            colour: ["http://example.org/blue"],
        };
        expect(characterizationMatches(characterization(1), filters)).toBe(
            false,
        );
    });
});
