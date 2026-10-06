import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { flushPromises, mount } from "@vue/test-utils";
import L from "leaflet";
import { ref } from "vue";
import { createPinia, setActivePinia } from "pinia";

import ImagingPane from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/components/ImagingPane.vue";

import {
    ANNOUNCE_KEY,
    LINKED_SELECTION_KEY,
    WINDOW_RESIZE_KEY,
} from "@/manuspectrum/pages/AnalysisExplorer/injection-keys.ts";
import {
    analysisHit,
    imagingEntry,
    layerOf,
    layerMethod,
    layerUnit,
    valueRef,
} from "@/manuspectrum/pages/AnalysisExplorer/testing/fixtures.ts";
import { stubIiifLayer } from "@/manuspectrum/pages/AnalysisExplorer/testing/leaflet.ts";
import {
    AN1,
    startLinkedSelection,
} from "@/manuspectrum/pages/AnalysisExplorer/testing/linked.ts";
import { LAYER_DRAG_TYPE } from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/layer-drag.ts";
import { NEUTRAL_FILTERS } from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/light-table.ts";
import { analysisNode } from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/linked/node-id.ts";

import type { VueWrapper } from "@vue/test-utils";
import type { FileLayer } from "@/manuspectrum/pages/AnalysisExplorer/api/types.ts";
import type { NormalisedView } from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/pane-sync.ts";
import type { MapLine } from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/windows.ts";

vi.hoisted(() => {
    // jsdom's SVG has no createSVGRect: without it Leaflet has no path renderer.
    (
        SVGSVGElement.prototype as unknown as { createSVGRect: () => object }
    ).createSVGRect = () => ({});
});
vi.mock("leaflet-iiif", () => ({}));

const ELEMENT_MAP = valueRef("http://example.org/element-map", "Element map");
const SIZE = { w: 2000, h: 3000 };

function cu(label: string): Partial<FileLayer> {
    return {
        label,
        content: ELEMENT_MAP,
        elements: [
            {
                value: valueRef("http://example.org/el-Cu", "Cu"),
                symbol: "Cu",
            },
        ],
    };
}

/** A map of analysis `n`: canvas ids `c<n>-<index>`, image service `…/image/<n>-<index>`. */
function line(n: number, layers: Partial<FileLayer>[] = [{}, {}]): MapLine {
    const analysis = analysisHit(n);
    return {
        key: `an:${analysis.id}:-`,
        slot: n,
        analysis,
        file: imagingEntry({
            id: `${analysis.id}:imaging:0`,
            layers: layers.map((overrides, index) =>
                layerOf({
                    index,
                    id: `c${n}-${index}`,
                    label: `L${n}.${index}`,
                    image: {
                        service: `https://iiif.example/image/${n}-${index}`,
                        url: null,
                        width: 2000,
                        height: 3000,
                    },
                    ...overrides,
                }),
            ),
        }),
        named: null,
    };
}

let iiif: ReturnType<typeof stubIiifLayer>;
let wrapper: VueWrapper | null = null;
let frames: FrameRequestCallback[] = [];

beforeEach(() => {
    setActivePinia(createPinia());
    iiif = stubIiifLayer({ size: SIZE });
    frames = [];
    vi.stubGlobal("requestAnimationFrame", (callback: FrameRequestCallback) =>
        frames.push(callback),
    );
    vi.stubGlobal("cancelAnimationFrame", () => {
        frames = [];
    });
    // jsdom lays nothing out: Leaflet reads a container size of 0.
    Object.defineProperty(HTMLElement.prototype, "clientWidth", {
        configurable: true,
        get: () => 800,
    });
    Object.defineProperty(HTMLElement.prototype, "clientHeight", {
        configurable: true,
        get: () => 600,
    });
});

