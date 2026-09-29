import { mount } from "@vue/test-utils";
import { createPinia, setActivePinia } from "pinia";
import PrimeVue from "primevue/config";
import { describe, expect, it } from "vitest";
import { h, ref } from "vue";

import type { VNode } from "vue";

import ImagingPreview from "@/manuspectrum/pages/AnalysisExplorer/viewers/ImagingPreview.vue";

import {
    CURTAIN_KEY,
    FOLIO_ZONES_KEY,
    IMAGING_OVERLAYS_KEY,
} from "@/manuspectrum/pages/AnalysisExplorer/injection-keys.ts";
import { useExplorerStore } from "@/manuspectrum/pages/AnalysisExplorer/store/explorer.ts";
import {
    analysisPayload,
    imagingEntry,
    uuid,
} from "@/manuspectrum/pages/AnalysisExplorer/testing/fixtures.ts";

import type { Overlay } from "@/manuspectrum/pages/AnalysisExplorer/store/types.ts";

function mountPreview(
    zones: string[] = [uuid(101)],
    prepare: (store: ReturnType<typeof useExplorerStore>) => void = () =>
        undefined,
) {
    const pinia = createPinia();
    setActivePinia(pinia);
    prepare(useExplorerStore());
    const curtain = ref<string | null>(null);
    const file = imagingEntry();
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

describe("ImagingPreview", () => {
    it("silently retries at the image's own max size before saying the map is unavailable, and asks again on Retry", async () => {
        const { wrapper } = mountPreview();
        const bounded = wrapper.find("img.layer-image").attributes("src");
        expect(bounded).toContain("!480,480");
        await wrapper.find("img.layer-image").trigger("error");
        expect(wrapper.find(".unavailable").exists()).toBe(false);
        expect(wrapper.find("img.layer-image").attributes("src")).toContain(
            "/full/max/0/default.jpg",
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

    it("names the current layer by its kind and label", () => {
        const { wrapper } = mountPreview();
        expect(wrapper.find(".current").text()).toContain("Element");
        expect(wrapper.find(".current").text()).toContain("Pb");
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

    it("moves the laid map to the next layer when the layer scroll moves", async () => {
        const { wrapper, store } = mountPreview();
        await wrapper.find("input.lay").setValue(true);
        wrapper
            .findComponent({ name: "Slider" })
            .vm.$emit("update:modelValue", 1);
        await wrapper.vm.$nextTick();
        expect(store.overlays[`${uuid(101)}:0`]?.on).toBe(false);
        expect(store.overlays[`${uuid(101)}:1`]).toMatchObject({
            element: "Hg",
            on: true,
        });
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

    it("shows the ends of the layer scale and says where the handle is", () => {
        const { wrapper } = mountPreview();
        expect(wrapper.find(".scroll .ends").text()).toContain("Pb");
        expect(wrapper.find(".scroll .ends").text()).toContain("Hg");
        expect(
            wrapper.find(".scroll [role=slider]").attributes("aria-valuetext"),
        ).toBe("Pb, layer 1 of 2");
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

describe("ImagingPreview held by a parent (Compare)", () => {
    interface StageProps {
        layer: { label: string };
        opacity: number;
        underCurtain: boolean;
        attempt: number;
        failed: () => void;
    }

    function mountHeld(
        props: { held?: number | null; contrastNote?: boolean } = {},
        withStage = false,
    ) {
        const pinia = createPinia();
        setActivePinia(pinia);
        const settings = ref<Record<string, Overlay>>({});
        const curtain = ref<string | null>(null);
        const file = imagingEntry();
        const slots: Record<string, (stage: StageProps) => VNode> = {
            missing: () => h("p", { class: "missing-stub" }, "No Cu"),
        };
        if (withStage) {
            slots.stage = (stage) =>
                h(
                    "div",
                    {
                        class: "stage-stub",
                        "data-attempt": stage.attempt,
                        onClick: stage.failed,
                    },
                    `${stage.layer.label} ${stage.opacity} ${stage.underCurtain}`,
                );
        }
        const wrapper = mount(ImagingPreview, {
            props: {
                file,
                analysis: { id: uuid(101) },
                ...props,
            },
            slots,
            global: {
                plugins: [pinia, PrimeVue],
                provide: {
                    [CURTAIN_KEY as symbol]: curtain,
                    [FOLIO_ZONES_KEY as symbol]: ref(new Set([uuid(101)])),
                    [IMAGING_OVERLAYS_KEY as symbol]: {
                        settings,
                        set(key: string, overlay: Overlay | null): void {
                            const next = { ...settings.value };
                            if (overlay) next[key] = overlay;
                            else delete next[key];
                            settings.value = next;
                        },
                    },
                },
            },
        });
        return { wrapper, settings, curtain, store: useExplorerStore() };
    }

    it("shows the layer its parent holds, without a layer scroll of its own", async () => {
        const { wrapper } = mountHeld({ held: 1 });
        expect(wrapper.find(".current").text()).toContain("Hg");
        expect(wrapper.find(".scroll").exists()).toBe(false);
        await wrapper.setProps({ held: 0 });
        expect(wrapper.find(".current").text()).toContain("Pb");
        expect(wrapper.find("img.layer-image").attributes("alt")).toBe("Pb");
    });

    it("carries the laid map to the layer its parent moves to", async () => {
        const { wrapper, settings } = mountHeld({ held: 0 });
        await wrapper.find("input.lay").setValue(true);
        await wrapper.setProps({ held: 1 });
        expect(settings.value[`${uuid(101)}:0`]?.on).toBe(false);
        expect(settings.value[`${uuid(101)}:1`]).toMatchObject({
            element: "Hg",
            on: true,
        });
    });

    it("shows what its parent says in place of a layer the map lacks, with nothing to lay", () => {
        const { wrapper } = mountHeld({ held: null });
        expect(wrapper.find(".missing-stub").text()).toBe("No Cu");
        expect(wrapper.find(".current").exists()).toBe(false);
        expect(wrapper.find("img.layer-image").exists()).toBe(false);
        expect(wrapper.find("input.lay").exists()).toBe(false);
    });

    it("keeps the laid layers in the settings provided, never in the store", async () => {
        const { wrapper, settings, store } = mountHeld();
        await wrapper.find("input.lay").setValue(true);
        expect(settings.value[`${uuid(101)}:0`]?.on).toBe(true);
        expect(store.overlays).toEqual({});
    });

    it("draws the laid layer in the stage its parent gives, the image alone while it is not laid", async () => {
        const { wrapper, curtain } = mountHeld({}, true);
        expect(wrapper.find(".stage-stub").exists()).toBe(false);
        expect(wrapper.find("img.layer-image").exists()).toBe(true);
        await wrapper.find("input.lay").setValue(true);
        expect(wrapper.find("img.layer-image").exists()).toBe(false);
        expect(wrapper.find(".stage-stub").text()).toBe("Pb 0.7 false");
        await wrapper.find("input.curtain").setValue(true);
        expect(curtain.value).toBe(`${uuid(101)}:0`);
        expect(wrapper.find(".stage-stub").text()).toBe("Pb 0.7 true");
    });

    it("says when the stage cannot draw the layer, and gives it a new attempt on Retry", async () => {
        const { wrapper } = mountHeld({}, true);
        await wrapper.find("input.lay").setValue(true);
        await wrapper.find(".stage-stub").trigger("click");
        expect(wrapper.find(".unavailable").text()).toContain(
            "Map unavailable (image server)",
        );
        expect(wrapper.find(".stage-stub").exists()).toBe(false);
        await wrapper.find(".unavailable button").trigger("click");
        expect(wrapper.find(".stage-stub").attributes("data-attempt")).toBe(
            "1",
        );
    });

    it("leaves the contrast note to its parent when asked", () => {
        const { wrapper } = mountHeld({ contrastNote: false });
        expect(wrapper.text()).not.toContain(
            "Each map keeps its own contrast.",
        );
    });
});
