import { flushPromises, mount } from "@vue/test-utils";
import { createPinia, setActivePinia } from "pinia";
import PrimeVue from "primevue/config";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { h } from "vue";

import RailPanel from "@/manuspectrum/pages/AnalysisExplorer/views/Corpus/components/RailPanel.vue";

import { useRailWidth } from "@/manuspectrum/pages/AnalysisExplorer/composables/useRailWidth.ts";
import { RAIL_WIDTH_KEY } from "@/manuspectrum/pages/AnalysisExplorer/injection-keys.ts";

import type { RailWidth } from "@/manuspectrum/pages/AnalysisExplorer/composables/useRailWidth.ts";

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

afterEach(() => {
    vi.unstubAllGlobals();
    window.localStorage.clear();
});

/** `transitions`: run PrimeVue's own transitions, whose enter hook binds Escape. */
function mountPanel(transitions = false, railWidth: RailWidth | null = null) {
    return mount(RailPanel, {
        attachTo: document.body,
        props: { showLabel: "See 12 analyses" },
        slots: {
            default: () => h("input", { type: "checkbox", class: "filter" }),
        },
        global: {
            plugins: [PrimeVue],
            provide: railWidth ? { [RAIL_WIDTH_KEY as symbol]: railWidth } : {},
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

    it("puts a width toggle before the title that widens and narrows the column", async () => {
        const railWidth = useRailWidth();
        const wrapper = mountPanel(false, railWidth);
        const head = wrapper.find(".rail-head");
        const button = head.find("button");
        expect(head.element.firstElementChild?.contains(button.element)).toBe(
            true,
        );
        expect(head.element.lastElementChild?.matches("h2.rail-title")).toBe(
            true,
        );
        const name = () =>
            document.getElementById(button.attributes("aria-labelledby") ?? "")
                ?.textContent;
        expect(button.attributes("aria-pressed")).toBe("false");
        expect(name()).toBe("Widen the filters");
        await button.trigger("click");
        expect(railWidth.wide.value).toBe(true);
        expect(button.attributes("aria-pressed")).toBe("true");
        expect(name()).toBe("Widen the filters");
        await button.trigger("click");
        expect(railWidth.wide.value).toBe(false);
        wrapper.unmount();
    });

    it("focuses the first filter on request, not the width toggle", () => {
        const wrapper = mountPanel(false, useRailWidth());
        expect(wrapper.find(".rail-width button").exists()).toBe(true);
        (wrapper.vm as unknown as { focusFilters: () => void }).focusFilters();
        expect(document.activeElement).toBe(wrapper.find(".filter").element);
        wrapper.unmount();
    });

    it("has no width toggle without a provider or in the drawer", async () => {
        const alone = mountPanel();
        expect(alone.find(".rail-width").exists()).toBe(false);
        alone.unmount();
        compact = true;
        const wrapper = mountPanel(false, useRailWidth());
        await wrapper.find(".toggle").trigger("click");
        await flushPromises();
        expect(
            document.querySelector(".explorer-rail-drawer .rail-width"),
        ).toBeNull();
        wrapper.unmount();
    });
});
