import { beforeEach, describe, expect, it } from "vitest";
import { defineComponent, ref } from "vue";
import { mount } from "@vue/test-utils";
import { createPinia, setActivePinia } from "pinia";

import { useActiveFilters } from "@/manuspectrum/pages/AnalysisExplorer/composables/useActiveFilters.ts";
import { FACET_LABELS_KEY } from "@/manuspectrum/pages/AnalysisExplorer/injection-keys.ts";
import { useExplorerStore } from "@/manuspectrum/pages/AnalysisExplorer/store/explorer.ts";

import type { ActiveFilter } from "@/manuspectrum/pages/AnalysisExplorer/composables/useActiveFilters.ts";

function entries(): ActiveFilter[] {
    let found: ActiveFilter[] = [];
    const Probe = defineComponent({
        setup() {
            const { activeFilters } = useActiveFilters();
            return () => {
                found = activeFilters.value;
                return null;
            };
        },
    });
    mount(Probe, {
        global: {
            provide: {
                [FACET_LABELS_KEY as symbol]: ref(
                    new Map([
                        ["colour:c1", { value: "Bleu", lang: "fr" }],
                        ["place:p1", { value: "Paris", lang: "fr" }],
                    ]),
                ),
            },
        },
    });
    return found;
}

beforeEach(() => setActivePinia(createPinia()));

describe("useActiveFilters", () => {
    it("names a colour chip « Colour », by the label the payload gave", () => {
        useExplorerStore().setFilter("colour", ["c1"]);
        expect(entries().map((entry) => entry.label)).toEqual(["Colour: Bleu"]);
    });

    it("has one chip per place, named by its label, and clearing it leaves the others", () => {
        const store = useExplorerStore();
        store.setFilter("place", ["p1", "p2"]);
        const chips = entries();
        expect(chips.map((entry) => entry.label)).toEqual([
            "Place of production: Paris",
            "Place of production: p2",
        ]);
        chips[0].clear();
        expect(store.filters.place).toEqual(["p2"]);
    });

    it("has no chip for a scope of everywhere", () => {
        expect(entries()).toEqual([]);
    });

    it("shows where the colour is recorded only when it is not everywhere, and clearing it restores everywhere", () => {
        const store = useExplorerStore();
        store.setFilter("colourScope", "part");
        let chips = entries();
        expect(chips.map((entry) => entry.label)).toEqual([
            "Colour recorded: Studied component",
        ]);
        chips[0].clear();
        expect(store.filters.colourScope).toBe("all");
        store.setFilter("colourScope", "material");
        chips = entries();
        expect(chips.map((entry) => entry.label)).toEqual([
            "Colour recorded: Identified material",
        ]);
    });
});
