import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ref } from "vue";
import { flushPromises, mount } from "@vue/test-utils";
import { createPinia, setActivePinia } from "pinia";

import CorpusHome from "@/manuspectrum/pages/AnalysisExplorer/views/Corpus/CorpusHome.vue";

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

function pageOf(url: string): string | null {
    return new URLSearchParams(url.split("?")[1] ?? "").get("page");
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

    it("features the document with the most analyses", async () => {
        const wrapper = mountHome();
        await flushPromises();
        expect(wrapper.find(".featured .document-card .link").text()).toBe(
            "Manuscript 7",
        );
    });

    it("offers Retry, not the way home, when the overview is unavailable", async () => {
        vi.stubGlobal(
            "fetch",
            vi.fn(async () => jsonResponse({}, 404)),
        );
        const wrapper = mountHome();
        await flushPromises();
        expect(wrapper.find(".unavailable-state .retry").exists()).toBe(true);
        expect(wrapper.find(".unavailable-state .home").exists()).toBe(false);
    });

    it("aborts the other overview pages as soon as one fails", async () => {
        const signals: AbortSignal[] = [];
        vi.stubGlobal(
            "fetch",
            vi.fn(async (url: string, init: RequestInit) => {
                const page = pageOf(url);
                if (page === null || page === "1") {
                    return jsonResponse(
                        searchResponse({
                            results: [documentHit(2)],
                            total: 150,
                            page: { number: 1, size: 50, count: 1 },
                            facets: [facet("technique", 1)],
                        }),
                    );
                }
                if (page === "2") {
                    return jsonResponse({}, 429);
                }
                signals.push(init.signal as AbortSignal);
                return new Promise<Response>(() => {});
            }),
        );
        const wrapper = mountHome();
        await flushPromises();
        expect(signals).toHaveLength(1);
        expect(signals[0].aborted).toBe(true);
        expect(wrapper.find(".unavailable-state .retry").exists()).toBe(true);
    });

    it("features the document with the most analyses over every results page, not only the first", async () => {
        vi.stubGlobal(
            "fetch",
            vi.fn(async (url: string) =>
                pageOf(url) === "2"
                    ? jsonResponse(
                          searchResponse({
                              results: [documentHit(9)],
                              total: 60,
                              page: { number: 2, size: 50, count: 1 },
                          }),
                      )
                    : jsonResponse(
                          searchResponse({
                              results: [documentHit(2)],
                              total: 60,
                              page: { number: 1, size: 50, count: 1 },
                              facets: [facet("technique", 1)],
                          }),
                      ),
            ),
        );
        const wrapper = mountHome();
        await flushPromises();
        expect(wrapper.find(".featured .document-card .link").text()).toBe(
            "Manuscript 9",
        );
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
