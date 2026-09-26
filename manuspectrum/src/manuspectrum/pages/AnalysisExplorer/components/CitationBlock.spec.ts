import { mount } from "@vue/test-utils";
import { describe, expect, it } from "vitest";

import CitationBlock from "@/manuspectrum/pages/AnalysisExplorer/components/CitationBlock.vue";
import CopyButton from "@/manuspectrum/pages/AnalysisExplorer/components/CopyButton.vue";

import { analysisPayload } from "@/manuspectrum/pages/AnalysisExplorer/testing/fixtures.ts";

import type { Citation } from "@/manuspectrum/pages/AnalysisExplorer/api/types.ts";

function citation(overrides: Partial<Citation> = {}): Citation {
    return { ...analysisPayload().citation, ...overrides };
}

describe("CitationBlock", () => {
    it("shows the recommended text as text", () => {
        const wrapper = mount(CitationBlock, {
            props: {
                citation: citation({ recommended: "Heu, S. <b>Parchment</b>" }),
            },
        });

        const text = wrapper.find(".recommended");
        expect(text.text()).toBe("Heu, S. <b>Parchment</b>");
        expect(text.find("b").exists()).toBe(false);
    });

    it("copies BibTeX, RIS, CSL-JSON and the availability statement", () => {
        const given = citation();
        const wrapper = mount(CitationBlock, { props: { citation: given } });

        const copied = Object.fromEntries(
            wrapper
                .findAllComponents(CopyButton)
                .map((button) => [button.props("label"), button.props("text")]),
        );
        expect(copied).toEqual({
            "Copy the citation": given.recommended,
            "Copy BibTeX": given.bibtex,
            "Copy RIS": given.ris,
            "Copy CSL-JSON": JSON.stringify(given.csl, null, 2),
            "Copy the data availability statement": given.availability,
        });
    });
});
