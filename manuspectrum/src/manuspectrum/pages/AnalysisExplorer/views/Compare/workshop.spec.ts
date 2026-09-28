// @vitest-environment node
//
// Reads the parity fixtures from disk: jsdom's URL would not reach
// `fileURLToPath`, and nothing here touches the DOM.
import fs from "fs";
import { fileURLToPath } from "url";
import { describe, expect, it } from "vitest";

import {
    dashOf,
    extent,
    neutraliseText,
    offsetLifts,
    outOfRange,
    panelGrid,
    ranksInSlot,
    sharedViews,
    symbolOf,
    treat,
    workshopCsv,
} from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/workshop.ts";

interface ParityCase {
    config: { presetKey: string };
    expected: { x: number[]; y: number[]; x_reversed: boolean };
}

const CASES: ParityCase[] = JSON.parse(
    fs.readFileSync(
        fileURLToPath(
            new URL(
                "../../../../../../../tests/fixtures/xy/parity/cases.json",
                import.meta.url,
            ),
        ),
        "utf-8",
    ),
);

interface FormulaCase {
    text: string;
    safe: string;
}

const FORMULA_CASES: FormulaCase[] = JSON.parse(
    fs.readFileSync(
        fileURLToPath(
            new URL(
                "../../../../../../../tests/fixtures/csv/formula-cells.json",
                import.meta.url,
            ),
        ),
        "utf-8",
    ),
).cases;

function parity(presetKey: string): ParityCase["expected"] {
    const found = CASES.find((entry) => entry.config.presetKey === presetKey);
    if (!found) throw new Error(`no parity case for ${presetKey}`);
    return found.expected;
}

function keys(presetKeys: (string | null)[]): string[] {
    return sharedViews(presetKeys).views.map((view) => view.key);
}

describe("workshop", () => {
    it("dashes the 2nd, 3rd… file of a slot, the first solid", () => {
        const ranks = ranksInSlot([0, 0, 1, 0, 1]);
        expect(ranks).toEqual([0, 1, 0, 2, 1]);
        expect(ranks.map(dashOf)).toEqual([
            "solid",
            "dash",
            "solid",
            "dot",
            "dash",
        ]);
    });

    it("gives each of the thirty slots its own marker shape, filled then open", () => {
        const symbols = Array.from({ length: 30 }, (_, slot) => symbolOf(slot));
        expect(new Set(symbols).size).toBe(30);
        expect(symbols.slice(0, 3)).toEqual(["circle", "square", "diamond"]);
        expect(symbols[15]).toBe("circle-open");
    });

    it("measures a range in one pass, past the arguments limit of a spread", () => {
        const values = Array.from({ length: 136_805 }, (_, index) => index);
        values[5] = Number.NaN;
        expect(extent(values)).toEqual({
            min: 0,
            max: 136_804,
            count: 136_804,
        });
        expect(extent([Number.NaN])).toBeNull();
    });

    it("offers the treatments of a preset, base first", () => {
        expect(keys(["xrf"])).toEqual(["base", "normalize-max"]);
        expect(keys(["fors"])).toEqual([
            "base",
            "log-inverse-r",
            "kubelka-munk",
            "derivative-1",
            "derivative-2",
        ]);
        expect(sharedViews(["fors", "fors"]).mixed).toBe(false);
    });

    it("offers only the treatments shared by mixed presets", () => {
        expect(sharedViews(["ftir_reflection", "fors"])).toMatchObject({
            mixed: true,
        });
        expect(keys(["ftir_reflection", "fors"])).toEqual([
            "base",
            "log-inverse-r",
            "kubelka-munk",
        ]);
        expect(keys(["xrf", null])).toEqual(["base"]);
    });

    it("applies a treatment of xy-views to a parity series", () => {
        const fors = parity("fors");
        const [, pseudoAbsorbance] = sharedViews(["fors"]).views;
        const treated = treat(fors.x, fors.y, pseudoAbsorbance);
        treated.forEach((value, index) =>
            expect(value).toBeCloseTo(Math.log10(1 / fors.y[index]), 12),
        );
        const xrf = parity("xrf");
        const [, normaliseMax] = sharedViews(["xrf"]).views;
        expect(extent(treat(xrf.x, xrf.y, normaliseMax))?.max).toBe(1);
    });

    it("leaves the values as they are under the base view", () => {
        const xrf = parity("xrf");
        const [base] = sharedViews(["xrf"]).views;
        expect(treat(xrf.x, xrf.y, base)).toBe(xrf.y);
    });

    it("lifts each offset curve above the one before it, a tenth of the widest span apart", () => {
        expect(
            offsetLifts([
                { min: 10, max: 15, count: 2 },
                { min: 0, max: 2, count: 2 },
                null,
                { min: -1, max: 1, count: 2 },
            ]),
        ).toEqual([0, 15.5, 15.5, 19]);
        expect(
            offsetLifts([
                { min: 3, max: 3, count: 1 },
                { min: 3, max: 3, count: 1 },
            ]),
        ).toEqual([0, 1]);
    });

    it("flags a curve whose X range meets no other", () => {
        expect(
            outOfRange([
                { min: 0, max: 10, count: 2 },
                { min: 5, max: 20, count: 2 },
                { min: 30, max: 40, count: 2 },
                null,
            ]),
        ).toEqual([false, false, true, false]);
        expect(outOfRange([{ min: 0, max: 1, count: 2 }])).toEqual([false]);
    });

    it("lays small multiples out on at most four columns", () => {
        expect(panelGrid(1)).toEqual({ rows: 1, columns: 1 });
        expect(panelGrid(9)).toEqual({ rows: 3, columns: 3 });
        expect(panelGrid(30)).toEqual({ rows: 8, columns: 4 });
    });

    it("neutralises curator text as the Explorer's series CSV does", () => {
        expect(FORMULA_CASES.length).toBeGreaterThan(0);
        for (const { text, safe } of FORMULA_CASES) {
            expect(neutraliseText(text)).toBe(safe);
        }
    });

    it("writes one pair of columns per curve after a byte order mark, neutralising curator text", () => {
        const csv = workshopCsv(
            [
                { label: "A1 · a;=cmd.csv", x: [1, 2], y: [0.5, Number.NaN] },
                { label: 'A2 · b,"c".csv', x: [3], y: [-4] },
            ],
            "Energy (keV)",
            "Counts",
        );
        expect(csv.startsWith("\ufeff")).toBe(true);
        expect(csv.slice(1).split("\r\n")).toEqual([
            "A1 · a;'=cmd.csv · Energy (keV),A1 · a;'=cmd.csv · Counts," +
                `"A2 · b,'c'.csv · Energy (keV)","A2 · b,'c'.csv · Counts"`,
            "1,0.5,3,-4",
            "2,,,",
            "",
        ]);
        expect(
            workshopCsv([{ label: " =A1", x: [], y: [] }], "x", "y")
                .slice(1)
                .split("\r\n")[0],
        ).toBe("'=A1 · x,'=A1 · y");
    });
});
