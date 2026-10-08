import { beforeEach, describe, expect, it } from "vitest";
import { ref } from "vue";
import { mount } from "@vue/test-utils";
import { createPinia, setActivePinia } from "pinia";

import ActiveFiltersBar from "@/manuspectrum/pages/AnalysisExplorer/components/ActiveFiltersBar.vue";

import {
    CORPUS_COUNT_KEY,
    FACET_LABELS_KEY,
} from "@/manuspectrum/pages/AnalysisExplorer/injection-keys.ts";
import { useExplorerStore } from "@/manuspectrum/pages/AnalysisExplorer/store/explorer.ts";

import type { Pinia } from "pinia";

let pinia: Pinia;

function mountBar(count: number | null = null) {
    const labels = ref(
        new Map([["technique:http://x/xrf", { value: "XRF", lang: "en" }]]),
    );
    return mount(ActiveFiltersBar, {
        global: {
            plugins: [pinia],
            provide: {
                [FACET_LABELS_KEY as symbol]: labels,
                [CORPUS_COUNT_KEY as symbol]: ref(count),
            },
        },
    });
}

beforeEach(() => {
    pinia = createPinia();
    setActivePinia(pinia);
});

describe("ActiveFiltersBar", () => {
    it("renders nothing without an active filter", () => {
        expect(mountBar().find(".active-filters").exists()).toBe(false);
    });

    it("shows one chip per filter with its known label and removes it", async () => {
        const store = useExplorerStore();
        store.setFilter("technique", ["http://x/xrf", "http://x/unknown"]);
        store.setFilter("q", "lead");
        const wrapper = mountBar();
        const chips = wrapper.findAll(".active-filters .chip");
        expect(chips.map((chip) => chip.text())).toEqual([
            "Text: lead×",
            "Technique: http://x/unknown×",
            "Technique: XRF×",
        ]);
        expect(chips[2].attributes("aria-label")).toBe(
            "Remove filter: Technique: XRF",
        );
        await chips[2].trigger("click");
        expect(store.filters.technique).toEqual(["http://x/unknown"]);
    });

    it("shows apostrophes and ampersands as typed, in the chip and its label", () => {
        const store = useExplorerStore();
        store.setFilter("q", "Livre d'heures & or");
        const chip = mountBar().find(".active-filters .chip");
        expect(chip.text()).toBe("Text: Livre d'heures & or×");
        expect(chip.attributes("aria-label")).toBe(
            "Remove filter: Text: Livre d'heures & or",
        );
    });

    it("names the whole corpus and its size on the way out of the filters", async () => {
        const store = useExplorerStore();
        store.setFilter("year", [2023]);
        const wrapper = mountBar(51);
        const button = wrapper.find(".active-filters .clear-all");
        expect(button.text()).toBe("See the whole corpus (51 documents)");
        await button.trigger("click");
        expect(store.filters.year).toEqual([]);
    });

    it("says a single document in the singular", () => {
        useExplorerStore().setFilter("year", [2023]);
        expect(mountBar(1).find(".active-filters .clear-all").text()).toBe(
            "See the whole corpus (1 document)",
        );
    });

    it("leaves the size out while the corpus count is unknown, and still clears everything", async () => {
        const store = useExplorerStore();
        store.setFilter("year", [2023]);
        const button = mountBar(null).find(".active-filters .clear-all");
        expect(button.text()).toBe("See the whole corpus");
        await button.trigger("click");
        expect(store.filters.year).toEqual([]);
    });

    it("hides event types outside the map", () => {
        const store = useExplorerStore();
        store.setFilter("eventType", ["production"]);
        expect(mountBar().find(".active-filters").exists()).toBe(false);
    });
});
