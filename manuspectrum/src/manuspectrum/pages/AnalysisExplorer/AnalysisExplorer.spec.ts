import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { flushPromises, mount } from "@vue/test-utils";
import { createPinia, setActivePinia } from "pinia";

import AnalysisExplorer from "@/manuspectrum/pages/AnalysisExplorer/AnalysisExplorer.vue";

import { useExplorerStore } from "@/manuspectrum/pages/AnalysisExplorer/store/explorer.ts";
import { searchResponse } from "@/manuspectrum/pages/AnalysisExplorer/testing/fixtures.ts";
import { jsonResponse } from "@/manuspectrum/pages/AnalysisExplorer/testing/responses.ts";

import type { Pinia } from "pinia";

vi.mock("@/arches/utils/generate-arches-url.ts", () => ({
    generateArchesURL: (name: string) => `/en/${name}`,
}));

const KEY = "ch:00000000-0000-4000-8000-000000000001:-";
let pinia: Pinia;

beforeEach(() => {
    pinia = createPinia();
    setActivePinia(pinia);
    window.localStorage.clear();
    vi.stubGlobal(
        "fetch",
        vi.fn(async (url: string) =>
            url.includes("explorer-items")
                ? jsonResponse({ items: [], missing: [] })
                : jsonResponse(searchResponse()),
        ),
    );
});

afterEach(() => vi.unstubAllGlobals());

describe("AnalysisExplorer", () => {
    it("records the server's connection flag", () => {
        window.history.replaceState(null, "", "/en/discover");
        mount(AnalysisExplorer, {
            props: { connected: true },
            global: { plugins: [pinia] },
        });
        expect(useExplorerStore().session.connected).toBe(true);
    });

    it("opens the screen the URL names", async () => {
        window.history.replaceState(null, "", "/en/discover?q=gold");
        const wrapper = mount(AnalysisExplorer, {
            props: { connected: false },
            global: { plugins: [pinia] },
        });
        await flushPromises();
        expect(wrapper.find(".corpus-results").exists()).toBe(true);
        expect(wrapper.find(".active-filters").exists()).toBe(true);
    });

    it("prompts for a shared Selection and removes sel from the URL", async () => {
        window.history.replaceState(null, "", `/en/discover?sel=${KEY}`);
        const wrapper = mount(AnalysisExplorer, {
            props: { connected: false },
            global: { plugins: [pinia] },
        });
        await flushPromises();
        expect(window.location.search).toBe("");
        expect(wrapper.find(".shared-selection").exists()).toBe(true);
        await wrapper.find(".shared-selection .replace").trigger("click");
        expect(wrapper.find(".shared-selection").exists()).toBe(false);
        expect(wrapper.find("[aria-live=polite].announcer").text()).toBe(
            "Your Selection now holds the 1 shared item.",
        );
        expect(useExplorerStore().basket.map((item) => item.key)).toEqual([
            KEY,
        ]);
    });
});
