import { mount } from "@vue/test-utils";
import PrimeVue from "primevue/config";
import { describe, expect, it } from "vitest";

import FolioViewSwitch from "@/manuspectrum/pages/AnalysisExplorer/views/Corpus/document/FolioViewSwitch.vue";

import type { FolioView } from "@/manuspectrum/pages/AnalysisExplorer/store/types.ts";

function mountSwitch(view: FolioView, available: FolioView[]) {
    return mount(FolioViewSwitch, {
        props: { view, available },
        global: { plugins: [PrimeVue] },
    });
}

describe("FolioViewSwitch", () => {
    it("offers the views that have something on the page, the current one pressed", () => {
        const wrapper = mountSwitch("analyses", ["analyses", "samples"]);
        const group = wrapper.find('[role="group"]');
        expect(group.attributes("aria-label")).toBe("Show");
        const buttons = wrapper.findAll("button");
        expect(buttons.map((button) => button.text())).toEqual([
            "Analyses",
            "Samples",
        ]);
        expect(buttons[0].attributes("aria-pressed")).toBe("true");
        expect(buttons[1].attributes("aria-pressed")).toBe("false");
    });

    it("emits the view chosen", async () => {
        const wrapper = mountSwitch("analyses", [
            "analyses",
            "characterizations",
            "samples",
        ]);
        await wrapper.findAll("button")[1].trigger("click");
        expect(wrapper.emitted("change")).toEqual([["characterizations"]]);
    });

    it("keeps the current view when its own button is pressed again", async () => {
        const wrapper = mountSwitch("samples", ["analyses", "samples"]);
        await wrapper.findAll("button")[1].trigger("click");
        expect(wrapper.emitted("change")).toBeUndefined();
    });

    it("is hidden when only one view has something on the page", () => {
        const wrapper = mountSwitch("analyses", ["analyses"]);
        expect(wrapper.find('[role="group"]').exists()).toBe(false);
    });
});
