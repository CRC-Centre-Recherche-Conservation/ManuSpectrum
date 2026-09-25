import { mount } from "@vue/test-utils";
import { describe, expect, it } from "vitest";

import TechniqueTag from "@/manuspectrum/pages/AnalysisExplorer/components/TechniqueTag.vue";

describe("TechniqueTag", () => {
    it("draws the family colour dot and the code", () => {
        const wrapper = mount(TechniqueTag, {
            props: { code: "pXRF", colour: 3 },
        });
        expect(wrapper.find(".dot").classes()).toContain("dot--tech-3");
        expect(wrapper.find(".dot").attributes("aria-hidden")).toBe("true");
        expect(wrapper.find(".code").text()).toBe("pXRF");
        expect(wrapper.find(".name").exists()).toBe(false);
    });

    it("draws a technique without colour in ink", () => {
        const wrapper = mount(TechniqueTag, {
            props: { code: "LDMS", colour: null },
        });
        expect(wrapper.find(".dot").classes()).toContain("dot--ink");
    });

    it("writes the label in its own language when given", () => {
        const wrapper = mount(TechniqueTag, {
            props: {
                code: "XRF",
                colour: 1,
                label: { value: "Fluorescence X", lang: "fr" },
            },
        });
        const name = wrapper.find(".name");
        expect(name.text()).toBe("Fluorescence X");
        expect(name.attributes("lang")).toBe("fr");
    });
});
