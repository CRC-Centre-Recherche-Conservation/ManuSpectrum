import { describe, expect, it, vi } from "vitest";
import { effectScope, nextTick, ref } from "vue";
import { flushPromises } from "@vue/test-utils";

import { getJson } from "@/manuspectrum/pages/AnalysisExplorer/api/http.ts";
import {
    filterQuery,
    searchQuery,
    useSearch,
} from "@/manuspectrum/pages/AnalysisExplorer/composables/useSearch.ts";
import { emptyFilters } from "@/manuspectrum/pages/AnalysisExplorer/store/explorer.ts";
import { searchResponse } from "@/manuspectrum/pages/AnalysisExplorer/testing/fixtures.ts";

vi.mock("@/manuspectrum/pages/AnalysisExplorer/api/http.ts", () => ({
    getJson: vi.fn(),
}));

describe("searchQuery", () => {
    it("always sends the grain, and nothing else by default", () => {
        expect(searchQuery(emptyFilters(), 1).toString()).toBe(
            "grain=documents",
        );
    });

    it("sends text, facets, years, the page size and the page, never place, period or eventType", () => {
        const query = searchQuery(
            {
                ...emptyFilters(),
                q: "lead",
                grain: "analyses",
                size: 25,
                part: ["p2", "p1"],
                year: [2023, 2021],
                place: "x",
                period: [1000, 1100],
                eventType: ["production"],
            },
            3,
        );
        expect(query.toString()).toBe(
            "q=lead&grain=analyses&size=25&part=p1&part=p2&year=2021&year=2023&page=3",
        );
    });

    it("asks for the documents without analyses only in the documents grain", () => {
        const filters = { ...emptyFilters(), empty: true };
        expect(searchQuery(filters, 1).toString()).toBe(
            "grain=documents&empty=1",
        );
        expect(
            searchQuery({ ...filters, grain: "analyses" }, 1).toString(),
        ).toBe("grain=analyses");
    });

    it("gives the filters alone, without grain, page size nor page", () => {
        expect(
            filterQuery({
                ...emptyFilters(),
                q: "lead",
                grain: "analyses",
                size: 25,
                empty: true,
                technique: ["t2", "t1"],
                year: [2021],
            }).toString(),
        ).toBe("q=lead&technique=t1&technique=t2&year=2021");
    });

    it("asks for one page of a given size", () => {
        expect(searchQuery(emptyFilters(), 4, { size: 1 }).toString()).toBe(
            "grain=documents&size=1&page=4",
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
            query: new URLSearchParams("grain=documents&page=2"),
            signal: expect.any(AbortSignal),
        });
        expect(search?.status.value).toBe("ready");
        expect(search?.data.value).toBe(payload);
        scope.stop();
    });
});
