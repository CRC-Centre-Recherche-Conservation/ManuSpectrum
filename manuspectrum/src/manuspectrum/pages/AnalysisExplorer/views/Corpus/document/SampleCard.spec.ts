import { mount } from "@vue/test-utils";
import { createPinia, setActivePinia } from "pinia";
import { describe, expect, it } from "vitest";

import SampleCard from "@/manuspectrum/pages/AnalysisExplorer/views/Corpus/document/SampleCard.vue";

import { useExplorerStore } from "@/manuspectrum/pages/AnalysisExplorer/store/explorer.ts";
import {
    label,
    sample,
    uuid,
} from "@/manuspectrum/pages/AnalysisExplorer/testing/fixtures.ts";

import type { SampleSummary } from "@/manuspectrum/pages/AnalysisExplorer/api/types.ts";

function mountCard(overrides: Partial<SampleSummary> = {}) {
    const pinia = createPinia();
    setActivePinia(pinia);
    const wrapper = mount(SampleCard, {
        props: {
            sample: sample(1, {
                analyses: [uuid(101), uuid(102)],
                ...overrides,
            }),
            analysisNames: new Map([[uuid(101), label("X01 — f. 1v")]]),
        },
        global: { plugins: [pinia] },
    });
    return { wrapper, store: useExplorerStore() };
}

describe("SampleCard", () => {
    it("names the sample and counts the analyses made on it", () => {
        const { wrapper } = mountCard();
        expect(wrapper.find("h3").text()).toBe("Sample 1");
        expect(wrapper.text()).toContain("Analyses on this sample (2)");
        expect(
            wrapper.findAll(".analyses button").map((button) => button.text()),
        ).toEqual(["X01 — f. 1v", "Analysis 2"]);
    });

    it("marks a draft sample", () => {
        const { wrapper } = mountCard({ unpublished: true });
        expect(wrapper.find(".badge.draft").text()).toBe("Draft");
    });

    it("opens an analysis of the sample on the analyses view", async () => {
        const { wrapper, store } = mountCard();
        store.openDocument(uuid(1));
        store.focusOn({ kind: "sample", id: uuid(601) });
        await wrapper.findAll(".analyses button")[1].trigger("click");
        expect(store.focus).toEqual({ kind: "analysis", id: uuid(102) });
        expect(store.folioView).toBe("analyses");
    });

    it("emits close from its close button", async () => {
        const { wrapper } = mountCard();
        await wrapper.find(".close").trigger("click");
        expect(wrapper.emitted("close")).toHaveLength(1);
    });

    it("says when no analysis of this document used the sample", () => {
        const { wrapper } = mountCard({ analyses: [] });
        expect(wrapper.text()).toContain("Analyses on this sample (0)");
        expect(wrapper.find(".analyses button").exists()).toBe(false);
    });
});
