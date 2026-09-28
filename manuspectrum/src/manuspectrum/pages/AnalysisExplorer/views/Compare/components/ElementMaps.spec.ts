import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { flushPromises, mount } from "@vue/test-utils";
import L from "leaflet";
import PrimeVue from "primevue/config";
import { ref } from "vue";
import { createPinia, setActivePinia } from "pinia";

import ElementMaps from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/components/ElementMaps.vue";

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

function layer(
    index: number,
    name: string,
    kind: FileLayer["kind"] = "element",
): FileLayer {
    const value = Number.parseInt(name, 10);
    return {
        index,
        label: name,
        kind,
        element: kind === "element" ? name : null,
        band: kind === "band" ? { value, unit: "nm" } : null,
        image: {
            service: `https://iiif.example/image/${name.replace(" ", "")}`,
            url: null,
            width: 900,
            height: 600,
        },
    };
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
    wrapper = mount(ElementMaps, {
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

function laidOn(view: VueWrapper): (string | null)[] {
    return view.findAll(".element-map-card").map((card) => {
        const image = card.find("img.folio-overlay");
        if (image.exists()) return image.attributes("alt") ?? null;
        const note = card.find(".not-mapped");
        return note.exists() ? note.text() : null;
    });
}

describe("ElementMaps", () => {
    it("shows the maps side by side, each under its slot and name, with one layer picker over them", async () => {
        const view = await mountMaps();
        expect(
            view.findAll("figcaption").map((caption) => caption.text()),
        ).toEqual([
            expect.stringMatching(/^A1.*map-1$/),
            expect.stringMatching(/^A2.*map-2$/),
        ]);
        const picker = view.find(".layer-picker");
        expect(picker.find("label").text()).toBe("Element");
        expect(picker.findAll("option").map((option) => option.text())).toEqual(
            ["Pb", "Hg", "Cu"],
        );
        expect(view.text()).toContain("Each map keeps its own contrast.");
    });

    it("reads a document shared by several maps once", async () => {
        await mountMaps();
        expect(fetchMock).toHaveBeenCalledTimes(1);
    });

    it("holds the chosen layer on every map, and says so where a map lacks it", async () => {
        const view = await mountMaps();
        expect(laidOn(view)).toEqual(["Pb", "Pb"]);
        await view.find(".layer-picker select").setValue(1);
        await flushPromises();
        expect(laidOn(view)).toEqual(["Hg", "Element not mapped"]);
        await view.find(".layer-picker select").setValue(2);
        await flushPromises();
        expect(laidOn(view)).toEqual(["Element not mapped", "Cu"]);
    });

    it("scrolls every map through the layers together, saying where the handle is", async () => {
        const view = await mountMaps();
        view.findComponent({ name: "Slider" }).vm.$emit("update:modelValue", 1);
        await flushPromises();
        expect(laidOn(view)).toEqual(["Hg", "Element not mapped"]);
        expect(
            (view.find(".layer-picker select").element as HTMLSelectElement)
                .value,
        ).toBe("1");
        expect(
            view.find(".scroll [role=slider]").attributes("aria-valuetext"),
        ).toBe("Hg, layer 2 of 3");
    });

    it("names bands by their kind and sorts them by value", async () => {
        const view = await mountMaps([
            map(0, [layer(0, "650 nm", "band"), layer(1, "400 nm", "band")]),
            map(1, [layer(0, "450 nm", "band")]),
        ]);
        expect(view.find(".layer-picker label").text()).toBe("Band");
        expect(
            view.findAll(".layer-picker option").map((option) => option.text()),
        ).toEqual(["400 nm", "450 nm", "650 nm"]);
        expect(laidOn(view)).toEqual(["400 nm", "Band not mapped"]);
    });

    it("puts each map's layer under a curtain of its own, over its page", async () => {
        const view = await mountMaps();
        expect(sideBySide).toHaveBeenCalledTimes(2);
        const card = view.findAll(".element-map-card")[0];
        await card.find("input.curtain").setValue(false);
        expect(sideBySide.mock.results[0].value.remove).toHaveBeenCalled();
        expect(sideBySide.mock.results[1].value.remove).not.toHaveBeenCalled();
        expect(view.text()).toContain(
            "Indicative positioning, not registered.",
        );
    });

    it("shows a map without a zone on a page alone", async () => {
        const view = await mountMaps([map(0, [layer(0, "Pb")], null)]);
        expect(fetchMock).not.toHaveBeenCalled();
        const card = view.find(".element-map-card");
        expect(card.find("img.layer-image").attributes("alt")).toBe("Pb");
        expect(card.find("input.curtain").exists()).toBe(false);
        expect(card.text()).toContain(
            "No zone on a page: the map is shown alone.",
        );
    });

    it("says when the image server does not give a map, and lays it again on Retry", async () => {
        const view = await mountMaps();
        const card = view.findAll(".element-map-card")[0];
        await card.find("img.folio-overlay").trigger("error");
        const status = card.find(".unavailable");
        expect(status.text()).toContain("Map unavailable (image server)");
        await status.find("button").trigger("click");
        await flushPromises();
        expect(card.text()).not.toContain("Map unavailable (image server)");
        expect(card.find("img.folio-overlay").exists()).toBe(true);
    });

    it("draws the maps again when the window is resized", async () => {
        const resize = vi.spyOn(L.Map.prototype, "invalidateSize");
        await mountMaps();
        resize.mockClear();
        resizeTick.value += 1;
        await flushPromises();
        expect(resize).toHaveBeenCalledTimes(2);
    });

    it("takes each map down with its page and its curtain when the window closes", async () => {
        const iiif = stubIiifLayer({ laid: true });
        const view = await mountMaps();
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
            wrapper = mount(ElementMaps, {
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

        function shown(view: VueWrapper): string {
            const picker = view.find(".layer-picker select")
                .element as HTMLSelectElement;
            return picker.selectedOptions[0]?.text.trim() ?? "";
        }

        afterEach(() => {
            stopLinked?.();
            stopLinked = null;
            vi.useRealTimers();
        });

        it("switches the shared layer to an element selected, says so, and brings the previous one back once it is unselected", async () => {
            const { view, linked } = await mountLinked();
            expect(shown(view)).toBe("Fe Ka");
            linked.toggle(elementNode("Pb"));
            await flushPromises();
            expect(shown(view)).toBe("Pb La");
            expect(announce).toHaveBeenLastCalledWith(
                "1 selected · 3 related. The element maps show Pb La.",
            );
            linked.toggle(elementNode("Pb"));
            await flushPromises();
            expect(shown(view)).toBe("Fe Ka");
            expect(announce).toHaveBeenLastCalledWith(
                "Nothing selected. The element maps show Fe Ka again.",
            );
        });

        it("follows the last element selected that a map holds", async () => {
            const { view, linked } = await mountLinked();
            linked.toggle(elementNode("Cu"));
            linked.toggle(elementNode("Zn"));
            await flushPromises();
            expect(shown(view)).toBe("Cu");
            linked.toggle(elementNode("Pb"));
            await flushPromises();
            expect(shown(view)).toBe("Pb La");
        });

        it("keeps the layer the reader picked once the element is unselected", async () => {
            const { view, linked } = await mountLinked();
            linked.toggle(elementNode("Pb"));
            await flushPromises();
            await view.find(".layer-picker select").setValue(2);
            linked.toggle(elementNode("Pb"));
            await flushPromises();
            expect(shown(view)).toBe("Cu");
        });

        it("never switches the layer on a preview", async () => {
            vi.useFakeTimers();
            const { view, linked } = await mountLinked();
            linked.preview(elementNode("Pb"), { pointerType: "mouse" });
            vi.runAllTimers();
            await view.vm.$nextTick();
            expect(shown(view)).toBe("Fe Ka");
            expect(
                view.find(".element-map-card").attributes("data-preview"),
            ).toBe("direct");
        });

        it("marks each map by its analysis and selects it from its name", async () => {
            const { view, linked } = await mountLinked();
            linked.toggle(elementNode("Fe"));
            await flushPromises();
            expect(
                view
                    .findAll(".element-map-card")
                    .map((card) => card.attributes("data-rel")),
            ).toEqual(["direct", "none"]);
            linked.clear();
            await view.find(".element-map-card button.record").trigger("click");
            expect(useExplorerStore().compare.selection).toEqual([
                analysisNode(AN1),
            ]);
            expect(view.find(".element-map-card").attributes("data-rel")).toBe(
                "self",
            );
        });
    });
});
