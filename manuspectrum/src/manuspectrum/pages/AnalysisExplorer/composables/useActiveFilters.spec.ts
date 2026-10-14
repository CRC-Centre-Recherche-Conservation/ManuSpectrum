import { beforeEach, describe, expect, it } from "vitest";
import { defineComponent, ref } from "vue";
import { mount } from "@vue/test-utils";
import { createPinia, setActivePinia } from "pinia";

import { useActiveFilters } from "@/manuspectrum/pages/AnalysisExplorer/composables/useActiveFilters.ts";
import {
    FACET_LABELS_KEY,
    FACET_NARROWER_KEY,
} from "@/manuspectrum/pages/AnalysisExplorer/injection-keys.ts";
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
                        [
                            "material:m:blue",
                            { value: "Blue pigment", lang: "en" },
                        ],
                        [
                            "material:m:azurite",
                            { value: "Azurite", lang: "en" },
                        ],
                    ]),
                ),
                [FACET_NARROWER_KEY as symbol]: ref(
                    new Set(["material:m:blue", "place:p1"]),
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

    it("a value with narrower terms gets the suffix, a leaf and a place never", () => {
        const store = useExplorerStore();
        store.setFilter("material", ["m:blue", "m:azurite"]);
        store.setFilter("place", ["p1"]);
        expect(entries().map((entry) => entry.label)).toEqual([
            "Place of production: Paris",
            "Identified material: Azurite",
            "Identified material: Blue pigment (and narrower terms)",
        ]);
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

    it("names the period, with its rule and the undated as suffixes, and clearing it restores them", () => {
        const store = useExplorerStore();
        store.setFilter("period", [1300, 1400]);
        expect(entries().map((entry) => entry.label)).toEqual([
            "Date of production: 1300–1400",
        ]);
        store.setFilter("periodMatch", "within");
        store.setFilter("undated", true);
        const chips = entries();
        expect(chips.map((entry) => entry.label)).toEqual([
            "Date of production: 1300–1400 · entirely within · with undated",
        ]);
        chips[0].clear();
        expect(store.filters.period).toBeNull();
        expect(store.filters.periodMatch).toBe("overlap");
        expect(store.filters.undated).toBe(false);
    });
});