afterEach(() => {
    wrapper?.unmount();
    wrapper = null;
    vi.unstubAllGlobals();
    delete (HTMLElement.prototype as unknown as Record<string, unknown>)
        .clientWidth;
    delete (HTMLElement.prototype as unknown as Record<string, unknown>)
        .clientHeight;
});

interface Options {
    canvas?: string | null;
    maps?: MapLine[];
    view?: NormalisedView | null;
    scaleNote?: object | null;
    filters?: typeof NEUTRAL_FILTERS;
    provide?: Record<symbol, unknown>;
}

async function mountPane(options: Options = {}): Promise<VueWrapper> {
    wrapper = mount(ImagingPane, {
        attachTo: document.body,
        props: {
            canvas: options.canvas === undefined ? "c1-0" : options.canvas,
            maps: options.maps ?? [line(1)],
            letter: "A",
            active: false,
            filters: options.filters ?? { ...NEUTRAL_FILTERS },
            view: options.view ?? null,
            scaleNote: options.scaleNote ?? null,
        },
        global: {
            provide: {
                [WINDOW_RESIZE_KEY as symbol]: ref(0),
                ...options.provide,
            },
        },
    });
    await flushPromises();
    return wrapper;
}

function leafletMap(view: VueWrapper): L.Map {
    return (view.vm as unknown as { leafletMap: () => L.Map }).leafletMap();
}

function onTiles(view: VueWrapper): HTMLElement {
    return view.find(".leaflet-tile-pane").element as HTMLElement;
}

describe("the image", () => {
    it("lays the canvas through its image service, not fitted by leaflet-iiif", async () => {
        await mountPane();
        expect(iiif).toHaveBeenCalledTimes(1);
        expect(iiif).toHaveBeenCalledWith(
            "https://iiif.example/image/1-0/info.json",
            { fitBounds: false, setMaxBounds: false },
        );
    });

    it("says the size the service serves, once the page is laid", async () => {
        const view = await mountPane();
        expect(view.emitted("size-read")).toEqual([
            [{ canvas: "c1-0", size: SIZE }],
        ]);
    });

    it("lays nothing in an empty pane", async () => {
        const view = await mountPane({ canvas: null });
        expect(iiif).not.toHaveBeenCalled();
        expect(view.text()).toContain("Empty pane");
    });

    it("takes the old page off and lays the new one when the canvas changes, the map staying", async () => {
        const view = await mountPane();
        const map = view.find(".leaflet-container").element;
        const removed = vi.spyOn(L.Map.prototype, "removeLayer");
        await view.setProps({ canvas: "c1-1" });
        await flushPromises();
        expect(removed).toHaveBeenCalledTimes(1);
        expect(iiif).toHaveBeenCalledTimes(2);
        expect(iiif).toHaveBeenLastCalledWith(
            "https://iiif.example/image/1-1/info.json",
            expect.anything(),
        );
        expect(view.find(".leaflet-container").element).toBe(map);
        removed.mockRestore();
    });

    it("keeps the view across a canvas served at the same size and fits one served at another", async () => {
        iiif = stubIiifLayer({
            size: (url) => (url.includes("1-2") ? { w: 600, h: 1000 } : SIZE),
        });
        const view = await mountPane({
            maps: [line(1, [{}, {}, {}])],
        });
        const zoomed = leafletMap(view).getZoom() + 1;
        leafletMap(view).setZoom(zoomed, { animate: false });
        await view.setProps({ canvas: "c1-1" });
        await flushPromises();
        expect(leafletMap(view).getZoom()).toBe(zoomed);
        await view.setProps({ canvas: "c1-2" });
        await flushPromises();
        const fresh = await mountPane({
            maps: [line(1, [{}, {}, {}])],
            canvas: "c1-2",
        });
        const fitted = leafletMap(fresh).getZoom();
        expect(fitted).not.toBe(zoomed);
        expect(leafletMap(view).getZoom()).toBe(fitted);
        view.unmount();
    });

    it("tells that the map is unavailable when the info.json cannot be read, and tries again on request", async () => {
        iiif = stubIiifLayer();
        const view = await mountPane();
        expect(view.text()).toContain("Map unavailable (image server)");
        expect(iiif).toHaveBeenCalledTimes(1);
        iiif = stubIiifLayer({ size: SIZE });
        await view.find('[data-action="retry"]').trigger("click");
        await flushPromises();
        expect(iiif).toHaveBeenCalledTimes(1);
        expect(view.text()).not.toContain("Map unavailable");
        expect(view.emitted("size-read")).toHaveLength(1);
    });

    it("reads an image without a service by its URL and its natural size", async () => {
        class FakeImage {
            onload: (() => void) | null = null;
            onerror: (() => void) | null = null;
            naturalWidth = 600;
            naturalHeight = 1000;
            set src(_value: string) {
                queueMicrotask(() => this.onload?.());
            }
        }
        vi.stubGlobal("Image", FakeImage);
        const view = await mountPane({
            maps: [
                line(1, [
                    {
                        image: {
                            service: null,
                            url: "https://img.example/a.jpg",
                            width: 0,
                            height: 0,
                        },
                    },
                ]),
            ],
        });
        expect(iiif).not.toHaveBeenCalled();
        expect(view.emitted("size-read")).toEqual([
            [{ canvas: "c1-0", size: { w: 600, h: 1000 } }],
        ]);
    });
});

