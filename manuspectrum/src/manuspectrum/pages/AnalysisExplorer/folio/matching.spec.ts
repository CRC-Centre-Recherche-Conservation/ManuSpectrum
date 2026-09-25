import { describe, expect, it } from "vitest";

import { characterizationMatches } from "@/manuspectrum/pages/AnalysisExplorer/folio/matching.ts";
import { emptyFilters } from "@/manuspectrum/pages/AnalysisExplorer/store/explorer.ts";
import {
    characterization,
    label,
    valueRef,
} from "@/manuspectrum/pages/AnalysisExplorer/testing/fixtures.ts";

import type {
    Facet,
    FacetValue,
} from "@/manuspectrum/pages/AnalysisExplorer/api/types.ts";

const FACETS: Facet[] = [
    {
        key: "material",
        values: [facetValue("http://example.org/vermilion")],
    },
    { key: "colour", values: [facetValue("http://example.org/blue")] },
    { key: "element", values: [facetValue("el:Hg")] },
];

function facetValue(id: string): FacetValue {
    return { id, label: label(id), count: 1, selected: false };
}

describe("identified material matching", () => {
    it("keeps every identified material when no material filter is set", () => {
        expect(
            characterizationMatches(
                characterization(1),
                {
                    ...emptyFilters(),
                    technique: ["t:xrf"],
                },
                FACETS,
            ),
        ).toBe(true);
    });

    it("keeps one that carries a selected material, colour, element or layer", () => {
        const summary = characterization(1, {
            elements: [{ level: null, values: [valueRef("el:Hg", "Hg")] }],
        });
        expect(
            characterizationMatches(
                summary,
                {
                    ...emptyFilters(),
                    material: ["http://example.org/vermilion"],
                },
                FACETS,
            ),
        ).toBe(true);
        expect(
            characterizationMatches(
                summary,
                {
                    ...emptyFilters(),
                    element: ["el:Hg"],
                },
                FACETS,
            ),
        ).toBe(true);
        expect(
            characterizationMatches(
                summary,
                {
                    ...emptyFilters(),
                    colour: ["http://example.org/blue"],
                },
                FACETS,
            ),
        ).toBe(false);
    });

    it("needs every material facet to agree", () => {
        const filters = {
            ...emptyFilters(),
            material: ["http://example.org/vermilion"],
            colour: ["http://example.org/blue"],
        };
        expect(
            characterizationMatches(characterization(1), filters, FACETS),
        ).toBe(false);
    });

    it("ignores a selected value that no facet of the search offers, as the server does", () => {
        const filters = {
            ...emptyFilters(),
            colour: ["http://example.org/not-in-the-corpus"],
        };
        expect(
            characterizationMatches(characterization(1), filters, FACETS),
        ).toBe(true);
        expect(characterizationMatches(characterization(1), filters, [])).toBe(
            true,
        );
    });
});
