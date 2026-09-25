import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ref } from "vue";
import { flushPromises, mount } from "@vue/test-utils";
import { createPinia, setActivePinia } from "pinia";

import CorpusHome from "@/manuspectrum/pages/AnalysisExplorer/views/Corpus/CorpusHome.vue";

import { dayIndex } from "@/manuspectrum/pages/AnalysisExplorer/views/Corpus/document-of-the-day.ts";
import { FACET_LABELS_KEY } from "@/manuspectrum/pages/AnalysisExplorer/injection-keys.ts";
import { useExplorerStore } from "@/manuspectrum/pages/AnalysisExplorer/store/explorer.ts";
import {
    documentHit,
    facet,
    searchResponse,
} from "@/manuspectrum/pages/AnalysisExplorer/testing/fixtures.ts";
import { jsonResponse } from "@/manuspectrum/pages/AnalysisExplorer/testing/responses.ts";

import type { Pinia } from "pinia";

vi.mock("@/arches/utils/generate-arches-url.ts", () => ({
    generateArchesURL: (name: string) => `/en/${name}`,
}));

let pinia: Pinia;

function mountHome() {
    return mount(CorpusHome, {
        global: {
            plugins: [pinia],
            provide: { [FACET_LABELS_KEY as symbol]: ref(new Map()) },
        },
    });
}

function queryOf(url: string): URLSearchParams {
    return new URLSearchParams(url.split("?")[1] ?? "");
}

function sizeOf(url: string): string | null {
    return queryOf(url).get("size");
}

beforeEach(() => {
    pinia = createPinia();
    setActivePinia(pinia);
});

afterEach(() => vi.unstubAllGlobals());

describe("CorpusHome", () => {
    beforeEach(() => {
        vi.stubGlobal(
            "fetch",
            vi.fn(async () =>
                jsonResponse(
                    searchResponse({
                        results: [
                            documentHit(2),
                            documentHit(7),
                            documentHit(4),
                        ],
                        total: 3,
                        facets: [facet("technique", 2), facet("project", 1)],
                    }),
                ),
            ),
        );
    });

    it("holds the place of the doors while the overview loads", async () => {
        let answer: (response: Response) => void = () => undefined;
        vi.stubGlobal(
            "fetch",
            vi.fn(
                () =>
                    new Promise<Response>((resolve) => {
                        answer = resolve;
                    }),
            ),
        );
        const wrapper = mountHome();
        await flushPromises();
        expect(wrapper.findAll(".door-skeleton")).toHaveLength(3);
        expect(wrapper.find("[role=status]").text()).toBe("Loading…");
        answer(
            jsonResponse(
                searchResponse({
                    results: [documentHit(2)],
                    total: 1,
                    facets: [facet("technique", 2)],
                }),
            ),
        );
        await flushPromises();
        expect(wrapper.find(".door-skeleton").exists()).toBe(false);
        expect(wrapper.find(".door.techniques").exists()).toBe(true);
    });

    it("features the document of the day: one page of size 1 at the day's position", async () => {
        vi.useFakeTimers({ toFake: ["Date"] });
        vi.setSystemTime(new Date(2026, 8, 25, 10));
        const fetchMock = vi.fn(async (url: string) =>
            sizeOf(url) === "1"
                ? jsonResponse(
                      searchResponse({
                          results: [documentHit(9)],
                          total: 55,
                          page: { number: 35, size: 1, count: 1 },
                      }),
                  )
                : jsonResponse(
                      searchResponse({
                          results: [documentHit(2)],
                          total: 55,
                          page: { number: 1, size: 10, count: 1 },
                          facets: [facet("technique", 1)],
                      }),
                  ),
        );
        vi.stubGlobal("fetch", fetchMock);
        const wrapper = mountHome();
        await flushPromises();
        const urls = fetchMock.mock.calls.map(([url]) => url);
        expect(urls).toHaveLength(2);
        expect(queryOf(urls[1]).toString()).toBe(
            `grain=documents&size=1&page=${dayIndex(new Date(2026, 8, 25), 55)! + 1}`,
        );
        expect(wrapper.find(".featured .title").text()).toBe(
            "Document of the day",
        );
        expect(wrapper.find(".featured .document-card .link").text()).toBe(
            "Manuscript 9",
        );
        vi.useRealTimers();
    });

    it("shows the other doors before the document of the day arrives", async () => {
        vi.stubGlobal(
            "fetch",
            vi.fn((url: string) =>
                sizeOf(url) === "1"
                    ? new Promise<Response>(() => {})
                    : Promise.resolve(
                          jsonResponse(
                              searchResponse({
                                  total: 3,
                                  facets: [facet("technique", 2)],
                              }),
                          ),
                      ),
            ),
        );
        const wrapper = mountHome();
        await flushPromises();
        expect(wrapper.find(".door.techniques").exists()).toBe(true);
        expect(wrapper.find(".featured .ms-skeleton").exists()).toBe(true);
    });

    it("opens the whole corpus in the results, with no filter", async () => {
        const store = useExplorerStore();
        const wrapper = mountHome();
        await flushPromises();
        await wrapper.find(".browse-all").trigger("click");
        expect(store.corpusScreen).toBe("results");
        expect(store.activeFilterCount).toBe(0);
    });

    it("opens the results filtered by a technique, at the analyses grain", async () => {
        const store = useExplorerStore();
        const wrapper = mountHome();
        await flushPromises();
        await wrapper.findAll(".techniques button")[1].trigger("click");
        expect(store.filters.technique).toEqual(["technique-1"]);
        expect(store.filters.grain).toBe("analyses");
        expect(store.corpusScreen).toBe("results");
    });

    it("opens the results filtered by a project", async () => {
        const store = useExplorerStore();
        const wrapper = mountHome();
        await flushPromises();
        await wrapper.find(".projects button").trigger("click");
        expect(store.filters.project).toEqual(["project-0"]);
        expect(store.corpusScreen).toBe("results");
    });

    it("searches the typed text", async () => {
        const store = useExplorerStore();
        const wrapper = mountHome();
        await wrapper.find("input[type=search]").setValue("  vermilion ");
        await wrapper.find("form").trigger("submit");
        expect(store.filters.q).toBe("vermilion");
        expect(store.corpusScreen).toBe("results");
    });
});

describe("CorpusHome with no published analysis", () => {
    it("says so instead of showing the doors", async () => {
        vi.stubGlobal(
            "fetch",
            vi.fn(async () =>
                jsonResponse(searchResponse({ results: [], total: 0 })),
            ),
        );
        const wrapper = mountHome();
        await flushPromises();
        expect(wrapper.text()).toContain("No analysis published");
        expect(wrapper.find(".doors").exists()).toBe(false);
    });
});
