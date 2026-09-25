import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ref } from "vue";
import { flushPromises, mount } from "@vue/test-utils";
import { createPinia, setActivePinia } from "pinia";
import PrimeVue from "primevue/config";

import CorpusResults from "@/manuspectrum/pages/AnalysisExplorer/views/Corpus/CorpusResults.vue";

import { FACET_LABELS_KEY } from "@/manuspectrum/pages/AnalysisExplorer/injection-keys.ts";
import { useExplorerStore } from "@/manuspectrum/pages/AnalysisExplorer/store/explorer.ts";
import {
    analysisHit,
    documentHit,
    facet,
    label,
    searchResponse,
} from "@/manuspectrum/pages/AnalysisExplorer/testing/fixtures.ts";
import { jsonResponse } from "@/manuspectrum/pages/AnalysisExplorer/testing/responses.ts";

import type { Ref } from "vue";
import type { Pinia } from "pinia";

import type {
    Facet,
    Label,
} from "@/manuspectrum/pages/AnalysisExplorer/api/types.ts";

vi.mock("@/arches/utils/generate-arches-url.ts", () => ({
    generateArchesURL: (name: string) => `/en/${name}`,
}));

const fetchMock = vi.fn();
let pinia: Pinia;
let labels: Ref<Map<string, Label>>;

function queryOf(call: unknown[]): URLSearchParams {
    return new URLSearchParams(String(call[0]).split("?")[1] ?? "");
}

function mountResults() {
    return mount(CorpusResults, {
        global: {
            plugins: [pinia, PrimeVue],
            provide: { [FACET_LABELS_KEY as symbol]: labels },
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

    it("offers documents without analyses at zero results, with their count", async () => {
        fetchMock.mockImplementation(async (url: string) =>
            new URLSearchParams(url.split("?")[1]).get("onlyWithAnalyses") ===
            "false"
                ? jsonResponse(
                      searchResponse({ results: [documentHit(3)], total: 1 }),
                  )
                : jsonResponse(searchResponse({ results: [], total: 0 })),
        );
        const store = useExplorerStore();
        store.setFilter("q", "zzz");
        const wrapper = mountResults();
        await flushPromises();
        const include = wrapper.find(".include-without");
        expect(include.text()).toBe("Include documents without analyses (1)");
        expect(wrapper.find(".remove-filter").text()).toBe("Remove: Text: zzz");
        await include.trigger("click");
        expect(store.filters.onlyWithAnalyses).toBe(false);
    });

    it("hides the include button in the analyses grain", async () => {
        fetchMock.mockResolvedValue(
            jsonResponse(searchResponse({ results: [], total: 0 })),
        );
        useExplorerStore().setFilter("grain", "analyses");
        const wrapper = mountResults();
        await flushPromises();
        expect(wrapper.find(".include-without").exists()).toBe(false);
        expect(fetchMock).toHaveBeenCalledTimes(1);
    });

    it("writes facet changes to the store and records the value labels", async () => {
        const year: Facet = {
            key: "year",
            values: [
                ...facet("year", 2).values,
                { id: "2021", label: label("2021"), count: 1, selected: false },
            ],
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
