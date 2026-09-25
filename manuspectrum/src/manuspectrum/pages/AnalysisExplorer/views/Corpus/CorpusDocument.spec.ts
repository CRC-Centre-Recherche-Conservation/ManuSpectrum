import { flushPromises, mount } from "@vue/test-utils";
import { createPinia, setActivePinia } from "pinia";
import PrimeVue from "primevue/config";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { defineComponent, h } from "vue";

import CorpusDocument from "@/manuspectrum/pages/AnalysisExplorer/views/Corpus/CorpusDocument.vue";

import { useExplorerStore } from "@/manuspectrum/pages/AnalysisExplorer/store/explorer.ts";
import {
    snapshotOf,
    toQuery,
} from "@/manuspectrum/pages/AnalysisExplorer/store/url.ts";
import { sizedContainer } from "@/manuspectrum/pages/AnalysisExplorer/testing/leaflet.ts";
import {
    analysisPayload,
    annotation,
    characterization,
    documentPayload,
    sample,
    searchResponse,
    uuid,
} from "@/manuspectrum/pages/AnalysisExplorer/testing/fixtures.ts";
import { jsonResponse } from "@/manuspectrum/pages/AnalysisExplorer/testing/responses.ts";

import type { Pinia } from "pinia";
import type { Component, PropType } from "vue";

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
        view: { type: String, required: true },
        samples: { type: Array, default: () => [] },
        overlays: { type: Array, default: () => [] },
        curtain: { type: String, default: null },
    },
    emits: ["select"],
    setup(_props, { expose }) {
        expose({ focusTarget });
        return () => h("div", { class: "folio-stub" });
    },
});

/** A card that exposes what the screen calls on it; a plain options object, as a test double. */
function cardStub(name: string): Component {
    return {
        name,
        props: {
            handle: { type: Object, default: null },
            analysisId: { type: String, default: null },
            summary: { type: Object, default: null },
            scale: { type: Object, default: null },
            sample: { type: Object, default: null },
            analysisNames: { type: Map, default: null },
        },
        emits: ["close"],
        setup(_props, { expose }) {
            expose({ focusHeading: () => undefined });
            return () => h("article", { class: `${name}-stub` });
        },
    };
}

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
    const fetchMock = vi.fn(async (url: string) => {
        if (url.includes("/search")) {
            return jsonResponse(searchResponse({ results: [] }));
        }
        if (url.includes("/analysis/")) {
            const id = url.split("/analysis/")[1].split("?")[0];
            return jsonResponse(analysisPayload({ id, files: [] }));
        }
        return jsonResponse(structuredClone(payload), status);
    });
    vi.stubGlobal("fetch", fetchMock);
    return fetchMock;
}

