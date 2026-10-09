import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ref } from "vue";
import { flushPromises, mount } from "@vue/test-utils";
import { createPinia, setActivePinia } from "pinia";

import CorpusHome from "@/manuspectrum/pages/AnalysisExplorer/views/Corpus/CorpusHome.vue";

import { forgetPayloads } from "@/manuspectrum/pages/AnalysisExplorer/api/http.ts";
import { INTENT_MS } from "@/manuspectrum/pages/AnalysisExplorer/composables/useDocumentPrefetch.ts";
import { FACET_LABELS_KEY } from "@/manuspectrum/pages/AnalysisExplorer/injection-keys.ts";
import { useExplorerStore } from "@/manuspectrum/pages/AnalysisExplorer/store/explorer.ts";
import {
    documentHit,
    homeResponse,
    uuid,
} from "@/manuspectrum/pages/AnalysisExplorer/testing/fixtures.ts";
import { jsonResponse } from "@/manuspectrum/pages/AnalysisExplorer/testing/responses.ts";

import type { Ref } from "vue";
import type { Pinia } from "pinia";

import type { Label } from "@/manuspectrum/pages/AnalysisExplorer/api/types.ts";

vi.mock("@/arches/utils/generate-arches-url.ts", () => ({
    generateArchesURL: (
        name: string,
        parameters: Record<string, string> = {},
    ) =>
        `/en/${name}${parameters.resourceid ? `/${parameters.resourceid}` : ""}`,
}));

let pinia: Pinia;
let labels: Ref<Map<string, Label>>;
const fetchMock = vi.fn();

function mountHome() {
    return mount(CorpusHome, {
        global: {
            plugins: [pinia],
            provide: { [FACET_LABELS_KEY as symbol]: labels },
        },
    });
}

function urls(): string[] {
    return fetchMock.mock.calls.map(([url]) => String(url));
}

beforeEach(() => {
    forgetPayloads();
    pinia = createPinia();
    setActivePinia(pinia);
    labels = ref(new Map());
    fetchMock.mockReset();
    fetchMock.mockImplementation(async () => jsonResponse(homeResponse()));
    vi.stubGlobal("fetch", fetchMock);
});

afterEach(() => {
    vi.useRealTimers();
    vi.unstubAllGlobals();
});

describe("CorpusHome", () => {
    it("holds the place of the doors while the home loads", async () => {
        let answer: (response: Response) => void = () => undefined;
        fetchMock.mockImplementation(
            () =>
                new Promise<Response>((resolve) => {
                    answer = resolve;
                }),
        );
        const wrapper = mountHome();
        await flushPromises();
        expect(wrapper.findAll(".door-skeleton")).toHaveLength(3);
        expect(wrapper.find("[role=status]").text()).toBe("Loading…");
        answer(jsonResponse(homeResponse()));
        await flushPromises();
        expect(wrapper.find(".door-skeleton").exists()).toBe(false);
        expect(wrapper.find(".door.techniques").exists()).toBe(true);
    });

    it("asks once for the home of the reader's local day and features its document", async () => {
        vi.useFakeTimers({ toFake: ["Date"] });
        vi.setSystemTime(new Date(2026, 8, 25, 10));
        fetchMock.mockImplementation(async () =>
            jsonResponse(homeResponse({ featured: documentHit(9) })),
        );
        const wrapper = mountHome();
        await flushPromises();
        expect(urls()).toEqual([
            "/en/manuspectrum:explorer-home?day=2026-09-25",
        ]);
        expect(wrapper.find(".featured .title").text()).toBe(
            "Document of the day",
        );
        expect(wrapper.find(".featured .document-card .link").text()).toBe(
            "Manuscript 9",
        );
    });

    it("shows no document of the day when the home has none", async () => {
        const wrapper = mountHome();
        await flushPromises();
        expect(wrapper.find(".door.techniques").exists()).toBe(true);
        expect(wrapper.find(".featured").exists()).toBe(false);
    });

    it("names the technique and project values for the active filters bar", async () => {
        mountHome();
        await flushPromises();
        expect(labels.value.get("technique:technique-1")?.value).toBe(
            "technique 1",
        );
        expect(labels.value.get("project:project-0")?.value).toBe("project 0");
    });

    it("loads the document of the day ahead once the reader rests on its card", async () => {
        fetchMock.mockImplementation(async () =>
            jsonResponse(homeResponse({ featured: documentHit(9) })),
        );
        const wrapper = mountHome();
        await flushPromises();
        vi.useFakeTimers();
        await wrapper.find(".featured .document-card").trigger("pointerenter");
        vi.advanceTimersByTime(INTENT_MS);
        expect(urls().slice(1)).toEqual([
            `/en/manuspectrum:explorer-document/${uuid(9)}`,
            `/en/manuspectrum:explorer-document-match/${uuid(9)}`,
        ]);
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

    it("says so instead of showing the doors when nothing is published", async () => {
        fetchMock.mockImplementation(async () =>
            jsonResponse(
                homeResponse({
                    documentCount: 0,
                    techniques: [],
                    projects: [],
                }),
            ),
        );
        const wrapper = mountHome();
        await flushPromises();
        expect(wrapper.text()).toContain("No analysis published");
        expect(wrapper.find(".doors").exists()).toBe(false);
    });
});
