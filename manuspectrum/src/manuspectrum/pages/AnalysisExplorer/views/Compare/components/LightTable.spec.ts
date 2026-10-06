import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { flushPromises, mount } from "@vue/test-utils";
import L from "leaflet";
import { nextTick, ref } from "vue";
import { createPinia, setActivePinia } from "pinia";

import ImagingPane from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/components/ImagingPane.vue";
import LightTable from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/components/LightTable.vue";

import {
    ANNOUNCE_KEY,
    LIGHT_TABLE_KEY,
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
import type { LightTableContext } from "@/manuspectrum/pages/AnalysisExplorer/injection-keys.ts";
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

function storedLayout(view: VueWrapper): string {
    const provided = (
        view.vm.$ as unknown as {
            provides: Record<symbol, LightTableContext>;
        }
    ).provides[LIGHT_TABLE_KEY as symbol];
    return provided.state.value.layout;
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
        linkAll: false,
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

        it("disables « link across analyses » with one analysis and says why", async () => {
            const view = await mountTable(PLAIN_ONE);
            const toggle = view.find('[data-action="link-all"]');
            expect(toggle.attributes("aria-disabled")).toBe("true");
            expect(toggle.attributes("title")).toContain("linked");
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

        it("relays a move to the other panes of the same analysis", async () => {
            const view = await mountTable(PLAIN_ONE);
            await click(view, '[data-layout="grid2"]');
            panes(view)[0].vm.$emit("view-changed", VIEW);
            await flushPromises();
            expect(viewOf(panes(view)[1])).toEqual(VIEW);
        });

        it("does not relay a move between analyses until asked", async () => {
            const view = await mountTable(PLAIN_TWO);
            panes(view)[0].vm.$emit("view-changed", VIEW);
            await flushPromises();
            expect(viewOf(panes(view)[1])).toBeNull();
            await click(view, '[data-action="link-all"]');
            panes(view)[0].vm.$emit("view-changed", VIEW);
            await flushPromises();
            expect(viewOf(panes(view)[1])).toEqual(VIEW);
        });
    });

    describe("what it says about scales", () => {
        it("notes the pane served at another size than the one it is linked to", async () => {
            iiif = stubIiifLayer({
                size: (url) => (url.includes("/1-1/") ? SMALL : SIZE),
            });
            const view = await mountTable(PLAIN_ONE);
            await click(view, '[data-layout="grid2"]');
            const badged = view
                .findAll(".imaging-pane")
                .map((pane) => pane.find(".scale-badge").exists());
            expect(badged).toEqual([false, true]);
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
            await wrapper!.find('[data-action="link-all"]').trigger("click");
            wrapper!.unmount();
            wrapper = null;
            expect(readImaging()?.linkAll).toBe(true);
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
                    "linkAll",
                    "panes",
                    "stack",
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
    it("hides the gallery in M and shows it to the right in L", async () => {
        const medium = await mountTable(PLAIN_TWO, { frame: M_FRAME });
        expect(medium.find(".layer-gallery").exists()).toBe(false);
        medium.unmount();
        wrapper = null;
        const large = await mountTable(PLAIN_TWO, { frame: L_FRAME });
        expect(large.find(".layer-gallery").exists()).toBe(true);
        expect(large.find(".light-table").attributes("data-gallery")).toBe(
            "right",
        );
    });

    it("shows the gallery below the table in M when the header action asks", async () => {
        const view = await mountTable(PLAIN_TWO, { frame: M_FRAME });
        await runAction("gallery");
        expect(view.find(".layer-gallery").exists()).toBe(true);
        expect(view.find(".light-table").attributes("data-gallery")).toBe(
            "below",
        );
    });

    it("draws two panes instead of four in M and keeps the four in the state", async () => {
        const view = await mountTable(PLAIN_FIVE, { frame: M_FRAME });
        expect(panes(view)).toHaveLength(2);
        const provided = (
            view.vm.$ as unknown as {
                provides: Record<symbol, LightTableContext>;
            }
        ).provides[LIGHT_TABLE_KEY as symbol];
        expect(provided.state.value.layout).toBe("grid4");
        expect(provided.state.value.panes).toEqual([
            "c1-0",
            "c2-0",
            "c3-0",
            "c4-0",
        ]);
    });

    it("forces one pane in S and shows no gallery", async () => {
        const view = await mountTable(PLAIN_TWO, { frame: S_FRAME });
        expect(panes(view)).toHaveLength(1);
        expect(view.find(".layer-gallery").exists()).toBe(false);
        expect(
            actions().find((action) => action.id === "gallery")?.disabled,
        ).toBe(true);
    });

    it("lays the table out again from the Selection on « Rearrange »", async () => {
        const view = await mountTable(PLAIN_TWO);
        await click(view, '[data-layout="single"]');
        await runAction("rearrange");
        expect(paneLabels(view)).toEqual(["L1.0", "L2.0"]);
    });
});

describe("a phone", () => {
    const PHONE_FRAME: TableFrame = { size: "M", enlarged: false, phone: true };

    it("offers one pane, the curtain and the stack only", async () => {
        const view = await mountTable(PLAIN_TWO, { frame: PHONE_FRAME });
        const layouts = view
            .findAll(".segment button")
            .map((button) => button.attributes("data-layout"));
        expect(layouts).toEqual(["single", "curtain", "stack"]);
    });

    it("draws one pane for a stored grid and keeps the grid in the state", async () => {
        const view = await mountTable(PLAIN_FIVE, { frame: PHONE_FRAME });
        expect(panes(view)).toHaveLength(1);
        expect(view.find(".light-table").attributes("data-shown")).toBe(
            "single",
        );
        expect(storedLayout(view)).toBe("grid4");
    });

    it("puts the gallery in a strip below the table", async () => {
        const view = await mountTable(PLAIN_FIVE, { frame: PHONE_FRAME });
        expect(view.find(".light-table").attributes("data-gallery")).toBe(
            "strip",
        );
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
        await click(view, '[data-action="link-all"]');
        await flushPromises();
        const said = announced.filter((message) => message.includes("scale"));
        expect(said).toHaveLength(1);
        expect(said[0]).toContain("L2.0");
    });

    it("does not say it again while the pair stays the same", async () => {
        iiif = MIXED();
        const view = await mountTable(PLAIN_TWO);
        await click(view, '[data-action="link-all"]');
        await click(view, '[data-action="follow-focus"]');
        await flushPromises();
        expect(
            announced.filter((message) => message.includes("scale")),
        ).toHaveLength(1);
    });

    it("leaves the curtain to its own pane, which already says it", async () => {
        iiif = MIXED();
        const view = await mountTable(PLAIN_TWO);
        await click(view, '[data-action="link-all"]');
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

    it("keeps « Follow the focus » off by default", async () => {
        const { view } = await mountLinked(TILED);
        expect(
            view
                .find('[data-action="follow-focus"]')
                .attributes("aria-pressed"),
        ).toBe("false");
    });

    it("moves each pane to the layer of a pinned element once « Follow the focus » is on", async () => {
        const { view, linked } = await mountLinked(TILED);
        expect(paneLabels(view)).toEqual(["Pb map", "Fe map"]);
        await click(view, '[data-action="follow-focus"]');
        linked.toggle(elementNode("Cu"));
        await flushPromises();
        expect(paneLabels(view)).toEqual(["Cu map 1", "Cu map 2"]);
        expect(announced.some((text) => text.includes("Cu"))).toBe(true);
    });

    it("does not persist the toggle", async () => {
        const { view } = await mountLinked(TILED);
        await click(view, '[data-action="follow-focus"]');
        await click(view, '[data-layout="single"]');
        view.unmount();
        wrapper = null;
        const raw = window.localStorage.getItem(LAYOUT_STORAGE_KEY) ?? "";
        expect(raw).toContain("single");
        expect(raw).not.toContain("follow");
    });
});

describe("what it provides", () => {
    it("gives its parts the state, the canvases and the sizes read", async () => {
        const view = await mountTable(PLAIN_TWO);
        const provided = (
            view.vm.$ as unknown as {
                provides: Record<symbol, LightTableContext>;
            }
        ).provides[LIGHT_TABLE_KEY as symbol];
        expect(provided.state.value.layout).toBe("grid2");
        expect(provided.byCanvas.value.get("c2-1")?.layer.label).toBe("L2.1");
        expect(provided.sizes.value.get("c1-0")).toEqual(SIZE);
        provided.place("c1-2", 1);
        await flushPromises();
        expect(paneLabels(view)[1]).toBe("L1.2");
    });
});
