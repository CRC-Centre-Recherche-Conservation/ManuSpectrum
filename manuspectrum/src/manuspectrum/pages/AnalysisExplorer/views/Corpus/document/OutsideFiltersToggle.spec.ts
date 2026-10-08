import { mount } from "@vue/test-utils";
import { describe, expect, it } from "vitest";

import OutsideFiltersToggle from "@/manuspectrum/pages/AnalysisExplorer/views/Corpus/document/OutsideFiltersToggle.vue";

function mountToggle(shown: boolean, hiddenCount = 3) {
    return mount(OutsideFiltersToggle, { props: { shown, hiddenCount } });
}

describe("OutsideFiltersToggle", () => {
    it("is a switch named with the number of analyses outside the filters", () => {
        const wrapper = mountToggle(true, 4);
        const control = wrapper.find("button");
        expect(control.attributes("role")).toBe("switch");
        expect(control.text()).toContain("Analyses outside the filters (4)");
    });

    it("adds the identified materials outside the filters, alone when no analysis is", () => {
        const both = mount(OutsideFiltersToggle, {
            props: { shown: true, hiddenCount: 2, hiddenMaterials: 3 },
        });
        expect(both.find("button").text()).toContain(
            "Analyses outside the filters (2) · 3 identified materials",
        );
        const alone = mount(OutsideFiltersToggle, {
            props: { shown: true, hiddenCount: 0, hiddenMaterials: 1 },
        });
        expect(alone.find("button").text()).toContain(
            "Outside the filters: 1 identified material",
        );
    });

    it("reports the state it shows", () => {
        expect(
            mountToggle(true).find("button").attributes("aria-checked"),
        ).toBe("true");
        expect(
            mountToggle(false).find("button").attributes("aria-checked"),
        ).toBe("false");
    });

    it("asks for the opposite state when pressed", async () => {
        const shown = mountToggle(true);
        await shown.find("button").trigger("click");
        expect(shown.emitted("change")).toEqual([[false]]);
        const hidden = mountToggle(false);
        await hidden.find("button").trigger("click");
        expect(hidden.emitted("change")).toEqual([[true]]);
    });

    it("draws an open eye when shown and a crossed one when hidden", () => {
        const open = mountToggle(true).find("svg path").attributes("d");
        const crossed = mountToggle(false).find("svg path").attributes("d");
        expect(open).not.toBe(crossed);
    });
});
