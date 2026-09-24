import { describe, expect, it } from "vitest";

import { searchQuery } from "@/manuspectrum/pages/AnalysisExplorer/composables/useSearch.ts";
import { emptyFilters } from "@/manuspectrum/pages/AnalysisExplorer/store/explorer.ts";

describe("searchQuery", () => {
    it("always sends the grain and onlyWithAnalyses", () => {
        expect(searchQuery(emptyFilters(), 1).toString()).toBe(
            "grain=documents&onlyWithAnalyses=true",
        );
    });

    it("sends text, facets, years and the page, never place, period or eventType", () => {
        const query = searchQuery(
            {
                ...emptyFilters(),
                q: "lead",
                grain: "analyses",
                onlyWithAnalyses: false,
                part: ["p2", "p1"],
                year: [2023, 2021],
                place: "x",
                period: [1000, 1100],
                eventType: ["production"],
            },
            3,
        );
        expect(query.toString()).toBe(
            "q=lead&grain=analyses&onlyWithAnalyses=false&part=p1&part=p2&year=2021&year=2023&page=3",
        );
    });
});
