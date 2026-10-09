import { mount } from "@vue/test-utils";
import { createPinia, setActivePinia } from "pinia";
import { beforeEach, describe, expect, it } from "vitest";

import AnalysisRow from "@/manuspectrum/pages/AnalysisExplorer/views/Corpus/components/AnalysisRow.vue";

import { analysisKey } from "@/manuspectrum/pages/AnalysisExplorer/selection/entries.ts";
import { useExplorerStore } from "@/manuspectrum/pages/AnalysisExplorer/store/explorer.ts";
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

beforeEach(() => {
    setActivePinia(createPinia());
});

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

    it("puts the Selection checkbox before the title, named by the analysis", () => {
        const wrapper = mountRow();
        const input = wrapper.get(".selection-checkbox input");
        expect(input.attributes("aria-label")).toBe(
            "Add MS1_f12_XRF_03 to the Selection",
        );
        const html = wrapper.html();
        expect(html.indexOf("selection-checkbox")).toBeLessThan(
            html.indexOf("<h3"),
        );
    });

    it("keeps the title a separate button: the checkbox does not open the analysis", async () => {
        const wrapper = mountRow();
        await wrapper.get(".selection-checkbox input").setValue(true);
        expect(wrapper.emitted("open")).toBeUndefined();
        expect(wrapper.find("h3 .link").exists()).toBe(true);
    });

    it("adds the analysis under its own key and tints the row with its slot", async () => {
        const wrapper = mountRow();
        const store = useExplorerStore();
        await wrapper.get(".selection-checkbox input").setValue(true);
        expect(store.basket.map((item) => item.key)).toEqual([
            analysisKey(wrapper.props("hit").id),
        ]);
        expect(wrapper.classes()).toContain("held");
        expect(wrapper.get(".selection-checkbox .slot").text()).toBe("A1");
        expect(
            wrapper.get(".selection-checkbox input").attributes("aria-label"),
        ).toBe("Remove MS1_f12_XRF_03 from the Selection");
    });

    it("follows the store when the Selection changes elsewhere", async () => {
        const wrapper = mountRow();
        const store = useExplorerStore();
        store.addToBasket(analysisKey(wrapper.props("hit").id));
        await wrapper.vm.$nextTick();
        expect(wrapper.classes()).toContain("held");
        store.$patch((state) => {
            state.basket = [];
        });
        await wrapper.vm.$nextTick();
        expect(wrapper.classes()).not.toContain("held");
    });
});
