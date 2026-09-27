import { describe, expect, it } from "vitest";

import { placeholderWindows } from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/windows.ts";

import type { BasketItem } from "@/manuspectrum/pages/AnalysisExplorer/store/types.ts";

const ANALYSIS = "00000000-0000-4000-8000-000000000001";
const FILE = "00000000-0000-4000-8000-000000000002";

function item(key: string, kind: BasketItem["kind"], slot: number): BasketItem {
    return { key, kind, slot };
}

describe("placeholderWindows", () => {
    it("is empty for an empty Selection", () => {
        expect(placeholderWindows([])).toEqual([]);
    });

    it("gives one window per kind of item, with stable ids and the items in slot order", () => {
        const spectrum = `af:${ANALYSIS}:${FILE}`;
        const material = `ch:${ANALYSIS}:-`;
        const layer = `im:${ANALYSIS}:1`;
        const whole = `an:${ANALYSIS}:-`;
        const other = `af:${FILE}:${ANALYSIS}`;
        expect(
            placeholderWindows([
                item(layer, "imaging", 4),
                item(other, "analysis-file", 3),
                item(material, "characterization", 2),
                item(whole, "analysis", 1),
                item(spectrum, "analysis-file", 0),
            ]),
        ).toEqual([
            { id: "auto:xy:all", kind: "xy", keys: [spectrum, other] },
            { id: "auto:micro", kind: "micro", keys: [whole] },
            {
                id: "auto:characterizations",
                kind: "characterizations",
                keys: [material],
            },
            { id: "auto:not-in-chart", kind: "not-in-chart", keys: [layer] },
        ]);
    });
});
