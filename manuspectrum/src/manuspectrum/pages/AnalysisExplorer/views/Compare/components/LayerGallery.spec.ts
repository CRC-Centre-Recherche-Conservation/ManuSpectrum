import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { mount } from "@vue/test-utils";
import { createPinia, setActivePinia } from "pinia";

import LayerGallery from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/components/LayerGallery.vue";

import { LINKED_SELECTION_KEY } from "@/manuspectrum/pages/AnalysisExplorer/injection-keys.ts";
import {
    analysisHit,
    imagingEntry,
    label,
    layerOf,
    layerUnit,
    valueRef,
} from "@/manuspectrum/pages/AnalysisExplorer/testing/fixtures.ts";
import { startLinkedSelection } from "@/manuspectrum/pages/AnalysisExplorer/testing/linked.ts";
import { LAYER_DRAG_TYPE } from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/layer-drag.ts";
import {
    defaultState,
    setGrouping,
    toggleInStack,
} from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/light-table.ts";
import {
    analysisNode,
    elementNode,
} from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/linked/node-id.ts";

import type { VueWrapper } from "@vue/test-utils";

import type { FileLayer } from "@/manuspectrum/pages/AnalysisExplorer/api/types.ts";
import type { TableState } from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/light-table.ts";
import type { MapLine } from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/windows.ts";

const ELEMENT_MAP = valueRef("http://example.org/element-map", "Element map");
const HSI = valueRef("http://example.org/hsi", "HSI band");

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

function band(value: number, label: string): Partial<FileLayer> {
    return {
        label,
        content: HSI,
        band: {
            value,
            lower: null,
            upper: null,
            unit: layerUnit("Nanometre", "nm"),
        },
    };
}

