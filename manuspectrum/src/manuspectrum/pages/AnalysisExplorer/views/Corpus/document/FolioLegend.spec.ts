import { mount } from "@vue/test-utils";
import { createPinia, setActivePinia } from "pinia";
import { beforeEach, describe, expect, it } from "vitest";

import FolioLegend from "@/manuspectrum/pages/AnalysisExplorer/views/Corpus/document/FolioLegend.vue";

import { useExplorerStore } from "@/manuspectrum/pages/AnalysisExplorer/store/explorer.ts";
import { label } from "@/manuspectrum/pages/AnalysisExplorer/testing/fixtures.ts";

const ENTRIES = [
    { key: "t:xrf", code: "XRF", colour: 1, label: label("XRF"), count: 4 },
    {
        key: "t:dye",
        code: "D",
        colour: null,
        label: label("Dye test"),
        count: 1,
    },
];

beforeEach(() => {
    setActivePinia(createPinia());
});

describe("FolioLegend", () => {
    it("lists each technique with its code, colour and count", () => {
        useExplorerStore().setLegendOpen(true);
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
        expect(rows[0].find(".code").text()).toBe("XRF");
        expect(rows[0].find(".code").classes()).toContain("code--tech-1");
        expect(rows[1].find(".code").classes()).toContain("code--ink");
    });

    it("starts folded and keeps its state in the store for the next page", async () => {
        const wrapper = mount(FolioLegend, {
            props: { entries: ENTRIES },
            attachTo: document.body,
        });
        const toggle = wrapper.find(".toggle");
        expect(toggle.attributes("aria-expanded")).toBe("false");
        expect(wrapper.find(".entries").isVisible()).toBe(false);
        await toggle.trigger("click");
        expect(toggle.attributes("aria-expanded")).toBe("true");
        expect(wrapper.find(".entries").isVisible()).toBe(true);
        wrapper.unmount();

        const next = mount(FolioLegend, { props: { entries: ENTRIES } });
        expect(next.find(".toggle").attributes("aria-expanded")).toBe("true");
        expect(useExplorerStore().legendOpen).toBe(true);
    });

    it("is absent when the page draws no analysis", () => {
        const wrapper = mount(FolioLegend, { props: { entries: [] } });
        expect(wrapper.find(".folio-legend").exists()).toBe(false);
    });
});
