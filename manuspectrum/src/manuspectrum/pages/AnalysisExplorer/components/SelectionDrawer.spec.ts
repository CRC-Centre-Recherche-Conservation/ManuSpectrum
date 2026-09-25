import { flushPromises, mount } from "@vue/test-utils";
import { createPinia, setActivePinia } from "pinia";
import PrimeVue from "primevue/config";
import { afterEach, describe, expect, it, vi } from "vitest";

import SelectionDrawer from "@/manuspectrum/pages/AnalysisExplorer/components/SelectionDrawer.vue";

import { useExplorerStore } from "@/manuspectrum/pages/AnalysisExplorer/store/explorer.ts";
import { uuid } from "@/manuspectrum/pages/AnalysisExplorer/testing/fixtures.ts";
import { jsonResponse } from "@/manuspectrum/pages/AnalysisExplorer/testing/responses.ts";

vi.mock("@/arches/utils/generate-arches-url.ts", () => ({
    generateArchesURL: () => "/en/api/explorer/items",
}));

afterEach(() => {
    vi.unstubAllGlobals();
    document.body.innerHTML = "";
});

function mountDrawer() {
    vi.stubGlobal(
        "fetch",
        vi.fn(async () => jsonResponse({ items: [], missing: [] })),
    );
    const pinia = createPinia();
    setActivePinia(pinia);
    const wrapper = mount(SelectionDrawer, {
        attachTo: document.body,
        global: { plugins: [pinia, PrimeVue], stubs: { transition: false } },
    });
    return { wrapper, store: useExplorerStore() };
}

describe("SelectionDrawer", () => {
    it("says how many items the Selection holds on its button", async () => {
        const { wrapper, store } = mountDrawer();
        const button = wrapper.find("button.opener");
        expect(button.attributes("aria-label")).toBe("Selection 0/30");
        store.addToBasket(`ch:${uuid(1)}:-`);
        await flushPromises();
        expect(button.attributes("aria-label")).toBe("Selection 1/30");
        expect(button.find(".badge").text()).toBe("1");
        wrapper.unmount();
    });

    it("opens the Selection in a dialog and gives the focus back to the button on Escape", async () => {
        const { wrapper } = mountDrawer();
        const button = wrapper.find("button.opener");
        await button.trigger("click");
        await flushPromises();
        const dialog = document.querySelector<HTMLElement>(
            ".explorer-selection-drawer",
        );
        expect(dialog?.getAttribute("role")).toBe("dialog");
        expect(dialog?.getAttribute("aria-labelledby")).toBe("selection-title");
        expect(dialog?.querySelector(".selection-panel")).not.toBeNull();
        expect(button.attributes("aria-expanded")).toBe("true");

        document.dispatchEvent(
            new KeyboardEvent("keydown", { key: "Escape", code: "Escape" }),
        );
        await flushPromises();

        expect(button.attributes("aria-expanded")).toBe("false");
        expect(document.activeElement).toBe(button.element);
        wrapper.unmount();
    });
});
