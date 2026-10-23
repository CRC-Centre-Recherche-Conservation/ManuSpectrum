import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { flushPromises, mount } from "@vue/test-utils";
import L from "leaflet";
import { ref } from "vue";
import { createPinia, setActivePinia } from "pinia";

import LayerStack from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/components/LayerStack.vue";

import {
    ANNOUNCE_KEY,
    LINKED_SELECTION_KEY,
    WINDOW_RESIZE_KEY,
} from "@/manuspectrum/pages/AnalysisExplorer/injection-keys.ts";
import {
    analysisHit,
    imagingEntry,
    layerOf,
    valueRef,
} from "@/manuspectrum/pages/AnalysisExplorer/testing/fixtures.ts";
import {
    drawnExtent,
    maxNativeZoomOf,
} from "@/manuspectrum/pages/AnalysisExplorer/testing/leaflet.ts";
import {
    AN1,
    startLinkedSelection,
} from "@/manuspectrum/pages/AnalysisExplorer/testing/linked.ts";
import { LAYER_DRAG_TYPE } from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/layer-drag.ts";
import { NEUTRAL_FILTERS } from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/light-table.ts";
import { analysisNode } from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/linked/node-id.ts";
import { tintMatrix } from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/stack-panes.ts";
import {
    ELEMENT_TINTS,
    NO_TINT,
    RANK_TINTS,
} from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/stack-tints.ts";

import type { VueWrapper } from "@vue/test-utils";
import type { FileLayer } from "@/manuspectrum/pages/AnalysisExplorer/api/types.ts";
import type { StackLayer } from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/light-table.ts";
import type { MapLine } from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/windows.ts";

vi.hoisted(() => {
    (
        SVGSVGElement.prototype as unknown as { createSVGRect: () => object }
    ).createSVGRect = () => ({});
});
vi.mock("leaflet-iiif", () => ({}));

const SIZE = { w: 2000, h: 3000 };
const SMALL = { w: 600, h: 1000 };

type Fake = L.LayerGroup & {
    _imageSizes: { x: number; y: number }[];
    maxNativeZoom: number;
    _served: { w: number; h: number };
    options: { pane?: string; zoomOffset?: number; maxNativeZoom?: number };
    setBounds: ReturnType<typeof vi.fn>;
    _fitBounds: ReturnType<typeof vi.fn>;
};

let factory: ReturnType<typeof vi.fn>;
let fakes: Fake[] = [];
let sizes: (url: string) => { w: number; h: number } | null;
let wrapper: VueWrapper | null = null;

function cu(label: string): Partial<FileLayer> {
    return {
        label,
        content: valueRef("http://example.org/element-map", "Element map"),
        elements: [
            {
                value: valueRef("http://example.org/el-Cu", "Cu"),
                symbol: "Cu",
            },
        ],
    };
}

function band(label: string): Partial<FileLayer> {
    return {
        label,
        content: valueRef("http://example.org/hsi", "HSI band"),
        band: { value: 650, lower: null, upper: null, unit: null },
    };
}

