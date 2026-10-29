import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";

import {
    layerOf,
    valueRef,
} from "@/manuspectrum/pages/AnalysisExplorer/testing/fixtures.ts";
import {
    ELEMENT_TINTS,
    NO_TINT,
    RANK_TINTS,
    TINT_CHOICES,
    tintFor,
} from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/stack-tints.ts";

import type { FileLayer } from "@/manuspectrum/pages/AnalysisExplorer/api/types.ts";
import type { StackLayer } from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/light-table.ts";

const CONTENT = valueRef("http://example.org/element-map", "Element map");

function stacked(tint: string | null = null): StackLayer {
    return { canvas: "c", opacity: 100, on: true, tint };
}

function mapped(symbols: string[]): FileLayer {
    return layerOf({
        index: 0,
        content: CONTENT,
        elements: symbols.map((symbol) => ({
            value: valueRef(`http://example.org/el-${symbol}`, symbol),
            symbol,
        })),
    });
}

describe("without layer tiles", () => {
    it("tints by rank, twelve hues going round again", () => {
        const bare = layerOf({ index: 0 });
        expect(tintFor(stacked(), 0, bare)).toBe(RANK_TINTS[0]);
        expect(tintFor(stacked(), 11, bare)).toBe(RANK_TINTS[11]);
        expect(tintFor(stacked(), 12, bare)).toBe(RANK_TINTS[0]);
        expect(tintFor(stacked(), 3, null)).toBe(RANK_TINTS[3]);
    });

    it("has twelve distinct rank hues", () => {
        expect(RANK_TINTS).toHaveLength(12);
        expect(new Set(RANK_TINTS.map((tint) => tint.hex)).size).toBe(12);
    });
});

describe("with some tiles", () => {
    it("takes the element's hue over the rank when the family is one element", () => {
        expect(tintFor(stacked(), 5, mapped(["Cu"]))).toBe(
            ELEMENT_TINTS.get("Cu"),
        );
        expect(tintFor(stacked(), 0, mapped(["Pb"]))).toBe(
            ELEMENT_TINTS.get("Pb"),
        );
    });

    it("falls back on the rank for a composite family or an element without a hue", () => {
        expect(tintFor(stacked(), 2, mapped(["Cu", "Fe"]))).toBe(RANK_TINTS[2]);
        expect(tintFor(stacked(), 2, mapped(["Ti"]))).toBe(RANK_TINTS[2]);
    });

    it("does not tint a band by default", () => {
        const band = layerOf({
            index: 0,
            content: CONTENT,
            band: { value: 650, lower: null, upper: null, unit: null },
        });
        expect(tintFor(stacked(), 1, band)).toBeNull();
    });
});

describe("the reader's choice", () => {
    it("wins over the default, and none means no tint", () => {
        const choice = RANK_TINTS[7];
        expect(tintFor(stacked(choice.key), 0, mapped(["Cu"]))).toBe(choice);
        expect(tintFor(stacked(NO_TINT), 0, mapped(["Cu"]))).toBeNull();
    });

    it("ignores a stored key that no hue has any more", () => {
        expect(tintFor(stacked("gone"), 4, null)).toBe(RANK_TINTS[4]);
    });

    it("offers the twelve rank hues for a palette", () => {
        expect(TINT_CHOICES).toEqual(RANK_TINTS);
    });
});

describe("the tokens", () => {
    const scss = readFileSync(
        `${__dirname}/../../../../../../media/css/_ms-chrome.scss`,
        "utf8",
    );

    it("has a --map-* token of the same colour for every hue", () => {
        const all = [...ELEMENT_TINTS.values(), ...RANK_TINTS];
        expect(all.length).toBe(12 + 12);
        for (const tint of all) {
            expect(scss).toContain(`${tint.token}: ${tint.hex};`);
        }
    });

    it("gives each hue its rgb", () => {
        expect(ELEMENT_TINTS.get("Cu")?.rgb).toEqual([34, 211, 238]);
    });
});
