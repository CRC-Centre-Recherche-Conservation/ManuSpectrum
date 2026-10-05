import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { flushPromises, mount } from "@vue/test-utils";
import L from "leaflet";
import PrimeVue from "primevue/config";
import { ref } from "vue";
import { createPinia, setActivePinia } from "pinia";

import ChemicalImaging from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/components/ChemicalImaging.vue";

import { forgetPayloads } from "@/manuspectrum/pages/AnalysisExplorer/api/http.ts";
import {
    ANNOUNCE_KEY,
    LINKED_SELECTION_KEY,
    WINDOW_RESIZE_KEY,
} from "@/manuspectrum/pages/AnalysisExplorer/injection-keys.ts";
import { useExplorerStore } from "@/manuspectrum/pages/AnalysisExplorer/store/explorer.ts";
import {
    analysisHit,
    documentPayload,
    imagingEntry,
    label,
    layerOf,
    uuid,
} from "@/manuspectrum/pages/AnalysisExplorer/testing/fixtures.ts";
import {
    sizedContainer,
    stubIiifLayer,
} from "@/manuspectrum/pages/AnalysisExplorer/testing/leaflet.ts";
import {
    AN1,
    ITEMS,
    startLinkedSelection,
} from "@/manuspectrum/pages/AnalysisExplorer/testing/linked.ts";
import { jsonResponse } from "@/manuspectrum/pages/AnalysisExplorer/testing/responses.ts";
import {
    analysisNode,
    elementNode,
} from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/linked/node-id.ts";

import type { VueWrapper } from "@vue/test-utils";
import type {
    AnalysisHit,
    DocumentPayload,
    FileEntry,
    FileLayer,
} from "@/manuspectrum/pages/AnalysisExplorer/api/types.ts";
import type { LinkedSelection } from "@/manuspectrum/pages/AnalysisExplorer/composables/useLinkedSelection.ts";
import type { MapLine } from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/windows.ts";

vi.hoisted(() => {
    // jsdom's SVG has no createSVGRect: without it Leaflet has no path renderer.
    (
        SVGSVGElement.prototype as unknown as { createSVGRect: () => object }
    ).createSVGRect = () => ({});
});
vi.mock("leaflet-iiif", () => ({}));
vi.mock("leaflet-side-by-side", () => ({}));
vi.mock("utils/leaflet-stack", () => ({ stackSmallestOnTop: vi.fn() }));
vi.mock("@/arches/utils/generate-arches-url.ts", () => ({
    generateArchesURL: (_name: string, parameters: Record<string, string>) =>
        `/en/api/explorer/document/${parameters.resourceid}`,
}));

const REAL_SIDE_BY_SIDE = L.control.sideBySide;
const REAL_IIIF = (L.tileLayer as unknown as { iiif: unknown }).iiif;

const C1 = "https://iiif.example/c1";
const ZONE = { type: "rect" as const, x: 100, y: 100, w: 800, h: 400 };
const DOCUMENT: DocumentPayload = documentPayload({
    canvases: documentPayload().canvases.map((canvas, index) =>
        index === 0
            ? {
                  ...canvas,
                  image: {
                      service: "https://iiif.example/image/c1",
                      url: null,
                      width: 4000,
                      height: 6000,
                  },
              }
            : canvas,
    ),
    analyses: [101, 102].map((n) => ({
        id: uuid(n),
        name: label(`MS1_${n}`),
        technique: null,
        dataKind: "chemical-imaging" as const,
        unpublished: false,
        zones: [{ canvas: 0, shape: ZONE, feature: `f${n}` }],
    })),
});

function layer(index: number, name: string): FileLayer {
    return layerOf({
        index,
        label: name,
        image: {
            service: `https://iiif.example/image/${name.replace(" ", "")}`,
            url: null,
            width: 900,
            height: 600,
        },
    });
}

