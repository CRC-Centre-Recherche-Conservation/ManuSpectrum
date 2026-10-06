import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { flushPromises, mount } from "@vue/test-utils";
import L from "leaflet";
import { nextTick, ref } from "vue";
import { createPinia, setActivePinia } from "pinia";

import CurtainPane from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/components/CurtainPane.vue";
import ImagingPane from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/components/ImagingPane.vue";
import LightTable from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/components/LightTable.vue";

import {
    ANNOUNCE_KEY,
    LINKED_SELECTION_KEY,
    WINDOW_ACTIONS_KEY,
    WINDOW_FRAME_KEY,
    WINDOW_RESIZE_KEY,
} from "@/manuspectrum/pages/AnalysisExplorer/injection-keys.ts";
import {
    analysisHit,
    imagingEntry,
    layerOf,
    valueRef,
} from "@/manuspectrum/pages/AnalysisExplorer/testing/fixtures.ts";
import { stubIiifLayer } from "@/manuspectrum/pages/AnalysisExplorer/testing/leaflet.ts";
import { startLinkedSelection } from "@/manuspectrum/pages/AnalysisExplorer/testing/linked.ts";
import {
    LAYOUT_STORAGE_KEY,
    readImaging,
    writeImaging,
} from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/layout.ts";
import { elementNode } from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/linked/node-id.ts";
import { filterCss } from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/pane-filters.ts";

import type { VueWrapper } from "@vue/test-utils";
import type { FileLayer } from "@/manuspectrum/pages/AnalysisExplorer/api/types.ts";
import type { WindowAction } from "@/manuspectrum/pages/AnalysisExplorer/composables/useWindowActions.ts";
import type { StoredImaging } from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/light-table.ts";
import type { TableFrame } from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/table-frame.ts";
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
const ELEMENT_MAP = valueRef("http://example.org/element-map", "Element map");
const L_FRAME: TableFrame = { size: "L", enlarged: false, phone: false };
const M_FRAME: TableFrame = { size: "M", enlarged: false, phone: false };
const S_FRAME: TableFrame = { size: "S", enlarged: false, phone: false };
const BY_HAND_FRAME: TableFrame = {
    size: null,
    enlarged: false,
    phone: false,
};

