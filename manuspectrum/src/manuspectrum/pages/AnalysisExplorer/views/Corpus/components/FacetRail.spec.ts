import { beforeEach, describe, expect, it } from "vitest";
import { mount } from "@vue/test-utils";
import { createPinia, setActivePinia } from "pinia";
import PrimeVue from "primevue/config";

import FacetRail from "@/manuspectrum/pages/AnalysisExplorer/views/Corpus/components/FacetRail.vue";

import { useExplorerStore } from "@/manuspectrum/pages/AnalysisExplorer/store/explorer.ts";
import {
    facet,
    facetValue,
    label,
} from "@/manuspectrum/pages/AnalysisExplorer/testing/fixtures.ts";

import type { Facet } from "@/manuspectrum/pages/AnalysisExplorer/api/types.ts";

function mountRail(props: InstanceType<typeof FacetRail>["$props"]) {
    return mount(FacetRail, { props, global: { plugins: [PrimeVue] } });
}

beforeEach(() => {
    setActivePinia(createPinia());
});

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

    it("checks what the filters hold", () => {
        const colour = facet("colour", 2);
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

    it("draws the swatch the server gives a colour and none without one", () => {
        const colour: Facet = {
            key: "colour",
            group: "characterization",
            values: [
                facetValue("c1", "Azzurro", { swatch: "royalblue" }),
                facetValue("c2", "Polychrome"),
            ],
            total: 2,
        };
        const wrapper = mountRail({ facets: [colour], selected: {} });
        const rows = wrapper.findAll(".value");
        expect(rows[0].find(".swatch").attributes("style")).toContain(
            "royalblue",
        );
        expect(rows[1].find(".swatch").exists()).toBe(false);
    });

    it("gives each technique the colour of its mark", () => {
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
        const wrapper = mountRail({ facets: [technique], selected: {} });
        const rows = wrapper.findAll(".value");
        expect(rows[0].find(".dot").classes()).toContain("dot--tech-3");
        expect(rows[1].find(".dot").classes()).toContain("dot--ink");
    });

    it("shows the part, analysis and identified material groups in that order, each folding", async () => {
        const wrapper = mountRail({
            facets: [
                facet("material", 1),
                facet("technique", 1),
                facet("partType", 1),
            ],
            selected: {},
        });
        const titles = wrapper.findAll(".group-title button");
        expect(titles.map((title) => title.text())).toEqual([
            "▾Studied part",
            "▾Analysis",
            "▾Identified material",
        ]);
        expect(titles[1].attributes("aria-expanded")).toBe("true");
        await titles[1].trigger("click");
        expect(useExplorerStore().collapsedGroups).toEqual(["analysis"]);
        expect(titles[1].attributes("aria-expanded")).toBe("false");
        const body = wrapper.find(`#${titles[1].attributes("aria-controls")}`);
        expect(body.isVisible()).toBe(false);
    });

    it("shows one Colour facet whose toggle picks the level the ticks apply to", async () => {
        const wrapper = mountRail({
            facets: [facet("partColour", 2), facet("colour", 3)],
            selected: { partColour: ["partColour-1"] },
        });
        expect(wrapper.findAll(".facet")).toHaveLength(1);
        expect(wrapper.find(".facet legend").text()).toBe("Colour");
        const levels = wrapper.findAll(".level-button");
        expect(
            levels.map((level) => level.find(".level-label").text()),
        ).toEqual(["Part", "Analysis"]);
        expect(levels[1].attributes("aria-pressed")).toBe("true");
        expect(wrapper.findAll(".value")).toHaveLength(3);
        expect(levels[0].find(".ticks").text()).toBe("1");
        const hint = wrapper.find(
            `#${levels[0].attributes("aria-describedby")}`,
        );
        expect(hint.text()).toBe(
            "Colours described on the studied part, even without analysis",
        );

        await levels[0].trigger("click");

        expect(useExplorerStore().colourLevel).toBe("partColour");
        expect(wrapper.findAll(".value")).toHaveLength(2);
        expect(
            wrapper.findAll<HTMLInputElement>(".value input")[1].element
                .checked,
        ).toBe(true);
        await wrapper.findAll(".value input")[0].setValue(true);
        expect(wrapper.emitted("change")?.[0]).toEqual([
            "partColour",
            ["partColour-1", "partColour-0"],
        ]);
    });

    it("names the ticked values and their colour level on the facet title", () => {
        const wrapper = mountRail({
            facets: [facet("partColour", 2), facet("colour", 2)],
            selected: { partColour: ["partColour-0"], colour: ["colour-1"] },
        });
        const fieldset = wrapper.find(".facet");
        const summary = wrapper.find(
            `#${fieldset.attributes("aria-describedby")}`,
        );
        expect(summary.text()).toBe(
            "Selection: partColour 0 (seen on the part) · colour 1 (identified by analysis)",
        );
        expect(fieldset.find(".title-text").attributes("tabindex")).toBe("0");
    });

    it("keeps the whole label for a label cut on screen", () => {
        const project: Facet = {
            key: "project",
            group: "analysis",
            values: [
                facetValue(
                    "p1",
                    "ATRAMENTA — Encres ferrogalliques et carbonées",
                ),
            ],
            total: 1,
        };
        const wrapper = mountRail({ facets: [project], selected: {} });
        expect(wrapper.find(".value .label").attributes("title")).toBe(
            "ATRAMENTA — Encres ferrogalliques et carbonées",
        );
    });
});