function mountScreen(
    prepare: (store: ExplorerStore) => void = (store) =>
        store.openDocument(uuid(1)),
    options: {
        stubs?: Record<string, unknown>;
        attachTo?: HTMLElement;
    } = {},
) {
    const store = useExplorerStore();
    prepare(store);
    const wrapper = mount(CorpusDocument, {
        attachTo: options.attachTo,
        props: { documentId: uuid(1) },
        global: {
            plugins: [pinia, PrimeVue],
            stubs: {
                FolioMap: FolioStub,
                AnalysisCard: cardStub("AnalysisCard"),
                CharacterizationCard: cardStub("CharacterizationCard"),
                SampleCard: cardStub("SampleCard"),
                ...options.stubs,
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

    it("opens the page a result names by its image service", async () => {
        const base = documentPayload();
        const canvases = base.canvases.map((canvas, index) => ({
            ...canvas,
            image: {
                ...canvas.image,
                service: `https://iiif.example/image/p${index + 1}`,
            },
        }));
        stubFetch(documentPayload({ canvases }));
        const { wrapper } = mountScreen((store) =>
            store.openDocument(uuid(1), "https://iiif.example/image/p2/"),
        );
        await flushPromises();
        expect(wrapper.findComponent(FolioStub).props("canvas")?.id).toBe(
            "https://iiif.example/c2",
        );
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

    describe("folio views", () => {
        function everything() {
            return documentPayload({
                annotations: [annotation(1)],
                characterizations: [
                    characterization(1, {
                        evidence: [uuid(101)],
                        zone: {
                            canvas: "https://iiif.example/c1",
                            shape: { type: "point", x: 10, y: 10 },
                            source: "own",
                        },
                    }),
                ],
                samples: [
                    sample(1, { analyses: [uuid(101)] }),
                    sample(2, {
                        zone: {
                            canvas: "https://iiif.example/c2",
                            shape: { type: "point", x: 10, y: 10 },
                        },
                    }),
                ],
            });
        }

        it("offers the views the page has and draws and lists the one chosen", async () => {
            stubFetch(everything());
            const { wrapper, store } = mountScreen();
            await flushPromises();
            expect(wrapper.find(".layers").exists()).toBe(false);
            const buttons = wrapper.findAll(".folio-view-switch button");
            expect(buttons.map((button) => button.text())).toEqual([
                "Analyses",
                "Identified materials",
                "Samples",
            ]);
            const folio = wrapper.findComponent(FolioStub);
            expect(folio.props("view")).toBe("analyses");
            await buttons[2].trigger("click");
            expect(store.folioView).toBe("samples");
            expect(folio.props("view")).toBe("samples");
            expect(
                (folio.props("samples") as { id: string }[]).map((s) => s.id),
            ).toEqual([uuid(601)]);
            expect(wrapper.find(".on-this-page .samples").text()).toContain(
                "Sample 1",
            );
            expect(wrapper.find(".on-this-page .technique").exists()).toBe(
                false,
            );
        });

        it("hides the switch when only the analyses have something on the page", async () => {
            stubFetch();
            const { wrapper } = mountScreen();
            await flushPromises();
            expect(wrapper.find(".folio-view-switch").exists()).toBe(false);
            expect(wrapper.findComponent(FolioStub).props("view")).toBe(
                "analyses",
            );
        });

        it("draws the analyses when the view chosen has nothing on this page", async () => {
            stubFetch();
            const { wrapper, store } = mountScreen();
            store.setFolioView("samples");
            await flushPromises();
            expect(wrapper.findComponent(FolioStub).props("view")).toBe(
                "analyses",
            );
        });

        it("shows the analyses view when the identified-material card opens an evidence analysis", async () => {
            stubFetch(everything());
            const { wrapper, store } = mountScreen(undefined, {
                stubs: { CharacterizationCard: false },
            });
            await flushPromises();
            wrapper.findComponent(FolioStub).vm.$emit("select", {
                kind: "characterization",
                id: uuid(501),
            });
            await flushPromises();
            expect(wrapper.findComponent(FolioStub).props("view")).toBe(
                "characterizations",
            );
            await wrapper
                .find(".characterization-card .evidence button")
                .trigger("click");
            await flushPromises();
            expect(store.focus).toEqual({ kind: "analysis", id: uuid(101) });
            expect(wrapper.findComponent(FolioStub).props("view")).toBe(
                "analyses",
            );
        });

        it("opens a sample's card from the folio and gives the focus back to its marker on close", async () => {
            stubFetch(everything());
            const { wrapper, store } = mountScreen();
            await flushPromises();
            wrapper
                .findComponent(FolioStub)
                .vm.$emit("select", { kind: "sample", id: uuid(601) });
            await flushPromises();
            expect(store.folioView).toBe("samples");
            const card = wrapper.findComponent({ name: "SampleCard" });
            expect(card.props("sample")).toMatchObject({ id: uuid(601) });
            expect(
                (card.props("analysisNames") as Map<string, unknown>).has(
                    uuid(101),
                ),
            ).toBe(true);
            card.vm.$emit("close");
            await flushPromises();
            expect(store.focus).toBeNull();
            expect(focusTarget).toHaveBeenCalledWith(`sample:${uuid(601)}`);
        });

        it("follows a sample to the page of its zone", async () => {
            stubFetch(everything());
            const { store } = mountScreen();
            await flushPromises();
            store.focusOn({ kind: "sample", id: uuid(602) });
            await flushPromises();
            expect(store.document?.canvas).toBe("https://iiif.example/c2");
        });
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

    it("keeps the page after a filter reload with a card open", async () => {
        stubFetch();
        const { store } = mountScreen();
        await flushPromises();
        store.focusOn({ kind: "analysis", id: uuid(101) });
        await flushPromises();
        store.setCanvas("https://iiif.example/c2");
        await flushPromises();
        store.setFilter("technique", ["http://example.org/xrf"]);
        await flushPromises();
        expect(store.document?.canvas).toBe("https://iiif.example/c2");
    });

    it("stays on the page of the clicked zone of an analysis zoned on several pages", async () => {
        stubFetch(
            documentPayload({
                annotations: [
                    annotation(2, { key: "on-c1" }),
                    annotation(2, {
                        key: "on-c2",
                        canvas: "https://iiif.example/c2",
                    }),
                ],
            }),
        );
        const { store } = mountScreen();
        await flushPromises();
        store.setCanvas("https://iiif.example/c2");
        await flushPromises();
        store.focusOn({ kind: "analysis", id: uuid(102) });
        await flushPromises();
        expect(store.document?.canvas).toBe("https://iiif.example/c2");
    });

    it("keeps the document on screen and offers Retry when a reload fails", async () => {
        const fetchMock = stubFetch();
        const { wrapper, store } = mountScreen();
        await flushPromises();
        fetchMock.mockImplementation(async (url: string) =>
            url.includes("/search")
                ? jsonResponse(searchResponse({ results: [] }))
                : jsonResponse({}, 503),
        );
        store.setFilter("technique", ["http://example.org/xrf"]);
        await flushPromises();
        expect(wrapper.find(".document-bar h2").exists()).toBe(true);
        expect(wrapper.text()).toContain(
            "The service is not answering right now.",
        );
        const calls = fetchMock.mock.calls.length;
        await wrapper.find(".unavailable-state .retry").trigger("click");
        expect(fetchMock.mock.calls.length).toBeGreaterThan(calls);
    });

    describe("closing a card", () => {
        let back: ReturnType<typeof vi.spyOn>;

        beforeEach(() => {
            back = vi
                .spyOn(window.history, "back")
                .mockImplementation(() => undefined);
        });

        afterEach(() => {
            back.mockRestore();
            window.history.replaceState(null, "", "/");
        });

        function standOnTheDocumentEntry(store: ExplorerStore): void {
            const search = toQuery(snapshotOf(store)).toString();
            window.history.replaceState(null, "", `/?${search}`);
        }

        it("goes back over the entry its opening pushed", async () => {
            stubFetch();
            const { wrapper, store } = mountScreen();
            await flushPromises();
            standOnTheDocumentEntry(store);
            wrapper
                .findComponent(FolioStub)
                .vm.$emit("select", { kind: "analysis", id: uuid(101) });
            await flushPromises();
            wrapper.findComponent({ name: "AnalysisCard" }).vm.$emit("close");
            await flushPromises();
            expect(store.focus).toBeNull();
            expect(back).toHaveBeenCalledTimes(1);
        });

        it("stays on its entry when the filters changed since it opened", async () => {
            stubFetch();
            const { wrapper, store } = mountScreen();
            await flushPromises();
            standOnTheDocumentEntry(store);
            wrapper
                .findComponent(FolioStub)
                .vm.$emit("select", { kind: "analysis", id: uuid(101) });
            await flushPromises();
            store.setFilter("technique", ["http://example.org/xrf"]);
            await flushPromises();
            wrapper.findComponent({ name: "AnalysisCard" }).vm.$emit("close");
            await flushPromises();
            expect(store.focus).toBeNull();
            expect(back).not.toHaveBeenCalled();
        });
    });

    it("gives the keyboard focus to the card heading when the list that opened it goes away", async () => {
        stubFetch();
        const { wrapper } = mountScreen(undefined, {
            stubs: { AnalysisCard: false },
            attachTo: document.body,
        });
        await flushPromises();
        const entry = wrapper.find(".on-this-page button");
        (entry.element as HTMLButtonElement).focus();
        await entry.trigger("click");
        await flushPromises();
        expect(document.activeElement).toBe(
            wrapper.find(".analysis-card h3").element,
        );
        wrapper.unmount();
    });

    it("gives the keyboard focus to the new card's heading when a card opens a card of the other kind", async () => {
        stubFetch(
            documentPayload({
                annotations: [annotation(1)],
                characterizations: [
                    characterization(1, { evidence: [uuid(101)] }),
                ],
            }),
        );
        const { wrapper, store } = mountScreen(undefined, {
            stubs: { AnalysisCard: false, CharacterizationCard: false },
            attachTo: document.body,
        });
        await flushPromises();
        store.focusOn({ kind: "characterization", id: uuid(501) });
        await flushPromises();
        const evidence = wrapper.find(
            ".characterization-card .evidence button",
        );
        (evidence.element as HTMLButtonElement).focus();
        await evidence.trigger("click");
        await flushPromises();
        expect(document.activeElement).toBe(
            wrapper.find(".analysis-card h3").element,
        );
        wrapper.unmount();
    });

    it("returns the focus to the folio marker when Escape closes the card drawer", async () => {
        narrow = true;
        stubFetch();
        const { wrapper, store } = mountScreen(undefined, {
            stubs: { FolioMap: false, transition: false },
            attachTo: sizedContainer(),
        });
        await flushPromises();
        const marker = wrapper.find(`#folio-marker-${uuid(101)}`);
        (marker.element as HTMLElement).focus();
        await marker.trigger("keydown", { key: "Enter" });
        await flushPromises();
        expect(store.focus).toEqual({ kind: "analysis", id: uuid(101) });
        expect(document.activeElement).not.toBe(marker.element);
        document.dispatchEvent(
            new KeyboardEvent("keydown", { key: "Escape", code: "Escape" }),
        );
        await flushPromises();
        expect(store.focus).toBeNull();
        expect(document.activeElement).toBe(
            wrapper.find(`#folio-marker-${uuid(101)}`).element,
        );
        wrapper.unmount();
    });
});
