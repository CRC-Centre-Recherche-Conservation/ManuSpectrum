import { describe, expect, it } from "vitest";
import { mount } from "@vue/test-utils";
import PrimeVue from "primevue/config";

import FacetRail from "@/manuspectrum/pages/AnalysisExplorer/views/Corpus/components/FacetRail.vue";

import {
    facet,
    label,
} from "@/manuspectrum/pages/AnalysisExplorer/testing/fixtures.ts";

import type { Facet } from "@/manuspectrum/pages/AnalysisExplorer/api/types.ts";

function mountRail(props: InstanceType<typeof FacetRail>["$props"]) {
    return mount(FacetRail, { props, global: { plugins: [PrimeVue] } });
}

function checkedIds(wrapper: ReturnType<typeof mount>): string[] {
    return wrapper
        .findAll<HTMLInputElement>("input[type=checkbox]")
        .filter((input) => input.element.checked)
        .map((input) => input.attributes("value") ?? "");
}

describe("FacetRail", () => {
    it("shows the first six values, a selected one past them, and Show all", async () => {
        const technique = facet("technique", 9);
        const wrapper = mountRail({
            facets: [technique],
            selected: { technique: ["technique-8"] },
        });
        expect(wrapper.find("legend").text()).toBe("Technique");
        expect(wrapper.text()).not.toContain("at least one of");
        expect(wrapper.findAll("input[type=checkbox]")).toHaveLength(7);
        const more = wrapper.find(".more");
        expect(more.text()).toBe("Show all (9)");
        expect(more.attributes("aria-expanded")).toBe("false");
        await more.trigger("click");
        expect(wrapper.findAll("input[type=checkbox]")).toHaveLength(9);
        expect(wrapper.find(".more").text()).toBe("Show fewer");
    });

    it("emits the next selection of a facet", async () => {
        const part = facet("part", 3);
        const wrapper = mountRail({
            facets: [part],
            selected: { part: ["part-0"] },
        });
        await wrapper.findAll("input[type=checkbox]")[2].setValue(true);
        expect(wrapper.emitted("change")?.[0]).toEqual([
            "part",
            ["part-0", "part-2"],
        ]);
        await wrapper.findAll("input[type=checkbox]")[0].setValue(false);
        expect(wrapper.emitted("change")?.[1]).toEqual(["part", []]);
    });

    it("keeps a first tick when a second one comes before the facets reload", async () => {
        const technique = facet("technique", 3);
        const wrapper = mountRail({ facets: [technique], selected: {} });
        await wrapper.findAll("input[type=checkbox]")[0].setValue(true);
        // The store holds the first tick; the server's facets are still the old ones.
        await wrapper.setProps({ selected: { technique: ["technique-0"] } });
        expect(checkedIds(wrapper)).toEqual(["technique-0"]);
        await wrapper.findAll("input[type=checkbox]")[1].setValue(true);
        expect(wrapper.emitted("change")?.[1]).toEqual([
            "technique",
            ["technique-0", "technique-1"],
        ]);
    });

    it("checks what the filters hold, not what the last payload said", () => {
        const colour = facet("colour", 2);
        colour.values[1].selected = true;
        const wrapper = mountRail({
            facets: [colour],
            selected: { colour: ["colour-0"] },
        });
        expect(checkedIds(wrapper)).toEqual(["colour-0"]);
    });

    it("filters a long facet by a search box, ignoring accents and case", async () => {
        const part: Facet = facet("part", 12);
        part.values[10].label = label("Initiale « É » ornée");
        const wrapper = mountRail({
            facets: [part, facet("colour", 3)],
            selected: {},
        });
        const boxes = wrapper.findAll("input[type=search]");
        expect(boxes).toHaveLength(1);
        await boxes[0].setValue("ORNÉE");
        expect(
            wrapper.findAll(".facet")[0].findAll("input[type=checkbox]"),
        ).toHaveLength(1);
        expect(wrapper.findAll(".facet")[0].text()).toContain(
            "Initiale « É » ornée",
        );
        await boxes[0].setValue("zzz");
        expect(wrapper.findAll(".facet")[0].text()).toContain("No match");
    });

    it("puts a colour dot on the colour names it knows and none on others", () => {
        const colour: Facet = {
            key: "colour",
            values: [
                { id: "c1", label: label("Bleu"), count: 2, selected: false },
                {
                    id: "c2",
                    label: label("Polychrome"),
                    count: 1,
                    selected: false,
                },
            ],
        };
        const wrapper = mountRail({ facets: [colour], selected: {} });
        const rows = wrapper.findAll(".value");
        expect(rows[0].find(".swatch").exists()).toBe(true);
        expect(rows[1].find(".swatch").exists()).toBe(false);
    });

    it("gives each technique the folio colour it is drawn in", () => {
        const technique = facet("technique", 2);
        const wrapper = mountRail({
            facets: [technique],
            selected: {},
            techniqueColours: new Map([
                ["technique-0", 3],
                ["technique-1", null],
            ]),
        });
        const rows = wrapper.findAll(".value");
        expect(rows[0].find(".dot").classes()).toContain("dot--tech-3");
        expect(rows[1].find(".dot").classes()).toContain("dot--ink");
    });

    it("keeps the whole label for a label cut on screen", () => {
        const project: Facet = {
            key: "project",
            values: [
                {
                    id: "p1",
                    label: label(
                        "ATRAMENTA — Encres ferrogalliques et carbonées",
                    ),
                    count: 2,
                    selected: false,
                },
            ],
        };
        const wrapper = mountRail({ facets: [project], selected: {} });
        expect(wrapper.find(".value .label").attributes("title")).toBe(
            "ATRAMENTA — Encres ferrogalliques et carbonées",
        );
    });
});