/** A map of analysis `n`; canvas ids `c<n>-<index>`, every layer unclassified unless overridden. */
function line(n: number, layers: Partial<FileLayer>[]): MapLine {
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

const PLAIN = [line(1, [{}, {}, {}]), line(2, [{}, {}])];
const TILED = [
    line(1, [
        element("Cu", "MS59-deconv_Cu"),
        element("Pb", "MS59-deconv_Pb"),
        band(650, "band_650"),
        {},
    ]),
    line(2, [element("Cu", "f57 cuivre"), { label: "Video 1" }]),
];

function gallery(
    maps: MapLine[],
    state: TableState = defaultState(maps),
): VueWrapper {
    return mount(LayerGallery, { props: { maps, state } });
}

function titles(view: VueWrapper): string[] {
    return view.findAll("section .group-title").map((node) => node.text());
}

let stop: (() => void) | null = null;

beforeEach(() => {
    setActivePinia(createPinia());
});

afterEach(() => {
    stop?.();
    stop = null;
});

describe("LayerGallery without layer tiles", () => {
    it("draws every canvas with its stored label, one group per analysis", () => {
        const view = gallery(PLAIN);
        expect(view.findAll(".group")).toHaveLength(2);
        expect(view.findAll(".layer-thumb")).toHaveLength(5);
        expect(view.findAll(".layer-thumb .label")[0].text()).toBe("L1.0");
    });

    it("disables the grouping segment and forces Analysis, even when the state says tag", () => {
        const maps = PLAIN;
        const view = gallery(maps, setGrouping(defaultState(maps), "tag"));
        const tag = view.find('[data-grouping="tag"]');
        expect(tag.attributes("disabled")).toBeDefined();
        expect(
            view.find('[data-grouping="analysis"]').attributes("aria-pressed"),
        ).toBe("true");
        expect(view.findAll(".group")).toHaveLength(2);
    });

    it("shows no tag badge, no Unclassified group and no Compare chip", () => {
        const view = gallery(PLAIN);
        expect(view.find(".tag-badge").exists()).toBe(false);
        expect(titles(view).join("|")).not.toContain("Unclassified");
        expect(view.find(".compare").exists()).toBe(false);
    });

    it("filters on the stored label, case and accents folded", async () => {
        const maps = [line(1, [{ label: "Cuivre é" }, { label: "Pb" }])];
        const view = gallery(maps);
        await view.find('input[type="search"]').setValue("CUIVRE E");
        expect(view.findAll(".layer-thumb")).toHaveLength(1);
        expect(view.find(".layer-thumb .label").text()).toBe("Cuivre é");
    });

    it("keeps the other behaviours: click places, pile click toggles", async () => {
        const view = gallery(PLAIN);
        await view.findAll(".layer-thumb")[1].trigger("click");
        expect(view.emitted("place")?.[0]).toEqual(["c1-1"]);
        const stacked = { ...defaultState(PLAIN), layout: "stack" as const };
        const pile = gallery(PLAIN, stacked);
        await pile.findAll(".layer-thumb")[1].trigger("click");
        expect(pile.emitted("toggle-stack")?.[0]).toEqual(["c1-1"]);
        expect(pile.emitted("place")).toBeUndefined();
    });
});

describe("LayerGallery with some tiles", () => {
    it("groups by element or band, shared families first, Unclassified last", () => {
        const view = gallery(TILED, setGrouping(defaultState(TILED), "tag"));
        expect(titles(view)).toEqual([
            "Cu",
            "Pb",
            "650 nm",
            "Unclassified · 2",
        ]);
    });

    it("opens on Element or band when two analyses share a family", () => {
        const view = gallery(TILED);
        expect(
            view.find('[data-grouping="tag"]').attributes("aria-pressed"),
        ).toBe("true");
        expect(view.find('[data-grouping="tag"]').attributes("disabled")).toBe(
            undefined,
        );
    });

    it("offers Compare on a shared family only and emits its canvases", async () => {
        const view = gallery(TILED);
        const compares = view.findAll(".compare");
        expect(compares).toHaveLength(1);
        await compares[0].trigger("click");
        expect(view.emitted("compare")?.[0]).toEqual([["c1-0", "c2-0"]]);
    });

    it("shows the tag as a badge where it differs from the stored label", () => {
        const view = gallery(TILED);
        const badges = view.findAll(".tag-badge").map((node) => node.text());
        expect(badges).toContain("Cu");
        expect(badges).toContain("650 nm");
    });

    it("filters on the tag text as well as on the label", async () => {
        const view = gallery(TILED);
        await view.find('input[type="search"]').setValue("pb");
        expect(view.findAll(".layer-thumb")).toHaveLength(1);
        expect(view.find(".layer-thumb .label").text()).toBe("MS59-deconv_Pb");
    });

    it("narrows to an analysis with its tab", async () => {
        const view = gallery(TILED);
        await view.findAll(".analysis-tab")[2].trigger("click");
        expect(view.findAll(".layer-thumb")).toHaveLength(2);
    });

    it("names a tab and a group by the first segment of the analysis name, the whole name in the title", async () => {
        const whole = "REC-0031 — MA-XRF — parchment — 61v";
        const maps = PLAIN.map((entry, index) =>
            index === 0
                ? {
                      ...entry,
                      analysis: { ...entry.analysis, name: label(whole) },
                  }
                : entry,
        );
        const view = gallery(maps);
        const tab = view.findAll(".analysis-tab")[1];
        expect(tab.text()).toBe("REC-0031");
        expect(tab.attributes("title")).toBe(whole);
        const title = view.find(".group-title");
        expect(title.text()).toBe("REC-0031");
        expect(title.attributes("title")).toBe(whole);
    });

    it("switches grouping through the segment", async () => {
        const view = gallery(TILED);
        await view.find('[data-grouping="analysis"]').trigger("click");
        expect(view.emitted("group-change")?.[0]).toEqual(["analysis"]);
    });

    it("marks the thumbs of a pinned element", async () => {
        const started = startLinkedSelection(() => undefined);
        stop = started.stop;
        const view = mount(LayerGallery, {
            props: { maps: TILED, state: defaultState(TILED) },
            global: {
                provide: { [LINKED_SELECTION_KEY as symbol]: started.linked },
            },
        });
        started.linked.toggle(elementNode("Cu"));
        await view.vm.$nextTick();
        function rel(text: string): string | undefined {
            return view
                .findAll(".layer-thumb")
                .find((node) => node.find(".label").text() === text)
                ?.attributes("data-rel");
        }
        expect(rel("MS59-deconv_Cu")).toBe("self");
        expect(rel("MS59-deconv_Pb")).toBe("none");
        expect(rel("band_650")).toBeUndefined();
    });

    it("shows the focus slot of a pinned analysis on the head of its group, and none on the others", async () => {
        const started = startLinkedSelection(() => undefined);
        stop = started.stop;
        const view = mount(LayerGallery, {
            props: { maps: PLAIN, state: defaultState(PLAIN) },
            global: {
                provide: { [LINKED_SELECTION_KEY as symbol]: started.linked },
            },
        });
        expect(view.findAll(".group .pins")).toHaveLength(0);
        started.linked.toggle(analysisNode(PLAIN[0].analysis.id));
        await view.vm.$nextTick();
        const pins = view.findAll(".group .pins");
        expect(pins).toHaveLength(1);
        expect(pins[0].text()).toBe("1");
        expect(view.findAll(".group")[0].find(".pins").exists()).toBe(true);
    });

    it("gives a thumb linked by the focus the hue of its slot, for the outline of the recipe", async () => {
        const started = startLinkedSelection(() => undefined);
        stop = started.stop;
        const view = mount(LayerGallery, {
            props: { maps: TILED, state: defaultState(TILED) },
            global: {
                provide: { [LINKED_SELECTION_KEY as symbol]: started.linked },
            },
        });
        started.linked.toggle(elementNode("Cu"));
        await view.vm.$nextTick();
        function style(text: string): string | undefined {
            return view
                .findAll(".layer-thumb")
                .find((node) => node.find(".label").text() === text)
                ?.attributes("style");
        }
        expect(style("MS59-deconv_Cu")).toContain("--h1: var(--focus-1)");
        expect(style("MS59-deconv_Pb") ?? "").not.toContain("--h1");
    });
});

describe("LayerGallery targets and keyboard", () => {
    it("names the target pane and sets it", async () => {
        const view = gallery(PLAIN);
        const targets = view.findAll(".target-pane");
        expect(targets.map((node) => node.text())).toEqual(["A", "B"]);
        expect(targets[0].attributes("aria-pressed")).toBe("true");
        await targets[1].trigger("click");
        expect(view.emitted("set-target")?.[0]).toEqual([1]);
    });

    it("names no target pane and shows no hint in a stack", () => {
        const stacked = { ...defaultState(PLAIN), layout: "stack" as const };
        const view = gallery(PLAIN, stacked);
        expect(view.find(".target-pane").exists()).toBe(false);
        expect(view.find(".target").exists()).toBe(false);
    });

    it("marks the panes holding a canvas, and the layers in the stack only in the Stack layout", () => {
        const base = defaultState(PLAIN);
        const state = toggleInStack(base, "c1-2", PLAIN);
        const view = gallery(PLAIN, state);
        const thumbs = view.findAll(".layer-thumb");
        expect(thumbs[0].findAll(".pane-badge").map((n) => n.text())).toEqual([
            "A",
        ]);
        expect(thumbs[2].classes()).not.toContain("in-stack");
        const stacked = gallery(PLAIN, { ...state, layout: "stack" });
        expect(stacked.findAll(".layer-thumb")[2].classes()).toContain(
            "in-stack",
        );
    });

    it("marks and offers only the panes the layout shows", () => {
        const base = {
            ...defaultState(PLAIN),
            panes: ["c1-0", "c1-1", "c1-2", "c2-0"],
        };
        const letters = (layout: TableState["layout"]): string[][] => {
            const view = gallery(PLAIN, { ...base, layout });
            return [
                view.findAll(".target-pane").map((n) => n.text()),
                view.findAll(".layer-thumb .pane-badge").map((n) => n.text()),
            ];
        };
        expect(letters("single")).toEqual([["A"], ["A"]]);
        expect(letters("curtain")).toEqual([
            ["A", "B"],
            ["A", "B"],
        ]);
        expect(letters("grid2")).toEqual([
            ["A", "B"],
            ["A", "B"],
        ]);
        expect(letters("grid4")).toEqual([
            ["A", "B", "C", "D"],
            ["A", "B", "C", "D"],
        ]);
        expect(letters("stack")).toEqual([[], []]);
    });

    it("keeps the hidden panes in the state and gives no outline to a canvas only they hold", () => {
        const state = {
            ...defaultState(PLAIN),
            layout: "grid2" as const,
            panes: ["c1-0", "c1-1", "c1-2", null],
        };
        const view = gallery(PLAIN, state);
        const held = view.findAll(".layer-thumb")[2];
        expect(held.classes()).not.toContain("placed");
        expect(held.attributes("data-pane")).toBeUndefined();
        expect(held.attributes("aria-label")).not.toContain("C");
        expect(state.panes[2]).toBe("c1-2");
    });

    it("carries the canvas id on drag", async () => {
        const view = gallery(PLAIN);
        const data = new Map<string, string>();
        await view.findAll(".layer-thumb")[3].trigger("dragstart", {
            dataTransfer: {
                setData: (type: string, value: string) => data.set(type, value),
                effectAllowed: "",
            },
        });
        expect(data.get(LAYER_DRAG_TYPE)).toBe("c2-0");
    });

    it("moves the tab stop with the arrows and Home and End", async () => {
        const view = gallery(PLAIN);
        const list = view.find(".groups");
        expect(view.findAll(".layer-thumb")[0].attributes("tabindex")).toBe(
            "0",
        );
        await list.trigger("keydown", { key: "ArrowRight" });
        expect(view.findAll(".layer-thumb")[1].attributes("tabindex")).toBe(
            "0",
        );
        await list.trigger("keydown", { key: "End" });
        expect(view.findAll(".layer-thumb")[4].attributes("tabindex")).toBe(
            "0",
        );
        expect(view.findAll(".layer-thumb")[0].attributes("tabindex")).toBe(
            "-1",
        );
    });

    it("lays the first four layers of a group with Place all", async () => {
        const view = gallery(PLAIN);
        await view.findAll(".place-all")[0].trigger("click");
        expect(view.emitted("place-group")?.[0]).toEqual([
            ["c1-0", "c1-1", "c1-2"],
        ]);
    });
});

describe("LayerGallery header and filters disclosure", () => {
    it("keeps the title, the canvas count and the help in a header apart from the scrolling content", () => {
        const view = gallery(PLAIN);
        const head = view.find(".head");
        expect(head.find(".title").text()).toBe("Gallery");
        expect(head.find(".head-count").text()).toBe("5 canvases");
        expect(head.find(".compact-help").exists()).toBe(true);
        const scroller = view.find(".scroller");
        expect(scroller.find(".groups").exists()).toBe(true);
        expect(scroller.find(".head").exists()).toBe(false);
        expect(head.find(".groups").exists()).toBe(false);
    });

    it("folds the search, the analyses and the grouping behind a Filters button, closed by default", async () => {
        const view = gallery(PLAIN);
        const toggle = view.find(".filters-toggle");
        const panel = view.find(".filters");
        expect(toggle.attributes("aria-expanded")).toBe("false");
        expect(toggle.attributes("aria-controls")).toBe(panel.attributes("id"));
        expect(panel.attributes("data-open")).toBe("false");
        expect(panel.find(".filter").exists()).toBe(true);
        expect(panel.find(".tabs").exists()).toBe(true);
        expect(panel.find(".grouping").exists()).toBe(true);
        await toggle.trigger("click");
        expect(toggle.attributes("aria-expanded")).toBe("true");
        expect(panel.attributes("data-open")).toBe("true");
    });

    it("shows how many filters are active on the closed button", async () => {
        const view = gallery(PLAIN);
        expect(view.find(".filters-toggle .active-count").exists()).toBe(false);
        await view.find(".filter").setValue("L1");
        expect(view.find(".filters-toggle .active-count").text()).toBe("1");
        await view.findAll(".analysis-tab")[1].trigger("click");
        expect(view.find(".filters-toggle .active-count").text()).toBe("2");
        expect(view.find(".filters-toggle").attributes("aria-label")).toBe(
            "Filters, 2 active",
        );
        await view.find(".filter").setValue("");
        await view.findAll(".analysis-tab")[0].trigger("click");
        expect(view.find(".filters-toggle .active-count").exists()).toBe(false);
    });
});
