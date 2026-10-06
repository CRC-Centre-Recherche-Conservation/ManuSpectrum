import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { flushPromises, mount } from "@vue/test-utils";
import L from "leaflet";
import { ref } from "vue";
import { createPinia, setActivePinia } from "pinia";

import CurtainPane from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/components/CurtainPane.vue";

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
import {
    drawnExtent,
    stubIiifLayer,
} from "@/manuspectrum/pages/AnalysisExplorer/testing/leaflet.ts";
import {
    AN1,
    startLinkedSelection,
} from "@/manuspectrum/pages/AnalysisExplorer/testing/linked.ts";
import { LAYER_DRAG_TYPE } from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/layer-drag.ts";
import { NEUTRAL_FILTERS } from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/light-table.ts";
import { analysisNode } from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/linked/node-id.ts";

import type { VueWrapper } from "@vue/test-utils";
import type { FileLayer } from "@/manuspectrum/pages/AnalysisExplorer/api/types.ts";
import type { ScaleNote } from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/scale-notes.ts";
import type { MapLine } from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/windows.ts";

vi.hoisted(() => {
    (
        SVGSVGElement.prototype as unknown as { createSVGRect: () => object }
    ).createSVGRect = () => ({});
});
vi.mock("leaflet-iiif", () => ({}));
vi.mock("leaflet-side-by-side", () => ({}));

const SIZE = { w: 2000, h: 3000 };
const SMALL = { w: 600, h: 1000 };
const DIVIDER = 400;

interface FakeCurtain {
    addTo: ReturnType<typeof vi.fn>;
    remove: ReturnType<typeof vi.fn>;
    setLeftLayers: ReturnType<typeof vi.fn>;
    setRightLayers: ReturnType<typeof vi.fn>;
    getPosition: () => number;
    _range: HTMLInputElement;
}

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
let sideBySide: ReturnType<typeof vi.fn>;
let wrapper: VueWrapper | null = null;

beforeEach(() => {
    setActivePinia(createPinia());
    iiif = stubIiifLayer({ size: SIZE });
    sideBySide = vi.fn(() => {
        const control: FakeCurtain = {
            addTo: vi.fn(() => control),
            remove: vi.fn(),
            setLeftLayers: vi.fn(() => control),
            setRightLayers: vi.fn(() => control),
            getPosition: () => DIVIDER,
            _range: document.createElement("input"),
        };
        return control;
    });
    L.control.sideBySide = sideBySide as unknown as typeof L.control.sideBySide;
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
    vi.unstubAllGlobals();
    delete (HTMLElement.prototype as unknown as Record<string, unknown>)
        .clientWidth;
    delete (HTMLElement.prototype as unknown as Record<string, unknown>)
        .clientHeight;
});

interface Options {
    canvasA?: string | null;
    canvasB?: string | null;
    maps?: MapLine[];
    scaleNote?: ScaleNote | null;
    filtersB?: typeof NEUTRAL_FILTERS;
    provide?: Record<symbol, unknown>;
}

