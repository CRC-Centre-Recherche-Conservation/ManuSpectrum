import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ref } from "vue";
import { flushPromises, mount } from "@vue/test-utils";
import { createPinia, setActivePinia } from "pinia";
import PrimeVue from "primevue/config";

import CorpusResults from "@/manuspectrum/pages/AnalysisExplorer/views/Corpus/CorpusResults.vue";

import {
    FACET_LABELS_KEY,
    RESULTS_MEMO_KEY,
} from "@/manuspectrum/pages/AnalysisExplorer/injection-keys.ts";
import { useExplorerStore } from "@/manuspectrum/pages/AnalysisExplorer/store/explorer.ts";
import {
    analysisHit,
    documentHit,
    facet,
    facetValue,
    searchResponse,
} from "@/manuspectrum/pages/AnalysisExplorer/testing/fixtures.ts";
import { jsonResponse } from "@/manuspectrum/pages/AnalysisExplorer/testing/responses.ts";

import type { Ref } from "vue";
import type { Pinia } from "pinia";

import type {
    Facet,
    Label,
} from "@/manuspectrum/pages/AnalysisExplorer/api/types.ts";
import type { ResultsMemo } from "@/manuspectrum/pages/AnalysisExplorer/injection-keys.ts";

vi.mock("@/arches/utils/generate-arches-url.ts", () => ({
    generateArchesURL: (name: string) => `/en/${name}`,
}));

const fetchMock = vi.fn();
let pinia: Pinia;
let labels: Ref<Map<string, Label>>;

function queryOf(call: unknown[]): URLSearchParams {
    return new URLSearchParams(String(call[0]).split("?")[1] ?? "");
}

function mountResults({
    memo = ref<ResultsMemo | null>(null),
    attach = false,
}: { memo?: Ref<ResultsMemo | null>; attach?: boolean } = {}) {
    return mount(CorpusResults, {
        attachTo: attach ? document.body : undefined,
        global: {
            plugins: [pinia, PrimeVue],
            provide: {
                [FACET_LABELS_KEY as symbol]: labels,
                [RESULTS_MEMO_KEY as symbol]: memo,
            },
        },
    });
}

beforeEach(() => {
    pinia = createPinia();
    setActivePinia(pinia);
    labels = ref(new Map());
    fetchMock.mockReset();
    vi.stubGlobal("fetch", fetchMock);
});

afterEach(() => vi.unstubAllGlobals());

