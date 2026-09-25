import { flushPromises, mount } from "@vue/test-utils";
import { createPinia, setActivePinia } from "pinia";
import PrimeVue from "primevue/config";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { defineComponent, h } from "vue";

import CorpusDocument from "@/manuspectrum/pages/AnalysisExplorer/views/Corpus/CorpusDocument.vue";

import { useExplorerStore } from "@/manuspectrum/pages/AnalysisExplorer/store/explorer.ts";
import {
    annotation,
    characterization,
    documentPayload,
    searchResponse,
    uuid,
} from "@/manuspectrum/pages/AnalysisExplorer/testing/fixtures.ts";
import { jsonResponse } from "@/manuspectrum/pages/AnalysisExplorer/testing/responses.ts";

import type { Pinia } from "pinia";
import type { PropType } from "vue";

import type { ExplorerStore } from "@/manuspectrum/pages/AnalysisExplorer/store/explorer.ts";
import type { LayerToggles } from "@/manuspectrum/pages/AnalysisExplorer/store/types.ts";

vi.mock("@/arches/utils/generate-arches-url.ts", () => ({
    generateArchesURL: (
        name: string,
        parameters: Record<string, string> = {},
    ) =>
        name === "manuspectrum:explorer-search"
            ? "/en/api/explorer/search"
            : `/en/api/explorer/${name.split("explorer-")[1]}/${parameters.resourceid}`,
}));

const focusTarget = vi.fn();
const FolioStub = defineComponent({
    name: "FolioMap",
    props: {
        canvas: { type: Object, default: null },
        annotations: { type: Array, default: () => [] },
        characterizations: { type: Array, default: () => [] },
        styles: { type: Map, default: () => new Map() },
        focus: { type: Object, default: null },
        slots: { type: Map, default: () => new Map() },
        lit: { type: Set, default: null },
        dimmedMaterials: { type: Set, default: () => new Set() },
        layers: { type: Object as PropType<LayerToggles>, required: true },
        overlays: { type: Array, default: () => [] },
        curtain: { type: String, default: null },
    },
    emits: ["select"],
    setup(_props, { expose }) {
        expose({ focusTarget });
        return () => h("div", { class: "folio-stub" });
    },
});

let narrow = false;
let pinia: Pinia;

beforeEach(() => {
    narrow = false;
    focusTarget.mockClear();
    pinia = createPinia();
    setActivePinia(pinia);
    vi.stubGlobal("matchMedia", (query: string) => ({
        matches: narrow && query.includes("48rem"),
        media: query,
        addEventListener: () => undefined,
        removeEventListener: () => undefined,
    }));
});

afterEach(() => vi.unstubAllGlobals());

function stubFetch(
    payload = documentPayload({
        annotations: [
            annotation(1),
            annotation(2, { canvas: "https://iiif.example/c2" }),
        ],
    }),
    status = 200,
) {
    const fetchMock = vi.fn(async (url: string) =>
        url.includes("/search")
            ? jsonResponse(searchResponse({ results: [] }))
            : jsonResponse(payload, status),
    );
    vi.stubGlobal("fetch", fetchMock);
    return fetchMock;
}

function mountScreen(
    prepare: (store: ExplorerStore) => void = (store) =>
        store.openDocument(uuid(1)),
) {
    const store = useExplorerStore();
    prepare(store);
    const wrapper = mount(CorpusDocument, {
        props: { documentId: uuid(1) },
        global: {
            plugins: [pinia, PrimeVue],
            stubs: {
                FolioMap: FolioStub,
                AnalysisCard: true,
                CharacterizationCard: true,
            },
        },
    });
    return { wrapper, store };
}

