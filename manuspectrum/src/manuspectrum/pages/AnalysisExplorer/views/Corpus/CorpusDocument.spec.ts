import { flushPromises, mount } from "@vue/test-utils";
import { createPinia, setActivePinia } from "pinia";
import PrimeVue from "primevue/config";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { defineComponent, h, inject, ref } from "vue";

import CorpusDocument from "@/manuspectrum/pages/AnalysisExplorer/views/Corpus/CorpusDocument.vue";

import { forgetPayloads } from "@/manuspectrum/pages/AnalysisExplorer/api/http.ts";
import {
    reloadRegistrations,
    useRegistration,
} from "@/manuspectrum/pages/AnalysisExplorer/composables/useRegistration.ts";
import { DEBOUNCE_MS } from "@/manuspectrum/pages/AnalysisExplorer/composables/useRequest.ts";
import {
    FOLIO_CANVAS_KEY,
    RESULTS_MEMO_KEY,
} from "@/manuspectrum/pages/AnalysisExplorer/injection-keys.ts";
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
    imagingEntry,
    documentComponent,
    documentPayload,
    documentResponses,
    facet,
    facetValue,
    label,
    rangeFacet,
    sample,
    technique,
    uuid,
} from "@/manuspectrum/pages/AnalysisExplorer/testing/fixtures.ts";
import { jsonResponse } from "@/manuspectrum/pages/AnalysisExplorer/testing/responses.ts";

import type { Pinia } from "pinia";
import type { Component, PropType } from "vue";