function element(symbol: string, label: string): Partial<FileLayer> {
    return {
        label,
        content: ELEMENT_MAP,
        elements: [
            {
                value: valueRef(`http://example.org/el-${symbol}`, symbol),
                symbol,
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

const PLAIN_ONE = [line(1, [{}, {}, {}])];
const PLAIN_TWO = [line(1, [{}, {}, {}]), line(2, [{}, {}])];
const PLAIN_FIVE = [1, 2, 3, 4, 5].map((n) => line(n));
const TILED = [
    line(1, [element("Pb", "Pb map"), element("Cu", "Cu map 1"), {}]),
    line(2, [element("Fe", "Fe map"), element("Cu", "Cu map 2")]),
];

let iiif: ReturnType<typeof stubIiifLayer>;
let wrapper: VueWrapper | null = null;
let stopLinked: (() => void) | null = null;
let announced: string[] = [];
let actionSources: (() => readonly WindowAction[])[] = [];

beforeEach(() => {
    setActivePinia(createPinia());
    window.localStorage.clear();
    iiif = stubIiifLayer({ size: SIZE });
    L.control.sideBySide = vi.fn(() => {
        const control = {
            addTo: vi.fn(() => control),
            remove: vi.fn(),
            setLeftLayers: vi.fn(() => control),
            setRightLayers: vi.fn(() => control),
            getPosition: () => 400,
            _range: document.createElement("input"),
        };
        return control;
    }) as unknown as typeof L.control.sideBySide;
    announced = [];
    actionSources = [];
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
    stopLinked?.();
    stopLinked = null;
    vi.useRealTimers();
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
    delete (HTMLElement.prototype as unknown as Record<string, unknown>)
        .clientWidth;
    delete (HTMLElement.prototype as unknown as Record<string, unknown>)
        .clientHeight;
});

interface Options {
    frame?: TableFrame;
    linked?: ReturnType<typeof startLinkedSelection>["linked"];
}

async function mountTable(
    maps: MapLine[],
    options: Options = {},
): Promise<VueWrapper> {
    wrapper = mount(LightTable, {
        attachTo: document.body,
        props: { maps, windowId: "auto:chemical-imaging" },
        global: {
            provide: {
                [WINDOW_RESIZE_KEY as symbol]: ref(0),
                [WINDOW_FRAME_KEY as symbol]: ref(options.frame ?? L_FRAME),
                [ANNOUNCE_KEY as symbol]: (message: string) =>
                    announced.push(message),
                [WINDOW_ACTIONS_KEY as symbol]: {
                    register: (source: () => readonly WindowAction[]) => {
                        actionSources.push(source);
                        return () => undefined;
                    },
                },
                ...(options.linked
                    ? { [LINKED_SELECTION_KEY as symbol]: options.linked }
                    : {}),
            },
        },
    });
    await flushPromises();
    return wrapper;
}

/** The table's state, read off its setup state. */
function tableState(view: VueWrapper): {
    layout: string;
    panes: (string | null)[];
} {
    return (
        view.vm as unknown as {
            state: { layout: string; panes: (string | null)[] };
        }
    ).state;
}

function storedLayout(view: VueWrapper): string {
    return tableState(view).layout;
}

function panes(view: VueWrapper): VueWrapper[] {
    return view.findAllComponents(ImagingPane);
}

function viewOf(pane: VueWrapper): unknown {
    return (pane.props() as { view: unknown }).view;
}

function paneLabels(view: VueWrapper): string[] {
    return view
        .findAll(".imaging-pane .chip .label")
        .map((node) => node.text());
}

async function click(view: VueWrapper, selector: string): Promise<void> {
    await view.find(selector).trigger("click");
    await flushPromises();
}

function actions(): WindowAction[] {
    return actionSources.flatMap((source) => [...source()]);
}

async function runAction(id: string): Promise<void> {
    actions()
        .find((action) => action.id === id)
        ?.run();
    await flushPromises();
}

function stored(partial: Partial<StoredImaging>): StoredImaging {
    return {
        layout: "grid2",
        panes: ["c1-2", "c2-1", null, null],
        syncViews: false,
        filters: Array.from({ length: 5 }, () => ({
            brightness: 100,
            contrast: 100,
            saturation: 100,
            greyscale: false,
        })),
        stack: { analysis: null, layers: [] },
        grouping: "analysis",
        ...partial,
    };
}

describe("without layer tiles", () => {
    describe("the layout it opens on", () => {
        it("opens one analysis on a curtain between its first two maps", async () => {
            const view = await mountTable(PLAIN_ONE);
            expect(view.find(".curtain-pane").exists()).toBe(true);
            expect(
                view
                    .findAll(".curtain-pane .chip .label")
                    .map((node) => node.text()),
            ).toEqual(["L1.0", "L1.1"]);
        });

        it("opens two analyses side by side, each on its first map", async () => {
            const view = await mountTable(PLAIN_TWO);
            expect(paneLabels(view)).toEqual(["L1.0", "L2.0"]);
        });

        it("opens five analyses on a grid of four with the gallery open", async () => {
            const view = await mountTable(PLAIN_FIVE);
            expect(paneLabels(view)).toEqual(["L1.0", "L2.0", "L3.0", "L4.0"]);
            expect(view.find(".layer-gallery").exists()).toBe(true);
        });
    });

    describe("every layout", () => {
        it.each([
            ["single", ".imaging-pane", 1],
            ["grid2", ".imaging-pane", 2],
            ["grid4", ".imaging-pane", 4],
            ["curtain", ".curtain-pane", 1],
            ["stack", ".layer-stack", 1],
        ])("draws %s", async (layout, selector, count) => {
            const view = await mountTable(PLAIN_TWO);
            await click(view, `[data-layout="${layout}"]`);
            expect(view.findAll(selector)).toHaveLength(count);
            expect(
                view
                    .find(`[data-layout="${layout}"]`)
                    .attributes("aria-pressed"),
            ).toBe("true");
        });

        it("fills the panes a new layout shows", async () => {
            const view = await mountTable(PLAIN_TWO);
            await click(view, '[data-layout="grid4"]');
            expect(paneLabels(view)).toEqual(["L1.0", "L2.0", "L1.1", "L1.2"]);
        });

        it("says the layout chosen", async () => {
            const view = await mountTable(PLAIN_TWO);
            await click(view, '[data-layout="grid4"]');
            expect(announced.some((text) => text.includes("Four panes"))).toBe(
                true,
            );
        });
    });

    describe("the toolbar", () => {
        it("swaps A and B, the panes' canvases only", async () => {
            const view = await mountTable(PLAIN_TWO);
            await click(view, '[data-action="swap"]');
            expect(paneLabels(view)).toEqual(["L2.0", "L1.0"]);
        });

        it("offers no swap on one pane or a stack", async () => {
            const view = await mountTable(PLAIN_TWO);
            await click(view, '[data-layout="single"]');
            expect(view.find('[data-action="swap"]').exists()).toBe(false);
            await click(view, '[data-layout="stack"]');
            expect(view.find('[data-action="swap"]').exists()).toBe(false);
        });

        it("offers one sync toggle, pressed off by default, and presses it", async () => {
            const view = await mountTable(PLAIN_TWO);
            const toggle = () => view.find('[data-action="sync-views"]');
            expect(toggle().exists()).toBe(true);
            expect(toggle().element.tagName).toBe("BUTTON");
            expect(toggle().attributes("aria-pressed")).toBe("false");
            expect(view.find('[data-action="link-all"]').exists()).toBe(false);
            await click(view, '[data-action="sync-views"]');
            expect(toggle().attributes("aria-pressed")).toBe("true");
            await click(view, '[data-action="sync-views"]');
            expect(toggle().attributes("aria-pressed")).toBe("false");
        });

        it("names the toggle by its sync tip", async () => {
            const view = await mountTable(PLAIN_ONE);
            expect(view.find('[data-action="sync-views"]').text()).toBe("");
            expect(view.text()).toContain("Sync zoom and pan across panes");
            expect(view.find('[data-action="follow-focus"]').exists()).toBe(
                false,
            );
        });

        it("sets the filters of one pane on its map", async () => {
            const view = await mountTable(PLAIN_TWO);
            panes(view)[0].vm.$emit("filters-change", { brightness: 150 });
            await flushPromises();
            const expected = filterCss({
                brightness: 150,
                contrast: 100,
                saturation: 100,
                greyscale: false,
            });
            const tiles = view.findAll(".leaflet-tile-pane");
            expect((tiles[0].element as HTMLElement).style.filter).toBe(
                expected,
            );
            expect((tiles[1].element as HTMLElement).style.filter).toBe("");
        });

        it("applies the filters of a pane to every pane", async () => {
            const view = await mountTable(PLAIN_TWO);
            panes(view)[0].vm.$emit("filters-change", { contrast: 130 });
            await flushPromises();
            panes(view)[0].vm.$emit("filters-apply-all");
            await flushPromises();
            const tiles = view.findAll(".leaflet-tile-pane");
            expect((tiles[1].element as HTMLElement).style.filter).not.toBe("");
        });

        it("resets the filters of a pane", async () => {
            const view = await mountTable(PLAIN_TWO);
            panes(view)[0].vm.$emit("filters-change", { contrast: 130 });
            await flushPromises();
            panes(view)[0].vm.$emit("filters-reset");
            await flushPromises();
            const tiles = view.findAll(".leaflet-tile-pane");
            expect((tiles[0].element as HTMLElement).style.filter).toBe("");
        });
    });

    describe("the link between panes", () => {
        const VIEW = {
            cx: 0.4,
            cy: 0.5,
            dz: 1,
            size: SIZE,
            origin: "c1-0",
        };

        it("relays nothing by default, even within one analysis", async () => {
            const view = await mountTable(PLAIN_ONE);
            await click(view, '[data-layout="grid2"]');
            panes(view)[0].vm.$emit("view-changed", VIEW);
            await flushPromises();
            expect(viewOf(panes(view)[1])).toBeNull();
        });

        it("relays a move to the other panes of the same analysis once synced", async () => {
            const view = await mountTable(PLAIN_ONE);
            await click(view, '[data-layout="grid2"]');
            await click(view, '[data-action="sync-views"]');
            panes(view)[0].vm.$emit("view-changed", VIEW);
            await flushPromises();
            expect(viewOf(panes(view)[1])).toEqual(VIEW);
        });

        it("relays a move between analyses once synced, and not before", async () => {
            const view = await mountTable(PLAIN_TWO);
            panes(view)[0].vm.$emit("view-changed", VIEW);
            await flushPromises();
            expect(viewOf(panes(view)[1])).toBeNull();
            await click(view, '[data-action="sync-views"]');
            panes(view)[0].vm.$emit("view-changed", VIEW);
            await flushPromises();
            expect(viewOf(panes(view)[1])).toEqual(VIEW);
        });

        it("drops the view relayed to a pane when its canvas changes, so a stale view of another pane is not applied", async () => {
            const view = await mountTable(PLAIN_ONE);
            await click(view, '[data-layout="grid2"]');
            await click(view, '[data-action="sync-views"]');
            const other = { ...VIEW, cx: 0.8, origin: "c1-1" };
            panes(view)[0].vm.$emit("view-changed", VIEW);
            panes(view)[1].vm.$emit("view-changed", other);
            await flushPromises();
            expect(viewOf(panes(view)[0])).toEqual(other);
            expect(viewOf(panes(view)[1])).toEqual(VIEW);
            panes(view)[1].vm.$emit("step", 1);
            await flushPromises();
            expect(paneLabels(view)[1]).toBe("L1.2");
            expect(viewOf(panes(view)[1])).toBeNull();
            expect(viewOf(panes(view)[0])).toEqual(other);
        });

        it("steps the pane of the curtain a side asks for, and leaves the other side", async () => {
            const view = await mountTable(PLAIN_ONE);
            const curtain = view.findComponent(CurtainPane);
            curtain.vm.$emit("step", { pane: 1, delta: 1 });
            await flushPromises();
            expect(
                view
                    .findAll(".curtain-pane .chip .label")
                    .map((node) => node.text()),
            ).toEqual(["L1.0", "L1.2"]);
            curtain.vm.$emit("step", { pane: 0, delta: 1 });
            await flushPromises();
            expect(
                view
                    .findAll(".curtain-pane .chip .label")
                    .map((node) => node.text()),
            ).toEqual(["L1.1", "L1.2"]);
        });

        it("drops the view of a pane that is given a canvas of another analysis", async () => {
            const view = await mountTable(PLAIN_TWO);
            await click(view, '[data-action="sync-views"]');
            panes(view)[0].vm.$emit("view-changed", VIEW);
            await flushPromises();
            expect(viewOf(panes(view)[1])).toEqual(VIEW);
            panes(view)[1].vm.$emit("place", "c1-2");
            await flushPromises();
            expect(paneLabels(view)[1]).toBe("L1.2");
            expect(viewOf(panes(view)[1])).toBeNull();
        });
    });

    describe("what it says about scales", () => {
        it("does not say again that the curtain sides differ when only the filters change", async () => {
            iiif = stubIiifLayer({
                size: (url) => (url.includes("/2-0") ? SMALL : SIZE),
            });
            const view = await mountTable(PLAIN_TWO);
            await click(view, '[data-layout="curtain"]');
            const said = (): number =>
                announced.filter((text) =>
                    text.startsWith("Curtain: side B is not at the same scale"),
                ).length;
            expect(said()).toBe(1);
            await click(view, '[data-action="filters"]');
            await view.find('input[type="range"]').setValue(150);
            await flushPromises();
            expect(said()).toBe(1);
        });

        it("notes the pane served at another size than the one it is synced with, and none while unsynced", async () => {
            iiif = stubIiifLayer({
                size: (url) => (url.includes("/1-1/") ? SMALL : SIZE),
            });
            const view = await mountTable(PLAIN_ONE);
            await click(view, '[data-layout="grid2"]');
            const badges = () =>
                view
                    .findAll(".imaging-pane")
                    .map((pane) => pane.find(".scale-badge").exists());
            expect(badges()).toEqual([false, false]);
            await click(view, '[data-action="sync-views"]');
            expect(badges()).toEqual([false, true]);
        });

        it("notes nothing when every size is the same", async () => {
            const view = await mountTable(PLAIN_ONE);
            await click(view, '[data-layout="grid2"]');
            expect(view.find(".scale-badge").exists()).toBe(false);
        });
    });

    describe("what tags would add", () => {
        it("shows no pair chip, no tag badge, and a grouping segment off", async () => {
            const view = await mountTable(PLAIN_TWO);
            expect(view.find('[data-action="pair"]').exists()).toBe(false);
            expect(view.find(".tag-badge").exists()).toBe(false);
            expect(
                view.find('[data-grouping="tag"]').attributes("disabled"),
            ).toBeDefined();
            expect(view.findAll(".layer-gallery .group")).toHaveLength(2);
        });

        it("tints the stack by rank", async () => {
            const view = await mountTable(PLAIN_ONE);
            await click(view, '[data-layout="stack"]');
            await click(view, '.layer-thumb[data-canvas="c1-0"]');
            await click(view, '.layer-thumb[data-canvas="c1-1"]');
            const swatches = view.findAll(".layer-stack .layers .swatch");
            expect(swatches).toHaveLength(2);
            for (const swatch of swatches) {
                expect(swatch.attributes("style")).toContain("var(--");
                expect(swatch.attributes("style")).not.toContain("--map-cu");
            }
        });
    });

    describe("the gallery and the stack", () => {
        it("lays a thumbnail in the target pane", async () => {
            const view = await mountTable(PLAIN_TWO);
            await click(view, '.target-pane[aria-pressed="false"]');
            await click(view, '.layer-thumb[data-canvas="c1-2"]');
            expect(paneLabels(view)).toEqual(["L1.0", "L1.2"]);
        });

        it("lays every canvas of a group in the panes, two on a grid of two", async () => {
            const view = await mountTable(PLAIN_TWO);
            await click(
                view,
                ".layer-gallery .group:nth-of-type(2) .place-all",
            );
            expect(paneLabels(view)).toEqual(["L2.0", "L2.1"]);
        });

        it("refuses a layer of another analysis in a stack, and says so", async () => {
            const view = await mountTable(PLAIN_TWO);
            await click(view, '[data-layout="stack"]');
            await click(view, '.layer-thumb[data-canvas="c1-0"]');
            await click(view, '.layer-thumb[data-canvas="c2-0"]');
            expect(view.findAll(".layer-stack .layers li")).toHaveLength(1);
            expect(view.find(".notice").text()).toContain("one analysis");
            expect(announced.at(-1)).toContain("one analysis");
        });
    });

    describe("what it remembers", () => {
        it("reads the stored layout on opening", async () => {
            writeImaging(
                stored({
                    layout: "grid2",
                    panes: ["c1-2", "c2-1", null, null],
                }),
            );
            const view = await mountTable(PLAIN_TWO);
            expect(paneLabels(view)).toEqual(["L1.2", "L2.1"]);
        });

        it("starts again from the default when nothing stored is in the Selection", async () => {
            writeImaging(stored({ panes: ["x-1", "x-2", null, null] }));
            const view = await mountTable(PLAIN_TWO);
            expect(paneLabels(view)).toEqual(["L1.0", "L2.0"]);
        });

        it("writes every change after a pause, and on closing", async () => {
            vi.useFakeTimers({ toFake: ["setTimeout", "clearTimeout"] });
            await mountTable(PLAIN_TWO);
            await wrapper!.find('[data-layout="grid4"]').trigger("click");
            await nextTick();
            expect(readImaging()).toBeUndefined();
            vi.advanceTimersByTime(1000);
            expect(readImaging()?.layout).toBe("grid4");
            await wrapper!.find('[data-action="sync-views"]').trigger("click");
            wrapper!.unmount();
            wrapper = null;
            expect(readImaging()?.syncViews).toBe(true);
        });

        it("opens unsynced on a record that holds the old linkAll", async () => {
            window.localStorage.setItem(
                LAYOUT_STORAGE_KEY,
                JSON.stringify({
                    version: 3,
                    boxes: {},
                    imaging: {
                        ...stored({}),
                        syncViews: undefined,
                        linkAll: true,
                    },
                }),
            );
            const view = await mountTable(PLAIN_TWO);
            expect(
                view
                    .find('[data-action="sync-views"]')
                    .attributes("aria-pressed"),
            ).toBe("false");
        });

        it("reads a stored syncViews on opening", async () => {
            writeImaging(stored({ syncViews: true }));
            const view = await mountTable(PLAIN_TWO);
            expect(
                view
                    .find('[data-action="sync-views"]')
                    .attributes("aria-pressed"),
            ).toBe("true");
        });

        it("keeps no zoom, pan or active pane", async () => {
            const view = await mountTable(PLAIN_TWO);
            await click(view, '[data-layout="grid4"]');
            view.unmount();
            wrapper = null;
            const raw = JSON.parse(
                window.localStorage.getItem(LAYOUT_STORAGE_KEY) ?? "{}",
            );
            expect(Object.keys(raw.imaging).sort()).toEqual(
                [
                    "filters",
                    "grouping",
                    "layout",
                    "panes",
                    "stack",
                    "syncViews",
                ].sort(),
            );
        });
    });

    describe("when the Selection changes", () => {
        it("empties the panes of an analysis it no longer holds", async () => {
            const view = await mountTable(PLAIN_TWO);
            await view.setProps({ maps: [PLAIN_TWO[0]] });
            await flushPromises();
            expect(
                paneLabels(view).some((text) => text.startsWith("L2.")),
            ).toBe(false);
            expect(paneLabels(view)).toHaveLength(2);
        });
    });
});

describe("with some tiles", () => {
    it("groups by element or band and offers « Compare » for the shared family", async () => {
        const view = await mountTable(TILED);
        expect(
            view.find('[data-grouping="tag"]').attributes("aria-pressed"),
        ).toBe("true");
        expect(view.find(".layer-gallery .compare").exists()).toBe(true);
    });

    it("badges a layer of a tag and offers the pair only where a family is shared", async () => {
        const view = await mountTable(TILED);
        await click(view, '.layer-thumb[data-canvas="c1-1"]');
        expect(view.find(".layer-gallery .tag-badge").exists()).toBe(true);
        expect(view.find('[data-action="pair"]').exists()).toBe(true);
    });

    it("turns one pane into a curtain with the pair of its map", async () => {
        const view = await mountTable(TILED);
        await click(view, '[data-layout="single"]');
        await click(view, '.layer-thumb[data-canvas="c1-1"]');
        await click(view, '[data-action="pair"]');
        expect(view.find(".curtain-pane").exists()).toBe(true);
        expect(
            view
                .findAll(".curtain-pane .chip .label")
                .map((node) => node.text()),
        ).toEqual(["Cu map 1", "Cu map 2"]);
    });

    it("lays the pair in the other pane when there are several", async () => {
        const view = await mountTable(TILED);
        await click(view, '.layer-thumb[data-canvas="c1-1"]');
        await click(view, '[data-action="pair"]');
        expect(paneLabels(view)).toEqual(["Cu map 1", "Cu map 2"]);
    });

    it("offers no pair on a single analysis", async () => {
        const view = await mountTable([TILED[0]]);
        await click(view, '[data-layout="single"]');
        await click(view, '.layer-thumb[data-canvas="c1-1"]');
        expect(view.find('[data-action="pair"]').exists()).toBe(false);
    });

    it("compares the canvases of a shared family in the panes", async () => {
        const view = await mountTable(TILED);
        await click(view, ".layer-gallery .compare");
        expect(paneLabels(view)).toEqual(["Cu map 1", "Cu map 2"]);
    });

    it("tints a stacked element layer by its element, the others by rank", async () => {
        const view = await mountTable([TILED[0]]);
        await click(view, '[data-layout="stack"]');
        await click(view, '.layer-thumb[data-canvas="c1-1"]');
        await click(view, '.layer-thumb[data-canvas="c1-2"]');
        const swatches = view.findAll(".layer-stack .layers .swatch");
        expect(swatches).toHaveLength(2);
        expect(swatches[0].attributes("style")).toContain("--map-cu");
        expect(swatches[1].attributes("style")).not.toContain("--map-cu");
        expect(swatches[1].attributes("style")).toContain("var(--");
    });
});

describe("the size of the window", () => {
    it("starts the gallery closed in M, open in L, and offers the toggle in both", async () => {
        const medium = await mountTable(PLAIN_TWO, { frame: M_FRAME });
        expect(medium.find(".layer-gallery").exists()).toBe(false);
        expect(
            medium
                .find('[data-action="gallery-toggle"]')
                .attributes("aria-expanded"),
        ).toBe("false");
        medium.unmount();
        wrapper = null;
        const large = await mountTable(PLAIN_TWO, { frame: L_FRAME });
        expect(large.find(".layer-gallery").exists()).toBe(true);
        expect(large.find(".light-table").attributes("data-gallery")).toBe(
            "right",
        );
        expect(
            large
                .find('[data-action="gallery-toggle"]')
                .attributes("aria-expanded"),
        ).toBe("true");
    });

    it("shows and hides the gallery to the right of the table with the toggle, at every size", async () => {
        for (const frame of [S_FRAME, M_FRAME, L_FRAME, BY_HAND_FRAME]) {
            const view = await mountTable(PLAIN_TWO, { frame });
            const rail = () => view.find('[data-action="gallery-toggle"]');
            const was = view.find(".layer-gallery").exists();
            await rail().trigger("click");
            expect(view.find(".layer-gallery").exists()).toBe(!was);
            expect(rail().attributes("aria-expanded")).toBe(String(!was));
            expect(rail().attributes("aria-label")).toBe(
                was ? "Show the gallery" : "Hide the gallery",
            );
            expect(rail().find(".count").exists()).toBe(was);
            if (was) {
                expect(rail().find(".count .n").text()).toBe("5");
                expect(rail().find(".count .unit").text()).toBe("images");
            }
            await rail().trigger("click");
            expect(view.find(".layer-gallery").exists()).toBe(was);
            view.unmount();
            wrapper = null;
        }
    });

    it("shows up to three preview images in the closed tab", async () => {
        const view = await mountTable(PLAIN_TWO, { frame: M_FRAME });
        const previews = view.findAll(
            '[data-action="gallery-toggle"] .previews img',
        );
        expect(previews).toHaveLength(3);
        expect(previews[0].attributes("src")).toContain("iiif.example");
        expect(
            view
                .find('[data-action="gallery-toggle"] .previews')
                .attributes("aria-hidden"),
        ).toBe("true");
        await view.find('[data-action="gallery-toggle"]').trigger("click");
        expect(
            view.find('[data-action="gallery-toggle"] .previews').exists(),
        ).toBe(false);
    });

    it("keeps the same button, focused, when the gallery is hidden and shown, and names the dock it controls", async () => {
        const view = await mountTable(PLAIN_TWO, { frame: L_FRAME });
        const button = view.find('[data-action="gallery-toggle"]')
            .element as HTMLButtonElement;
        button.focus();
        for (const open of [false, true]) {
            await view.find('[data-action="gallery-toggle"]').trigger("click");
            const again = view.find('[data-action="gallery-toggle"]')
                .element as HTMLButtonElement;
            expect(again).toBe(button);
            expect(document.activeElement).toBe(button);
            expect(button.getAttribute("aria-expanded")).toBe(String(open));
            const dock = document.getElementById(
                button.getAttribute("aria-controls") as string,
            );
            expect(dock).not.toBeNull();
            expect(dock?.contains(button)).toBe(true);
            expect(dock?.getAttribute("data-open")).toBe(String(open));
        }
    });

    it("opens the gallery by default once the window holds the table and the gallery, and closes it below", async () => {
        const observers: ((entries: unknown[]) => void)[] = [];
        vi.stubGlobal(
            "ResizeObserver",
            class {
                constructor(callback: (entries: unknown[]) => void) {
                    observers.push(callback);
                }
                observe(): void {}
                unobserve(): void {}
                disconnect(): void {}
            },
        );
        const view = await mountTable(PLAIN_TWO, { frame: M_FRAME });
        const measure = async (px: number) => {
            observers.forEach((callback) =>
                callback([{ contentRect: { width: px } }]),
            );
            await flushPromises();
        };
        await measure(1100);
        expect(view.find(".layer-gallery").exists()).toBe(true);
        await measure(700);
        expect(view.find(".layer-gallery").exists()).toBe(false);
    });

    it("keeps the reader's choice over the default, and stores it", async () => {
        vi.useFakeTimers({ toFake: ["setTimeout", "clearTimeout"] });
        await mountTable(PLAIN_TWO, { frame: L_FRAME });
        await wrapper!.find('[data-action="gallery-toggle"]').trigger("click");
        expect(wrapper!.find(".layer-gallery").exists()).toBe(false);
        vi.advanceTimersByTime(1000);
        expect(readImaging()?.gallery).toBe(false);
        wrapper!.unmount();
        wrapper = null;
        const again = await mountTable(PLAIN_TWO, { frame: L_FRAME });
        expect(again.find(".layer-gallery").exists()).toBe(false);
        await again.find('[data-action="gallery-toggle"]').trigger("click");
        again.unmount();
        wrapper = null;
        expect(readImaging()?.gallery).toBe(true);
        const third = await mountTable(PLAIN_TWO, { frame: M_FRAME });
        expect(third.find(".layer-gallery").exists()).toBe(true);
    });

    it("writes no choice about the gallery until the reader makes one", async () => {
        vi.useFakeTimers({ toFake: ["setTimeout", "clearTimeout"] });
        await mountTable(PLAIN_TWO, { frame: L_FRAME });
        await wrapper!.find('[data-layout="grid4"]').trigger("click");
        vi.advanceTimersByTime(1000);
        expect(readImaging()?.layout).toBe("grid4");
        expect(readImaging()).not.toHaveProperty("gallery");
    });

    it("reads a record stored before the gallery choice existed", async () => {
        writeImaging(stored({}));
        const view = await mountTable(PLAIN_TWO, { frame: L_FRAME });
        expect(view.find(".layer-gallery").exists()).toBe(true);
    });

    it("has no gallery action in the window header beside the table, and one on a phone", async () => {
        await mountTable(PLAIN_TWO, { frame: M_FRAME });
        expect(actions().map((action) => action.id)).toEqual(["rearrange"]);
    });

    it("draws four panes in M, S aside, and in a window resized by hand when four is chosen", async () => {
        for (const frame of [M_FRAME, L_FRAME, BY_HAND_FRAME]) {
            const view = await mountTable(PLAIN_FIVE, { frame });
            expect(panes(view)).toHaveLength(4);
            expect(tableState(view).layout).toBe("grid4");
            expect(view.find(".light-table").attributes("data-shown")).toBe(
                "grid4",
            );
            view.unmount();
            wrapper = null;
        }
    });

    it("forces one pane in S, with its layouts disabled and explained, and the gallery still reachable", async () => {
        const view = await mountTable(PLAIN_TWO, { frame: S_FRAME });
        expect(panes(view)).toHaveLength(1);
        const grid = view.find('[data-layout="grid2"]');
        expect(grid.attributes("aria-disabled")).toBe("true");
        expect(grid.attributes("title")).toBeTruthy();
        expect(view.find('[data-action="gallery-toggle"]').exists()).toBe(true);
    });

    it("lays the table out again from the Selection on « Rearrange »", async () => {
        const view = await mountTable(PLAIN_TWO);
        await click(view, '[data-layout="single"]');
        await runAction("rearrange");
        expect(paneLabels(view)).toEqual(["L1.0", "L2.0"]);
    });
});

describe("the swap", () => {
    it.each([
        ["curtain", true],
        ["grid2", true],
        ["single", false],
        ["grid4", false],
        ["stack", false],
    ])("in %s: offered %s", async (layout, offered) => {
        const view = await mountTable(PLAIN_FIVE);
        await click(view, `[data-layout="${layout}"]`);
        expect(view.find('[data-action="swap"]').exists()).toBe(offered);
    });
});

describe("a phone", () => {
    const PHONE_FRAME: TableFrame = { size: "M", enlarged: false, phone: true };

    it("disables the two grids with a reason and keeps the other layouts", async () => {
        const view = await mountTable(PLAIN_TWO, { frame: PHONE_FRAME });
        const buttons = view.findAll(".segment button");
        expect(
            buttons.map((button) => button.attributes("data-layout")),
        ).toEqual(["single", "curtain", "grid2", "grid4", "stack"]);
        const disabled = buttons
            .filter((button) => button.attributes("aria-disabled") === "true")
            .map((button) => button.attributes("data-layout"));
        expect(disabled).toEqual(["grid2", "grid4"]);
        expect(
            view.find('[data-layout="grid4"]').attributes("title"),
        ).toContain("wider screen");
        await click(view, '[data-layout="grid4"]');
        expect(storedLayout(view)).not.toBe("grid4");
    });

    it("draws one pane for a stored grid, keeps the grid in the state and presses One pane", async () => {
        const view = await mountTable(PLAIN_FIVE, { frame: PHONE_FRAME });
        expect(panes(view)).toHaveLength(1);
        expect(view.find(".light-table").attributes("data-shown")).toBe(
            "single",
        );
        expect(storedLayout(view)).toBe("grid4");
        expect(
            view.find('[data-layout="single"]').attributes("aria-pressed"),
        ).toBe("true");
    });

    it("puts the gallery in a strip below the table, with no toggle, and keeps the header action", async () => {
        const view = await mountTable(PLAIN_FIVE, { frame: PHONE_FRAME });
        expect(view.find(".light-table").attributes("data-gallery")).toBe(
            "strip",
        );
        expect(view.find('[data-action="gallery-toggle"]').exists()).toBe(
            false,
        );
        expect(actions().map((action) => action.id)).toEqual([
            "gallery",
            "rearrange",
        ]);
    });
});

describe("announcements", () => {
    const MIXED = () =>
        stubIiifLayer({
            size: (url) => (url.includes("image/2-") ? SMALL : SIZE),
        });

    it("says a layer is at a different scale once it is laid beside another", async () => {
        iiif = MIXED();
        const view = await mountTable(PLAIN_TWO);
        expect(
            announced.filter((message) => message.includes("scale")),
        ).toEqual([]);
        await click(view, '[data-action="sync-views"]');
        await flushPromises();
        const said = announced.filter((message) => message.includes("scale"));
        expect(said).toHaveLength(1);
        expect(said[0]).toContain("L2.0");
    });

    it("does not say it again while the pair stays the same", async () => {
        iiif = MIXED();
        const view = await mountTable(PLAIN_TWO);
        await click(view, '[data-action="sync-views"]');
        await flushPromises();
        await flushPromises();
        expect(
            announced.filter((message) => message.includes("scale")),
        ).toHaveLength(1);
    });

    it("leaves the curtain to its own pane, which already says it", async () => {
        iiif = MIXED();
        const view = await mountTable(PLAIN_TWO);
        await click(view, '[data-action="sync-views"]');
        announced.length = 0;
        await click(view, '[data-layout="curtain"]');
        await flushPromises();
        expect(
            announced.filter((message) => message.includes("scale")),
        ).toHaveLength(1);
    });
});

describe("the focus", () => {
    async function mountLinked(maps: MapLine[]) {
        const started = startLinkedSelection();
        stopLinked = started.stop;
        const view = await mountTable(maps, { linked: started.linked });
        return { view, linked: started.linked };
    }

    it("lays nothing and moves nothing when an element is pinned", async () => {
        const { view, linked } = await mountLinked(TILED);
        const before = iiif.mock.calls.length;
        const added = vi.spyOn(L.Map.prototype, "addLayer");
        const reset = vi.spyOn(L.TileLayer.prototype, "setUrl");
        const labels = paneLabels(view);
        linked.toggle(elementNode("Cu"));
        await flushPromises();
        expect(iiif.mock.calls.length).toBe(before);
        expect(added).not.toHaveBeenCalled();
        expect(reset).not.toHaveBeenCalled();
        expect(paneLabels(view)).toEqual(labels);
    });
});
