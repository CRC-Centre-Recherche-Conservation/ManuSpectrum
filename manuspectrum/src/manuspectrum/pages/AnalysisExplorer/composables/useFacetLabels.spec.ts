import { describe, expect, it } from "vitest";
import { defineComponent, h, nextTick, ref, shallowRef } from "vue";
import { mount } from "@vue/test-utils";

import {
    recordEventLabels,
    recordFacetNarrower,
    useFacetLabels,
} from "@/manuspectrum/pages/AnalysisExplorer/composables/useFacetLabels.ts";
import {
    FACET_LABELS_KEY,
    FACET_NARROWER_KEY,
} from "@/manuspectrum/pages/AnalysisExplorer/injection-keys.ts";
import {
    facet,
    facetValue,
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
        const narrower = ref(new Set<string>());
        const facets = shallowRef<Facet[] | undefined>(undefined);
        const Probe = defineComponent({
            setup() {
                useFacetLabels(() => facets.value);
                return () => h("div");
            },
        });
        mount(Probe, {
            global: {
                provide: {
                    [FACET_LABELS_KEY as symbol]: labels,
                    [FACET_NARROWER_KEY as symbol]: narrower,
                },
            },
        });
        expect(labels.value.size).toBe(1);
        facets.value = [
            facet("technique", 2),
            {
                ...facet("material", 0),
                values: [facetValue("m:blue", "Blue", { narrower: true })],
            },
        ];
        await nextTick();
        expect(labels.value.get("technique:technique-1")?.value).toBe(
            "technique 1",
        );
        expect(labels.value.get("part:old")?.value).toBe("Old part");
        expect([...narrower.value]).toEqual(["material:m:blue"]);
    });

    it("records the material and colour uris and the place ids of an events payload", () => {
        const labels = ref(new Map<string, Label>());
        recordEventLabels(labels, {
            materials: {
                "http://m/lapis": {
                    uri: "http://m/lapis",
                    label: label("Lapis"),
                    colours: [],
                    swatch: null,
                    ancestors: [],
                },
            },
            coveringMaterials: {},
            colours: {
                "http://c/blue": {
                    uri: "http://c/blue",
                    label: label("Blue"),
                    swatch: null,
                },
            },
            places: {
                p1: {
                    id: "p1",
                    name: label("Paris"),
                    lngLat: null,
                    geometryKind: "point",
                    extentKm: null,
                    parent: null,
                    unpublished: false,
                    authorities: {},
                },
            },
        });
        expect(labels.value.get("material:http://m/lapis")?.value).toBe(
            "Lapis",
        );
        expect(labels.value.get("colour:http://c/blue")?.value).toBe("Blue");
        expect(labels.value.get("place:p1")?.value).toBe("Paris");
    });

    it("records the covering materials", () => {
        const labels = ref(new Map<string, Label>());
        recordEventLabels(labels, {
            materials: {},
            coveringMaterials: { "http://m/blue": label("Blue pigment") },
            colours: {},
            places: {},
        });
        expect(labels.value.get("material:http://m/blue")?.value).toBe(
            "Blue pigment",
        );
    });

    it("records which values have narrower terms, and forgets a value that lost them", () => {
        const narrower = ref(new Set<string>(["material:m:gone"]));
        recordFacetNarrower(narrower, [
            {
                ...facet("material", 0),
                values: [
                    facetValue("m:blue", "Blue pigment", { narrower: true }),
                    facetValue("m:azurite", "Azurite"),
                    facetValue("m:gone", "Gone"),
                ],
            },
        ]);
        expect([...narrower.value]).toEqual(["material:m:blue"]);
        recordFacetNarrower(narrower, [facet("technique", 1)]);
        expect([...narrower.value]).toEqual(["material:m:blue"]);
    });
});