function map(
    slot: number,
    layers: FileLayer[],
    canvas: string | null = C1,
): MapLine {
    const analysis = analysisHit(slot + 1, {
        canvas,
        dataKinds: ["chemical-imaging"],
    });
    return {
        key: `an:${analysis.id}:-`,
        slot,
        analysis,
        file: imagingEntry({ name: `map-${slot + 1}`, layers }),
        named: null,
    };
}

const XRF_MAPS = [
    map(0, [layer(0, "Pb"), layer(1, "Hg")]),
    map(1, [layer(0, "Cu"), layer(1, "Pb")]),
];

let fetchMock: ReturnType<typeof vi.fn>;
let sideBySide: ReturnType<typeof vi.fn>;
let resizeTick = ref(0);
let wrapper: VueWrapper | null = null;

beforeEach(() => {
    setActivePinia(createPinia());
    forgetPayloads();
    stubIiifLayer();
    fetchMock = vi.fn(async () => jsonResponse(DOCUMENT));
    vi.stubGlobal("fetch", fetchMock);
    sideBySide = vi.fn(() => ({
        addTo: vi.fn().mockReturnThis(),
        on: vi.fn().mockReturnThis(),
        remove: vi.fn(),
        setRightLayers: vi.fn().mockReturnThis(),
        _range: document.createElement("input"),
    }));
    L.control.sideBySide = sideBySide as unknown as typeof L.control.sideBySide;
    resizeTick = ref(0);
});

afterEach(() => {
    wrapper?.unmount();
    wrapper = null;
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
    L.control.sideBySide = REAL_SIDE_BY_SIDE;
    (L.tileLayer as unknown as { iiif: unknown }).iiif = REAL_IIIF;
});

async function mountMaps(maps: MapLine[] = XRF_MAPS): Promise<VueWrapper> {
    wrapper = mount(ChemicalImaging, {
        attachTo: sizedContainer(),
        props: { maps },
        global: {
            plugins: [PrimeVue],
            provide: { [WINDOW_RESIZE_KEY as symbol]: resizeTick },
        },
    });
    await flushPromises();
    return wrapper;
}

/** The label of the layer each map currently shows. */
function shown(view: VueWrapper): string[] {
    return view
        .findAll(".chemical-imaging-map")
        .map((card) => card.find(".imaging-preview .current .value").text());
}

async function lay(view: VueWrapper, index: number): Promise<void> {
    await view
        .findAll(".chemical-imaging-map")
        [index].find("input.lay")
        .setValue(true);
    await flushPromises();
}

/** The end labels of the layer scroll of the map at `index`. */
function ends(view: VueWrapper, index: number): string[] {
    return view
        .findAll(".imaging-preview .scroll")
        [index].findAll(".ends span")
        .map((end) => end.text());
}

