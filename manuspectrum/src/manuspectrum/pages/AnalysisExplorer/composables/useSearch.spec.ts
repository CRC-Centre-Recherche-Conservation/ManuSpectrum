import { describe, expect, it, vi } from "vitest";
import { effectScope, nextTick, ref } from "vue";
import { flushPromises } from "@vue/test-utils";

import { getJson } from "@/manuspectrum/pages/AnalysisExplorer/api/http.ts";
import {
    searchQuery,
    useSearch,
} from "@/manuspectrum/pages/AnalysisExplorer/composables/useSearch.ts";
import { emptyFilters } from "@/manuspectrum/pages/AnalysisExplorer/store/explorer.ts";
import { searchResponse } from "@/manuspectrum/pages/AnalysisExplorer/testing/fixtures.ts";

vi.mock("@/manuspectrum/pages/AnalysisExplorer/api/http.ts", () => ({
    getJson: vi.fn(),
}));

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

describe("useSearch", () => {
    it("asks the search route for the source query and stays idle without one", async () => {
        const payload = searchResponse({ total: 4 });
        vi.mocked(getJson).mockResolvedValue(payload);
        const source = ref<URLSearchParams | null>(null);
        const scope = effectScope();
        const search = scope.run(() => useSearch(() => source.value));
        expect(search?.status.value).toBe("idle");
        expect(getJson).not.toHaveBeenCalled();

        source.value = searchQuery(emptyFilters(), 2);
        await nextTick();
        await flushPromises();
        expect(getJson).toHaveBeenCalledWith("manuspectrum:explorer-search", {
            query: new URLSearchParams(
                "grain=documents&onlyWithAnalyses=true&page=2",
            ),
            signal: expect.any(AbortSignal),
        });
        expect(search?.status.value).toBe("ready");
        expect(search?.data.value).toBe(payload);
        scope.stop();
    });
});
