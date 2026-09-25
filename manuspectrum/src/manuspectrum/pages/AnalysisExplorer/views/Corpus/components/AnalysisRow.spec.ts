import { mount } from "@vue/test-utils";
import { describe, expect, it } from "vitest";

import AnalysisRow from "@/manuspectrum/pages/AnalysisExplorer/views/Corpus/components/AnalysisRow.vue";

import {
    analysisHit,
    label,
    technique,
    uuid,
} from "@/manuspectrum/pages/AnalysisExplorer/testing/fixtures.ts";

const FORS = technique(
    "http://example.org/fors",
    "Fibre optic reflectance spectroscopy",
    2,
    uuid(901),
    "FORS",
);

function mountRow(overrides = {}) {
    return mount(AnalysisRow, {
        props: {
            hit: analysisHit(1, {
                technique: FORS,
                component: {
                    id: uuid(2),
                    model: "component",
                    name: label("Initial P"),
                },
                ...overrides,
            }),
        },
    });
}

describe("AnalysisRow", () => {
    it("heads the result with the analysis name", () => {
        const wrapper = mountRow();
        expect(wrapper.find("h3").text()).toBe("MS1_f12_XRF_03");
    });

    it("gives the technique as meta with its dot, code and label", () => {
        const tag = mountRow().find(".meta .technique-tag");
        expect(tag.find(".dot").classes()).toContain("dot--tech-2");
        expect(tag.find(".code").text()).toBe("FORS");
        expect(tag.find(".name").text()).toBe(
            "Fibre optic reflectance spectroscopy",
        );
    });

    it("then the document, the part, the date and the data kinds", () => {
        const wrapper = mountRow();
        expect(wrapper.find(".where").text()).toContain("Manuscript 1");
        expect(wrapper.find(".where").text()).toContain("Initial P");
        expect(wrapper.find(".where").text()).toContain("2023-05");
        expect(wrapper.find(".badges").text()).toContain("spectrum");
    });

    it("has no technique meta for an analysis without technique", () => {
        const wrapper = mountRow({ technique: null });
        expect(wrapper.find(".technique-tag").exists()).toBe(false);
        expect(wrapper.find("h3").text()).toBe("MS1_f12_XRF_03");
    });

    it("asks to open the analysis from its heading", async () => {
        const wrapper = mountRow();
        await wrapper.find("h3 .link").trigger("click");
        expect(wrapper.emitted("open")).toHaveLength(1);
    });
});
