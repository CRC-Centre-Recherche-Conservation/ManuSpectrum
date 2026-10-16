import { describe, expect, it } from "vitest";

import { tagText } from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/layer-tag-text.ts";

import type { TagTranslate } from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/layer-tag-text.ts";
import type { TagParts } from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/layer-tags.ts";

const EMPTY: TagParts = {
    symbols: [],
    line: null,
    band: null,
    unit: null,
    method: null,
    index: null,
    contentLabel: { value: "Visible video", lang: "en" },
};

const TEXT: TagTranslate = {
    $gettext: (msgid) => msgid,
    interpolate: (msgid, values) =>
        msgid.replace(/%\{(\w+)\}/g, (_, key: string) => values[key]),
};

function textOf(parts: Partial<TagParts>): string {
    return tagText({ ...EMPTY, ...parts }, TEXT);
}

describe("tagText", () => {
    it("writes declared elements with their line", () => {
        expect(textOf({ symbols: ["Cu"] })).toBe("Cu");
        expect(
            textOf({ symbols: ["Cu"], line: { value: "Lα", lang: "en" } }),
        ).toBe("Cu Lα");
    });

    it("writes a band value or range with its unit", () => {
        expect(
            textOf({
                band: { value: 650, lower: null, upper: null },
                unit: "nm",
            }),
        ).toBe("650 nm");
        expect(
            textOf({
                band: { value: null, lower: 400, upper: 700 },
                unit: "nm",
            }),
        ).toBe("400–700 nm");
    });

    it("writes a band with only one bound as a lower or upper limit", () => {
        expect(
            textOf({
                band: { value: null, lower: 400, upper: null },
                unit: "nm",
            }),
        ).toBe("≥ 400 nm");
        expect(
            textOf({
                band: { value: null, lower: null, upper: 700 },
                unit: "nm",
            }),
        ).toBe("≤ 700 nm");
    });

    it("writes a band without a unit as its number", () => {
        expect(textOf({ band: { value: 550, lower: null, upper: null } })).toBe(
            "550",
        );
    });

    it("writes a component by its method and index, or as a component without a method", () => {
        expect(textOf({ method: "PCA", index: 3 })).toBe("PCA 3");
        expect(textOf({ index: 3 })).toBe("Component 3");
    });

    it("writes the content's label when nothing else reads", () => {
        expect(textOf({})).toBe("Visible video");
    });
});