describe("filters", () => {
    it("sets the CSS filter of the tile pane, none when neutral", async () => {
        const view = await mountPane();
        expect(onTiles(view).style.filter).toBe("");
        await view.setProps({
            filters: {
                brightness: 150,
                contrast: 100,
                saturation: 100,
                greyscale: true,
            },
        });
        expect(onTiles(view).style.filter).toBe(
            "brightness(1.5) contrast(1) saturate(1) grayscale(1)",
        );
    });

    it("opens the filters under a button that says so, and passes their events on", async () => {
        const view = await mountPane({
            filters: { ...NEUTRAL_FILTERS, greyscale: true },
        });
        const button = view.find('[data-action="filters"]');
        expect(button.attributes("aria-expanded")).toBe("false");
        expect(view.find("fieldset").exists()).toBe(false);
        await button.trigger("click");
        expect(button.attributes("aria-expanded")).toBe("true");
        await view.findAll('input[type="range"]')[0].setValue("130");
        await view.find('[data-action="reset"]').trigger("click");
        await view.find('[data-action="apply-all"]').trigger("click");
        expect(view.emitted("filters-change")).toEqual([[{ brightness: 130 }]]);
        expect(view.emitted("filters-reset")).toHaveLength(1);
        expect(view.emitted("filters-apply-all")).toHaveLength(1);
    });
});

describe("stepping", () => {
    it("steps to the next and the previous layer of the same manifest", async () => {
        const view = await mountPane({ canvas: "c1-1" });
        await view.find('[data-action="previous"]').trigger("click");
        expect(view.emitted("step")).toEqual([[-1]]);
        const first = await mountPane({ canvas: "c1-0" });
        await first.find('[data-action="next"]').trigger("click");
        expect(first.emitted("step")).toEqual([[1]]);
    });

    it("cannot step past the first or the last layer", async () => {
        const view = await mountPane({ canvas: "c1-0" });
        expect(
            view.find('[data-action="previous"]').attributes("aria-disabled"),
        ).toBe("true");
        await view.find('[data-action="previous"]').trigger("click");
        expect(view.emitted("step")).toBeUndefined();
    });

    it("steps with the [ and ] keys", async () => {
        const view = await mountPane({ canvas: "c1-0" });
        const map = view.find(".leaflet-container");
        await map.trigger("keydown", { key: "]" });
        await map.trigger("keydown", { key: "[" });
        expect(view.emitted("step")).toEqual([[1], [-1]]);
    });
});

