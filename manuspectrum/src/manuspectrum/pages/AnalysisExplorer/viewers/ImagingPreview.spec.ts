import { mount } from "@vue/test-utils";
import { createPinia, setActivePinia } from "pinia";
import PrimeVue from "primevue/config";
import { describe, expect, it } from "vitest";
import { ref } from "vue";

import type {
    FileEntry,
    FileLayer,
} from "@/manuspectrum/pages/AnalysisExplorer/api/types.ts";

import ImagingPreview from "@/manuspectrum/pages/AnalysisExplorer/viewers/ImagingPreview.vue";

import {
    CURTAIN_KEY,
    FOLIO_ZONES_KEY,
} from "@/manuspectrum/pages/AnalysisExplorer/injection-keys.ts";
import { useExplorerStore } from "@/manuspectrum/pages/AnalysisExplorer/store/explorer.ts";
import {
    analysisPayload,
    imagingEntry,
    layerOf,
    uuid,
    valueRef,
} from "@/manuspectrum/pages/AnalysisExplorer/testing/fixtures.ts";

function mountPreview(
    zones: string[] = [uuid(101)],
    prepare: (store: ReturnType<typeof useExplorerStore>) => void = () =>
        undefined,
    file = imagingEntry(),
) {
    const pinia = createPinia();
    setActivePinia(pinia);
    prepare(useExplorerStore());
    const curtain = ref<string | null>(null);
    const wrapper = mount(ImagingPreview, {
        props: { file, analysis: analysisPayload({ files: [file] }) },
        global: {
            plugins: [pinia, PrimeVue],
            provide: {
                [CURTAIN_KEY as symbol]: curtain,
                [FOLIO_ZONES_KEY as symbol]: ref(new Set(zones)),
            },
        },
    });
    return { wrapper, curtain, store: useExplorerStore() };
}

const ELEMENT_MAP = valueRef("http://example.org/element-map", "Element map");

function elementLayer(index: number, symbol: string): FileLayer {
    return layerOf({
        index,
        label: `${symbol} map`,
        content: ELEMENT_MAP,
        elements: [
            {
                value: valueRef(`http://example.org/el-${symbol}`, symbol),
                symbol,
            },
        ],
    });
}

function manyLayers(count: number): FileEntry {
    return imagingEntry({
        layers: Array.from({ length: count }, (_, index) =>
            layerOf({ index, label: `L${index}` }),
        ),
    });
}

function thumbs(wrapper: ReturnType<typeof mountPreview>["wrapper"]) {
    return wrapper.findAll(".strip .layer-thumb");
}

