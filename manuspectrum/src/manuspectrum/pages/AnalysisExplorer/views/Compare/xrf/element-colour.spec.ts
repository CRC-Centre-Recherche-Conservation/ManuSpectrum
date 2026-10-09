import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";

import {
    ELEMENT_HUES,
    PIGMENT_HUES,
    elementColour,
    elementHue,
} from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/xrf/element-colour.ts";
import { ELEMENT_FALLBACKS } from "@/manuspectrum/pages/AnalysisExplorer/xy/plot-theme.ts";

const CHROME = readFileSync(
    `${__dirname}/../../../../../../../media/css/_ms-chrome.scss`,
    "utf8",
);

/** Elements that share a pigment or a line region: each pair must tell apart by colour. */
const PAIRS: [string, string][] = [
    ["Pb", "Sn"],
    ["Pb", "Sb"],
    ["Pb", "Hg"],
    ["Pb", "S"],
    ["Pb", "As"],
    ["Pb", "Bi"],
    ["Cu", "As"],
    ["Cu", "Zn"],
    ["Cu", "Co"],
    ["Cu", "Pb"],
    ["Cu", "Fe"],
    ["S", "Cl"],
    ["Hg", "S"],
    ["Ca", "Ti"],
    ["Ca", "K"],
    ["Ba", "Ti"],
    ["Ba", "Ca"],
    ["Fe", "Mn"],
    ["Fe", "Co"],
    ["Fe", "Cr"],
    ["Cr", "Ba"],
    ["Sn", "Sb"],
    ["Sn", "Cd"],
    ["Cd", "Ag"],
    ["Ag", "Cl"],
    ["Au", "Hg"],
    ["Au", "Pb"],
    ["Au", "Ag"],
    ["Zn", "Cd"],
    ["Al", "Si"],
    ["Se", "Hg"],
    ["Se", "Cd"],
    ["Sr", "Ca"],
    ["Sr", "Ba"],
    ["As", "Hg"],
    ["Mn", "Cr"],
    ["Co", "Zn"],
    ["Sb", "Cd"],
    ["Bi", "Au"],
    ["Cl", "K"],
    ["Sn", "Ag"],
    ["Fe", "Zn"],
    ["Mn", "Ba"],
    ["Cd", "S"],
    ["Hg", "Cl"],
    ["Sr", "Cr"],
    ["Au", "Sn"],
    ["Ba", "Se"],
];

/** Smallest OKLab distance (×100) between the two colours of a pair. */
const MIN_DELTA_E = 10;

function oklab(hex: string): [number, number, number] {
    const [r, g, b] = [1, 3, 5].map((at) =>
        channel(parseInt(hex.slice(at, at + 2), 16)),
    );
    const l = Math.cbrt(0.4122214708 * r + 0.5363325363 * g + 0.0514459929 * b);
    const m = Math.cbrt(0.2119034982 * r + 0.6806995451 * g + 0.1073969566 * b);
    const s = Math.cbrt(0.0883024619 * r + 0.2817188376 * g + 0.6299787005 * b);
    return [
        0.2104542553 * l + 0.793617785 * m - 0.0040720468 * s,
        1.9779984951 * l - 2.428592205 * m + 0.4505937099 * s,
        0.0259040371 * l + 0.7827717662 * m - 0.808675766 * s,
    ];
}

function deltaE(one: string, other: string): number {
    const [a, b] = [oklab(one), oklab(other)];
    return 100 * Math.hypot(a[0] - b[0], a[1] - b[1], a[2] - b[2]);
}

function channel(value: number): number {
    const unit = value / 255;
    return unit <= 0.04045 ? unit / 12.92 : ((unit + 0.055) / 1.055) ** 2.4;
}

function luminance(hex: string): number {
    const [r, g, b] = [1, 3, 5].map((at) =>
        channel(parseInt(hex.slice(at, at + 2), 16)),
    );
    return 0.2126 * r + 0.7152 * g + 0.0722 * b;
}

function contrast(one: string, other: string): number {
    const [high, low] = [luminance(one), luminance(other)].sort(
        (a, b) => b - a,
    );
    return (high + 0.05) / (low + 0.05);
}

describe("elementHue", () => {
    it("gives every pair of elements that travel together a hue of its own", () => {
        for (const [one, other] of PAIRS) {
            expect(elementHue(one), `${one}/${other}`).not.toBe(
                elementHue(other),
            );
        }
    });

    it("gives every pair colours at least 10 apart in OKLab, not just two palette slots", () => {
        for (const [one, other] of PAIRS) {
            expect(
                deltaE(
                    ELEMENT_FALLBACKS[elementHue(one)],
                    ELEMENT_FALLBACKS[elementHue(other)],
                ),
                `${one}/${other}`,
            ).toBeGreaterThanOrEqual(MIN_DELTA_E);
        }
    });

    it("keeps the ten first common elements on ten different hues", () => {
        const ten = ["Pb", "Fe", "Ca", "Cu", "Hg", "Zn", "K", "S", "Ag", "Au"];
        expect(new Set(ten.map(elementHue)).size).toBe(10);
    });

    it("depends on the element alone, never on the others drawn", () => {
        expect(elementHue("Hg")).toBe(elementHue("Hg"));
        expect(elementHue("Na")).toBe(11 % ELEMENT_HUES);
    });

    it("stays inside the palette for any symbol, known or not", () => {
        for (const symbol of ["U", "Na", "Xx", ""]) {
            expect(elementHue(symbol)).toBeGreaterThanOrEqual(0);
            expect(elementHue(symbol)).toBeLessThan(ELEMENT_HUES);
        }
        for (const hue of Object.values(PIGMENT_HUES)) {
            expect(hue).toBeLessThan(ELEMENT_HUES);
        }
    });
});

describe("elementColour", () => {
    it("reads the theme's palette, ink when it has none", () => {
        const element = Array.from(
            { length: ELEMENT_HUES },
            (_, i) => `#e${i}`,
        );
        expect(elementColour({ element, ink: "#000" }, "Fe")).toBe("#e1");
        expect(elementColour({ element: [], ink: "#000" }, "Fe")).toBe("#000");
    });
});

describe("the element palette", () => {
    it("holds one fallback per hue, equal to the tokens of the stylesheet", () => {
        expect(ELEMENT_FALLBACKS).toHaveLength(ELEMENT_HUES);
        ELEMENT_FALLBACKS.forEach((colour, index) => {
            expect(CHROME).toContain(`--element-${index + 1}: ${colour};`);
        });
    });

    it("reads as text at 4.5:1 on the page and on a white surface", () => {
        for (const colour of ELEMENT_FALLBACKS) {
            expect(contrast(colour, "#ffffff"), colour).toBeGreaterThanOrEqual(
                4.5,
            );
            expect(contrast(colour, "#faf9f7"), colour).toBeGreaterThanOrEqual(
                4.5,
            );
        }
    });
});
