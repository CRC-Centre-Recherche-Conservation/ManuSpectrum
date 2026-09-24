import { describe, expect, it } from "vitest";
import { mount } from "@vue/test-utils";

import FacetRail from "@/manuspectrum/pages/AnalysisExplorer/views/Corpus/components/FacetRail.vue";

import { facet } from "@/manuspectrum/pages/AnalysisExplorer/testing/fixtures.ts";

describe("FacetRail", () => {
    it("shows the first six values, a selected one past them, and Show all", async () => {
        const technique = facet("technique", 9);
        technique.values[8].selected = true;
        const wrapper = mount(FacetRail, { props: { facets: [technique] } });
        expect(wrapper.find("legend").text()).toBe("Technique");
        expect(wrapper.text()).toContain("at least one of");
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
        part.values[0].selected = true;
        const wrapper = mount(FacetRail, { props: { facets: [part] } });
        await wrapper.findAll("input[type=checkbox]")[2].setValue(true);
        expect(wrapper.emitted("change")?.[0]).toEqual([
            "part",
            ["part-0", "part-2"],
        ]);
        await wrapper.findAll("input[type=checkbox]")[0].setValue(false);
        expect(wrapper.emitted("change")?.[1]).toEqual(["part", []]);
    });
});
