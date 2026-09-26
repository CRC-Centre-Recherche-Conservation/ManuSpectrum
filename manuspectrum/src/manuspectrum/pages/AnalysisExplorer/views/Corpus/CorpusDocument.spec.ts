import { flushPromises, mount } from "@vue/test-utils";
import { createPinia, setActivePinia } from "pinia";
import PrimeVue from "primevue/config";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { defineComponent, h, ref } from "vue";

import CorpusDocument from "@/manuspectrum/pages/AnalysisExplorer/views/Corpus/CorpusDocument.vue";

import { forgetPayloads } from "@/manuspectrum/pages/AnalysisExplorer/api/http.ts";
import { DEBOUNCE_MS } from "@/manuspectrum/pages/AnalysisExplorer/composables/useRequest.ts";
import { RESULTS_MEMO_KEY } from "@/manuspectrum/pages/AnalysisExplorer/injection-keys.ts";
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
    documentResponses,
    facet,
    facetValue,
    label,
    sample,
    technique,
    uuid,
} from "@/manuspectrum/pages/AnalysisExplorer/testing/fixtures.ts";
import { jsonResponse } from "@/manuspectrum/pages/AnalysisExplorer/testing/responses.ts";

import type { Pinia } from "pinia";
import type { Component, PropType } from "vue";

import type { ResultsMemo } from "@/manuspectrum/pages/AnalysisExplorer/injection-keys.ts";
import type { DocumentShown } from "@/manuspectrum/pages/AnalysisExplorer/testing/fixtures.ts";
import type { ExplorerStore } from "@/manuspectrum/pages/AnalysisExplorer/store/explorer.ts";
import type { LayerToggles } from "@/manuspectrum/pages/AnalysisExplorer/store/types.ts";

vi.mock("@/arches/utils/generate-arches-url.ts", () => ({
    generateArchesURL: (
        name: string,
        parameters: Record<string, string> = {},
    ) =>
        name === "manuspectrum:explorer-search"
            ? "/en/api/explorer/search"
            : `/en/api/explorer/${name.split("explorer-")[1]}/${parameters.resourceid ?? parameters.key}`,
}));

const loadPlotly = vi.hoisted(() => vi.fn(async () => ({})));

vi.mock("@/manuspectrum/pages/AnalysisExplorer/xy/plotly.ts", () => ({
    loadPlotly,
}));

const focusTarget = vi.fn();
const focusCurrent = vi.fn();
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
        caption: { type: String, default: "" },
    },
    emits: ["select"],
    setup(_props, { expose }) {
        expose({ focusTarget, focusCurrent });
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
            headingId: { type: String, default: undefined },
            closable: { type: Boolean, default: true },
            zone: { type: Object, default: null },
        },
        emits: ["close"],
        setup(props, { expose }) {
            expose({ focusHeading: () => undefined });
            return () =>
                h("article", { class: `${name}-stub` }, [
                    h("h3", { id: props.headingId, tabindex: -1 }),
                ]);
        },
    };
}

let narrow = false;
let pinia: Pinia;

