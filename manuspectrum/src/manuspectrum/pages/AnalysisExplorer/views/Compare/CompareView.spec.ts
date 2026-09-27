import { beforeEach, describe, expect, it, vi } from "vitest";
import { flushPromises, mount } from "@vue/test-utils";
import { createPinia, setActivePinia } from "pinia";

import CompareView from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/CompareView.vue";

import { useExplorerStore } from "@/manuspectrum/pages/AnalysisExplorer/store/explorer.ts";
import { resetFakeGrids } from "@/manuspectrum/pages/AnalysisExplorer/testing/gridstack.ts";

import type { Pinia } from "pinia";

vi.mock("gridstack", async () =>
    (
        await import(
            "@/manuspectrum/pages/AnalysisExplorer/testing/gridstack.ts"
        )
    ).gridstackModule(),
);

const SPECTRUM =
    "af:00000000-0000-4000-8000-000000000001:00000000-0000-4000-8000-000000000002";
const MATERIAL = "ch:00000000-0000-4000-8000-000000000003:-";

let pinia: Pinia;

beforeEach(() => {
    resetFakeGrids();
    window.localStorage.clear();
    pinia = createPinia();
    setActivePinia(pinia);
});

function mountView() {
    return mount(CompareView, {
        attachTo: document.body,
        global: { plugins: [pinia] },
    });
}

describe("CompareView", () => {
    it("says how to fill an empty Selection, with no windows", () => {
        const wrapper = mountView();
        expect(wrapper.find(".empty").text()).toBe(
            "Your Selection is empty. Add analyses or identified materials with « + Selection ».",
        );
        expect(wrapper.find(".grid-stack").exists()).toBe(false);
        wrapper.unmount();
    });

    it("opens one window per kind of item in the Selection", async () => {
        useExplorerStore().addManyToBasket([SPECTRUM, MATERIAL]);
        const wrapper = mountView();
        await flushPromises();
        expect(
            wrapper
                .findAll(".grid-stack-item")
                .map((item) => item.attributes("data-window-id")),
        ).toEqual(["auto:xy:all", "auto:characterizations"]);
        expect(
            wrapper.findAll(".compare-window h3").map((h) => h.text()),
        ).toEqual(["Spectra", "Identified materials"]);
        wrapper.unmount();
    });

    it("takes a closed window's items out of the Selection", async () => {
        const store = useExplorerStore();
        store.addManyToBasket([SPECTRUM, MATERIAL]);
        const wrapper = mountView();
        await flushPromises();
        await wrapper
            .find(
                '[data-window-id="auto:characterizations"] [data-action="close"]',
            )
            .trigger("click");
        expect(store.basket.map((item) => item.key)).toEqual([SPECTRUM]);
        expect(
            wrapper.find('[data-window-id="auto:characterizations"]').exists(),
        ).toBe(false);
        wrapper.unmount();
    });
});
