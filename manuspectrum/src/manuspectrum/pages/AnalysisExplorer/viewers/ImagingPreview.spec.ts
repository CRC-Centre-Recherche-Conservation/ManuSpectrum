import { mount } from "@vue/test-utils";
import { createPinia, setActivePinia } from "pinia";
import PrimeVue from "primevue/config";
import { describe, expect, it } from "vitest";
import { ref } from "vue";

import ImagingPreview from "@/manuspectrum/pages/AnalysisExplorer/viewers/ImagingPreview.vue";

import {
    CURTAIN_KEY,
    FOLIO_ZONES_KEY,
} from "@/manuspectrum/pages/AnalysisExplorer/injection-keys.ts";
import { useExplorerStore } from "@/manuspectrum/pages/AnalysisExplorer/store/explorer.ts";
import {
    analysisPayload,
    imagingEntry,
    uuid,
} from "@/manuspectrum/pages/AnalysisExplorer/testing/fixtures.ts";

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
    it("says when the image server does not give the map, and asks again on Retry", async () => {
        const { wrapper } = mountPreview();
        await wrapper.find("img.layer-image").trigger("error");
        const status = wrapper.find(".unavailable");
        expect(status.attributes("role")).toBe("status");
        expect(status.text()).toContain("Map unavailable (image server)");
        expect(wrapper.find("img.layer-image").exists()).toBe(false);
        await status.find("button").trigger("click");
        expect(wrapper.find("img.layer-image").exists()).toBe(true);
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