describe("ImagingPreview", () => {
    it("silently tries a percentage size, then max, before saying the map is unavailable, and asks again on Retry", async () => {
        const { wrapper } = mountPreview();
        const bounded = wrapper.find("img.layer-image").attributes("src");
        expect(bounded).toContain("!480,480");
        await wrapper.find("img.layer-image").trigger("error");
        expect(wrapper.find(".unavailable").exists()).toBe(false);
        expect(wrapper.find("img.layer-image").attributes("src")).toContain(
            "/full/pct:",
        );
        await wrapper.find("img.layer-image").trigger("error");
        expect(wrapper.find(".unavailable").exists()).toBe(false);
        expect(wrapper.find("img.layer-image").attributes("src")).toContain(
            "/full/max/",
        );
        await wrapper.find("img.layer-image").trigger("error");
        const status = wrapper.find(".unavailable");
        expect(status.attributes("role")).toBe("status");
        expect(status.text()).toContain("Map unavailable (image server)");
        expect(wrapper.find("img.layer-image").exists()).toBe(false);
        await status.find("button").trigger("click");
        expect(wrapper.find("img.layer-image").exists()).toBe(true);
        expect(wrapper.find("img.layer-image").attributes("src")).toBe(bounded);
    });

    it("names the current layer by its stored label", () => {
        const { wrapper } = mountPreview();
        expect(wrapper.find(".current .value").text()).toBe("Pb");
    });

    it("lays the current layer on the page and keeps its opacity", async () => {
        const { wrapper, store } = mountPreview();
        await wrapper.find("input.lay").setValue(true);
        expect(store.overlays[`${uuid(101)}:0`]).toEqual({
            element: "Pb",
            opacity: 0.7,
            on: true,
        });
        expect(wrapper.text()).toContain(
            "Indicative positioning, not registered.",
        );
    });

    it("moves the laid map to the next layer with the next button", async () => {
        const { wrapper, store } = mountPreview();
        await wrapper.find("input.lay").setValue(true);
        await wrapper.find("[data-action=next]").trigger("click");
        expect(store.overlays[`${uuid(101)}:0`]?.on).toBe(false);
        expect(store.overlays[`${uuid(101)}:1`]).toMatchObject({
            element: "Hg",
            on: true,
        });
    });

    it("carries a laid map to the layer whose thumbnail is clicked", async () => {
        const { wrapper, store } = mountPreview(
            [uuid(101)],
            undefined,
            manyLayers(5),
        );
        await wrapper.find("input.lay").setValue(true);
        await thumbs(wrapper)[3].trigger("click");
        expect(store.overlays[`${uuid(101)}:0`]?.on).toBe(false);
        expect(store.overlays[`${uuid(101)}:3`]).toMatchObject({
            element: "L3",
            on: true,
        });
        expect(wrapper.find(".current").text()).toContain("4 / 5");
    });

    it("disables the arrows at the ends and does not wrap", async () => {
        const { wrapper } = mountPreview();
        const previous = wrapper.find("[data-action=previous]");
        const next = wrapper.find("[data-action=next]");
        expect(previous.attributes("aria-disabled")).toBe("true");
        expect(next.attributes("aria-disabled")).toBeUndefined();
        expect(wrapper.find(".current").text()).toContain("1 / 2");
        await next.trigger("click");
        expect(wrapper.find(".current").text()).toContain("2 / 2");
        expect(next.attributes("aria-disabled")).toBe("true");
        await next.trigger("click");
        expect(wrapper.find(".current").text()).toContain("2 / 2");
        expect(previous.attributes("aria-disabled")).toBeUndefined();
    });

    it("marks the current thumbnail and keeps one tab stop moved by the arrow keys", async () => {
        const { wrapper } = mountPreview([uuid(101)], undefined, manyLayers(4));
        const list = thumbs(wrapper);
        expect(list).toHaveLength(4);
        expect(list.map((item) => item.attributes("aria-current"))).toEqual([
            "true",
            undefined,
            undefined,
            undefined,
        ]);
        expect(list.map((item) => item.attributes("tabindex"))).toEqual([
            "0",
            "-1",
            "-1",
            "-1",
        ]);
        await list[0].trigger("keydown", { key: "ArrowRight" });
        expect(
            thumbs(wrapper).map((item) => item.attributes("tabindex")),
        ).toEqual(["-1", "0", "-1", "-1"]);
        await list[1].trigger("keydown", { key: "End" });
        expect(thumbs(wrapper)[3].attributes("tabindex")).toBe("0");
    });

    it("shows group headings only when the layers fall in two groups or more", () => {
        const plain = mountPreview();
        expect(plain.wrapper.find(".group-title").exists()).toBe(false);
        const grouped = mountPreview(
            [uuid(101)],
            undefined,
            imagingEntry({
                layers: [
                    elementLayer(0, "Pb"),
                    layerOf({ index: 1, label: "Raw" }),
                    elementLayer(2, "Fe"),
                    elementLayer(3, "Pb"),
                ],
            }),
        );
        const titles = grouped.wrapper
            .findAll(".group-title")
            .map((item) => item.text());
        expect(titles).toEqual(["Fe", "Pb", "Unclassified · 1"]);
    });

    it("shows no navigation and no strip for a file with one layer", () => {
        const { wrapper } = mountPreview([uuid(101)], undefined, manyLayers(1));
        expect(wrapper.find("[data-action=next]").exists()).toBe(false);
        expect(wrapper.find(".strip").exists()).toBe(false);
        expect(wrapper.find(".current .value").text()).toBe("L0");
    });

    it("puts the laid layer under the curtain", async () => {
        const { wrapper, curtain } = mountPreview();
        await wrapper.find("input.lay").setValue(true);
        await wrapper.find("input.curtain").setValue(true);
        expect(curtain.value).toBe(`${uuid(101)}:0`);
    });

    it("explains why a layer cannot be laid when the analysis has no zone on this page", () => {
        const { wrapper } = mountPreview([]);
        expect(wrapper.find("input.lay").attributes("disabled")).toBeDefined();
        expect(wrapper.text()).toContain("no zone on this page");
    });

    it("offers no button of its own to add a map to the Selection", () => {
        const { wrapper } = mountPreview();
        expect(wrapper.find(".add-to-selection").exists()).toBe(false);
        expect(wrapper.text()).not.toContain("Add the map");
    });

    it("opens on the layer of this file that is laid on the page", () => {
        const { wrapper } = mountPreview([uuid(101)], (store) =>
            store.setOverlay(`${uuid(101)}:1`, {
                element: "Hg",
                opacity: 0.4,
                on: true,
            }),
        );
        expect(wrapper.find(".current").text()).toContain("Hg");
        expect(
            (wrapper.find("input.lay").element as HTMLInputElement).checked,
        ).toBe(true);
    });
});