describe("CorpusResults", () => {
    it("announces the result count with the right plural and lists document cards", async () => {
        fetchMock.mockResolvedValue(
            jsonResponse(
                searchResponse({ results: [documentHit(1)], total: 1 }),
            ),
        );
        const wrapper = mountResults();
        await flushPromises();
        expect(wrapper.find("[aria-live=polite]").text()).toBe("1 result");
        expect(wrapper.findAll(".document-card")).toHaveLength(1);
        expect(queryOf(fetchMock.mock.calls[0]).get("grain")).toBe("documents");
    });

    it("switches to analyses with a badge per data kind and the draft banner", async () => {
        fetchMock.mockResolvedValue(
            jsonResponse(
                searchResponse({
                    results: [
                        analysisHit(1, {
                            dataKinds: ["xy", "chemical-imaging"],
                            unpublished: true,
                        }),
                    ],
                    total: 1,
                    unpublishedCount: 1,
                }),
            ),
        );
        const store = useExplorerStore();
        store.setFilter("grain", "analyses");
        const wrapper = mountResults();
        await flushPromises();
        expect(
            wrapper
                .findAll(".analysis-row .badge")
                .map((badge) => badge.text()),
        ).toEqual(["spectrum", "map", "Draft"]);
        expect(wrapper.find(".draft-banner").text()).toContain(
            "1 draft in these results",
        );
        expect(wrapper.find(".only-with-analyses").exists()).toBe(false);
    });

    it("offers the documents without analyses under the list, and hides them again", async () => {
        fetchMock.mockResolvedValue(
            jsonResponse(searchResponse({ withoutAnalyses: 3 })),
        );
        const store = useExplorerStore();
        const wrapper = mountResults();
        await flushPromises();
        expect(wrapper.find(".only-with-analyses").exists()).toBe(false);
        const toggle = wrapper.find(".without-analyses button");
        expect(toggle.text()).toBe("+ 3 documents without analyses — show");
        await toggle.trigger("click");
        await flushPromises();
        expect(store.filters.empty).toBe(true);
        expect(queryOf(fetchMock.mock.lastCall!).get("empty")).toBe("1");
        expect(wrapper.find(".without-analyses button").text()).toBe(
            "Hide the 3 documents without analyses",
        );
    });

    it("says nothing of documents without analyses when there are none or in the analyses grain", async () => {
        fetchMock.mockResolvedValue(
            jsonResponse(searchResponse({ results: [], total: 0 })),
        );
        useExplorerStore().setFilter("grain", "analyses");
        const wrapper = mountResults();
        await flushPromises();
        expect(wrapper.find(".without-analyses").exists()).toBe(false);
        expect(wrapper.find(".remove-filter").exists()).toBe(false);
        expect(fetchMock).toHaveBeenCalledTimes(1);
    });

    it("shows 10, 25 or 50 results a page and asks for the size chosen", async () => {
        fetchMock.mockResolvedValue(jsonResponse(searchResponse()));
        const store = useExplorerStore();
        const wrapper = mountResults();
        await flushPromises();
        expect(queryOf(fetchMock.mock.lastCall!).get("size")).toBeNull();
        const sizes = wrapper.findAll(".page-size button");
        expect(sizes.map((button) => button.text())).toEqual([
            "10",
            "25",
            "50",
        ]);
        expect(sizes[0].attributes("aria-pressed")).toBe("true");
        await sizes[1].trigger("click");
        await flushPromises();
        expect(store.filters.size).toBe(25);
        expect(queryOf(fetchMock.mock.lastCall!).get("size")).toBe("25");
    });

    it("comes back from a document to the same results, scroll and card, without asking again", async () => {
        fetchMock.mockResolvedValue(
            jsonResponse(
                searchResponse({
                    results: [documentHit(1), documentHit(2)],
                    total: 30,
                    page: { number: 1, size: 10, count: 2 },
                }),
            ),
        );
        const memo = ref<ResultsMemo | null>(null);
        const scrollTo = vi.fn();
        vi.stubGlobal("scrollTo", scrollTo);
        const store = useExplorerStore();
        const first = mountResults({ memo, attach: true });
        await flushPromises();
        await first.find(".pagination .next").trigger("click");
        await flushPromises();
        Object.defineProperty(window, "scrollY", {
            value: 640,
            configurable: true,
        });
        await first
            .findAll(".document-card .link")[1]
            .trigger("click", { button: 0 });
        first.unmount();
        const calls = fetchMock.mock.calls.length;

        store.setCorpusScreen("results");
        const back = mountResults({ memo, attach: true });
        await flushPromises();
        expect(fetchMock.mock.calls.length).toBe(calls);
        expect(back.find(".pagination").text()).toContain("Page 2 of 3");
        expect(scrollTo).toHaveBeenCalledWith(0, 640);
        expect(document.activeElement?.textContent).toBe("Manuscript 2");
        back.unmount();
    });

    it("writes facet changes to the store and records the value labels", async () => {
        const year: Facet = {
            key: "year",
            group: "analysis",
            values: [...facet("year", 2).values, facetValue("2021")],
        };
        fetchMock.mockResolvedValue(
            jsonResponse(
                searchResponse({ facets: [facet("technique", 2), year] }),
            ),
        );
        const store = useExplorerStore();
        const wrapper = mountResults();
        await flushPromises();
        expect(labels.value.get("year:year-1")?.value).toBe("year 1");
        const [techniqueSet, yearSet] = wrapper.findAll(".facet-rail fieldset");
        await yearSet.findAll("input")[1].setValue(true);
        expect(store.filters.year).toEqual([]);
        await techniqueSet.findAll("input")[1].setValue(true);
        expect(store.filters.technique).toEqual(["technique-1"]);
        await yearSet.findAll("input")[2].setValue(true);
        expect(store.filters.year).toEqual([2021]);
    });

    it("opens a document from its card", async () => {
        fetchMock.mockResolvedValue(
            jsonResponse(
                searchResponse({ results: [documentHit(1)], total: 1 }),
            ),
        );
        const store = useExplorerStore();
        const wrapper = mountResults();
        await flushPromises();
        await wrapper
            .find(".document-card .link")
            .trigger("click", { button: 0 });
        expect(store.corpusScreen).toBe("document");
        expect(store.document?.id).toBe(documentHit(1).id);
    });

    it("opens an analysis on its document with the focus on it", async () => {
        fetchMock.mockResolvedValue(
            jsonResponse(
                searchResponse({
                    results: [analysisHit(1, { canvas: "c1" })],
                    total: 1,
                }),
            ),
        );
        const store = useExplorerStore();
        store.setFilter("grain", "analyses");
        const wrapper = mountResults();
        await flushPromises();
        await wrapper.find(".analysis-row .link").trigger("click");
        expect(store.document).toEqual({
            id: analysisHit(1).document.id,
            canvas: "c1",
        });
        expect(store.focus).toEqual({
            kind: "analysis",
            id: analysisHit(1).id,
        });
    });

    it("pages through results and returns to page 1 when a filter changes", async () => {
        fetchMock.mockResolvedValue(
            jsonResponse(
                searchResponse({
                    total: 120,
                    page: { number: 1, size: 50, count: 50 },
                }),
            ),
        );
        const store = useExplorerStore();
        const wrapper = mountResults();
        await flushPromises();
        expect(wrapper.find(".pagination").text()).toContain("Page 1 of 3");
        await wrapper.find(".pagination .next").trigger("click");
        await flushPromises();
        expect(queryOf(fetchMock.mock.lastCall!).get("page")).toBe("2");
        const callsBefore = fetchMock.mock.calls.length;
        store.setFilter("q", "gold");
        await flushPromises();
        expect(fetchMock.mock.calls.length).toBe(callsBefore + 1);
        expect(queryOf(fetchMock.mock.lastCall!).get("page")).toBeNull();
    });

    it("shows the retry state on a 503 and reloads on Retry", async () => {
        fetchMock
            .mockResolvedValueOnce(jsonResponse({}, 503))
            .mockResolvedValueOnce(jsonResponse(searchResponse()));
        const wrapper = mountResults();
        await flushPromises();
        expect(wrapper.find(".unavailable-state .retry").exists()).toBe(true);
        await wrapper.find(".unavailable-state .retry").trigger("click");
        await flushPromises();
        expect(wrapper.findAll(".document-card")).toHaveLength(2);
    });

    it("folds the rail behind a Filters button that counts active filters below 80rem", async () => {
        vi.stubGlobal("matchMedia", (query: string) => ({
            matches: query.includes("80rem"),
            media: query,
            addEventListener: () => undefined,
            removeEventListener: () => undefined,
        }));
        fetchMock.mockResolvedValue(jsonResponse(searchResponse()));
        useExplorerStore().setFilter("technique", ["t1", "t2"]);
        const wrapper = mountResults();
        await flushPromises();
        const toggle = wrapper.find(".rail .toggle");
        expect(toggle.text()).toBe("Filters (2)");
        expect(toggle.attributes("aria-expanded")).toBe("false");
        expect(wrapper.find(".facet-rail").exists()).toBe(false);
    });

    it("shows card placeholders on the first load, then dims the old list while the next one loads", async () => {
        let answer: (response: Response) => void = () => undefined;
        fetchMock.mockImplementation(
            () =>
                new Promise<Response>((resolve) => {
                    answer = resolve;
                }),
        );
        const wrapper = mountResults();
        await flushPromises();
        expect(wrapper.findAll(".card-skeleton")).toHaveLength(4);
        expect(wrapper.find("[role=status]").text()).toBe("Loading…");
        answer(jsonResponse(searchResponse()));
        await flushPromises();
        expect(wrapper.find(".card-skeleton").exists()).toBe(false);
        useExplorerStore().setFilter("grain", "analyses");
        await flushPromises();
        const list = wrapper.find(".list");
        expect(list.attributes("aria-busy")).toBe("true");
        expect(list.findAll(".document-card")).toHaveLength(2);
        expect(wrapper.find("[role=status]").text()).toBe("Updating…");
    });
});
