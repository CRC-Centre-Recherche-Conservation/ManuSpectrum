import { mount } from "@vue/test-utils";
import { describe, expect, it } from "vitest";

import FolioLegend from "@/manuspectrum/pages/AnalysisExplorer/views/Corpus/document/FolioLegend.vue";

import { label } from "@/manuspectrum/pages/AnalysisExplorer/testing/fixtures.ts";

const ENTRIES = [
    { key: "t:xrf", code: "X", colour: 1, label: label("XRF"), count: 4 },
    {
        key: "t:dye",
        code: "D",
        colour: null,
        label: label("Dye test"),
        count: 1,
    },
];

describe("FolioLegend", () => {
    it("lists each technique with its code, colour and count", () => {
        const wrapper = mount(FolioLegend, { props: { entries: ENTRIES } });
        const rows = wrapper.findAll("li");
        expect(rows.map((row) => row.find(".name").text())).toEqual([
            "XRF",
            "Dye test",
        ]);
        expect(rows.map((row) => row.find(".count").text())).toEqual([
            "4",
            "1",
        ]);
        expect(rows[0].find(".code").classes()).toContain("code--tech-1");
        expect(rows[1].find(".code").classes()).toContain("code--ink");
    });

    it("folds to its title and opens again", async () => {
        const wrapper = mount(FolioLegend, {
            props: { entries: ENTRIES },
            attachTo: document.body,
        });
        const toggle = wrapper.find(".toggle");
        expect(toggle.attributes("aria-expanded")).toBe("true");
        await toggle.trigger("click");
        expect(toggle.attributes("aria-expanded")).toBe("false");
        expect(wrapper.find(".entries").isVisible()).toBe(false);
        await toggle.trigger("click");
        expect(wrapper.find(".entries").isVisible()).toBe(true);
        wrapper.unmount();
    });

    it("starts folded when asked", () => {
        const wrapper = mount(FolioLegend, {
            props: { entries: ENTRIES, startOpen: false },
        });
        expect(wrapper.find(".toggle").attributes("aria-expanded")).toBe(
            "false",
        );
    });

    it("is absent when the page draws no analysis", () => {
        const wrapper = mount(FolioLegend, { props: { entries: [] } });
        expect(wrapper.find(".folio-legend").exists()).toBe(false);
    });
});
