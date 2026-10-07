import { describe, expect, it } from "vitest";
import { mount } from "@vue/test-utils";

import FacetTree from "@/manuspectrum/pages/AnalysisExplorer/views/Corpus/components/FacetTree.vue";

import { facetValue } from "@/manuspectrum/pages/AnalysisExplorer/testing/fixtures.ts";

import type { Facet } from "@/manuspectrum/pages/AnalysisExplorer/api/types.ts";

function placeFacet(): Facet {
    return {
        key: "place",
        group: "document",
        values: [
            facetValue("europe", "Europe", { count: 5 }),
            facetValue("france", "France", {
                parent: "europe",
                count: 4,
                unpublished: true,
            }),
            facetValue("paris", "Paris", { parent: "france", count: 3 }),
            facetValue("lille", "Lille", { parent: "france", count: 1 }),
            facetValue("italy", "Italie", { parent: "europe", count: 1 }),
        ],
        total: 5,
    };
}

function mountTree(props: Partial<InstanceType<typeof FacetTree>["$props"]>) {
    const facet = placeFacet();
    return mount(FacetTree, {
        props: { facet, values: facet.values, selected: [], ...props },
    });
}

function box(wrapper: ReturnType<typeof mount>, id: string) {
    return wrapper.find<HTMLInputElement>(`input[value="${id}"]`);
}

describe("FacetTree", () => {
    it("shows only the roots when nothing is ticked, with their counts", () => {
        const wrapper = mountTree({});
        expect(wrapper.findAll("input[type=checkbox]")).toHaveLength(1);
        expect(wrapper.find(".node .label").text()).toBe("Europe");
        expect(wrapper.find(".node .count").text()).toBe("5");
        expect(wrapper.find("[role=tree]").exists()).toBe(false);
    });

    it("unfolds a node with its button, naming what it controls", async () => {
        const wrapper = mountTree({});
        const toggle = wrapper.find("button.expander");
        expect(toggle.attributes("aria-expanded")).toBe("false");
        await toggle.trigger("click");
        expect(toggle.attributes("aria-expanded")).toBe("true");
        expect(box(wrapper, "france").exists()).toBe(true);
        expect(box(wrapper, "paris").exists()).toBe(false);
        expect(toggle.attributes("aria-controls")).toBe(
            wrapper.find("ul ul").attributes("id"),
        );
        await toggle.trigger("click");
        expect(box(wrapper, "france").exists()).toBe(false);
    });

    it("has no unfold button on a leaf", async () => {
        const wrapper = mountTree({ expandedByDefault: true });
        expect(wrapper.findAll("button.expander")).toHaveLength(2);
        expect(wrapper.find("li.leaf button.expander").exists()).toBe(false);
    });

    it("opens the ancestors of a ticked place and marks them mixed", () => {
        const wrapper = mountTree({ selected: ["paris"] });
        expect(box(wrapper, "paris").element.checked).toBe(true);
        expect(box(wrapper, "paris").element.indeterminate).toBe(false);
        expect(box(wrapper, "france").element.indeterminate).toBe(true);
        expect(box(wrapper, "france").element.checked).toBe(false);
        expect(box(wrapper, "europe").element.indeterminate).toBe(true);
        expect(box(wrapper, "italy").exists()).toBe(true);
        expect(box(wrapper, "lille").exists()).toBe(true);
    });

    it("shows the children of a ticked parent as implicit: pale tick, still native", async () => {
        const wrapper = mountTree({
            selected: ["france"],
            expandedByDefault: true,
        });
        expect(box(wrapper, "france").element.checked).toBe(true);
        const paris = box(wrapper, "paris");
        expect(paris.element.checked).toBe(true);
        expect(paris.element.indeterminate).toBe(false);
        expect(paris.element.closest("li")?.classList).toContain("implicit");
        expect(
            box(wrapper, "france").element.closest("li")?.classList,
        ).not.toContain("implicit");
    });

    it("emits the ticks after a click", async () => {
        const wrapper = mountTree({
            selected: ["france"],
            expandedByDefault: true,
        });
        await box(wrapper, "paris").setValue(false);
        expect(wrapper.emitted("change")?.[0]).toEqual([["lille"]]);
        await box(wrapper, "italy").setValue(true);
        expect(wrapper.emitted("change")?.[1]).toEqual([["france", "italy"]]);
    });

    it("shows the unpublished badge of a Draft place", () => {
        const wrapper = mountTree({ expandedByDefault: true });
        const badges = wrapper.findAll(".unpublished");
        expect(badges).toHaveLength(1);
        expect(badges[0].text()).toBe("unpublished");
    });

    it("disables a place with no hit unless it or an ancestor is ticked", () => {
        const facet = placeFacet();
        facet.values.push(
            facetValue("rome", "Rome", { parent: "italy", count: 0 }),
        );
        const wrapper = mountTree({
            facet,
            values: facet.values,
            expandedByDefault: true,
        });
        expect(box(wrapper, "rome").attributes("disabled")).toBeDefined();
        expect(box(wrapper, "paris").attributes("disabled")).toBeUndefined();
    });

    it("lists the matches flat with their path while a query is typed", () => {
        const wrapper = mountTree({ query: "par" });
        const rows = wrapper.findAll(".flat .node");
        expect(rows).toHaveLength(1);
        expect(rows[0].find(".label").text()).toBe("Paris");
        expect(rows[0].find(".path").text()).toBe("France — Europe");
        expect(wrapper.find("button.expander").exists()).toBe(false);
    });

    it("ticks from the flat list", async () => {
        const wrapper = mountTree({ query: "ital" });
        await box(wrapper, "italy").setValue(true);
        expect(wrapper.emitted("change")?.[0]).toEqual([["italy"]]);
    });
});
