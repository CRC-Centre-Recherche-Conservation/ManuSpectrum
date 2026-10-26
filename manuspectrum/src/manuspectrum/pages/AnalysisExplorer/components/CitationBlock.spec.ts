import { enableAutoUnmount, flushPromises, mount } from "@vue/test-utils";
import PrimeVue from "primevue/config";
import { afterEach, describe, expect, it } from "vitest";

import CitationBlock from "@/manuspectrum/pages/AnalysisExplorer/components/CitationBlock.vue";
import CopyButton from "@/manuspectrum/pages/AnalysisExplorer/components/CopyButton.vue";

import { analysisPayload } from "@/manuspectrum/pages/AnalysisExplorer/testing/fixtures.ts";

import type { Citation } from "@/manuspectrum/pages/AnalysisExplorer/api/types.ts";

enableAutoUnmount(afterEach);

function citation(overrides: Partial<Citation> = {}): Citation {
    return { ...analysisPayload().citation, ...overrides };
}

function mountBlock(given: Citation) {
    return mount(CitationBlock, {
        props: { citation: given },
        global: { plugins: [PrimeVue] },
    });
}

describe("CitationBlock", () => {
    it("shows the text citation first, as text", () => {
        const wrapper = mountBlock(
            citation({ text: "Heu, S. <b>Parchment</b>" }),
        );

        const tabs = wrapper.findAll("[role=tab]");
        expect(tabs.map((tab) => tab.text())).toEqual(["Text", "BibTeX"]);
        expect(tabs[0].attributes("aria-selected")).toBe("true");
        const text = wrapper.find(".text");
        expect(text.text()).toBe("Heu, S. <b>Parchment</b>");
        expect(text.find("b").exists()).toBe(false);
    });

    it("has one copy button that copies the form shown", async () => {
        const given = citation();
        const wrapper = mountBlock(given);

        const copies = () => wrapper.findAllComponents(CopyButton);
        expect(copies()).toHaveLength(1);
        expect(copies()[0].props()).toMatchObject({
            text: given.text,
            label: "Copy the citation",
        });

        await wrapper.findAll("[role=tab]")[1].trigger("click");
        await flushPromises();

        expect(wrapper.find("pre.bibtex").text()).toBe(given.bibtex.trim());
        expect(copies()).toHaveLength(1);
        expect(copies()[0].props()).toMatchObject({
            text: given.bibtex,
            label: "Copy BibTeX",
        });
    });

    it("offers no RIS or CSL-JSON form", () => {
        const wrapper = mountBlock(citation());

        expect(wrapper.text()).not.toMatch(/RIS|CSL/);
    });
});