async function mountCurtain(options: Options = {}): Promise<VueWrapper> {
    wrapper = mount(CurtainPane, {
        attachTo: document.body,
        props: {
            canvasA: options.canvasA === undefined ? "c1-0" : options.canvasA,
            canvasB: options.canvasB === undefined ? "c2-0" : options.canvasB,
            maps: options.maps ?? [line(1), line(2)],
            filtersA: { ...NEUTRAL_FILTERS },
            filtersB: options.filtersB ?? { ...NEUTRAL_FILTERS },
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

function control(): FakeCurtain {
    return sideBySide.mock.results[0].value as FakeCurtain;
}

function leafletMap(view: VueWrapper): L.Map {
    return (view.vm as unknown as { leafletMap: () => L.Map }).leafletMap();
}

function paneOf(view: VueWrapper, side: 0 | 1): HTMLElement {
    const layer = iiif.mock.results[side].value as L.Layer;
    const name = (iiif.mock.calls[side][1] as { pane: string }).pane;
    expect(layer).toBeDefined();
    return leafletMap(view).getPane(name) as HTMLElement;
}

describe("the curtain", () => {
    it("lays the two canvases, of two analyses, each in a pane of its own and not fitted by leaflet-iiif", async () => {
        const view = await mountCurtain();
        expect(iiif).toHaveBeenCalledTimes(2);
        const [first, second] = iiif.mock.calls;
        expect(first[0]).toBe("https://iiif.example/image/1-0/info.json");
        expect(second[0]).toBe("https://iiif.example/image/2-0/info.json");
        expect(first[1]).toMatchObject({ fitBounds: false });
        expect(first[1].pane).not.toBe(second[1].pane);
        expect(paneOf(view, 0)).not.toBe(paneOf(view, 1));
    });

    it("makes one L.control.sideBySide with side A on the left and side B on the right", async () => {
        await mountCurtain();
        expect(sideBySide).toHaveBeenCalledTimes(1);
        expect(control().addTo).toHaveBeenCalledTimes(1);
        expect(control().setLeftLayers).toHaveBeenLastCalledWith(
            iiif.mock.results[0].value,
        );
        expect(control().setRightLayers).toHaveBeenLastCalledWith(
            iiif.mock.results[1].value,
        );
    });

    it("names the divider's range for assistive technology", async () => {
        await mountCurtain();
        expect(control()._range.getAttribute("aria-label")).toBe(
            "Curtain position",
        );
    });

    it("changes one side without touching the other", async () => {
        const view = await mountCurtain();
        await view.setProps({ canvasB: "c2-1" });
        await flushPromises();
        expect(iiif).toHaveBeenCalledTimes(3);
        expect(iiif).toHaveBeenLastCalledWith(
            "https://iiif.example/image/2-1/info.json",
            expect.anything(),
        );
        expect(control().setRightLayers).toHaveBeenLastCalledWith(
            iiif.mock.results[2].value,
        );
        expect(sideBySide).toHaveBeenCalledTimes(1);
    });

    it("says the size each side is served at", async () => {
        iiif = stubIiifLayer({
            size: (url) => (url.includes("2-0") ? SMALL : SIZE),
        });
        const view = await mountCurtain();
        expect(view.emitted("size-read")).toEqual([
            [{ canvas: "c1-0", size: SIZE }],
            [{ canvas: "c2-0", size: SMALL }],
        ]);
    });

    it("takes the control and the map away when it goes", async () => {
        const view = await mountCurtain();
        view.unmount();
        wrapper = null;
        expect(control().remove).toHaveBeenCalled();
    });

    it("tells a side that cannot be read and tries it again on request", async () => {
        iiif = stubIiifLayer();
        const view = await mountCurtain();
        expect(view.text()).toContain("Map unavailable (image server)");
        iiif = stubIiifLayer({ size: SIZE });
        await view.find('[data-action="retry-b"]').trigger("click");
        await flushPromises();
        expect(iiif).toHaveBeenCalledTimes(1);
        expect(view.emitted("size-read")).toEqual([
            [{ canvas: "c2-0", size: SIZE }],
        ]);
    });
});

describe("the scale of the two sides", () => {
    const SMALLER = { w: 600, h: 1202 };
    const LARGER = { w: 1529, h: 2405 };

    function extentOf(side: number): { w: number; h: number } {
        return drawnExtent(iiif.mock.results[side].value as L.Layer);
    }

    it("draws sides of different power-of-two buckets in the ratio of their pixels", async () => {
        iiif = stubIiifLayer({
            size: (url) => (url.includes("2-0") ? LARGER : SMALLER),
        });
        await mountCurtain();
        expect(extentOf(1).w / extentOf(0).w).toBeCloseTo(
            LARGER.w / SMALLER.w,
            6,
        );
        expect(extentOf(1).h / extentOf(0).h).toBeCloseTo(
            LARGER.h / SMALLER.h,
            6,
        );
    });

    it("keeps the ratio whichever side is the larger", async () => {
        iiif = stubIiifLayer({
            size: (url) => (url.includes("1-0") ? LARGER : SMALLER),
        });
        await mountCurtain();
        expect(extentOf(0).w / extentOf(1).w).toBeCloseTo(
            LARGER.w / SMALLER.w,
            6,
        );
    });

    it("keeps the ratio when a side is changed for one of another bucket", async () => {
        iiif = stubIiifLayer({
            size: (url) => (url.includes("2-1") ? LARGER : SMALLER),
        });
        const view = await mountCurtain();
        await view.setProps({ canvasB: "c2-1" });
        await flushPromises();
        expect(extentOf(2).w / extentOf(0).w).toBeCloseTo(
            LARGER.w / SMALLER.w,
            6,
        );
    });
});

describe("a side without an image service", () => {
    class FakeImage {
        onload: (() => void) | null = null;
        onerror: (() => void) | null = null;
        naturalWidth = 600;
        naturalHeight = 1000;
        set src(_value: string) {
            queueMicrotask(() => this.onload?.());
        }
    }

    function bareLines(): MapLine[] {
        const bare = line(2);
        bare.file.layers[0].image = {
            service: null,
            url: "https://img.example/b.png",
            width: 0,
            height: 0,
        };
        return [line(1), bare];
    }

    beforeEach(() => {
        vi.stubGlobal("Image", FakeImage);
    });

    it("lays the image as an overlay in the side's pane, which the divider clips", async () => {
        const view = await mountCurtain({ maps: bareLines() });
        expect(iiif).toHaveBeenCalledTimes(1);
        const overlay = control().setRightLayers.mock.calls.at(-1)?.[0] as
            | (L.ImageOverlay & { getContainer: () => HTMLElement })
            | undefined;
        expect(overlay).toBeInstanceOf(L.ImageOverlay);
        const pane = leafletMap(view).getPane(
            overlay?.options.pane as string,
        ) as HTMLElement;
        expect(overlay?.getContainer()).toBe(pane);
        expect(pane).not.toBe(paneOf(view, 0));
        expect(view.emitted("size-read")).toContainEqual([
            { canvas: "c2-0", size: { w: 600, h: 1000 } },
        ]);
        expect(view.text()).not.toContain("Map unavailable");
    });

    it("draws it in the ratio of its pixels to those of the other side", async () => {
        await mountCurtain({ maps: bareLines() });
        const overlay = control().setRightLayers.mock.calls.at(-1)?.[0];
        const bare = drawnExtent(overlay as L.Layer);
        const served = drawnExtent(iiif.mock.results[0].value as L.Layer);
        expect(bare.w / served.w).toBeCloseTo(600 / SIZE.w, 6);
        expect(bare.h / served.h).toBeCloseTo(1000 / SIZE.h, 6);
    });

    it("says a side without service or URL is unavailable", async () => {
        const maps = bareLines();
        maps[1].file.layers[0].image = {
            service: null,
            url: null,
            width: 0,
            height: 0,
        };
        const view = await mountCurtain({ maps });
        expect(view.text()).toContain("Map unavailable (image server)");
    });
});

describe("the tag text of the chips", () => {
    function tagOf(overrides: Partial<FileLayer>): Promise<VueWrapper> {
        return mountCurtain({ maps: [line(1, [overrides, {}]), line(2)] });
    }

    it("writes a component with its method, else as a component, and a lone bound as a limit", async () => {
        const pca = await tagOf({
            content: valueRef("http://example.org/c", "Component"),
            processing: {
                method: layerMethod(),
                index: 3,
                inputs: null,
            },
        });
        expect(pca.find('.chip[data-pane="a"] .tag').text()).toBe("PCA 3");
        pca.unmount();
        const bare = await tagOf({
            content: valueRef("http://example.org/c", "Component"),
            processing: { method: null, index: 3, inputs: null },
        });
        expect(bare.find('.chip[data-pane="a"] .tag').text()).toBe(
            "Component 3",
        );
        bare.unmount();
        const limit = await tagOf({
            content: valueRef("http://example.org/c", "Band"),
            band: {
                value: null,
                lower: 400,
                upper: null,
                unit: layerUnit("Nanometre", "nm"),
            },
        });
        expect(limit.find('.chip[data-pane="a"] .tag').text()).toBe("≥ 400 nm");
    });
});

describe("the scale badge", () => {
    const note = {
        canvas: "c2-0",
        size: SMALL,
        against: "c1-0",
        againstSize: SIZE,
    };

    it("is on side B when the pane has a scale note", async () => {
        const view = await mountCurtain({ scaleNote: note });
        const badge = view.find(".scale-badge");
        expect(badge.exists()).toBe(true);
        expect(badge.classes()).toContain("badge-b");
        expect(view.findAll(".scale-badge")).toHaveLength(1);
    });

    it("is absent when the sizes are the same", async () => {
        const view = await mountCurtain();
        expect(view.find(".scale-badge").exists()).toBe(false);
    });

    it("announces that the sides are not at the same scale, once the note appears", async () => {
        const announce = vi.fn();
        const view = await mountCurtain({
            provide: { [ANNOUNCE_KEY as symbol]: announce },
        });
        await view.setProps({ scaleNote: note });
        expect(announce).toHaveBeenCalledWith(
            "Curtain: side B is not at the same scale as side A (600 × 1000 px against 2000 × 3000 px)",
        );
    });

    const SAID = "Curtain: side B is not at the same scale";

    function said(announce: ReturnType<typeof vi.fn>): number {
        return announce.mock.calls.filter(([text]) =>
            String(text).startsWith(SAID),
        ).length;
    }

    it("says it once while the sizes are the same, whatever else changes", async () => {
        const announce = vi.fn();
        const view = await mountCurtain({
            scaleNote: note,
            provide: { [ANNOUNCE_KEY as symbol]: announce },
        });
        expect(said(announce)).toBe(1);
        await view.setProps({ scaleNote: note });
        await view.setProps({ scaleNote: { ...note } });
        await view.setProps({
            filtersB: { ...NEUTRAL_FILTERS, brightness: 150 },
            scaleNote: { ...note, size: { ...note.size } },
        });
        expect(said(announce)).toBe(1);
        await view.setProps({ scaleNote: null });
        await view.setProps({ scaleNote: { ...note } });
        expect(said(announce)).toBe(2);
    });

    it("says it again when a size of the note changes", async () => {
        const announce = vi.fn();
        const view = await mountCurtain({
            provide: { [ANNOUNCE_KEY as symbol]: announce },
        });
        await view.setProps({ scaleNote: note });
        await view.setProps({
            scaleNote: { ...note, size: { w: 500, h: 900 } },
        });
        expect(said(announce)).toBe(2);
    });
});

describe("the filters of each side", () => {
    it("sets the CSS filter of each side's pane apart", async () => {
        const view = await mountCurtain();
        expect(paneOf(view, 0).style.filter).toBe("");
        await view.setProps({
            filtersB: { ...NEUTRAL_FILTERS, brightness: 150 },
        });
        expect(paneOf(view, 0).style.filter).toBe("");
        expect(paneOf(view, 1).style.filter).toBe(
            "brightness(1.5) contrast(1) saturate(1) grayscale(0)",
        );
    });

    it("opens the filters of a side and tells which side its events come from", async () => {
        const view = await mountCurtain({
            filtersB: { ...NEUTRAL_FILTERS, greyscale: true },
        });
        const buttons = view.findAll('[data-action="filters"]');
        expect(buttons).toHaveLength(2);
        await buttons[1].trigger("click");
        expect(buttons[1].attributes("aria-expanded")).toBe("true");
        expect(buttons[0].attributes("aria-expanded")).toBe("false");
        await view.findAll('input[type="range"]')[0].setValue("130");
        await view.find('[data-action="reset"]').trigger("click");
        await view.find('[data-action="apply-all"]').trigger("click");
        expect(view.emitted("filters-change")).toEqual([
            [{ pane: 1, filters: { brightness: 130 } }],
        ]);
        expect(view.emitted("filters-reset")).toEqual([[1]]);
        expect(view.emitted("filters-apply-all")).toEqual([[1]]);
    });
});

describe("dropping a canvas", () => {
    function drop(
        view: VueWrapper,
        id: string,
        clientX: number,
    ): Promise<void> {
        return view.find(".curtain-pane").trigger("drop", {
            clientX,
            dataTransfer: {
                getData: (type: string) => (type === LAYER_DRAG_TYPE ? id : ""),
            },
        });
    }

    it("lays it on the side of the divider it was dropped on", async () => {
        const view = await mountCurtain({ maps: [line(1), line(2)] });
        await drop(view, "c2-1", DIVIDER - 50);
        await drop(view, "c1-1", DIVIDER + 50);
        expect(view.emitted("place")).toEqual([
            [{ pane: 0, canvas: "c2-1" }],
            [{ pane: 1, canvas: "c1-1" }],
        ]);
    });

    it("ignores what is not a canvas of the Selection", async () => {
        const view = await mountCurtain();
        await drop(view, "https://evil.example/x", 10);
        expect(view.emitted("place")).toBeUndefined();
    });
});

describe("the chips", () => {
    it("names each side by its letter, its stored label and its analysis, with no tag without a mapping", async () => {
        const view = await mountCurtain();
        const chips = view.findAll(".chip");
        expect(chips).toHaveLength(2);
        expect(chips[0].text()).toContain("L1.0");
        expect(chips[1].text()).toContain("L2.0");
        expect(view.find(".tag").exists()).toBe(false);
        expect(view.find(".map").attributes("aria-label")).toBe(
            "Curtain: A L1.0 | B L2.0",
        );
    });

    it("shows the tag of a mapped layer", async () => {
        const view = await mountCurtain({
            maps: [line(1, [cu("Cu Lα")]), line(2)],
            canvasB: "c2-1",
        });
        expect(view.findAll(".tag").map((tag) => tag.text())).toEqual(["Cu"]);
    });
});

describe("without layer tiles", () => {
    it("works the same on bare labels: laid, clipped, filtered, announced", async () => {
        const announce = vi.fn();
        const view = await mountCurtain({
            maps: [line(1), line(2)],
            provide: { [ANNOUNCE_KEY as symbol]: announce },
        });
        expect(sideBySide).toHaveBeenCalledTimes(1);
        expect(view.find(".tag").exists()).toBe(false);
        expect(view.find('[data-action="pair"]').exists()).toBe(false);
        expect(announce).toHaveBeenCalledWith("Curtain, side A: L1.0");
        expect(announce).toHaveBeenCalledWith("Curtain, side B: L2.0");
    });

    it("curtains two canvases of one analysis as well", async () => {
        const view = await mountCurtain({
            maps: [line(1)],
            canvasA: "c1-0",
            canvasB: "c1-1",
        });
        expect(iiif).toHaveBeenCalledTimes(2);
        expect(view.find(".scale-badge").exists()).toBe(false);
    });
});

describe("an empty side", () => {
    it("says so and lays nothing for it", async () => {
        const view = await mountCurtain({ canvasB: null });
        expect(iiif).toHaveBeenCalledTimes(1);
        expect(view.text()).toContain("Side B is empty");
    });
});

describe("the focus", () => {
    it("never lays a page or touches a layer when the focus changes", async () => {
        const { linked, stop } = startLinkedSelection();
        const view = await mountCurtain({
            maps: [
                { ...line(1), analysis: analysisHit(1, { id: AN1 }) },
                line(2),
            ],
            provide: { [LINKED_SELECTION_KEY as symbol]: linked },
        });
        const add = vi.spyOn(L.Map.prototype, "addLayer");
        const remove = vi.spyOn(L.Map.prototype, "removeLayer");
        const setView = vi.spyOn(L.Map.prototype, "setView");
        const before = iiif.mock.calls.length;
        const setLeft = control().setLeftLayers.mock.calls.length;
        linked.toggle(analysisNode(AN1));
        await flushPromises();
        expect(
            view.findAll(".chip")[0].find(".analysis").attributes("data-rel"),
        ).toBe("self");
        linked.toggle(analysisNode(AN1));
        await flushPromises();
        expect(iiif.mock.calls.length).toBe(before);
        expect(control().setLeftLayers.mock.calls.length).toBe(setLeft);
        expect(add).not.toHaveBeenCalled();
        expect(remove).not.toHaveBeenCalled();
        expect(setView).not.toHaveBeenCalled();
        add.mockRestore();
        remove.mockRestore();
        setView.mockRestore();
        stop();
    });
});
