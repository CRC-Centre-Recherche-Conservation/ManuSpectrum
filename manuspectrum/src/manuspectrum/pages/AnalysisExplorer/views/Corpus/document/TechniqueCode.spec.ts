import { mount } from "@vue/test-utils";
import { describe, expect, it } from "vitest";

import TechniqueCode from "@/manuspectrum/pages/AnalysisExplorer/views/Corpus/document/TechniqueCode.vue";

describe("TechniqueCode", () => {
    it("writes the code in its family colour, hidden from assistive technologies", () => {
        const wrapper = mount(TechniqueCode, {
            props: { code: "XRF", colour: 3 },
        });
        expect(wrapper.text()).toBe("XRF");
        expect(wrapper.classes()).toEqual(
            expect.arrayContaining(["technique-code", "code", "code--tech-3"]),
        );
        expect(wrapper.classes()).not.toContain("technique-code--small");
        expect(wrapper.attributes("aria-hidden")).toBe("true");
    });

    it("draws a technique without colour in ink", () => {
        const wrapper = mount(TechniqueCode, {
            props: { code: "LDMS", colour: null },
        });
        expect(wrapper.classes()).toContain("code--ink");
    });

    it("draws the small chip of the legend", () => {
        const wrapper = mount(TechniqueCode, {
            props: { code: "XRF", colour: 1, size: "small" },
        });
        expect(wrapper.classes()).toContain("technique-code--small");
    });

    it("lets assistive technologies read a code that is not decorative", () => {
        const wrapper = mount(TechniqueCode, {
            props: { code: "XRF", colour: 1, decorative: false },
        });
        expect(wrapper.attributes("aria-hidden")).toBeUndefined();
    });
});
