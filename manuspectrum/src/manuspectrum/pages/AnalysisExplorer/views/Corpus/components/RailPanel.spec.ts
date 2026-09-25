import { flushPromises, mount } from "@vue/test-utils";
import { createPinia, setActivePinia } from "pinia";
import PrimeVue from "primevue/config";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { h } from "vue";

import RailPanel from "@/manuspectrum/pages/AnalysisExplorer/views/Corpus/components/RailPanel.vue";

let compact = false;

beforeEach(() => {
    compact = false;
    setActivePinia(createPinia());
    vi.stubGlobal("matchMedia", (query: string) => ({
        matches: compact && query.includes("80rem"),
        media: query,
        addEventListener: () => undefined,
        removeEventListener: () => undefined,
    }));
});

afterEach(() => vi.unstubAllGlobals());

/** `transitions`: run PrimeVue's own transitions, whose enter hook binds Escape. */
function mountPanel(transitions = false) {
    return mount(RailPanel, {
        attachTo: document.body,
        props: { showLabel: "See 12 analyses" },
        slots: {
            default: () => h("input", { type: "checkbox", class: "filter" }),
        },
        global: {
            plugins: [PrimeVue],
            stubs: transitions ? { transition: false } : {},
        },
    });
}

describe("RailPanel", () => {
    it("is a column of filters on a wide screen and focuses the first one on request", () => {
        const wrapper = mountPanel();
        expect(wrapper.find("aside.rail-panel").exists()).toBe(true);
        (wrapper.vm as unknown as { focusFilters: () => void }).focusFilters();
        expect(document.activeElement).toBe(wrapper.find(".filter").element);
        wrapper.unmount();
    });

    it("opens the filters in a drawer below 80rem and closes it on « See n analyses »", async () => {
        compact = true;
        const wrapper = mountPanel();
        const toggle = wrapper.find(".toggle");
        expect(toggle.text()).toBe("Filters (0)");
        await toggle.trigger("click");
        await flushPromises();
        const drawer = document.querySelector(".explorer-rail-drawer");
        expect(drawer?.getAttribute("role")).toBe("dialog");
        expect(drawer?.querySelector(".filter")).not.toBeNull();
        (drawer?.querySelector(".show") as HTMLButtonElement).click();
        await flushPromises();
        expect(document.querySelector(".explorer-rail-drawer")).toBeNull();
        expect(document.activeElement).toBe(toggle.element);
        wrapper.unmount();
    });

    it("closes the drawer on Escape and gives the focus back to the toggle", async () => {
        compact = true;
        const wrapper = mountPanel(true);
        const toggle = wrapper.find(".toggle");
        await toggle.trigger("click");
        await flushPromises();
        expect(toggle.attributes("aria-expanded")).toBe("true");
        document.dispatchEvent(
            new KeyboardEvent("keydown", { key: "Escape", code: "Escape" }),
        );
        await flushPromises();
        expect(toggle.attributes("aria-expanded")).toBe("false");
        expect(document.activeElement).toBe(toggle.element);
        wrapper.unmount();
    });
});