describe("CorpusDocument", () => {
    it("asks the document with the Corpus filters", async () => {
        const fetchMock = stubFetch();
        const { store } = mountScreen();
        store.setFilter("technique", ["http://example.org/xrf"]);
        await flushPromises();
        const documentCalls = fetchMock.mock.calls
            .map(([url]) => String(url))
            .filter((url) => url.includes("/document/"));
        expect(documentCalls.at(-1)).toContain("technique=http");
    });

    it("names the document, its holding and its counts", async () => {
        stubFetch(
            documentPayload({
                annotations: [annotation(1), annotation(2)],
                characterizations: [characterization(1)],
            }),
        );
        const { wrapper } = mountScreen();
        await flushPromises();
        expect(wrapper.find(".document-bar h2").text()).toBe("Manuscript 1");
        expect(wrapper.find(".document-bar").text()).toContain("Avranches, BM");
        expect(wrapper.find(".document-bar .counts").text()).toBe(
            "2 analyses · 1 identified material",
        );
    });

    it("shows the first analysed page and changes page from the strip", async () => {
        stubFetch();
        const { wrapper, store } = mountScreen();
        await flushPromises();
        expect(wrapper.findComponent(FolioStub).props("canvas")?.id).toBe(
            "https://iiif.example/c1",
        );
        await wrapper.find(".canvas-strip button").trigger("click");
        expect(store.document?.canvas).toBe("https://iiif.example/c1");
    });

    it("counts the page's analyses the filters keep", async () => {
        stubFetch(
            documentPayload({
                annotations: [
                    annotation(1),
                    annotation(2, { match: false }),
                    annotation(3, { canvas: "https://iiif.example/c2" }),
                ],
            }),
        );
        const { wrapper } = mountScreen();
        await flushPromises();
        expect(wrapper.find(".rail-foot").text()).toContain(
            "1 / 2 analyses on this page",
        );
    });

    it("switches a folio layer", async () => {
        stubFetch();
        const { wrapper, store } = mountScreen();
        await flushPromises();
        await wrapper.find(".layers input").setValue(false);
        expect(store.layers.points).toBe(false);
        expect(wrapper.findComponent(FolioStub).props("layers").points).toBe(
            false,
        );
    });

    it("opens the analysis card when the folio selects an analysis", async () => {
        stubFetch();
        const { wrapper, store } = mountScreen();
        await flushPromises();
        wrapper
            .findComponent(FolioStub)
            .vm.$emit("select", { kind: "analysis", id: uuid(101) });
        await flushPromises();
        expect(store.focus).toEqual({ kind: "analysis", id: uuid(101) });
        expect(wrapper.findComponent({ name: "AnalysisCard" }).exists()).toBe(
            true,
        );
        expect(wrapper.find(".on-this-page").exists()).toBe(false);
    });

    it("returns the focus to the marker when the card closes", async () => {
        stubFetch();
        const { wrapper, store } = mountScreen();
        await flushPromises();
        wrapper
            .findComponent(FolioStub)
            .vm.$emit("select", { kind: "analysis", id: uuid(101) });
        await flushPromises();
        wrapper.findComponent({ name: "AnalysisCard" }).vm.$emit("close");
        await flushPromises();
        expect(store.focus).toBeNull();
        expect(focusTarget).toHaveBeenCalledWith(uuid(101));
        expect(wrapper.find(".on-this-page").exists()).toBe(true);
    });

    it("follows an analysis to its page", async () => {
        stubFetch();
        const { wrapper, store } = mountScreen();
        await flushPromises();
        store.focusOn({ kind: "analysis", id: uuid(102) });
        await flushPromises();
        expect(store.document?.canvas).toBe("https://iiif.example/c2");
        expect(wrapper.findComponent(FolioStub).props("canvas")?.id).toBe(
            "https://iiif.example/c2",
        );
    });

    it("keeps the page list usable when the document has no manifest", async () => {
        const unlocated = [
            {
                analysis: uuid(150),
                name: { value: "FORS_014", lang: "en" },
                technique: null,
                dataKind: "xy" as const,
                unpublished: false,
                match: true,
            },
        ];
        stubFetch(documentPayload({ manifest: null, canvases: [], unlocated }));
        const { wrapper } = mountScreen();
        await flushPromises();
        expect(wrapper.find(".on-this-page").text()).toContain("FORS_014");
        expect(wrapper.find(".selection-panel").exists()).toBe(true);
    });

    it("returns the focus to the marker when the card drawer closes", async () => {
        narrow = true;
        stubFetch();
        const { wrapper, store } = mountScreen();
        await flushPromises();
        wrapper
            .findComponent(FolioStub)
            .vm.$emit("select", { kind: "analysis", id: uuid(101) });
        await flushPromises();
        wrapper
            .findComponent({ name: "Drawer" })
            .vm.$emit("update:visible", false);
        await flushPromises();
        expect(store.focus).toBeNull();
        expect(focusTarget).toHaveBeenCalledWith(uuid(101));
    });

    it("shows S7 for an unknown or refused document", async () => {
        stubFetch(documentPayload(), 404);
        const { wrapper } = mountScreen();
        await flushPromises();
        expect(wrapper.text()).toContain("This item is not available.");
    });

    it("offers one way home when a document opened from the home is unavailable", async () => {
        stubFetch(documentPayload(), 404);
        const { wrapper } = mountScreen();
        await flushPromises();
        const homeLabels = wrapper
            .findAll("button")
            .filter((button) => button.text() === "Back to the explorer home");
        expect(homeLabels).toHaveLength(1);
    });

    it("goes back to the results it was opened from", async () => {
        stubFetch();
        const { wrapper, store } = mountScreen((store) => {
            store.setFilter("technique", ["http://x/xrf"]);
            store.setCorpusScreen("results");
            store.openDocument(uuid(1));
        });
        await flushPromises();
        const back = wrapper.find(".back");
        expect(back.text()).toBe("Back to the results");
        await back.trigger("click");
        expect(store.corpusScreen).toBe("results");
        expect(store.document).toBeNull();
        expect(store.filters.technique).toEqual(["http://x/xrf"]);
    });

    it("goes back to the explorer home when opened from it", async () => {
        stubFetch();
        const { wrapper, store } = mountScreen();
        await flushPromises();
        const back = wrapper.find(".back");
        expect(back.text()).toBe("Back to the explorer home");
        await back.trigger("click");
        expect(store.corpusScreen).toBe("home");
    });
});
