import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { effectScope, nextTick, ref } from "vue";
import { flushPromises } from "@vue/test-utils";

import {
    getJson,
    peekJson,
    prefetchJson,
} from "@/manuspectrum/pages/AnalysisExplorer/api/http.ts";
import { DEBOUNCE_MS } from "@/manuspectrum/pages/AnalysisExplorer/composables/useRequest.ts";
import {
    filterQuery,
    filtersOf,
    searchQuery,
    useSearch,
} from "@/manuspectrum/pages/AnalysisExplorer/composables/useSearch.ts";
import { emptyFilters } from "@/manuspectrum/pages/AnalysisExplorer/store/explorer.ts";
import { searchResponse } from "@/manuspectrum/pages/AnalysisExplorer/testing/fixtures.ts";

vi.mock("@/manuspectrum/pages/AnalysisExplorer/api/http.ts", () => ({
    getJson: vi.fn(),
    peekJson: vi.fn(() => null),
    prefetchJson: vi.fn(),
    UnavailableError: class extends Error {},
}));

beforeEach(() => {
    vi.mocked(getJson).mockReset();
    vi.mocked(peekJson).mockReset();
    vi.mocked(peekJson).mockReturnValue(null);
    vi.mocked(prefetchJson).mockReset();
});

afterEach(() => vi.useRealTimers());

function sentQueries(): string[] {
    return vi
        .mocked(getJson)
        .mock.calls.map((call) => String(call[1]?.query ?? ""));
}

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
            reload: false,
        });
        expect(search?.status.value).toBe("ready");
        expect(search?.data.value).toBe(payload);
        scope.stop();
    });

    it("asks for no facets when the client holds those of the filters", async () => {
        vi.mocked(getJson).mockResolvedValue(searchResponse());
        const held = new Set(["q=lead"]);
        const source = ref(new URLSearchParams("q=lead&grain=documents"));
        const scope = effectScope();
        const search = scope.run(() =>
            useSearch(() => source.value, {
                holdsFacets: (filters) => held.has(filters),
            }),
        )!;
        source.value = new URLSearchParams("q=lead&grain=documents&page=2");
        await nextTick();
        source.value = new URLSearchParams("q=tin&grain=documents");
        await nextTick();
        search.prefetch(new URLSearchParams("q=lead&grain=documents&page=3"));
        expect(sentQueries()).toEqual([
            "q=lead&grain=documents&facets=0",
            "q=lead&grain=documents&page=2&facets=0",
            "q=tin&grain=documents",
        ]);
        expect(String(vi.mocked(prefetchJson).mock.calls[0][1]?.query)).toBe(
            "q=lead&grain=documents&page=3&facets=0",
        );
        scope.stop();
    });

    it("waits for the filters to settle, not for a page change", async () => {
        vi.useFakeTimers();
        vi.mocked(getJson).mockResolvedValue(searchResponse());
        const source = ref(new URLSearchParams("grain=documents"));
        const scope = effectScope();
        scope.run(() =>
            useSearch(() => source.value, { debounceFilters: true }),
        );
        source.value = new URLSearchParams("grain=documents&page=2");
        await nextTick();
        expect(getJson).toHaveBeenCalledTimes(2);
        source.value = new URLSearchParams("q=a&grain=documents");
        await nextTick();
        source.value = new URLSearchParams("q=ab&grain=documents");
        await nextTick();
        expect(getJson).toHaveBeenCalledTimes(2);
        vi.advanceTimersByTime(DEBOUNCE_MS);
        expect(sentQueries().at(-1)).toBe("q=ab&grain=documents");
        expect(getJson).toHaveBeenCalledTimes(3);
        scope.stop();
    });

    it("answers from the tab memo without a request", () => {
        const payload = searchResponse({ total: 9 });
        vi.mocked(peekJson).mockReturnValue(payload);
        const scope = effectScope();
        const search = scope.run(() =>
            useSearch(() => new URLSearchParams("grain=documents")),
        )!;
        expect(search.data.value).toBe(payload);
        expect(getJson).not.toHaveBeenCalled();
        scope.stop();
    });
});

describe("filtersOf", () => {
    it("keeps the filters of a search query only", () => {
        expect(
            filtersOf(
                "q=a&grain=analyses&size=25&empty=1&page=2&facets=0&part=p",
            ),
        ).toBe("q=a&part=p");
    });
});