/** A map of analysis `n`: canvas ids `c<n>-<index>`, image service `…/image/<n>-<index>`. */
function line(n: number, layers: Partial<FileLayer>[] = [{}, {}, {}]): MapLine {
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

function stacked(
    canvas: string,
    overrides: Partial<StackLayer> = {},
): StackLayer {
    return { canvas, opacity: 100, on: true, tint: null, ...overrides };
}

beforeEach(() => {
    setActivePinia(createPinia());
    fakes = [];
    sizes = () => SIZE;
    factory = vi.fn((infoUrl: string, options: { pane?: string }) => {
        const served = sizes(infoUrl);
        const layer = Object.assign(L.layerGroup(), {
            options: served
                ? { ...options, maxNativeZoom: maxNativeZoomOf(served) }
                : options,
            setBounds: vi.fn(),
            _fitBounds: vi.fn(),
            ...(served
                ? {
                      _imageSizes: [{ x: served.w, y: served.h }],
                      maxNativeZoom: maxNativeZoomOf(served),
                      _served: served,
                  }
                : {}),
        }) as unknown as Fake;
        fakes.push(layer);
        return layer;
    });
    (L.tileLayer as unknown as { iiif: unknown }).iiif = factory;
    vi.stubGlobal("requestAnimationFrame", () => 1);
    vi.stubGlobal("cancelAnimationFrame", () => undefined);
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
    vi.useRealTimers();
    vi.unstubAllGlobals();
    delete (HTMLElement.prototype as unknown as Record<string, unknown>)
        .clientWidth;
    delete (HTMLElement.prototype as unknown as Record<string, unknown>)
        .clientHeight;
});

interface Options {
    maps?: MapLine[];
    layers?: StackLayer[];
    analysis?: string | null;
    notes?: Map<string, object>;
    filters?: typeof NEUTRAL_FILTERS;
    provide?: Record<symbol, unknown>;
}

async function mountStack(options: Options = {}): Promise<VueWrapper> {
    const layers = options.layers ?? [stacked("c1-0"), stacked("c1-1")];
    wrapper = mount(LayerStack, {
        attachTo: document.body,
        props: {
            maps: options.maps ?? [line(1)],
            stack: {
                analysis:
                    options.analysis === undefined
                        ? analysisHit(1).id
                        : options.analysis,
                layers,
            },
            filters: options.filters ?? { ...NEUTRAL_FILTERS },
            notes: options.notes ?? new Map(),
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

function paneOf(view: VueWrapper, index: number): HTMLElement {
    const name = fakes[index].options.pane as string;
    return leafletMap(view).getPane(name) as HTMLElement;
}

function rows(view: VueWrapper): ReturnType<VueWrapper["findAll"]> {
    return view.findAll(".layers li");
}

describe("the layers", () => {
    it("lays each layer through its own service, in a pane of its own, fitted by nobody", async () => {
        const view = await mountStack();
        expect(factory).toHaveBeenCalledTimes(2);
        expect(factory).toHaveBeenNthCalledWith(
            1,
            "https://iiif.example/image/1-0/info.json",
            expect.objectContaining({
                fitBounds: false,
                setMaxBounds: false,
                tileFormat: "png",
            }),
        );
        expect(fakes[0].options.pane).not.toBe(fakes[1].options.pane);
        expect(paneOf(view, 0)).not.toBe(paneOf(view, 1));
    });

    it("keeps each layer at the bounds its service serves: nothing is set, fitted or stretched", async () => {
        sizes = (url) => (url.includes("1-1") ? SMALL : SIZE);
        const view = await mountStack();
        await view.setProps({
            stack: {
                analysis: analysisHit(1).id,
                layers: [
                    stacked("c1-1", { opacity: 40 }),
                    stacked("c1-0", { tint: RANK_TINTS[3].key }),
                ],
            },
            filters: { ...NEUTRAL_FILTERS, brightness: 150 },
        });
        for (const fake of fakes) {
            expect(fake.setBounds).not.toHaveBeenCalled();
            expect(fake._fitBounds).not.toHaveBeenCalled();
        }
        expect(fakes[0]._imageSizes).toEqual([{ x: 2000, y: 3000 }]);
        expect(fakes[1]._imageSizes).toEqual([{ x: 600, y: 1000 }]);
        for (let index = 0; index < 2; index += 1) {
            const pane = paneOf(view, index);
            expect(pane.style.width).toBe("");
            expect(pane.style.height).toBe("");
            expect(pane.style.transform).toBe("");
        }
    });

    it("says the size each layer is served at", async () => {
        sizes = (url) => (url.includes("1-1") ? SMALL : SIZE);
        const view = await mountStack();
        expect(view.emitted("size-read")).toEqual([
            [{ canvas: "c1-0", size: SIZE }],
            [{ canvas: "c1-1", size: SMALL }],
        ]);
    });

    it("lays a layer added later and takes off one that left", async () => {
        const view = await mountStack();
        await view.setProps({
            stack: {
                analysis: analysisHit(1).id,
                layers: [stacked("c1-0"), stacked("c1-1"), stacked("c1-2")],
            },
        });
        await flushPromises();
        expect(factory).toHaveBeenCalledTimes(3);
        const removed = vi.spyOn(L.Map.prototype, "removeLayer");
        await view.setProps({
            stack: { analysis: analysisHit(1).id, layers: [stacked("c1-0")] },
        });
        await flushPromises();
        expect(removed).toHaveBeenCalledTimes(2);
        expect(factory).toHaveBeenCalledTimes(3);
        removed.mockRestore();
    });

    it("keeps the map out of the blending of the page", async () => {
        const view = await mountStack();
        expect(leafletMap(view).getContainer().style.isolation).toBe("isolate");
    });

    it("lays nothing for an empty stack and says how to fill it", async () => {
        const view = await mountStack({ layers: [], analysis: null });
        expect(factory).not.toHaveBeenCalled();
        expect(view.text()).toContain("The stack is empty");
    });

    it("tells a layer that cannot be read, the others staying", async () => {
        sizes = (url) => (url.includes("1-1") ? null : SIZE);
        const view = await mountStack();
        expect(rows(view)[1].text()).toContain("Map unavailable");
        expect(rows(view)[0].text()).not.toContain("Map unavailable");
    });
});

describe("blend, opacity and visibility", () => {
    it("blends every layer but the first shown with screen", async () => {
        const view = await mountStack({
            layers: [
                stacked("c1-0", { on: false }),
                stacked("c1-1"),
                stacked("c1-2"),
            ],
        });
        // The hidden layer is not laid: fakes are c1-1 then c1-2.
        expect(paneOf(view, 0).style.getPropertyValue("mix-blend-mode")).toBe(
            "normal",
        );
        expect(paneOf(view, 1).style.getPropertyValue("mix-blend-mode")).toBe(
            "screen",
        );
    });

    it("sets the opacity of a layer's pane", async () => {
        const view = await mountStack({
            layers: [stacked("c1-0"), stacked("c1-1", { opacity: 35 })],
        });
        expect(paneOf(view, 1).style.opacity).toBe("0.35");
    });

    it("emits the opacity chosen on a layer's range", async () => {
        const view = await mountStack();
        await rows(view)[1].find('input[type="range"]').setValue("55");
        expect(view.emitted("set-opacity")).toEqual([
            [{ canvas: "c1-1", opacity: 55 }],
        ]);
    });

    it("asks the stack to hide or show a layer under the eye, and hides its pane once it is off", async () => {
        const view = await mountStack();
        await rows(view)[0].find('[data-action="visible"]').trigger("click");
        expect(view.emitted("set-visible")).toEqual([
            [{ canvas: "c1-0", on: false }],
        ]);
        expect(paneOf(view, 0).style.display).toBe("");
        await view.setProps({
            stack: {
                analysis: analysisHit(1).id,
                layers: [stacked("c1-0", { on: false }), stacked("c1-1")],
            },
        });
        expect(paneOf(view, 0).style.display).toBe("none");
        await rows(view)[0].find('[data-action="visible"]').trigger("click");
        expect(view.emitted("set-visible")?.[1]).toEqual([
            { canvas: "c1-0", on: true },
        ]);
    });

    it("lays only layers that are on, and a hidden layer once it is switched on", async () => {
        const view = await mountStack({
            layers: [stacked("c1-0"), stacked("c1-1", { on: false })],
        });
        expect(factory).toHaveBeenCalledTimes(1);
        await view.setProps({
            stack: {
                analysis: analysisHit(1).id,
                layers: [stacked("c1-0"), stacked("c1-1")],
            },
        });
        await flushPromises();
        expect(factory).toHaveBeenCalledTimes(2);
    });

    it("applies the stack's filters to every layer's pane, before the hue", async () => {
        const view = await mountStack({
            filters: { ...NEUTRAL_FILTERS, brightness: 150 },
        });
        expect(paneOf(view, 0).style.filter).toMatch(
            /^brightness\(1\.5\) .*url\(#/,
        );
    });
});

describe("without layer tiles", () => {
    it("tints by rank and shows the stored labels, with no tag", async () => {
        const view = await mountStack({ maps: [line(1)] });
        const swatches = view.findAll(".layers .swatch");
        expect(swatches[0].attributes("style")).toContain(RANK_TINTS[0].token);
        expect(swatches[1].attributes("style")).toContain(RANK_TINTS[1].token);
        expect(rows(view)[0].text()).toContain("L1.0");
        expect(view.find(".tag").exists()).toBe(false);
        expect(paneOf(view, 0).style.filter).toMatch(/^url\(#.+\)$/);
    });

    it("draws the hue through an feColorMatrix per hue used, referenced by the pane", async () => {
        const view = await mountStack();
        const matrices = view
            .findAll("svg.tint-filters feColorMatrix")
            .map((node) => node.attributes("values"));
        expect(matrices).toEqual([
            tintMatrix(RANK_TINTS[0].rgb),
            tintMatrix(RANK_TINTS[1].rgb),
        ]);
        const id = view.find("svg.tint-filters filter").attributes("id");
        expect(paneOf(view, 0).style.filter).toContain(`url(#${id})`);
    });

    it("refuses a layer of another analysis and says so", async () => {
        const announce = vi.fn();
        const view = await mountStack({
            maps: [line(1), line(2)],
            provide: { [ANNOUNCE_KEY as symbol]: announce },
        });
        await view.find(".layer-stack").trigger("drop", {
            dataTransfer: {
                getData: (type: string) =>
                    type === LAYER_DRAG_TYPE ? "c2-0" : "",
            },
        });
        expect(view.emitted("add")).toBeUndefined();
        expect(announce).toHaveBeenCalledWith(
            "A stack holds the layers of one analysis: L2.0 is not added",
        );
    });
});

describe("with some tiles", () => {
    it("tints a layer of one element by the element and not by rank", async () => {
        const view = await mountStack({
            maps: [line(1, [{}, cu("Cu Lα"), band("650 nm")])],
            layers: [stacked("c1-0"), stacked("c1-1"), stacked("c1-2")],
        });
        const cuTint = ELEMENT_TINTS.get("Cu");
        const swatches = view.findAll(".layers .swatch");
        expect(swatches[1].attributes("style")).toContain("--map-cu");
        const matrices = view
            .findAll("svg.tint-filters feColorMatrix")
            .map((node) => node.attributes("values"));
        expect(matrices).toContain(tintMatrix(cuTint?.rgb ?? [0, 0, 0]));
        const id = view
            .findAll("svg.tint-filters filter")
            .find(
                (node) =>
                    node.find("feColorMatrix").attributes("values") ===
                    tintMatrix(cuTint?.rgb ?? [0, 0, 0]),
            )
            ?.attributes("id");
        expect(paneOf(view, 1).style.filter).toContain(`url(#${id})`);
    });

    it("does not tint a band", async () => {
        const view = await mountStack({
            maps: [line(1, [band("650 nm"), {}])],
            layers: [stacked("c1-0"), stacked("c1-1")],
        });
        expect(paneOf(view, 0).style.filter).toBe("");
        expect(view.findAll(".layers .swatch")[0].classes()).toContain("none");
    });

    it("takes the reader's tint over the default, and none over everything", async () => {
        const view = await mountStack({
            maps: [line(1, [cu("Cu Lα"), {}])],
            layers: [
                stacked("c1-0", { tint: RANK_TINTS[5].key }),
                stacked("c1-1", { tint: NO_TINT }),
            ],
        });
        expect(
            view.findAll(".layers .swatch")[0].attributes("style"),
        ).toContain(RANK_TINTS[5].token);
        expect(paneOf(view, 1).style.filter).toBe("");
    });
});

describe("the palette", () => {
    it("offers the default, none and twelve hues, and says the choice", async () => {
        const view = await mountStack();
        const row = rows(view)[0];
        expect(row.find(".palette").exists()).toBe(false);
        await row.find('[data-action="tint"]').trigger("click");
        expect(row.findAll(".palette button")).toHaveLength(14);
        await row.find(`[data-tint="${RANK_TINTS[4].key}"]`).trigger("click");
        await row.find('[data-action="tint"]').trigger("click");
        await row.find('[data-tint="none"]').trigger("click");
        await row.find('[data-action="tint"]').trigger("click");
        await row.find('[data-tint="default"]').trigger("click");
        expect(view.emitted("set-tint")).toEqual([
            [{ canvas: "c1-0", tint: RANK_TINTS[4].key }],
            [{ canvas: "c1-0", tint: NO_TINT }],
            [{ canvas: "c1-0", tint: null }],
        ]);
    });
});

describe("the order", () => {
    it("moves a layer up and down, and cannot past the ends", async () => {
        const view = await mountStack();
        await rows(view)[1].find('[data-action="up"]').trigger("click");
        await rows(view)[0].find('[data-action="down"]').trigger("click");
        await rows(view)[0].find('[data-action="up"]').trigger("click");
        await rows(view)[1].find('[data-action="down"]').trigger("click");
        expect(view.emitted("move")).toEqual([
            [{ canvas: "c1-1", step: -1 }],
            [{ canvas: "c1-0", step: 1 }],
        ]);
    });

    it("stacks the panes as the stack is ordered", async () => {
        const view = await mountStack();
        const [first, second] = [paneOf(view, 0), paneOf(view, 1)];
        expect(Number(second.style.zIndex)).toBeGreaterThan(
            Number(first.style.zIndex),
        );
        await view.setProps({
            stack: {
                analysis: analysisHit(1).id,
                layers: [stacked("c1-1"), stacked("c1-0")],
            },
        });
        expect(Number(second.style.zIndex)).toBeLessThan(
            Number(first.style.zIndex),
        );
        expect(factory).toHaveBeenCalledTimes(2);
    });

    it("takes a layer out", async () => {
        const view = await mountStack();
        await rows(view)[1].find('[data-action="remove"]').trigger("click");
        expect(view.emitted("remove")).toEqual([["c1-1"]]);
    });
});

describe("the scale of the layers in one map", () => {
    const SMALLER = { w: 600, h: 1202 };
    const LARGER = { w: 1529, h: 2405 };

    function expectPixelRatio(first: Fake, second: Fake): void {
        const a = drawnExtent(first);
        const b = drawnExtent(second);
        expect(b.w / a.w).toBeCloseTo(second._served.w / first._served.w, 6);
        expect(b.h / a.h).toBeCloseTo(second._served.h / first._served.h, 6);
    }

    it("draws layers of different power-of-two buckets in the ratio of their pixels", async () => {
        sizes = (url) => (url.includes("1-1") ? LARGER : SMALLER);
        await mountStack();
        expect([fakes[0].maxNativeZoom, fakes[1].maxNativeZoom]).toEqual([
            3, 4,
        ]);
        expectPixelRatio(fakes[0], fakes[1]);
    });

    it("keeps the ratio whichever of the two is laid first", async () => {
        sizes = (url) => (url.includes("1-0") ? LARGER : SMALLER);
        await mountStack();
        expectPixelRatio(fakes[0], fakes[1]);
    });

    it("keeps the ratio when a smaller layer is added to the stack later", async () => {
        sizes = (url) => (url.includes("1-1") ? SMALLER : LARGER);
        const view = await mountStack({ layers: [stacked("c1-0")] });
        await view.setProps({
            stack: {
                analysis: analysisHit(1).id,
                layers: [stacked("c1-0"), stacked("c1-1")],
            },
        });
        await flushPromises();
        expectPixelRatio(fakes[1], fakes[0]);
    });
});

describe("the layers without an image service", () => {
    class FakeImage {
        static sizes: Record<string, { w: number; h: number }> = {};
        onload: (() => void) | null = null;
        onerror: (() => void) | null = null;
        naturalWidth = 0;
        naturalHeight = 0;
        set src(value: string) {
            const size = FakeImage.sizes[value];
            if (!size) {
                queueMicrotask(() => this.onerror?.());
                return;
            }
            this.naturalWidth = size.w;
            this.naturalHeight = size.h;
            queueMicrotask(() => this.onload?.());
        }
    }

    function bareLine(): MapLine {
        const base = line(1, [{}, {}]);
        base.file.layers[0].image = {
            service: null,
            url: "https://img.example/a.png",
            width: 0,
            height: 0,
        };
        return base;
    }

    beforeEach(() => {
        FakeImage.sizes = { "https://img.example/a.png": SMALL };
        vi.stubGlobal("Image", FakeImage);
    });

    it("lays a layer given by URL as an image overlay at its natural size, in its own pane", async () => {
        const view = await mountStack({ maps: [bareLine()] });
        const map = leafletMap(view);
        const overlays: L.ImageOverlay[] = [];
        map.eachLayer((layer) => {
            if (layer instanceof L.ImageOverlay) overlays.push(layer);
        });
        expect(overlays).toHaveLength(1);
        expect(overlays[0].options.pane).toMatch(/^folio-overlay-stack-/);
        expect(view.emitted("size-read")).toContainEqual([
            { canvas: "c1-0", size: SMALL },
        ]);
        expect(view.find(".layers li").text()).not.toContain("unavailable");
    });

    it("draws it in the ratio of its pixels to those of a layer served by a service", async () => {
        const view = await mountStack({ maps: [bareLine()] });
        const map = leafletMap(view);
        let overlay: L.ImageOverlay | null = null;
        map.eachLayer((layer) => {
            if (layer instanceof L.ImageOverlay) overlay = layer;
        });
        const bare = drawnExtent(overlay as unknown as L.ImageOverlay);
        const served = drawnExtent(fakes[0]);
        expect(bare.w / served.w).toBeCloseTo(SMALL.w / SIZE.w, 6);
        expect(bare.h / served.h).toBeCloseTo(SMALL.h / SIZE.h, 6);
    });

    it("says a layer without service or URL is unavailable", async () => {
        const maps = [bareLine()];
        maps[0].file.layers[0].image = {
            service: null,
            url: null,
            width: 0,
            height: 0,
        };
        const view = await mountStack({ maps });
        expect(view.findAll(".layers li")[0].text()).toContain(
            "Map unavailable",
        );
    });
});

describe("the panes of the layers", () => {
    function twinLine(): MapLine {
        const base = line(1, [{}, {}]);
        base.file.layers[0].id = "https://x/c_1";
        base.file.layers[1].id = "https://x/c-1";
        return base;
    }

    it("gives two canvas ids that differ only by a punctuation character two panes", async () => {
        const view = await mountStack({
            maps: [twinLine()],
            layers: [stacked("https://x/c_1"), stacked("https://x/c-1")],
        });
        expect(fakes[0].options.pane).not.toBe(fakes[1].options.pane);
        expect(paneOf(view, 0)).not.toBe(paneOf(view, 1));
        expect(paneOf(view, 0)).toBeTruthy();
        expect(paneOf(view, 1)).toBeTruthy();
    });

    it("takes the pane of a layer off the map when the layer leaves the stack", async () => {
        const view = await mountStack({
            maps: [twinLine()],
            layers: [stacked("https://x/c_1"), stacked("https://x/c-1")],
        });
        const gone = fakes[1].options.pane as string;
        const kept = fakes[0].options.pane as string;
        await view.setProps({
            stack: {
                analysis: analysisHit(1).id,
                layers: [stacked("https://x/c_1")],
            },
        });
        await flushPromises();
        expect(leafletMap(view).getPane(gone)).toBeUndefined();
        expect(leafletMap(view).getPane(kept)).toBeDefined();
    });
});

describe("the scale", () => {
    const note = {
        canvas: "c1-1",
        size: SMALL,
        against: "c1-0",
        againstSize: SIZE,
    };

    it("badges the layers whose size differs and says the layers are not at the same scale", async () => {
        const view = await mountStack({ notes: new Map([["c1-1", note]]) });
        expect(rows(view)[0].find(".scale-badge").exists()).toBe(false);
        expect(rows(view)[1].find(".scale-badge").exists()).toBe(true);
        expect(view.text()).toContain(
            "The layers are not all at the same scale: they are laid centred, not registered.",
        );
    });

    it("says nothing when every size is the same", async () => {
        const view = await mountStack();
        expect(view.find(".scale-badge").exists()).toBe(false);
        expect(view.text()).not.toContain("not all at the same scale");
    });
});

describe("dropping a canvas", () => {
    function drop(view: VueWrapper, id: string): Promise<void> {
        return view.find(".layer-stack").trigger("drop", {
            dataTransfer: {
                getData: (type: string) => (type === LAYER_DRAG_TYPE ? id : ""),
            },
        });
    }

    it("adds a canvas of the stack's analysis", async () => {
        const view = await mountStack();
        await drop(view, "c1-2");
        expect(view.emitted("add")).toEqual([["c1-2"]]);
    });

    it("adds any analysis's canvas to an empty stack", async () => {
        const view = await mountStack({
            maps: [line(1), line(2)],
            layers: [],
            analysis: null,
        });
        await drop(view, "c2-0");
        expect(view.emitted("add")).toEqual([["c2-0"]]);
    });

    it("leaves a layer already in the stack alone and ignores what is not a canvas", async () => {
        const view = await mountStack();
        await drop(view, "c1-0");
        await drop(view, "https://evil.example/x");
        expect(view.emitted("add")).toBeUndefined();
    });
});

describe("the filters", () => {
    it("opens the stack's filters and passes their events on", async () => {
        const view = await mountStack({
            filters: { ...NEUTRAL_FILTERS, greyscale: true },
        });
        const button = view.find('[data-action="filters"]');
        expect(button.attributes("aria-expanded")).toBe("false");
        await button.trigger("click");
        expect(button.attributes("aria-expanded")).toBe("true");
        await view
            .find("fieldset")
            .findAll('input[type="range"]')[0]
            .setValue("130");
        await view.find('[data-action="reset"]').trigger("click");
        await view.find('[data-action="apply-all"]').trigger("click");
        expect(view.emitted("filters-change")).toEqual([[{ brightness: 130 }]]);
        expect(view.emitted("filters-reset")).toHaveLength(1);
        expect(view.emitted("filters-apply-all")).toHaveLength(1);
    });
});

describe("the focus", () => {
    it("never lays, adds, removes or redraws a layer when the focus changes; it only tints the stack", async () => {
        const { linked, stop } = startLinkedSelection();
        const view = await mountStack({
            maps: [{ ...line(1), analysis: analysisHit(1, { id: AN1 }) }],
            analysis: AN1,
            provide: { [LINKED_SELECTION_KEY as symbol]: linked },
        });
        const add = vi.spyOn(L.Map.prototype, "addLayer");
        const remove = vi.spyOn(L.Map.prototype, "removeLayer");
        const setView = vi.spyOn(L.Map.prototype, "setView");
        const before = factory.mock.calls.length;
        linked.toggle(analysisNode(AN1));
        await flushPromises();
        expect(view.find(".layer-stack").attributes("data-rel")).toBe("self");
        linked.toggle(analysisNode(AN1));
        await flushPromises();
        expect(factory.mock.calls.length).toBe(before);
        expect(add).not.toHaveBeenCalled();
        expect(remove).not.toHaveBeenCalled();
        expect(setView).not.toHaveBeenCalled();
        for (const fake of fakes) expect(fake.setBounds).not.toHaveBeenCalled();
        add.mockRestore();
        remove.mockRestore();
        setView.mockRestore();
        stop();
    });
});

describe("announcements", () => {
    it("announces a layer laid", async () => {
        const announce = vi.fn();
        await mountStack({
            provide: { [ANNOUNCE_KEY as symbol]: announce },
        });
        expect(announce).toHaveBeenCalledWith("Stack: L1.0");
    });
});

describe("labels with quotes and angle brackets", () => {
    it("names the row buttons as typed, not escaped twice", async () => {
        const view = await mountStack({
            maps: [line(1, [{ label: 'Map "Pb" <i>' }, {}, {}])],
            layers: [stacked("c1-0")],
        });
        const text = view.text();
        expect(text).toContain('Hide Map "Pb" <i>');
        expect(text).not.toContain("&quot;");
    });
});
