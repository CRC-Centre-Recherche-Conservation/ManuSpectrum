import { describe, expect, it } from "vitest";

import { tagText } from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/layer-tag-text.ts";

import type { TagParts } from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/layer-tags.ts";

const EMPTY: TagParts = {
    symbols: [],
    line: null,
    band: null,
    unit: null,
    index: null,
    contentLabel: { value: "Visible video", lang: "en" },
};

describe("tagText", () => {
    it("writes declared elements with their line", () => {
        expect(tagText({ ...EMPTY, symbols: ["Cu"] })).toBe("Cu");
        expect(
            tagText({
                ...EMPTY,
                symbols: ["Cu"],
                line: { value: "Lα", lang: "en" },
            }),
        ).toBe("Cu Lα");
    });

    it("writes a band value or range with its unit", () => {
        expect(
            tagText({
                ...EMPTY,
                band: { value: 650, lower: null, upper: null },
                unit: "nm",
            }),
        ).toBe("650 nm");
        expect(
            tagText({
                ...EMPTY,
                band: { value: null, lower: 400, upper: 700 },
                unit: "nm",
            }),
        ).toBe("400–700 nm");
    });

    it("writes a component by its content and index, else the content", () => {
        expect(tagText({ ...EMPTY, index: 3 })).toBe("Visible video 3");
        expect(tagText(EMPTY)).toBe("Visible video");
    });
});