import { ANNOUNCE_KEY } from "@/manuspectrum/pages/AnalysisExplorer/injection-keys.ts";

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
        components: { type: Array, default: () => [] },
        overlays: { type: Array, default: () => [] },
        curtain: { type: String, default: null },
        adjusting: { type: String, default: null },
        capturing: { type: String, default: null },
        caption: { type: String, default: "" },
        stage: { type: String, default: "dark" },
    },
    emits: [
        "select",
        "layer-adjust",
        "layer-turn",
        "layer-opacity",
        "layer-curtain",
        "layer-capture",
        "captured",
        "capture-failed",
        "layer-reset",
    ],
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
            component: { type: Object, default: null },
            analyses: { type: Array, default: null },
            materials: { type: Array, default: null },
            components: { type: Array, default: null },
            analysisNames: { type: Map, default: null },
            headingId: { type: String, default: undefined },
            closable: { type: Boolean, default: true },
            feature: { type: String, default: null },
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
                ComponentCard: cardStub("ComponentCard"),
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

    it("shows the production date and places of the document in its header", async () => {
        stubFetch({
            annotations: [annotation(1)],
            history: [
                {
                    type: "production",
                    places: [
                        { id: uuid(500), name: label("Le Mont-Saint-Michel") },
                        { id: uuid(501), name: label("Avranches") },
                    ],
                    date: { start: "1401", end: "1500", approximate: false },
                },
            ],
        });
        const { wrapper } = mountScreen();
        await flushPromises();
        expect(wrapper.find(".document-bar .production").text()).toBe(
            "Production: 15th century · Le Mont-Saint-Michel, Avranches",
        );
    });

    it("shows a date without a place", async () => {
        stubFetch({
            annotations: [annotation(1)],
            history: [
                {
                    type: "production",
                    places: [],
                    date: { start: "1464", end: "1464", approximate: true },
                },
            ],
        });
        const { wrapper } = mountScreen();
        await flushPromises();
        expect(wrapper.find(".document-bar .production").text()).toBe(
            "Production: c. 1464",
        );
    });

    it("shows a place without a date", async () => {
        stubFetch({
            annotations: [annotation(1)],
            history: [
                {
                    type: "production",
                    places: [{ id: uuid(500), name: label("Avranches") }],
                    date: { start: null, end: null, approximate: false },
                },
            ],
        });
        const { wrapper } = mountScreen();
        await flushPromises();
        expect(wrapper.find(".document-bar .production").text()).toBe(
            "Production: Avranches",
        );
    });

    it("shows no production chip without a production line", async () => {
        stubFetch({ annotations: [annotation(1)] });
        const { wrapper } = mountScreen();
        await flushPromises();
        expect(wrapper.find(".document-bar .production").exists()).toBe(false);
    });

    it("leaves the document's own place and date out of its rail", async () => {
        stubFetch({ annotations: [annotation(1)], period: rangeFacet() });
        const { wrapper } = mountScreen();
        await flushPromises();
        expect(wrapper.find(".rail .period-facet").exists()).toBe(false);
        expect(wrapper.find(".rail .tree").exists()).toBe(false);
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

    describe("analyses outside the filters", () => {
        const FILTERED = (store: ExplorerStore) => {
            store.setFilter("technique", ["http://example.org/xrf"]);
            store.openDocument(uuid(1));
        };

        function shown(extra: DocumentShown = {}): DocumentShown {
            return {
                annotations: [annotation(1), annotation(2, { match: false })],
                unlocated: [
                    {
                        analysis: uuid(150),
                        name: label("FORS_014"),
                        technique: null,
                        dataKind: "xy",
                        unpublished: false,
                        component: null,
                        match: false,
                    },
                ],
                ...extra,
            };
        }

        const names = (wrapper: ReturnType<typeof mountScreen>["wrapper"]) =>
            (
                wrapper.findComponent(FolioStub).props("annotations") as {
                    analysis: string;
                }[]
            ).map((entry) => entry.analysis);

        it("has no switch without filters or without an excluded analysis", async () => {
            stubFetch(shown());
            const open = mountScreen();
            await flushPromises();
            expect(open.wrapper.find("[role=switch]").exists()).toBe(false);
            forgetPayloads();
            stubFetch({ annotations: [annotation(1)] });
            const kept = mountScreen(FILTERED);
            await flushPromises();
            expect(kept.wrapper.find("[role=switch]").exists()).toBe(false);
        });

        it("offers the switch when only an identified material is left out", async () => {
            stubFetch({
                annotations: [annotation(1)],
                characterizations: [characterization(1), characterization(2)],
                dimmed: [uuid(502)],
            });
            const { wrapper } = mountScreen(FILTERED);
            await flushPromises();
            expect(wrapper.find(".stage-head [role=switch]").text()).toContain(
                "Outside the filters: 1 identified material",
            );
        });

        it("keeps the switch while the outside is hidden, whatever the filters leave out", async () => {
            stubFetch({ annotations: [annotation(1)] });
            const { wrapper, store } = mountScreen((opened) => {
                FILTERED(opened);
                opened.setShowOutside(false);
            });
            await flushPromises();
            const control = wrapper.find(".stage-head [role=switch]");
            expect(control.exists()).toBe(true);
            expect(control.attributes("aria-checked")).toBe("false");
            await control.trigger("click");
            expect(store.showOutside).toBe(true);
        });

        it("offers no switch without a filter, and lists everything even when the address says outside=hide", async () => {
            stubFetch(shown());
            const { wrapper } = mountScreen((opened) => {
                opened.openDocument(uuid(1));
                opened.setShowOutside(false);
            });
            await flushPromises();
            expect(wrapper.find(".stage-head [role=switch]").exists()).toBe(
                false,
            );
            expect(names(wrapper)).toEqual([uuid(101), uuid(102)]);
        });

        it("offers the switch in the stage head with the number of analyses left out, on by default", async () => {
            stubFetch(shown());
            const { wrapper } = mountScreen(FILTERED);
            await flushPromises();
            const control = wrapper.find(".stage-head [role=switch]");
            expect(control.text()).toContain(
                "Analyses outside the filters (2)",
            );
            expect(control.attributes("aria-checked")).toBe("true");
            expect(names(wrapper)).toEqual([uuid(101), uuid(102)]);
        });

        it("hides them from the folio and the list, keeps the page count, and writes the state in the store", async () => {
            stubFetch(shown());
            const { wrapper, store } = mountScreen(FILTERED);
            await flushPromises();
            await wrapper.find("[role=switch]").trigger("click");
            expect(store.showOutside).toBe(false);
            expect(names(wrapper)).toEqual([uuid(101)]);
            const list = wrapper.findComponent({ name: "OnThisPage" });
            expect(list.props("annotations")).toHaveLength(1);
            expect(list.props("unlocated")).toHaveLength(0);
            expect(list.props("hiddenCount")).toBe(2);
            expect(wrapper.find(".page-count").text()).toBe(
                "1 / 2 analyses on this page",
            );
            expect(
                wrapper.find("[role=switch]").attributes("aria-checked"),
            ).toBe("false");
        });

        it("starts hidden when the address says outside=hide", async () => {
            stubFetch(shown());
            const { wrapper } = mountScreen((store) => {
                FILTERED(store);
                store.setShowOutside(false);
            });
            await flushPromises();
            expect(names(wrapper)).toEqual([uuid(101)]);
        });

        it("keeps the focused analysis visible while the others are hidden", async () => {
            stubFetch(shown());
            const { wrapper, store } = mountScreen((store) => {
                FILTERED(store);
                store.setShowOutside(false);
                store.focusOn({ kind: "analysis", id: uuid(102) });
            });
            await flushPromises();
            expect(names(wrapper)).toEqual([uuid(101), uuid(102)]);
            store.focusOn(null);
            await flushPromises();
            expect(names(wrapper)).toEqual([uuid(101)]);
        });

        it("hides the identified materials the filters drop", async () => {
            stubFetch({
                ...shown(),
                characterizations: [
                    characterization(1, {
                        zone: {
                            canvas: "https://iiif.example/c1",
                            shape: { type: "point", x: 1, y: 1 },
                            source: "own",
                        },
                    }),
                    characterization(2, {
                        zone: {
                            canvas: "https://iiif.example/c1",
                            shape: { type: "point", x: 2, y: 2 },
                            source: "own",
                        },
                    }),
                ],
                dimmed: [uuid(502)],
            });
            const { wrapper, store } = mountScreen(FILTERED);
            await flushPromises();
            const drawn = () =>
                (
                    wrapper
                        .findComponent(FolioStub)
                        .props("characterizations") as { id: string }[]
                ).map((entry) => entry.id);
            expect(drawn()).toEqual([uuid(501), uuid(502)]);
            store.setShowOutside(false);
            await flushPromises();
            expect(drawn()).toEqual([uuid(501)]);
        });

        it("toggles without remounting or redrawing the folio", async () => {
            stubFetch(shown());
            const { wrapper } = mountScreen(FILTERED);
            await flushPromises();
            const folio = wrapper.findComponent(FolioStub);
            const canvas = folio.props("canvas");
            await wrapper.find("[role=switch]").trigger("click");
            await wrapper.find("[role=switch]").trigger("click");
            expect(wrapper.findComponent(FolioStub).vm).toBe(folio.vm);
            expect(wrapper.findComponent(FolioStub).props("canvas")).toBe(
                canvas,
            );
            expect(focusTarget).not.toHaveBeenCalled();
        });

        it("keeps every page in the strip and the available views when hiding", async () => {
            stubFetch(shown());
            const { wrapper, store } = mountScreen(FILTERED);
            await flushPromises();
            const before = wrapper
                .findComponent({ name: "CanvasStrip" })
                .props();
            store.setShowOutside(false);
            await flushPromises();
            expect(
                wrapper.findComponent({ name: "CanvasStrip" }).props(),
            ).toEqual(before);
        });

        it("shows the status line of a grouped change under the page checkbox, not after the panel", async () => {
            stubFetch(shown());
            const { wrapper } = mountScreen(FILTERED);
            await flushPromises();
            expect(wrapper.find(".bulk-status-line").exists()).toBe(false);
            await wrapper
                .find(".on-this-page .page-select input")
                .setValue(true);
            await flushPromises();
            expect(
                wrapper.find(".side .on-this-page .bulk-status-line").exists(),
            ).toBe(true);
            expect(
                wrapper.findAll(".side > .bulk-status-line, .bulk-status-line"),
            ).toHaveLength(1);
            expect(wrapper.find(".side > .bulk-status-line").exists()).toBe(
                false,
            );
        });
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
            const code = wrapper.find(
                ".characterization-card .evidence button .code",
            );
            expect(code.text()).toBe("XRF");
            expect(code.classes()).toContain("code--tech-1");
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

    describe("components", () => {
        const OBSERVED = uuid(703);
        function withComponents() {
            return {
                annotations: [
                    annotation(1, { component: OBSERVED }),
                    annotation(2, { canvas: "https://iiif.example/c2" }),
                ],
                components: [
                    documentComponent(1),
                    documentComponent(2, {
                        zones: [
                            { ...documentComponent(2).zones[0], canvas: 1 },
                        ],
                    }),
                    documentComponent(3, { zones: [], unpublished: true }),
                ],
            };
        }

        it("lists the components of the page, placed or observed by one of its analyses, and hands the folio their zones on the page", async () => {
            stubFetch(withComponents());
            const { wrapper } = mountScreen();
            await flushPromises();
            expect(
                wrapper
                    .findAll(".on-this-page .components button")
                    .map((button) => button.attributes("data-focus")),
            ).toEqual([`component:${uuid(701)}`, `component:${OBSERVED}`]);
            expect(
                (
                    wrapper.findComponent(FolioStub).props("components") as {
                        id: string;
                    }[]
                ).map((entry) => entry.id),
            ).toEqual([uuid(701)]);
        });

        it("opens the card of a component from the list with the analyses that observe it, and gives the focus back to the entry on close", async () => {
            stubFetch(withComponents());
            const { wrapper, store } = mountScreen(undefined, {
                attachTo: document.body,
            });
            await flushPromises();
            const selector = `.on-this-page [data-focus="component:${OBSERVED}"]`;
            const entry = wrapper.find(selector);
            (entry.element as HTMLButtonElement).focus();
            await entry.trigger("click");
            await flushPromises();
            expect(store.focus).toEqual({ kind: "component", id: OBSERVED });
            const card = wrapper.findComponent({ name: "ComponentCard" });
            expect(card.props("component")).toMatchObject({ id: OBSERVED });
            expect(
                (card.props("analyses") as { id: string }[]).map(
                    (item) => item.id,
                ),
            ).toEqual([uuid(101)]);
            expect(wrapper.find(".on-this-page").exists()).toBe(false);
            card.vm.$emit("close");
            await flushPromises();
            expect(store.focus).toBeNull();
            expect(document.activeElement).toBe(wrapper.find(selector).element);
            wrapper.unmount();
        });

        it("hands the card the materials linked to the component, and the material card its components", async () => {
            const observing = characterization(1, {
                objects: [
                    {
                        id: uuid(701),
                        model: "component",
                        name: label("Component 1"),
                    },
                ],
                components: [
                    {
                        id: uuid(701),
                        model: "component",
                        name: label("Component 1"),
                    },
                ],
            });
            const citing = characterization(2, {
                evidence: [{ id: uuid(101), name: label("MS1_f12_XRF_01") }],
                components: [
                    {
                        id: OBSERVED,
                        model: "component",
                        name: label("Component 3"),
                    },
                ],
            });
            stubFetch({
                ...withComponents(),
                characterizations: [observing, citing, characterization(3)],
            });
            const { wrapper, store } = mountScreen();
            await flushPromises();
            store.focusOn({ kind: "component", id: OBSERVED });
            await flushPromises();
            expect(
                (
                    wrapper
                        .findComponent({ name: "ComponentCard" })
                        .props("materials") as { id: string }[]
                ).map((entry) => entry.id),
            ).toEqual([citing.id]);
            store.focusOn({ kind: "characterization", id: citing.id });
            await flushPromises();
            expect(
                (
                    wrapper
                        .findComponent({ name: "CharacterizationCard" })
                        .props("components") as { id: string }[]
                ).map((entry) => entry.id),
            ).toEqual([OBSERVED]);
        });

        it("opens the card when the folio selects an outline", async () => {
            stubFetch(withComponents());
            const { wrapper, store } = mountScreen();
            await flushPromises();
            wrapper
                .findComponent(FolioStub)
                .vm.$emit("select", { kind: "component", id: uuid(701) });
            await flushPromises();
            expect(store.focus).toEqual({ kind: "component", id: uuid(701) });
            expect(
                wrapper
                    .findComponent({ name: "ComponentCard" })
                    .props("component"),
            ).toMatchObject({ id: uuid(701) });
        });

        it("gives the focus to the document name when an outline opened the card", async () => {
            stubFetch(withComponents());
            const { wrapper, store } = mountScreen(undefined, {
                attachTo: document.body,
            });
            await flushPromises();
            wrapper
                .findComponent(FolioStub)
                .vm.$emit("select", { kind: "component", id: uuid(701) });
            await flushPromises();
            wrapper.findComponent({ name: "ComponentCard" }).vm.$emit("close");
            await flushPromises();
            expect(store.focus).toBeNull();
            expect(document.activeElement).toBe(
                wrapper.find(".document-bar h2").element,
            );
            wrapper.unmount();
        });

        it("follows a component to the page of its first zone", async () => {
            stubFetch(withComponents());
            const { store } = mountScreen();
            await flushPromises();
            store.focusOn({ kind: "component", id: uuid(702) });
            await flushPromises();
            expect(store.document?.canvas).toBe("https://iiif.example/c2");
        });

        it("keeps a component card for a component the document does not hold closed", async () => {
            stubFetch(withComponents());
            const { wrapper, store } = mountScreen();
            await flushPromises();
            store.focusOn({ kind: "component", id: uuid(799) });
            await flushPromises();
            expect(
                wrapper.findComponent({ name: "ComponentCard" }).exists(),
            ).toBe(false);
        });

        it("shows the component card in the drawer on a narrow screen", async () => {
            narrow = true;
            stubFetch(withComponents());
            const { wrapper, store } = mountScreen(undefined, {
                stubs: { transition: false },
            });
            await flushPromises();
            store.focusOn({ kind: "component", id: uuid(701) });
            await flushPromises();
            const card = wrapper.findComponent({ name: "ComponentCard" });
            expect(card.exists()).toBe(true);
            expect(card.props("closable")).toBe(false);
            wrapper.unmount();
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

    it("hands the card the zone of the analysis on the page shown first", async () => {
        stubFetch({
            annotations: [
                annotation(1),
                annotation(1, {
                    key: uuid(902),
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
            wrapper.findComponent({ name: "AnalysisCard" }).props("feature"),
        ).toBe(uuid(902));
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
                    component: null,
                    match: true,
                },
            ],
        });
        const { wrapper, store } = mountScreen();
        await flushPromises();
        store.focusOn({ kind: "analysis", id: uuid(103) });
        await flushPromises();

        expect(
            wrapper.findComponent({ name: "AnalysisCard" }).props("feature"),
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
                component: null,
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
            .filter((button) => button.text() === "Explorer home");
        expect(homeLabels).toHaveLength(1);
        expect(wrapper.text()).not.toContain("Back to the explorer home");
    });

    it("goes back to the results it was opened from", async () => {
        stubFetch();
        const { wrapper, store } = mountScreen((store) => {
            store.setFilter("technique", ["http://x/xrf"]);
            store.setCorpusScreen("results");
            store.openDocument(uuid(1));
        });
        await flushPromises();
        const back = wrapper.find(".return-pill");
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
        expect(wrapper.find(".return-pill").text()).toBe(
            "Results · 30 documents",
        );
    });

    it("counts analyses when the results left list analyses", async () => {
        stubFetch();
        const memo = ref<ResultsMemo>({
            query: "grain=analyses",
            filterKey: "grain=analyses",
            page: 1,
            total: 1,
            grain: "analyses",
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
        expect(wrapper.find(".return-pill").text()).toBe(
            "Results · 1 analysis",
        );
    });

    it("shows the return pill and no breadcrumb", async () => {
        stubFetch();
        const { wrapper } = mountScreen();
        await flushPromises();
        expect(wrapper.find("nav.breadcrumb").exists()).toBe(false);
        expect(wrapper.find(".return-pill").exists()).toBe(true);
    });

    it("gives the folio the soft stage", async () => {
        stubFetch();
        const { wrapper } = mountScreen();
        await flushPromises();
        expect(wrapper.findComponent(FolioStub).props("stage")).toBe("soft");
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
        const back = wrapper.find(".return-pill");
        expect(back.text()).toBe("Explorer home");
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

    it("keeps the page and the scroll when a filter match arrives with a card open", async () => {
        const fetchMock = stubFetch();
        const { wrapper, store } = mountScreen(undefined, {
            attachTo: document.body,
        });
        await flushPromises();
        wrapper
            .findComponent(FolioStub)
            .vm.$emit("select", { kind: "analysis", id: uuid(101) });
        await flushPromises();
        store.setCanvas("https://iiif.example/c2");
        await flushPromises();
        expect(store.document?.canvas).toBe("https://iiif.example/c2");
        const scrolled = vi
            .spyOn(window, "scrollTo")
            .mockImplementation(() => undefined);
        const asked = fetchMock.mock.calls.length;
        await changeFilters(() =>
            store.setFacet("technique", ["http://example.org/xrf"]),
        );
        expect(
            fetchMock.mock.calls
                .slice(asked)
                .some(([url]) => url.includes("/document-match/")),
        ).toBe(true);
        expect(store.focus).toEqual({ kind: "analysis", id: uuid(101) });
        expect(store.document?.canvas).toBe("https://iiif.example/c2");
        expect(wrapper.findComponent(FolioStub).props("canvas")?.id).toBe(
            "https://iiif.example/c2",
        );
        expect(scrolled).not.toHaveBeenCalled();
        scrolled.mockRestore();
        wrapper.unmount();
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
        const entry = wrapper.find(".on-this-page li > button");
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

    it("returns the focus to the list entry that opened the card drawer when Escape closes it", async () => {
        narrow = true;
        stubFetch();
        const { wrapper, store } = mountScreen(undefined, {
            stubs: { transition: false },
            attachTo: document.body,
        });
        await flushPromises();
        const selector = `.on-this-page [data-focus="analysis:${uuid(101)}"]`;
        const entry = wrapper.find(selector);
        (entry.element as HTMLButtonElement).focus();
        await entry.trigger("click");
        await flushPromises();
        expect(store.focus).toEqual({ kind: "analysis", id: uuid(101) });
        expect(document.activeElement).not.toBe(entry.element);
        document.dispatchEvent(
            new KeyboardEvent("keydown", { key: "Escape", code: "Escape" }),
        );
        await flushPromises();
        expect(store.focus).toBeNull();
        expect(document.activeElement).toBe(wrapper.find(selector).element);
        expect(focusTarget).not.toHaveBeenCalled();
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
    describe("layer controls", () => {
        const LAYER = `${uuid(101)}:0`;

        beforeEach(() => {
            window.localStorage.clear();
            reloadRegistrations();
        });
        afterEach(() => {
            window.localStorage.clear();
            reloadRegistrations();
        });
        const ZONE_BOX = { x: 100, y: 100, w: 800, h: 400 };

        async function mountLaidLayer(announce?: (message: string) => void) {
            const base = stubFetch({
                annotations: [
                    annotation(1, {
                        dataKind: "chemical-imaging",
                        shape: { type: "rect", ...ZONE_BOX },
                    }),
                ],
            });
            const fetchMock = vi.fn(async (url: string) =>
                url.includes("/analysis/")
                    ? jsonResponse(analysisPayload({ files: [imagingEntry()] }))
                    : base(url),
            );
            vi.stubGlobal("fetch", fetchMock);
            const { wrapper, store } = mountScreen(
                (opened) => {
                    opened.openDocument(uuid(1));
                    opened.focusOn({ kind: "analysis", id: uuid(101) });
                    opened.setOverlay(LAYER, {
                        element: "Pb",
                        opacity: 0.7,
                        on: true,
                    });
                },
                announce
                    ? {
                          provide: {
                              [ANNOUNCE_KEY as unknown as symbol]: announce,
                          },
                      }
                    : {},
            );
            await flushPromises();
            const folio = wrapper.getComponent({ name: "FolioMap" });
            return { wrapper, store, folio };
        }

        it("lays the layer and hands its controls to the folio", async () => {
            const { wrapper, folio } = await mountLaidLayer();
            expect(folio.props("overlays")).toHaveLength(1);
            expect(folio.props("adjusting")).toBeNull();
            wrapper.unmount();
        });

        it("keeps a new opacity in the layer's setting", async () => {
            const { wrapper, store, folio } = await mountLaidLayer();
            folio.vm.$emit("layer-opacity", LAYER, 0.4);
            expect(store.overlays[LAYER]).toEqual({
                element: "Pb",
                opacity: 0.4,
                on: true,
            });
            wrapper.unmount();
        });

        it("puts the layer under the curtain and takes it off", async () => {
            const { wrapper, folio } = await mountLaidLayer();
            folio.vm.$emit("layer-curtain", LAYER, true);
            await flushPromises();
            expect(folio.props("curtain")).toBe(LAYER);
            folio.vm.$emit("layer-curtain", LAYER, false);
            await flushPromises();
            expect(folio.props("curtain")).toBeNull();
            wrapper.unmount();
        });

        it("tells the folio which layer is being adjusted", async () => {
            const { wrapper, folio } = await mountLaidLayer();
            folio.vm.$emit("layer-adjust", LAYER, true);
            await flushPromises();
            expect(folio.props("adjusting")).toBe(LAYER);
            folio.vm.$emit("layer-adjust", LAYER, false);
            await flushPromises();
            expect(folio.props("adjusting")).toBeNull();
            wrapper.unmount();
        });

        it("turns the layer from the zone's box, then from the registered box, and registers it", async () => {
            const { wrapper, folio } = await mountLaidLayer();
            folio.vm.$emit("layer-turn", LAYER, 1);
            await flushPromises();
            expect(useRegistration().get(uuid(101))).toMatchObject({
                canvas: "https://iiif.example/c1",
                quarter: 1,
                box: { x: 300, y: -100, w: 400, h: 800 },
            });
            expect(folio.props("overlays")[0]).toMatchObject({
                registered: true,
                quarter: 1,
            });
            folio.vm.$emit("layer-turn", LAYER, -1);
            await flushPromises();
            expect(useRegistration().get(uuid(101))).toMatchObject({
                quarter: 0,
                box: ZONE_BOX,
            });
            wrapper.unmount();
        });

        it("registers the box a layer was moved or resized to, keeping its turn", async () => {
            const { wrapper, folio } = await mountLaidLayer();
            folio.vm.$emit("layer-turn", LAYER, 1);
            await flushPromises();
            const moved = { x: 10, y: 20, w: 400, h: 800 };
            folio.vm.$emit("layer-place", LAYER, moved);
            await flushPromises();
            expect(useRegistration().get(uuid(101))).toMatchObject({
                canvas: "https://iiif.example/c1",
                quarter: 1,
                box: moved,
            });
            expect(folio.props("overlays")[0]).toMatchObject({
                registered: true,
                quarter: 1,
            });
            wrapper.unmount();
        });

        it("registers a first move from a layer still at its zone", async () => {
            const { wrapper, folio } = await mountLaidLayer();
            const moved = { x: 150, y: 120, w: 800, h: 400 };
            folio.vm.$emit("layer-place", LAYER, moved);
            await flushPromises();
            expect(useRegistration().get(uuid(101))).toMatchObject({
                quarter: 0,
                box: moved,
            });
            wrapper.unmount();
        });

        it("ignores a place for a layer that is no longer laid", async () => {
            const { wrapper, folio } = await mountLaidLayer();
            folio.vm.$emit("layer-place", "unknown:0", {
                x: 1,
                y: 1,
                w: 9,
                h: 9,
            });
            await flushPromises();
            expect(useRegistration().get(uuid(101))).toBeNull();
            wrapper.unmount();
        });

        it("tells the cards which page the folio shows", async () => {
            const seen: (string | null)[] = [];
            const Probe: Component = {
                setup() {
                    const canvas = inject(FOLIO_CANVAS_KEY, ref("unprovided"));
                    return () => {
                        seen.push(canvas.value);
                        return h("article");
                    };
                },
            };
            vi.stubGlobal("fetch", stubFetch({}));
            const { wrapper } = mountScreen(
                (opened) => {
                    opened.openDocument(uuid(1));
                    opened.focusOn({ kind: "analysis", id: uuid(101) });
                },
                { stubs: { AnalysisCard: Probe } },
            );
            await flushPromises();
            expect(seen.at(-1)).toBe("https://iiif.example/c1");
            wrapper.unmount();
        });

        it("forgets the registered place on reset", async () => {
            const { wrapper, folio } = await mountLaidLayer();
            folio.vm.$emit("layer-turn", LAYER, 1);
            await flushPromises();
            expect(folio.props("overlays")[0]).toMatchObject({
                registered: true,
            });
            folio.vm.$emit("layer-reset", LAYER);
            await flushPromises();
            expect(useRegistration().get(uuid(101))).toBeNull();
            expect(folio.props("overlays")[0]).toMatchObject({
                registered: false,
                quarter: 0,
            });
            wrapper.unmount();
        });

        describe("capturing the folio", () => {
            const CAPTURE = {
                url: "https://iiif.example/image/f12r/0,0,400,300/800,600/0/default.jpg",
                width: 800,
                height: 600,
            };

            function mountCapturing() {
                const announce = vi.fn();
                return mountLaidLayer(announce).then((mounted) => ({
                    ...mounted,
                    announce,
                }));
            }

            it("keeps the capture of the layer's analysis on the current canvas and announces it once", async () => {
                const { wrapper, folio, announce } = await mountCapturing();
                folio.vm.$emit("layer-capture", LAYER);
                await flushPromises();
                expect(folio.props("capturing")).toBe(LAYER);
                folio.vm.$emit("captured", LAYER, CAPTURE);
                await flushPromises();
                const held = useRegistration().get(uuid(101));
                expect(held?.capture).toMatchObject({
                    ...CAPTURE,
                    canvas: expect.any(String),
                    at: expect.any(Number),
                });
                expect(held?.capture?.canvas).toBe(held?.canvas);
                expect(announce).toHaveBeenCalledTimes(1);
                expect(announce).toHaveBeenCalledWith(
                    "Capture saved in this browser.",
                );
                expect(folio.props("capturing")).toBeNull();
                wrapper.unmount();
            });

            it("offers to see the capture in Compare", async () => {
                const { wrapper, store, folio } = await mountCapturing();
                folio.vm.$emit("captured", LAYER, CAPTURE);
                await flushPromises();
                const link = wrapper.find("button.capture-compare");
                expect(link.text()).toBe("See it in Compare");
                await link.trigger("click");
                expect(store.view).toBe("compare");
                wrapper.unmount();
            });

            it("announces a failed capture and stores nothing", async () => {
                const { wrapper, folio, announce } = await mountCapturing();
                folio.vm.$emit("layer-capture", LAYER);
                folio.vm.$emit("capture-failed", LAYER);
                await flushPromises();
                expect(announce).toHaveBeenCalledTimes(1);
                expect(announce).toHaveBeenCalledWith(
                    "The capture could not be taken: the image server did not answer.",
                );
                expect(
                    useRegistration().get(uuid(101))?.capture ?? null,
                ).toBeNull();
                expect(wrapper.find("button.capture-compare").exists()).toBe(
                    false,
                );
                expect(folio.props("capturing")).toBeNull();
                wrapper.unmount();
            });
        });
    });
});