describe("the chip", () => {
    it("names the pane by its letter, its stored label and its analysis, with no tag without a mapping", async () => {
        const view = await mountPane();
        expect(view.find(".chip").text()).toContain("A");
        expect(view.find(".chip").text()).toContain("L1.0");
        expect(view.find(".chip").text()).toContain("MS1_f12_XRF_03");
        expect(view.find(".tag").exists()).toBe(false);
        expect(view.find(".leaflet-container").attributes("aria-label")).toBe(
            "Pane A: L1.0, MS1_f12_XRF_03",
        );
        expect(view.find(".leaflet-container").attributes("role")).toBe(
            "group",
        );
    });

    it("shows the tag of a mapped layer", async () => {
        const view = await mountPane({
            maps: [line(1, [cu("Cu Lα map")])],
        });
        expect(view.find(".tag").text()).toBe("Cu");
    });

    async function tagOf(overrides: Partial<FileLayer>): Promise<string> {
        const view = await mountPane({ maps: [line(1, [overrides])] });
        const text = view.find(".tag").text();
        view.unmount();
        return text;
    }

    it("writes a component with its method, else as a component", async () => {
        const content = valueRef("http://example.org/c", "Component");
        expect(
            await tagOf({
                content,
                processing: {
                    method: layerMethod(),
                    index: 3,
                    inputs: null,
                },
            }),
        ).toBe("PCA 3");
        expect(
            await tagOf({
                content,
                processing: { method: null, index: 3, inputs: null },
            }),
        ).toBe("Component 3");
    });

    it("writes a band with its symbol, and a lone bound as a limit", async () => {
        const content = valueRef("http://example.org/b", "Band");
        const unit = layerUnit("Nanometre", "nm");
        expect(
            await tagOf({
                content,
                band: { value: 650, lower: null, upper: null, unit },
            }),
        ).toBe("650 nm");
        expect(
            await tagOf({
                content,
                band: { value: null, lower: null, upper: 700, unit },
            }),
        ).toBe("≤ 700 nm");
    });
});

describe("the pairing chip", () => {
    it("is absent without a mapping", async () => {
        const view = await mountPane({ maps: [line(1), line(2)] });
        expect(view.find('[data-action="pair"]').exists()).toBe(false);
    });

    it("offers the same family of the next analysis, and says so when it is clicked", async () => {
        const view = await mountPane({
            maps: [line(1, [cu("Cu 1")]), line(2, [{}, cu("Cu 2")])],
        });
        const chip = view.find('[data-action="pair"]');
        expect(chip.text()).toContain("Cu");
        expect(chip.text()).toContain("MS2_f12_XRF_03");
        await chip.trigger("click");
        expect(view.emitted("pair")).toEqual([["c2-1"]]);
    });
});

describe("the scale badge", () => {
    it("is there only when the pane has a scale note", async () => {
        const view = await mountPane();
        expect(view.find(".scale-badge").exists()).toBe(false);
        await view.setProps({
            scaleNote: {
                canvas: "c1-0",
                size: { w: 600, h: 1202 },
                against: "c2-0",
                againstSize: { w: 1529, h: 2405 },
            },
        });
        expect(view.find(".scale-badge").exists()).toBe(true);
    });
});

