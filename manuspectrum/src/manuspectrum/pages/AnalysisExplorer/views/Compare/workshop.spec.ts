// @vitest-environment node
//
// Reads the parity fixtures from disk: jsdom's URL would not reach
// `fileURLToPath`, and nothing here touches the DOM.
import fs from "fs";
import { fileURLToPath } from "url";
import { describe, expect, it } from "vitest";

import {
    curvePaint,
    curveState,
    dashArray,
    dashOf,
    endPoint,
    extent,
    hoverModeFor,
    neutraliseText,
    offsetLifts,
    openingLayout,
    outOfRange,
    panelGrid,
    panelSpacing,
    patchHoverInfo,
    ranksInSlot,
    restyleUpdate,
    sharedViews,
    spreadLabels,
    treat,
    slipZoom,
    undoZoom,
    workshopCsv,
    zoomedAfter,
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
    it("reads a zoom from a relayout: ranges set zoom, autoranges reset, the rest changes nothing", () => {
        expect(
            zoomedAfter({ "xaxis.range[0]": 1, "xaxis.range[1]": 2 }, false),
        ).toBe(true);
        expect(zoomedAfter({ "yaxis3.range": [0, 1] }, false)).toBe(true);
        expect(zoomedAfter({ "xaxis.autorange": true }, true)).toBe(false);
        expect(
            zoomedAfter(
                { "xaxis2.autorange": "reversed", "yaxis2.autorange": true },
                true,
            ),
        ).toBe(false);
        expect(zoomedAfter({ "annotations[0].opacity": 0.2 }, true)).toBe(true);
        expect(zoomedAfter({ "annotations[0].opacity": 0.2 }, false)).toBe(
            false,
        );
        expect(zoomedAfter(null, true)).toBe(true);
    });

    it("reads a zoom box narrower than 20 px on an axis it zooms as a press that slipped", () => {
        const before = {
            xaxis: {
                range: [100, 1997] as const,
                autorange: true,
                length: 440,
            },
            yaxis: {
                range: [-360, 11227] as const,
                autorange: true,
                length: 288,
            },
        };
        const slipped = {
            "xaxis.range[0]": 240.7,
            "xaxis.range[1]": 280.1,
            "yaxis.range[0]": 2635.1,
            "yaxis.range[1]": 3045.3,
        };
        expect(slipZoom(slipped, before)).toBe(true);
        expect(
            slipZoom({ "xaxis.range[0]": 668, "xaxis.range[1]": 1231 }, before),
        ).toBe(false);
        expect(slipZoom({ "yaxis.range": [4811.2, 4813.2] }, before)).toBe(
            true,
        );
        expect(slipZoom({ "xaxis.autorange": true }, before)).toBe(false);
        expect(slipZoom({ "annotations[0].opacity": 0 }, before)).toBe(false);
        expect(
            slipZoom({ "xaxis2.range[0]": 1, "xaxis2.range[1]": 2 }, before),
        ).toBe(false);
        expect(slipZoom(null, before)).toBe(false);
    });

    it("puts back the axes a slipped zoom moved: on autorange when they followed their data, else on their range", () => {
        const before = {
            xaxis: {
                range: [2000, 100] as const,
                autorange: true,
                length: 440,
            },
            yaxis: { range: [0, 5] as const, autorange: false, length: 288 },
            xaxis2: { range: [0, 1] as const, autorange: true, length: 200 },
        };
        expect(
            undoZoom(
                {
                    "xaxis.range[0]": 1366,
                    "xaxis.range[1]": 1367,
                    "yaxis.range[0]": 1,
                    "yaxis.range[1]": 1.01,
                },
                before,
            ),
        ).toEqual({
            "xaxis.autorange": "reversed",
            "yaxis.range": [0, 5],
        });
    });

    it("dashes the 2nd, 3rd… file of a slot with short dashes, the first solid", () => {
        const ranks = ranksInSlot([0, 0, 1, 0, 1, 0, 0, 0]);
        expect(ranks).toEqual([0, 1, 0, 2, 1, 3, 4, 5]);
        expect(ranks.map(dashOf)).toEqual([
            "solid",
            "6px,2px",
            "solid",
            "2px,2px",
            "6px,2px",
            "10px,2px,2px,2px",
            "14px,3px",
            "solid",
        ]);
    });

    it("draws a dash as an SVG dash array, none for a solid line", () => {
        expect(dashArray("solid")).toBe("");
        expect(dashArray("10px,2px,2px,2px")).toBe("10 2 2 2");
    });

    it("draws A1…A8 in colour and the later slots as grey context, emphasised in ink", () => {
        const palette = {
            series: ["#111", "#222"],
            context: "#999",
            ink: "#000",
        };
        expect(curvePaint(palette, 1, "plain")).toEqual({
            colour: "#222",
            width: 1.5,
            opacity: 1,
            hover: true,
        });
        expect(curvePaint(palette, 9, "plain")).toEqual({
            colour: "#999",
            width: 1.25,
            opacity: 1,
            hover: true,
        });
        expect(curvePaint(palette, 0, "emphasised")).toMatchObject({
            colour: "#111",
            width: 2.5,
            opacity: 1,
        });
        expect(curvePaint(palette, 9, "emphasised")).toMatchObject({
            colour: "#000",
            width: 2.5,
        });
        expect(curvePaint(palette, 9, "hidden")).toEqual({
            colour: "#999",
            width: 1.25,
            opacity: 0,
            hover: false,
        });
    });

    it("hides the curves the selection does not link, shows them all without a selection, and a preview wins", () => {
        expect(curveState(null, false, false)).toBe("plain");
        expect(curveState(null, true, false)).toBe("hidden");
        expect(curveState("evidence", true, false)).toBe("emphasised");
        expect(curveState(null, true, true)).toBe("emphasised");
        expect(curveState(null, false, true)).toBe("emphasised");
    });

    it("dims an unrelated curve instead of hiding it when the workshop's switch asks to, a preview and a link still winning", () => {
        expect(curveState(null, true, false, true)).toBe("dimmed");
        expect(curveState("direct", true, false, true)).toBe("emphasised");
        expect(curveState(null, true, true, true)).toBe("emphasised");
        expect(curveState(null, false, false, true)).toBe("plain");
    });

    it("draws a dimmed curve in grey context at reduced opacity, out of the hover", () => {
        const palette = {
            series: ["#111", "#222"],
            context: "#999",
            ink: "#000",
        };
        expect(curvePaint(palette, 0, "dimmed")).toEqual({
            colour: "#999",
            width: 1.25,
            opacity: 0.35,
            hover: false,
        });
        expect(curvePaint(palette, 9, "dimmed")).toEqual({
            colour: "#999",
            width: 1.25,
            opacity: 0.35,
            hover: false,
        });
    });

    it("gathers the paints into one restyle of style attributes, in trace order", () => {
        const update = restyleUpdate([
            { colour: "#111", width: 1.5, opacity: 1, hover: true },
            { colour: "#999", width: 1.25, opacity: 0, hover: false },
        ]);
        expect(update).toEqual({
            opacity: [1, 0],
            "line.color": ["#111", "#999"],
            "line.width": [1.5, 1.25],
            hoverinfo: ["all", "skip"],
        });
    });

    it("patches Plotly's stale calc-data trace with the hoverinfo a style-only restyle set, in trace order", () => {
        const calcdata = [
            [{ trace: { hoverinfo: "all" } }],
            [{ trace: { hoverinfo: "all" } }],
        ];
        patchHoverInfo(calcdata, [
            { colour: "#111", width: 1.5, opacity: 0, hover: false },
            { colour: "#222", width: 1.5, opacity: 1, hover: true },
        ]);
        expect(calcdata[0][0].trace.hoverinfo).toBe("skip");
        expect(calcdata[1][0].trace.hoverinfo).toBe("all");
    });

    it("does nothing when the chart holds no calc data yet, or a row lacks a trace", () => {
        expect(() => patchHoverInfo(undefined, [])).not.toThrow();
        const calcdata = [[]];
        expect(() =>
            patchHoverInfo(calcdata, [
                { colour: "#111", width: 1.5, opacity: 1, hover: true },
            ]),
        ).not.toThrow();
    });

    it("finds where a curve ends on screen, the smallest X on a reversed axis", () => {
        const x = [400, 500, 900, Number.NaN];
        const y = [1, 2, 3, 4];
        expect(endPoint(x, y, false)).toEqual({ x: 900, y: 3 });
        expect(endPoint(x, y, true)).toEqual({ x: 400, y: 1 });
        expect(endPoint([1], [Number.NaN], false)).toBeNull();
    });

    it("spreads labels at least 12 px apart around where they want to be, keeping their order", () => {
        expect(spreadLabels([100, 50], 12)).toEqual([100, 50]);
        expect(spreadLabels([100, 104], 12)).toEqual([96, 108]);
        expect(spreadLabels([10, 10, 10], 12)).toEqual([-2, 10, 22]);
        expect(spreadLabels([0, 4, 200], 12, { min: 0, max: 300 })).toEqual([
            0, 12, 200,
        ]);
    });

    it("opens on small multiples above eight curves, or when no slot is in colour", () => {
        expect(openingLayout(8, [0, 1, 2])).toBe("overlay");
        expect(openingLayout(9, [0, 1, 2])).toBe("multiples");
        expect(openingLayout(2, [8, 9])).toBe("multiples");
        expect(openingLayout(1, [9])).toBe("overlay");
    });

    it("hovers along X up to six curves, the closest curve beyond", () => {
        expect(hoverModeFor(6)).toBe("x unified");
        expect(hoverModeFor(7)).toBe("closest");
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

    it("lays small multiples out on at most four columns, each at least 220 px wide", () => {
        expect(panelGrid(1)).toEqual({ rows: 1, columns: 1 });
        expect(panelGrid(9)).toEqual({ rows: 3, columns: 3 });
        expect(panelGrid(30)).toEqual({ rows: 8, columns: 4 });
        expect(panelGrid(30, 700)).toEqual({ rows: 10, columns: 3 });
        expect(panelGrid(4, 200)).toEqual({ rows: 4, columns: 1 });
    });

    it("spaces the panels in pixels, 46 px down so a panel's X tick labels clear the title of the panel below, each at least 110 px high", () => {
        expect(panelSpacing({ rows: 2, columns: 2 }, 488, 400)).toEqual({
            xgap: 44 / 244,
            ygap: 46 / 200,
            height: 400,
        });
        expect(panelSpacing({ rows: 4, columns: 1 }, 300, 200)).toEqual({
            xgap: 0,
            ygap: 46 / 144.5,
            height: 4 * 110 + 3 * 46,
        });
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
            "The values drawn, = offset left out",
        );
        expect(csv.startsWith("\ufeff")).toBe(true);
        expect(csv.slice(1).split("\r\n")).toEqual([
            "# The values drawn,' = offset left out",
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
