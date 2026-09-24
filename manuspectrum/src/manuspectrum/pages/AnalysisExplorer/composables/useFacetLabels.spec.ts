import { describe, expect, it } from "vitest";
import { defineComponent, h, nextTick, ref, shallowRef } from "vue";
import { mount } from "@vue/test-utils";

import { useFacetLabels } from "@/manuspectrum/pages/AnalysisExplorer/composables/useFacetLabels.ts";
import { FACET_LABELS_KEY } from "@/manuspectrum/pages/AnalysisExplorer/injection-keys.ts";
import {
    facet,
    label,
} from "@/manuspectrum/pages/AnalysisExplorer/testing/fixtures.ts";

import type {
    Facet,
    Label,
} from "@/manuspectrum/pages/AnalysisExplorer/api/types.ts";

describe("useFacetLabels", () => {
    it("records every facet value label and keeps the ones seen before", async () => {
        const labels = ref(
            new Map<string, Label>([["part:old", label("Old part")]]),
        );
        const facets = shallowRef<Facet[] | undefined>(undefined);
        const Probe = defineComponent({
            setup() {
                useFacetLabels(() => facets.value);
                return () => h("div");
            },
        });
        mount(Probe, {
            global: { provide: { [FACET_LABELS_KEY as symbol]: labels } },
        });
        expect(labels.value.size).toBe(1);
        facets.value = [facet("technique", 2)];
        await nextTick();
        expect(labels.value.get("technique:technique-1")?.value).toBe(
            "technique 1",
        );
        expect(labels.value.get("part:old")?.value).toBe("Old part");
    });
});
