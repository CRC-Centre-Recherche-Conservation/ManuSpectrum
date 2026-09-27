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
    offsetStep,
    outOfRange,
    panelGrid,
    ranksInSlot,
    sharedViews,
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

    it("steps offset curves by the widest span", () => {
        expect(
            offsetStep([
                { min: 0, max: 2, count: 2 },
                { min: 10, max: 15, count: 2 },
                null,
            ]),
        ).toBe(5);
        expect(offsetStep([{ min: 3, max: 3, count: 1 }])).toBe(1);
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

    it("writes one pair of columns per curve, neutralising curator text", () => {
        const csv = workshopCsv(
            [
                { label: "A1 · =cmd.csv", x: [1, 2], y: [0.5, Number.NaN] },
                { label: 'A2 · b "c".csv', x: [3], y: [-4] },
            ],
            "Energy (keV)",
            "Counts [normalised to max]",
        );
        expect(csv.split("\r\n")).toEqual([
            "A1 · =cmd.csv · Energy (keV),A1 · =cmd.csv · Counts [normalised to max]," +
                '"A2 · b ""c"".csv · Energy (keV)","A2 · b ""c"".csv · Counts [normalised to max]"',
            "1,0.5,3,-4",
            "2,,,",
            "",
        ]);
        expect(
            workshopCsv([{ label: "=A1", x: [], y: [] }], "x", "y").split(
                "\r\n",
            )[0],
        ).toBe("'=A1 · x,'=A1 · y");
    });
});