describe("ChemicalImaging", () => {
    it("shows the maps side by side, each under its slot and name, each on its own first layer", async () => {
        const view = await mountMaps();
        expect(
            view.findAll("figcaption").map((caption) => caption.text()),
        ).toEqual([
            expect.stringMatching(/^A1.*map-1$/),
            expect.stringMatching(/^A2.*map-2$/),
        ]);
        expect(shown(view)).toEqual(["Pb", "Cu"]);
        expect(
            view.text().split("Each map keeps its own contrast.").length - 1,
        ).toBe(1);
    });

    it("shows no shared layer control: each map has its own layer scroll", async () => {
        const view = await mountMaps();
        expect(view.find(".sync").exists()).toBe(false);
        expect(view.find(".layer-picker").exists()).toBe(false);
        expect(view.find(".shared").exists()).toBe(false);
        expect(view.findAll(".imaging-preview .scroll")).toHaveLength(2);
    });

    it("reads a document shared by several maps once", async () => {
        await mountMaps();
        expect(fetchMock).toHaveBeenCalledTimes(1);
    });

    it("steps a map through its own layers by their stored label, leaving the other maps untouched", async () => {
        const view = await mountMaps();
        const first = view.findAllComponents({ name: "Slider" })[0];
        expect(ends(view, 0)).toEqual(["Pb", "Hg"]);
        first.vm.$emit("update:modelValue", 1);
        await flushPromises();
        expect(shown(view)).toEqual(["Hg", "Cu"]);
    });

    it("keeps each map's layers in the order given, without sorting or grouping them", async () => {
        const view = await mountMaps([
            map(0, [layer(0, "650 nm"), layer(1, "400 nm")]),
        ]);
        expect(ends(view, 0)).toEqual(["650 nm", "400 nm"]);
    });

    it("lays a map on its own page under a curtain of its own, keeping it out of the document screen", async () => {
        const view = await mountMaps();
        expect(view.findAll(".leaflet-container")).toHaveLength(0);
        await lay(view, 0);
        const card = view.findAll(".chemical-imaging-map")[0];
        expect(card.find("img.folio-overlay").attributes("alt")).toBe("Pb");
        expect(card.find("img.layer-image").exists()).toBe(false);
        expect(view.findAll(".leaflet-container")).toHaveLength(1);
        expect(sideBySide).not.toHaveBeenCalled();
        await card.find("input.curtain").setValue(true);
        expect(sideBySide).toHaveBeenCalledTimes(1);
        expect(view.text()).toContain(
            "Indicative positioning, not registered.",
        );
        expect(useExplorerStore().overlays).toEqual({});
    });

    it("carries a laid map to the layer its own scroll moves to", async () => {
        const view = await mountMaps();
        await lay(view, 0);
        const first = view.findAllComponents({ name: "Slider" })[0];
        first.vm.$emit("update:modelValue", 1);
        await flushPromises();
        const card = view.findAll(".chemical-imaging-map")[0];
        expect(card.find("img.folio-overlay").attributes("alt")).toBe("Hg");
    });

    it("shows a map without a zone on a page alone, with nothing to lay it on", async () => {
        const view = await mountMaps([map(0, [layer(0, "Pb")], null)]);
        expect(fetchMock).not.toHaveBeenCalled();
        const card = view.find(".chemical-imaging-map");
        expect(card.find("img.layer-image").attributes("alt")).toBe("Pb");
        expect(card.find("input.lay").attributes("disabled")).toBeDefined();
        expect(card.text()).toContain("no zone on this page");
    });

    it("says when the image server does not give a map, and asks again on Retry", async () => {
        const view = await mountMaps();
        const card = view.findAll(".chemical-imaging-map")[0];
        // Bounded, percentage, then max, each once; only the last failing is reported.
        await card.find("img.layer-image").trigger("error");
        await card.find("img.layer-image").trigger("error");
        await card.find("img.layer-image").trigger("error");
        const status = card.find(".unavailable");
        expect(status.text()).toContain("Map unavailable (image server)");
        await status.find("button").trigger("click");
        expect(card.find("img.layer-image").exists()).toBe(true);
    });

    it("says when a laid map is not given, and lays it again on Retry", async () => {
        const view = await mountMaps();
        await lay(view, 0);
        const card = view.findAll(".chemical-imaging-map")[0];
        await card.find("img.folio-overlay").trigger("error");
        await card.find("img.folio-overlay").trigger("error");
        await card.find("img.folio-overlay").trigger("error");
        expect(card.find(".unavailable").text()).toContain(
            "Map unavailable (image server)",
        );
        await card.find(".unavailable button").trigger("click");
        await flushPromises();
        expect(card.find("img.folio-overlay").exists()).toBe(true);
    });

    it("draws the laid maps again when the window is resized", async () => {
        const resize = vi.spyOn(L.Map.prototype, "invalidateSize");
        const view = await mountMaps();
        await lay(view, 0);
        await lay(view, 1);
        resize.mockClear();
        resizeTick.value += 1;
        await flushPromises();
        expect(resize).toHaveBeenCalledTimes(2);
    });

    it("takes each laid map down with its page and its curtain when the window closes", async () => {
        const iiif = stubIiifLayer({ laid: true });
        const view = await mountMaps();
        for (const index of [0, 1]) {
            await lay(view, index);
            await view
                .findAll(".chemical-imaging-map")
                [index].find("input.curtain")
                .setValue(true);
        }
        const pages = iiif.mock.results.map((result) => result.value);
        expect(pages).toHaveLength(2);
        const removeLayer = vi.spyOn(L.Map.prototype, "removeLayer");
        const removeMap = vi.spyOn(L.Map.prototype, "remove");
        view.unmount();
        wrapper = null;
        expect(removeMap).toHaveBeenCalledTimes(2);
        const lastMapRemoved = Math.max(...removeMap.mock.invocationCallOrder);
        for (const page of pages) {
            const call = removeLayer.mock.calls.findIndex(
                ([layer]) => layer === page,
            );
            expect(call).toBeGreaterThanOrEqual(0);
            expect(removeLayer.mock.invocationCallOrder[call]).toBeLessThan(
                lastMapRemoved,
            );
        }
        expect(sideBySide).toHaveBeenCalledTimes(2);
        for (const result of sideBySide.mock.results) {
            expect(result.value.remove).toHaveBeenCalled();
        }
    });

    describe("with the linked selection", () => {
        let stopLinked: (() => void) | null = null;
        let announce: ReturnType<typeof vi.fn>;

        async function mountLinked(): Promise<{
            view: VueWrapper;
            linked: LinkedSelection;
        }> {
            announce = vi.fn();
            const started = startLinkedSelection(announce);
            stopLinked = started.stop;
            const first = ITEMS[0] as {
                key: string;
                analysis: AnalysisHit;
                files: FileEntry[];
            };
            const second = ITEMS[1] as { key: string; analysis: AnalysisHit };
            const maps: MapLine[] = [
                {
                    key: first.key,
                    slot: 0,
                    analysis: first.analysis,
                    file: first.files[1],
                    named: null,
                },
                {
                    key: second.key,
                    slot: 1,
                    analysis: second.analysis,
                    file: imagingEntry({
                        name: "map-2",
                        layers: [layer(0, "Cu")],
                    }),
                    named: null,
                },
            ];
            wrapper = mount(ChemicalImaging, {
                attachTo: sizedContainer(),
                props: { maps },
                global: {
                    plugins: [PrimeVue],
                    provide: {
                        [WINDOW_RESIZE_KEY as symbol]: resizeTick,
                        [ANNOUNCE_KEY as symbol]: announce,
                        [LINKED_SELECTION_KEY as symbol]: started.linked,
                    },
                },
            });
            await flushPromises();
            return { view: wrapper, linked: started.linked };
        }

        afterEach(() => {
            stopLinked?.();
            stopLinked = null;
            vi.useRealTimers();
        });

        it("does not change any map's layer when an element is pinned, even one named like a layer of a map", async () => {
            const { view, linked } = await mountLinked();
            const before = shown(view);
            expect(before).toEqual(["Fe Ka", "Cu"]);
            linked.toggle(elementNode("Cu"));
            await flushPromises();
            expect(shown(view)).toEqual(before);
            expect(view.find(".sync").exists()).toBe(false);
        });

        it("marks each map by its analysis and selects it from its name", async () => {
            const { view, linked } = await mountLinked();
            linked.toggle(analysisNode(AN1));
            await flushPromises();
            expect(
                view
                    .findAll(".chemical-imaging-map")
                    .map((card) => card.attributes("data-rel")),
            ).toEqual(["self", "none"]);
            linked.clear();
            await view
                .find(".chemical-imaging-map button.record")
                .trigger("click");
            expect(useExplorerStore().compare.selection).toEqual([
                analysisNode(AN1),
            ]);
            expect(
                view.find(".chemical-imaging-map").attributes("data-rel"),
            ).toBe("self");
        });
    });
});
