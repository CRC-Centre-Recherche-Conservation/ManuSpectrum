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
                parents: ["europe"],
                count: 4,
                unpublished: true,
            }),
            facetValue("paris", "Paris", { parents: ["france"], count: 3 }),
            facetValue("lille", "Lille", { parents: ["france"], count: 1 }),
            facetValue("italy", "Italie", { parents: ["europe"], count: 1 }),
        ],
        total: 5,
        found: null,
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

    it("starts a row with the unfold button, then the checkbox, in focus order", () => {
        const wrapper = mountTree({});
        const parts = [...wrapper.find(".node .row").element.children];
        expect(parts[0].classList.contains("expander")).toBe(true);
        expect(parts[1].tagName).toBe("LABEL");
        expect(parts[1].querySelector("input[type=checkbox]")).not.toBeNull();
    });

    it("lays a leaf without a button so its checkbox lines up with its siblings", () => {
        const wrapper = mountTree({ expandedByDefault: true });
        const leaf = wrapper.find<HTMLInputElement>('input[value="paris"]');
        const node = leaf.element.closest(".node");
        expect(node?.classList.contains("leaf")).toBe(true);
        expect(node?.querySelector(".row > .expander")).toBeNull();
        expect(
            wrapper
                .find('input[value="france"]')
                .element.closest(".node")
                ?.classList.contains("leaf"),
        ).toBe(false);
    });

    it("reserves the leaf gap only when the tree has a branch", () => {
        expect(mountTree({}).find(".tree").classes()).toContain("has-branches");
        const flat = placeFacet();
        flat.values = [
            facetValue("paris", "Paris", { count: 3 }),
            facetValue("lille", "Lille", { count: 1 }),
        ];
        const wrapper = mountTree({ facet: flat, values: flat.values });
        expect(wrapper.find(".tree").classes()).not.toContain("has-branches");
    });

    it("shows labels and paths whole, with no hover-only title", () => {
        const wrapper = mountTree({});
        expect(
            wrapper.find(".node .label").attributes("title"),
        ).toBeUndefined();
        const flat = mountTree({ query: "par" });
        expect(flat.find(".label").attributes("title")).toBeUndefined();
        expect(flat.find(".path").text()).toBe("Europe — France");
        expect(flat.find(".path").attributes("title")).toBeUndefined();
        expect(flat.find(".node").classes()).toContain("flat");
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
        await box(wrapper, "italy").setValue(true);
        expect(wrapper.emitted("change")?.[0]).toEqual([["france", "italy"]]);
        await box(wrapper, "france").setValue(false);
        expect(wrapper.emitted("change")?.[1]).toEqual([[]]);
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
            facetValue("rome", "Rome", { parents: ["italy"], count: 0 }),
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
        expect(rows[0].find(".path").text()).toBe("Europe — France");
        expect(wrapper.find("button.expander").exists()).toBe(false);
    });

    it("ticks from the flat list", async () => {
        const wrapper = mountTree({ query: "ital" });
        await box(wrapper, "italy").setValue(true);
        expect(wrapper.emitted("change")?.[0]).toEqual([["italy"]]);
    });

    it("a covered value is aria-disabled and says covered by X", () => {
        const wrapper = mountTree({
            selected: ["france"],
            expandedByDefault: true,
        });
        const paris = box(wrapper, "paris");
        expect(paris.attributes("aria-disabled")).toBe("true");
        expect(paris.attributes("disabled")).toBeUndefined();
        const note = wrapper.find(`#${paris.attributes("aria-describedby")}`);
        expect(note.classes()).toContain("covered");
        expect(note.text()).toBe("covered by France");
        expect(box(wrapper, "france").attributes("aria-disabled")).toBe(
            undefined,
        );
        expect(box(wrapper, "italy").attributes("aria-describedby")).toBe(
            undefined,
        );
    });

    it("clicking a covered value emits nothing", async () => {
        const wrapper = mountTree({
            selected: ["france"],
            expandedByDefault: true,
        });
        const paris = box(wrapper, "paris");
        await paris.trigger("click");
        await paris.trigger("change");
        expect(wrapper.emitted("change")).toBeUndefined();
        expect(paris.element.checked).toBe(true);
    });

    it("two ticked ancestors are both named", () => {
        const values = [
            facetValue("blue", "Blue pigment", { narrower: true }),
            facetValue("mineral", "Mineral origin", { narrower: true }),
            facetValue("azurite", "Azurite", {
                parents: ["blue", "mineral"],
            }),
        ];
        const wrapper = mount(FacetTree, {
            props: {
                facet: { ...placeFacet(), key: "material", values },
                values,
                selected: ["mineral", "blue"],
                expandedByDefault: true,
            },
        });
        const notes = wrapper.findAll(".covered");
        expect(notes).toHaveLength(2);
        expect(notes[0].text()).toBe(
            "covered by Blue pigment and Mineral origin",
        );
    });

    it("a value with two parents is drawn twice with distinct list ids", () => {
        const values = [
            facetValue("blue", "Blue pigment"),
            facetValue("mineral", "Mineral origin"),
            facetValue("azurite", "Azurite", {
                parents: ["blue", "mineral"],
            }),
            facetValue("deep", "Deep azurite", { parents: ["azurite"] }),
        ];
        const wrapper = mount(FacetTree, {
            props: {
                facet: { ...placeFacet(), key: "material", values },
                values,
                selected: [],
                expandedByDefault: true,
            },
        });
        const azurites = wrapper.findAll('input[value="azurite"]');
        expect(azurites).toHaveLength(2);
        const lists = wrapper
            .findAll("ul ul ul")
            .map((list) => list.attributes("id"));
        expect(lists).toHaveLength(2);
        expect(new Set(lists).size).toBe(2);
        for (const id of lists) {
            expect(id).toMatch(/^[A-Za-z0-9_-]+$/);
        }
        const controls = wrapper
            .findAll("button.expander")
            .map((button) => button.attributes("aria-controls"));
        expect(new Set(controls).size).toBe(controls.length);
    });

    it("ticks every occurrence of a value with two parents at once", () => {
        const values = [
            facetValue("blue", "Blue pigment"),
            facetValue("mineral", "Mineral origin"),
            facetValue("azurite", "Azurite", {
                parents: ["blue", "mineral"],
            }),
        ];
        const wrapper = mount(FacetTree, {
            props: {
                facet: { ...placeFacet(), key: "material", values },
                values,
                selected: ["azurite"],
            },
        });
        const azurites = wrapper.findAll<HTMLInputElement>(
            'input[value="azurite"]',
        );
        expect(azurites).toHaveLength(2);
        expect(azurites.every((input) => input.element.checked)).toBe(true);
    });

    it("a technique node draws its mark dot and an implied ancestor none", () => {
        const values = [
            facetValue("spectro", "Spectrometry", { narrower: true }),
            facetValue("xrf", "X-ray fluorescence", {
                parents: ["spectro"],
                mark: { code: "XRF", colour: 3, family: "xrf" },
            }),
            facetValue("om", "Optical microscopy", {
                mark: { code: "OM", colour: null, family: "om" },
            }),
        ];
        const wrapper = mount(FacetTree, {
            props: {
                facet: { ...placeFacet(), key: "technique", values },
                values,
                selected: [],
                expandedByDefault: true,
            },
        });
        const row = (id: string) =>
            box(wrapper, id).element.closest(".row") as HTMLElement;
        expect(row("spectro").querySelector(".dot")).toBeNull();
        expect(row("xrf").querySelector(".dot")?.classList).toContain(
            "dot--tech-3",
        );
        expect(row("om").querySelector(".dot")?.classList).toContain(
            "dot--ink",
        );
    });

    it("draws the swatch a value carries", () => {
        const values = [
            facetValue("c1", "Azzurro", { swatch: "royalblue" }),
            facetValue("c2", "Polychrome"),
        ];
        const wrapper = mount(FacetTree, {
            props: {
                facet: { ...placeFacet(), key: "material", values },
                values,
                selected: [],
            },
        });
        expect(wrapper.findAll(".swatch")).toHaveLength(1);
        expect(wrapper.find(".swatch").attributes("style")).toContain(
            "royalblue",
        );
    });

    it("the flat list shows the found values with their paths", () => {
        const values = [
            facetValue("blue", "Blue pigment"),
            facetValue("mineral", "Mineral origin"),
            facetValue("azurite", "Azurite", {
                parents: ["blue", "mineral"],
            }),
            facetValue("lapis", "Lapis lazuli", { parents: ["blue"] }),
        ];
        const wrapper = mount(FacetTree, {
            props: {
                facet: { ...placeFacet(), key: "material", values },
                values,
                selected: [],
                query: "chessylite",
                found: ["azurite"],
            },
        });
        const rows = wrapper.findAll(".flat .node");
        expect(rows).toHaveLength(1);
        expect(rows[0].find(".label").text()).toBe("Azurite");
        const paths = rows[0].findAll(".path");
        expect(paths.map((path) => path.text())).toEqual([
            "Blue pigment",
            "Mineral origin",
        ]);
    });

    it("expandedByDefault opens every node", () => {
        const wrapper = mountTree({ expandedByDefault: true });
        expect(wrapper.findAll("input[type=checkbox]")).toHaveLength(5);
        expect(
            wrapper
                .findAll("button.expander")
                .every(
                    (button) => button.attributes("aria-expanded") === "true",
                ),
        ).toBe(true);
    });

    it("folded, the roots are drawn with their counts and nothing below them", () => {
        const values = [
            facetValue("blue", "Blue pigment", { count: 7 }),
            facetValue("mineral", "Mineral origin", { count: 4 }),
            facetValue("azurite", "Azurite", {
                parents: ["blue", "mineral"],
            }),
        ];
        const wrapper = mount(FacetTree, {
            props: {
                facet: { ...placeFacet(), key: "material", values },
                values,
                selected: [],
            },
        });
        expect(
            wrapper.findAll(".node .label").map((label) => label.text()),
        ).toEqual(["Blue pigment", "Mineral origin"]);
        expect(
            wrapper.findAll(".node .count").map((count) => count.text()),
        ).toEqual(["7", "4"]);
        expect(wrapper.find("ul ul").exists()).toBe(false);
    });

    it("opens the ancestors of a ticked value on every path", () => {
        const values = [
            facetValue("blue", "Blue pigment"),
            facetValue("mineral", "Mineral origin"),
            facetValue("azurite", "Azurite", {
                parents: ["blue", "mineral"],
            }),
        ];
        const wrapper = mount(FacetTree, {
            props: {
                facet: { ...placeFacet(), key: "material", values },
                values,
                selected: ["azurite"],
            },
        });
        expect(wrapper.findAll('input[value="azurite"]')).toHaveLength(2);
    });

    it("keeps a manual fold over the default", async () => {
        const wrapper = mountTree({ expandedByDefault: true });
        const europe = wrapper.find("button.expander");
        await europe.trigger("click");
        expect(europe.attributes("aria-expanded")).toBe("false");
        expect(box(wrapper, "france").exists()).toBe(false);
        await wrapper.setProps({ selected: ["paris"] });
        expect(box(wrapper, "france").exists()).toBe(false);
    });

    it("a node's label carries its lang", () => {
        const values = [
            facetValue("spectro", "Spectrométrie", {
                label: { value: "Spectrométrie", lang: "fr" },
            }),
            facetValue("xrf", "XRF", { parents: ["spectro"] }),
        ];
        const wrapper = mount(FacetTree, {
            props: {
                facet: { ...placeFacet(), key: "technique", values },
                values,
                selected: [],
                expandedByDefault: true,
            },
        });
        const labels = wrapper.findAll(".node .label");
        expect(labels.map((label) => label.attributes("lang"))).toEqual([
            "fr",
            "en",
        ]);
    });
});