describe("the view", () => {
    it("emits the view of the reader's moves once per frame, with its canvas", async () => {
        const view = await mountPane();
        await view.find('[data-action="zoom-in"]').trigger("click");
        expect(view.emitted("view-changed")).toBeUndefined();
        frames.splice(0).forEach((callback) => callback(0));
        const emitted = view.emitted("view-changed") as NormalisedView[][];
        expect(emitted).toHaveLength(1);
        expect(emitted[0][0].origin).toBe("c1-0");
        expect(emitted[0][0].size).toEqual(SIZE);
        expect(emitted[0][0].dz).toBeGreaterThan(0);
    });

    it("follows a view of another pane without sending it back", async () => {
        const view = await mountPane();
        const before = leafletMap(view).getZoom();
        await view.setProps({
            view: { cx: 0.5, cy: 0.5, dz: 2, size: SIZE, origin: "c2-0" },
        });
        frames.splice(0).forEach((callback) => callback(0));
        expect(leafletMap(view).getZoom()).toBe(before + 2);
        expect(view.emitted("view-changed")).toBeUndefined();
    });

    it("keeps its centre when the view comes from an image served at another size, and takes its relative zoom", async () => {
        const view = await mountPane();
        const centre = leafletMap(view).getCenter();
        const before = leafletMap(view).getZoom();
        await view.setProps({
            view: {
                cx: 0.1,
                cy: 0.9,
                dz: 1,
                size: { w: 600, h: 1202 },
                origin: "c2-0",
            },
        });
        expect(leafletMap(view).getCenter()).toEqual(centre);
        expect(leafletMap(view).getZoom()).toBe(before + 1);
    });

    it("redraws its map when the window changes size", async () => {
        const tick = ref(0);
        await mountPane({ provide: { [WINDOW_RESIZE_KEY as symbol]: tick } });
        const invalidate = vi.spyOn(L.Map.prototype, "invalidateSize");
        tick.value += 1;
        await flushPromises();
        expect(invalidate).toHaveBeenCalled();
        invalidate.mockRestore();
    });
});

describe("dropping a canvas", () => {
    function drop(view: VueWrapper, id: string): Promise<void> {
        return view.find(".imaging-pane").trigger("drop", {
            dataTransfer: {
                getData: (type: string) => (type === LAYER_DRAG_TYPE ? id : ""),
            },
        });
    }

    it("asks to place a canvas of the Selection", async () => {
        const view = await mountPane({ maps: [line(1), line(2)] });
        await drop(view, "c2-1");
        expect(view.emitted("place")).toEqual([["c2-1"]]);
    });

    it("ignores what is not a canvas of the Selection", async () => {
        const view = await mountPane();
        await drop(view, "https://evil.example/x");
        expect(view.emitted("place")).toBeUndefined();
    });
});

describe("the focus", () => {
    it("never lays a page or touches a layer when the focus changes; it only tints the pane", async () => {
        const { linked, stop } = startLinkedSelection();
        const view = await mountPane({
            maps: [
                {
                    ...line(1),
                    analysis: analysisHit(1, { id: AN1 }),
                },
            ],
            provide: { [LINKED_SELECTION_KEY as symbol]: linked },
        });
        const add = vi.spyOn(L.Map.prototype, "addLayer");
        const remove = vi.spyOn(L.Map.prototype, "removeLayer");
        const setView = vi.spyOn(L.Map.prototype, "setView");
        const before = iiif.mock.calls.length;
        linked.toggle(analysisNode(AN1));
        await flushPromises();
        expect(view.find(".imaging-pane").attributes("data-rel")).toBe("self");
        linked.toggle(analysisNode(AN1));
        await flushPromises();
        expect(iiif.mock.calls.length).toBe(before);
        expect(add).not.toHaveBeenCalled();
        expect(remove).not.toHaveBeenCalled();
        expect(setView).not.toHaveBeenCalled();
        add.mockRestore();
        remove.mockRestore();
        setView.mockRestore();
        stop();
    });
});

describe("announcements", () => {
    it("announces a canvas laid and a map that failed", async () => {
        const announce = vi.fn();
        const view = await mountPane({
            provide: { [ANNOUNCE_KEY as symbol]: announce },
        });
        expect(announce).toHaveBeenCalledWith("Pane A: L1.0");
        iiif = stubIiifLayer();
        await view.setProps({ canvas: "c1-1" });
        await flushPromises();
        expect(announce).toHaveBeenCalledWith(
            "Pane A: map unavailable (image server)",
        );
    });
});
