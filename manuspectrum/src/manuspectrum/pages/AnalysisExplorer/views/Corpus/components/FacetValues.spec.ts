import { describe, expect, it } from "vitest";
import { mount } from "@vue/test-utils";

import FacetValues from "@/manuspectrum/pages/AnalysisExplorer/views/Corpus/components/FacetValues.vue";

import {
    facet,
    facetValue,
} from "@/manuspectrum/pages/AnalysisExplorer/testing/fixtures.ts";

import type { Facet } from "@/manuspectrum/pages/AnalysisExplorer/api/types.ts";

function colourFacet(): Facet {
    return {
        key: "colour",
        group: "characterization",
        values: [
            facetValue("c1", "Bleu", { swatch: "#2f55a4", count: 4 }),
            facetValue("c2", "Gris", { swatch: "#8f8c86", count: 0 }),
            facetValue("c3", "Doré", {
                swatch: "linear-gradient(135deg, #f3dc8a, #b8891f)",
                count: 2,
            }),
        ],
        total: 3,
    };
}

function mountValues(
    props: Partial<InstanceType<typeof FacetValues>["$props"]> & {
        facet: Facet;
    },
) {
    return mount(FacetValues, {
        props: { values: props.facet.values, selected: [], ...props },
    });
}

describe("FacetValues", () => {
    it("lists a checkbox, the label in its language and the count of each value", () => {
        const wrapper = mountValues({
            facet: facet("part", 2),
            selected: ["part-1"],
        });
        const rows = wrapper.findAll(".value");
        expect(rows).toHaveLength(2);
        expect(rows[0].find(".label").text()).toBe("part 0");
        expect(rows[0].find(".label").attributes("lang")).toBe("en");
        expect(rows[1].find(".count").text()).toBe("2");
        expect(
            wrapper
                .findAll<HTMLInputElement>("input")
                .map((input) => input.element.checked),
        ).toEqual([false, true]);
    });

    it("says what a count counts in the count's title", () => {
        const wrapper = mountValues({
            facet: facet("part", 1),
            countHint: "%{n} in this document",
        });
        expect(wrapper.find(".count").attributes("title")).toBe(
            "1 in this document",
        );
        expect(
            mountValues({ facet: facet("part", 1) })
                .find(".count")
                .attributes("title"),
        ).toBeUndefined();
    });

    it("emits the value and whether it is now checked", async () => {
        const wrapper = mountValues({
            facet: facet("part", 2),
            selected: ["part-0"],
        });
        await wrapper.findAll("input")[1].setValue(true);
        await wrapper.findAll("input")[0].setValue(false);
        expect(wrapper.emitted("change")).toEqual([
            ["part-1", true],
            ["part-0", false],
        ]);
    });

    it("gives each technique the dot of its mark and the ink dot without a family colour", () => {
        const technique: Facet = {
            key: "technique",
            group: "analysis",
            values: [
                facetValue("t:xrf", "XRF", {
                    mark: { code: "XRF", colour: 3, family: "t:xrf" },
                }),
                facetValue("t:om", "OM", {
                    mark: { code: "OM", colour: null, family: "t:om" },
                }),
            ],
            total: 2,
        };
        const rows = mountValues({ facet: technique }).findAll(".value");
        expect(rows[0].find(".dot").classes()).toContain("dot--tech-3");
        expect(rows[1].find(".dot").classes()).toContain("dot--ink");
    });

    it("draws a square swatch from the colour the server gives, and none without one", () => {
        const wrapper = mountValues({
            facet: {
                ...colourFacet(),
                values: [
                    ...colourFacet().values,
                    facetValue("c4", "Polychrome"),
                ],
            },
        });
        const rows = wrapper.findAll(".value");
        expect(rows[0].find(".swatch").attributes("style")).toContain(
            "#2f55a4",
        );
        expect(rows[2].find(".swatch").attributes("style")).toContain(
            "linear-gradient",
        );
        expect(rows[0].find(".swatch").classes()).not.toContain("dot");
        expect(rows[3].find(".swatch").exists()).toBe(false);
    });

    it("greys a value at zero and keeps it unticked in a fixed list, never removing it", () => {
        const wrapper = mountValues({
            facet: colourFacet(),
            fixedList: true,
        });
        const rows = wrapper.findAll(".value");
        expect(rows).toHaveLength(3);
        expect(rows[1].classes()).toContain("zero");
        expect(rows[1].find("input").attributes("disabled")).toBeDefined();
        expect(rows[0].classes()).not.toContain("zero");
        expect(rows[0].find("input").attributes("disabled")).toBeUndefined();
    });

    it("keeps a ticked value at zero unticked-able so the reader can leave it", () => {
        const wrapper = mountValues({
            facet: colourFacet(),
            fixedList: true,
            selected: ["c2"],
        });
        expect(
            wrapper.findAll(".value")[1].find("input").attributes("disabled"),
        ).toBeUndefined();
    });

    it("disables a value at zero in any list, without the fixed-list grey", () => {
        const wrapper = mountValues({ facet: colourFacet() });
        const row = wrapper.findAll(".value")[1];
        expect(row.find("input").attributes("disabled")).toBeDefined();
        expect(row.classes()).not.toContain("zero");
    });

    it("badges an unpublished value", () => {
        const wrapper = mountValues({
            facet: {
                ...facet("place", 0),
                values: [
                    facetValue("p1", "Paris", { unpublished: true }),
                    facetValue("p2", "Rome"),
                ],
            },
        });
        const rows = wrapper.findAll(".value");
        expect(rows[0].find(".unpublished").text()).toBe("unpublished");
        expect(rows[1].find(".unpublished").exists()).toBe(false);
    });

    it("tells assistive technology and the eye that it is waiting for an answer", () => {
        const idle = mountValues({ facet: facet("part", 1) });
        expect(idle.find(".values").attributes("aria-busy")).toBe("false");
        expect(idle.find(".values").classes()).not.toContain("busy");
        const busy = mountValues({ facet: facet("part", 1), busy: true });
        expect(busy.find(".values").attributes("aria-busy")).toBe("true");
        expect(busy.find(".values").classes()).toContain("busy");
    });

    it("keeps the whole label for a label cut on screen", () => {
        const wrapper = mountValues({
            facet: {
                ...facet("project", 0),
                values: [facetValue("p1", "ATRAMENTA — Encres")],
            },
        });
        expect(wrapper.find(".label").attributes("title")).toBe(
            "ATRAMENTA — Encres",
        );
    });
});