beforeEach(() => {
    forgetPayloads();
    narrow = false;
    focusTarget.mockClear();
    focusCurrent.mockClear();
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

/** Runs a change of filters and lets the match wait out its debounce. */
async function changeFilters(change: () => void): Promise<void> {
    vi.useFakeTimers({ toFake: ["setTimeout", "clearTimeout"] });
    change();
    await vi.advanceTimersByTimeAsync(DEBOUNCE_MS);
    vi.useRealTimers();
    await flushPromises();
}

function stubFetch(
    shown: DocumentShown = {
        annotations: [
            annotation(1),
            annotation(2, { canvas: "https://iiif.example/c2" }),
        ],
    },
    status = 200,
) {
    const { payload, match } = documentResponses(shown);
    const fetchMock = vi.fn(async (url: string) => {
        if (url.includes("/document-match/")) {
            return jsonResponse(structuredClone(match), status);
        }
        if (url.includes("/facet/")) {
            const find = new URL(url, "http://x").searchParams.get("find");
            const asked = match.facets.find((entry) =>
                url.includes(`/facet/${entry.key}?`),
            )!;
            return jsonResponse({
                ...asked,
                values: asked.values.filter((value) =>
                    value.label.value.endsWith(find ?? ""),
                ),
            });
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
        provide?: Record<symbol, unknown>;
    } = {},
) {
    const store = useExplorerStore();
    prepare(store);
    const wrapper = mount(CorpusDocument, {
        attachTo: options.attachTo,
        props: { documentId: uuid(1) },
        global: {
            plugins: [pinia, PrimeVue],
            provide: options.provide,
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
    it("asks the document once and its match with the Corpus filters", async () => {
        const fetchMock = stubFetch();
        const { store } = mountScreen();
        await flushPromises();
        await changeFilters(() =>
            store.setFilter("technique", ["http://example.org/xrf"]),
        );
        const calls = fetchMock.mock.calls.map(([url]) => String(url));
        expect(calls.filter((url) => url.includes("/document/"))).toEqual([
            `/en/api/explorer/document/${uuid(1)}`,
        ]);
        expect(
            calls.filter((url) => url.includes("/document-match/")).at(-1),
        ).toContain("technique=http");
    });

    it("shows the match loading at once and asks for it once for quick filter changes", async () => {
        const fetchMock = stubFetch();
        const { wrapper, store } = mountScreen();
        await flushPromises();
        vi.useFakeTimers({ toFake: ["setTimeout", "clearTimeout"] });
        const before = fetchMock.mock.calls.length;
        for (const technique of ["t1", "t2", "t3"]) {
            store.setFilter("technique", [
                ...store.filters.technique,
                technique,
            ]);
            await flushPromises();
            expect(wrapper.find("[role=status]").text()).toBe("Updating…");
        }
        await vi.advanceTimersByTimeAsync(DEBOUNCE_MS);
        vi.useRealTimers();
        await flushPromises();
        const asked = fetchMock.mock.calls
            .slice(before)
            .map(([url]) => String(url));
        expect(asked).toHaveLength(1);
        expect(asked[0]).toContain("technique=t1&technique=t2&technique=t3");
    });

    it("starts loading the spectrum viewer when a spectrum analysis gets the focus", async () => {
        loadPlotly.mockClear();
        stubFetch({
            annotations: [
                annotation(1, { dataKind: "file" }),
                annotation(2, { dataKind: "xy" }),
            ],
        });
        const { store } = mountScreen();
        await flushPromises();
        store.focusOn({ kind: "analysis", id: uuid(101) });
        await flushPromises();
        expect(loadPlotly).not.toHaveBeenCalled();
        store.focusOn({ kind: "analysis", id: uuid(102) });
        await flushPromises();
        expect(loadPlotly).toHaveBeenCalledTimes(1);
    });

    it("names the document, its holding and its counts", async () => {
        stubFetch({
            annotations: [annotation(1), annotation(2)],
            characterizations: [characterization(1)],
        });
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
        stubFetch({ canvases });
        const { wrapper } = mountScreen((store) =>
            store.openDocument(uuid(1), "https://iiif.example/image/p2/"),
        );
        await flushPromises();
        expect(wrapper.findComponent(FolioStub).props("canvas")?.id).toBe(
            "https://iiif.example/c2",
        );
    });

    it("says on top of the page how many of its analyses the filters keep", async () => {
        stubFetch({
            annotations: [
                annotation(1),
                annotation(2, { match: false }),
                annotation(3, { canvas: "https://iiif.example/c2" }),
            ],
        });
        const { wrapper } = mountScreen();
        await flushPromises();
        expect(wrapper.find(".stage .page-count").text()).toBe(
            "1 / 2 analyses on this page",
        );
    });

    describe("folio views", () => {
        function everything() {
            return {
                annotations: [annotation(1)],
                characterizations: [
                    characterization(1, {
                        evidence: [
                            { id: uuid(101), name: label("MS1_f12_XRF_01") },
                        ],
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
            };
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

    it("hands the card the page and zone of the analysis, the page shown first", async () => {
        stubFetch({
            annotations: [
                annotation(1),
                annotation(1, {
                    canvas: "https://iiif.example/c2",
                    shape: { type: "point", x: 7, y: 8 },
                }),
                annotation(2, { canvas: "https://iiif.example/c2" }),
            ],
        });
        const { wrapper, store } = mountScreen((explorer) =>
            explorer.openDocument(uuid(1), "https://iiif.example/c2"),
        );
        await flushPromises();
        store.focusOn({ kind: "analysis", id: uuid(101) });
        await flushPromises();

        expect(
            wrapper.findComponent({ name: "AnalysisCard" }).props("zone"),
        ).toEqual({
            canvas: "https://iiif.example/c2",
            shape: { type: "point", x: 7, y: 8 },
        });
    });

    it("hands the card no zone for an unlocated analysis", async () => {
        stubFetch({
            annotations: [annotation(1)],
            unlocated: [
                {
                    analysis: uuid(103),
                    name: { value: "FORS_014", lang: "en" },
                    technique: null,
                    dataKind: "xy" as const,
                    unpublished: false,
                    match: true,
                },
            ],
        });
        const { wrapper, store } = mountScreen();
        await flushPromises();
        store.focusOn({ kind: "analysis", id: uuid(103) });
        await flushPromises();

        expect(
            wrapper.findComponent({ name: "AnalysisCard" }).props("zone"),
        ).toBeNull();
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
        stubFetch({ manifest: null, canvases: [], unlocated });
        const { wrapper } = mountScreen();
        await flushPromises();
        expect(wrapper.find(".on-this-page").text()).toContain("FORS_014");
        expect(wrapper.find(".side .selection-panel").exists()).toBe(false);
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
        stubFetch({}, 404);
        const { wrapper } = mountScreen();
        await flushPromises();
        expect(wrapper.text()).toContain("This item is not available.");
    });

    it("offers one way home when a document opened from the home is unavailable", async () => {
        stubFetch({}, 404);
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
        const back = wrapper.find(".explorer-back");
        expect(back.text()).toBe("Results");
        await back.trigger("click");
        expect(store.corpusScreen).toBe("results");
        expect(store.document).toBeNull();
        expect(store.filters.technique).toEqual(["http://x/xrf"]);
    });

    it("says how many results it goes back to", async () => {
        stubFetch();
        const memo = ref<ResultsMemo>({
            query: "grain=documents",
            filterKey: "grain=documents",
            page: 1,
            total: 30,
            grain: "documents",
            scroll: 0,
            opened: uuid(1),
        });
        const { wrapper } = mountScreen(
            (store) => {
                store.setCorpusScreen("results");
                store.openDocument(uuid(1));
            },
            { provide: { [RESULTS_MEMO_KEY as symbol]: memo } },
        );
        await flushPromises();
        expect(wrapper.find(".explorer-back").text()).toBe(
            "Results (30 documents)",
        );
    });

    it("counts its filters in this document only", async () => {
        const fetchMock = stubFetch();
        const { wrapper, store } = mountScreen();
        await changeFilters(() =>
            store.setFilter("technique", ["http://example.org/xrf"]),
        );
        const match = fetchMock.mock.calls
            .map(([url]) => String(url))
            .filter((url) => url.includes("/document-match/"))
            .at(-1)!;
        expect(match.split("?")[0]).toBe(
            `/en/api/explorer/document-match/${uuid(1)}`,
        );
        const query = new URLSearchParams(match.split("?")[1]);
        expect(query.get("grain")).toBeNull();
        expect(query.get("technique")).toBe("http://example.org/xrf");
        expect(wrapper.find(".rail .rail-title").text()).toBe(
            "Filters of this document",
        );
    });

    it("searches a facet of this document through the server under the filters it shows", async () => {
        const fetchMock = stubFetch({
            annotations: [annotation(1)],
            facets: [facet("project", 12)],
        });
        const { wrapper, store } = mountScreen();
        await changeFilters(() => store.setFilter("technique", ["t1"]));
        await wrapper.find(".rail input[type=search]").setValue("11");
        await flushPromises();
        const asked = fetchMock.mock.calls
            .map(([url]) => String(url))
            .filter((url) => url.includes("/facet/"));
        expect(asked).toHaveLength(1);
        const [path, search] = asked[0].split("?");
        expect(path).toBe("/en/api/explorer/facet/project");
        const query = new URLSearchParams(search);
        expect(query.get("document")).toBe(uuid(1));
        expect(query.get("technique")).toBe("t1");
        expect(query.get("find")).toBe("11");
        expect(query.get("grain")).toBeNull();
        expect(
            wrapper.findAll(".rail .value .label").map((item) => item.text()),
        ).toEqual(["project 11"]);
    });

    it("goes back to the explorer home when opened from it", async () => {
        stubFetch();
        const { wrapper, store } = mountScreen();
        await flushPromises();
        const back = wrapper.find(".explorer-back");
        expect(back.text()).toBe("Back to the explorer home");
        await back.trigger("click");
        expect(store.corpusScreen).toBe("home");
    });

    it("opens on the first page with results when filters are active and no page is named", async () => {
        stubFetch({
            annotations: [
                annotation(1, { match: false }),
                annotation(2, {
                    canvas: "https://iiif.example/c2",
                    match: true,
                }),
            ],
        });
        const { wrapper } = mountScreen((store) => {
            store.setFilter("technique", ["http://example.org/xrf"]);
            store.openDocument(uuid(1));
        });
        await flushPromises();
        expect(wrapper.findComponent(FolioStub).props("canvas")?.id).toBe(
            "https://iiif.example/c2",
        );
        expect(wrapper.find(".canvas-strip").classes()).toContain(
            "is-filtered",
        );
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
        stubFetch({
            annotations: [
                annotation(2, { key: "on-c1" }),
                annotation(2, {
                    key: "on-c2",
                    canvas: "https://iiif.example/c2",
                }),
            ],
        });
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
        fetchMock.mockImplementation(async () => jsonResponse({}, 503));
        await changeFilters(() =>
            store.setFilter("technique", ["http://example.org/xrf"]),
        );
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
        stubFetch({
            annotations: [annotation(1)],
            characterizations: [
                characterization(1, {
                    evidence: [
                        { id: uuid(101), name: label("MS1_f12_XRF_01") },
                    ],
                }),
            ],
        });
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

    describe("layout and keyboard", () => {
        it("offers skip links to the page, the filters and the card", async () => {
            stubFetch();
            const { wrapper } = mountScreen(undefined, {
                attachTo: document.body,
            });
            await flushPromises();
            const skips = wrapper.findAll(".skip-links button");
            expect(skips.map((skip) => skip.text())).toEqual([
                "Go to the page",
                "Go to the filters",
                "Go to the card",
            ]);
            await skips[0].trigger("click");
            expect(focusCurrent).toHaveBeenCalled();
            await skips[1].trigger("click");
            expect(document.activeElement).toBe(wrapper.find(".rail").element);
            await skips[2].trigger("click");
            expect(document.activeElement).toBe(
                wrapper.find("#on-this-page-title").element,
            );
            wrapper.unmount();
        });

        it("closes the card on Escape and gives the focus back to the list entry that opened it", async () => {
            stubFetch();
            const { wrapper, store } = mountScreen(undefined, {
                attachTo: document.body,
            });
            await flushPromises();
            const entry = wrapper.find(
                `.on-this-page [data-focus="analysis:${uuid(101)}"]`,
            );
            (entry.element as HTMLButtonElement).focus();
            await entry.trigger("click");
            await flushPromises();
            expect(store.focus).toEqual({ kind: "analysis", id: uuid(101) });
            await wrapper.find(".side article").trigger("keydown", {
                key: "Escape",
            });
            await flushPromises();
            expect(store.focus).toBeNull();
            expect(document.activeElement).toBe(
                wrapper.find(
                    `.on-this-page [data-focus="analysis:${uuid(101)}"]`,
                ).element,
            );
            expect(focusTarget).not.toHaveBeenCalled();
            wrapper.unmount();
        });

        it("brings the heading of a card opened from the folio into view", async () => {
            stubFetch();
            const scrollIntoView = vi.fn();
            Element.prototype.scrollIntoView = scrollIntoView;
            const { wrapper } = mountScreen(undefined, {
                attachTo: document.body,
            });
            await flushPromises();
            wrapper
                .findComponent(FolioStub)
                .vm.$emit("select", { kind: "analysis", id: uuid(101) });
            await flushPromises();
            expect(scrollIntoView).toHaveBeenCalledWith({ block: "nearest" });
            expect(scrollIntoView.mock.contexts[0]).toBe(
                document.getElementById("explorer-card-heading"),
            );
            delete (Element.prototype as Partial<Element>).scrollIntoView;
            wrapper.unmount();
        });

        it("lists in the legend only the techniques drawn on the page, with their counts", async () => {
            stubFetch({
                annotations: [
                    annotation(1),
                    annotation(2, {
                        technique: technique("t:fors", "FORS", 2),
                        canvas: "https://iiif.example/c2",
                    }),
                    annotation(3),
                ],
            });
            const { wrapper } = mountScreen();
            await flushPromises();
            expect(
                wrapper
                    .findAll(".folio-legend li")
                    .map((entry) =>
                        entry.findAll("span").map((part) => part.text()),
                    ),
            ).toEqual([["XRF", "XRF", "2"]]);
            expect(useExplorerStore().legendOpen).toBe(false);
        });

        it("draws a technique in the rail and on the folio in the colour the server gives it", async () => {
            const fors = technique("t:fors", "FORS", 7, "t:fors", "FORS");
            stubFetch({
                annotations: [annotation(1, { technique: fors })],
                facets: [
                    {
                        key: "technique",
                        group: "analysis",
                        values: [
                            facetValue("t:fors", "FORS", {
                                mark: {
                                    code: "FORS",
                                    colour: 7,
                                    family: "t:fors",
                                },
                            }),
                        ],
                        total: 1,
                    },
                ],
            });
            const { wrapper } = mountScreen();
            await flushPromises();
            const styles = wrapper
                .findComponent(FolioStub)
                .props("styles") as Map<string, { colour: number | null }>;
            expect(styles.get("t:fors")?.colour).toBe(7);
            expect(wrapper.find(".facet-rail .dot").classes()).toContain(
                "dot--tech-7",
            );
        });

        it("names the card drawer by the card heading and leaves out the card's own Close", async () => {
            narrow = true;
            stubFetch();
            const { wrapper } = mountScreen(undefined, {
                stubs: { transition: false },
                attachTo: document.body,
            });
            await flushPromises();
            wrapper
                .findComponent(FolioStub)
                .vm.$emit("select", { kind: "analysis", id: uuid(101) });
            await flushPromises();
            const dialog = document.querySelector(".explorer-card-drawer");
            expect(dialog?.getAttribute("role")).toBe("dialog");
            expect(dialog?.getAttribute("aria-labelledby")).toBe(
                "explorer-card-heading",
            );
            const card = wrapper.findComponent({ name: "AnalysisCard" });
            expect(card.props("closable")).toBe(false);
            expect(card.props("headingId")).toBe("explorer-card-heading");
            wrapper.unmount();
        });
    });
});
