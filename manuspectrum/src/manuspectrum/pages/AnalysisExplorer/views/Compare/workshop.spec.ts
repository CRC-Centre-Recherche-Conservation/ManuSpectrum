// @vitest-environment node
//
// Reads the parity fixtures from disk: jsdom's URL would not reach
// `fileURLToPath`, and nothing here touches the DOM.
import fs from "fs";
import { fileURLToPath } from "url";
import { describe, expect, it } from "vitest";

import {
    curveLook,
    itemClasses,
    itemCycle,
    itemHue,
    itemMarker,
    curveColourVar,
    curvePaint,
    curveState,
    dashArray,
    endPoint,
    extent,
    hoverModeFor,
    neutraliseText,
    offsetLifts,
    openingLayout,
    outOfRange,
    panelGrid,
    panelSpacing,
    ranksInSlot,
    restyleUpdate,
    sharedViews,
    spreadLabels,
    treat,
    slipZoom,
    undoZoom,
    visibleCurveCount,
    workshopCsv,
    RANGE_PRESETS,
    rangeUpdate,
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

    it("ranks the files of a slot in order of arrival", () => {
        expect(ranksInSlot([0, 0, 1, 0, 1, 0, 0, 0])).toEqual([
            0, 1, 0, 2, 1, 3, 4, 5,
        ]);
    });

    it("draws a dash as an SVG dash array, none for a solid line", () => {
        expect(dashArray("solid")).toBe("");
        expect(dashArray("6px,2px")).toBe("6 2");
    });

    it("gives an item one hue by its slot, cycling the twelve, and its cycle selects solid / dashed / dotted and filled / ring / ring with a dot", () => {
        expect(itemHue(0)).toBe(0);
        expect(itemHue(11)).toBe(11);
        expect(itemHue(12)).toBe(0);
        expect(itemHue(24)).toBe(0);
        expect([0, 12, 24].map(itemCycle)).toEqual([0, 1, 2]);
        expect([0, 11, 12, 24].map(itemMarker)).toEqual([
            "filled",
            "filled",
            "ring",
            "ring-dot",
        ]);
        expect(itemClasses(12)).toBe("slot-1 item-ring");
    });

    it("draws the 13th curve of a window in the first hue, dashed, then the 25th dotted, whatever the slots", () => {
        const thirteenth = { order: 12 };
        expect(curveLook(thirteenth, "plain")).toEqual({
            kind: "series",
            hue: 0,
            dash: "6px,2px",
        });
        expect(curveLook({ order: 24 }, "plain")).toEqual({
            kind: "series",
            hue: 0,
            dash: "2px,2px",
        });
        expect(itemClasses(12)).toBe("slot-1 item-ring");
        expect(curveLook({ order: 0 }, "plain")).toEqual({
            kind: "series",
            hue: 0,
            dash: "solid",
        });
    });

    const PALETTE = {
        series: Array.from({ length: 12 }, (_, index) => `#s${index}`),
        context: "#999",
    };

    it("paints every curve in its item's hue at 1.5 px, never grey or a fallback ink, whatever its slot", () => {
        expect(curvePaint(PALETTE, { order: 1 }, "plain")).toEqual({
            colour: "#s1",
            dash: "solid",
            width: 1.5,
            opacity: 1,
            hover: true,
        });
        // The 13th item (slot 12): hue wraps to the 1st series colour, dash to the 2nd variant.
        expect(curvePaint(PALETTE, { order: 12 }, "plain")).toEqual({
            colour: "#s0",
            dash: "6px,2px",
            width: 1.5,
            opacity: 1,
            hover: true,
        });
        expect(curvePaint(PALETTE, { order: 12 }, "hidden")).toEqual({
            colour: "#s0",
            dash: "6px,2px",
            width: 1.5,
            opacity: 0,
            hover: false,
        });
    });

    it("thickens an emphasised curve without changing its colour or dash: the focus never recolours a curve", () => {
        expect(curvePaint(PALETTE, { order: 5 }, "emphasised")).toEqual({
            colour: "#s5",
            dash: "solid",
            width: 2.5,
            opacity: 1,
            hover: true,
        });
        expect(curveLook({ order: 5 }, "emphasised")).toEqual(
            curveLook({ order: 5 }, "plain"),
        );
    });

    it("looks up a curve's own CSS var for the legend's swatch, resolved to the theme's hex for a Plotly trace", () => {
        const seriesLook = curveLook({ order: 1 }, "plain");
        expect(curveColourVar(seriesLook)).toBe("var(--series-2)");
        const dimmedLook = curveLook({ order: 1 }, "dimmed");
        expect(curveColourVar(dimmedLook)).toBe("var(--series-context)");
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

    it("draws a dimmed curve in grey context at reduced opacity, out of the hover, even one a pin would otherwise light", () => {
        expect(curvePaint(PALETTE, { order: 0 }, "dimmed")).toEqual({
            colour: "#999",
            dash: "solid",
            width: 1.25,
            opacity: 0.35,
            hover: false,
        });
        expect(curvePaint(PALETTE, { order: 12 }, "dimmed")).toEqual({
            colour: "#999",
            dash: "6px,2px",
            width: 1.25,
            opacity: 0.35,
            hover: false,
        });
    });

    it("gathers the paints into one restyle of style attributes, in trace order", () => {
        const update = restyleUpdate([
            {
                colour: "#111",
                dash: "solid",
                width: 1.5,
                opacity: 1,
                hover: true,
            },
            {
                colour: "#999",
                dash: "6px,2px",
                width: 1.25,
                opacity: 0,
                hover: false,
            },
        ]);
        expect(update).toEqual({
            opacity: [1, 0],
            "line.color": ["#111", "#999"],
            "line.width": [1.5, 1.25],
            "line.dash": ["solid", "6px,2px"],
            hoverinfo: ["all", "skip"],
        });
    });

    it("carries the hovertemplates along when given, one per trace", () => {
        const paints = [
            {
                colour: "#111",
                dash: "solid" as const,
                width: 1.5,
                opacity: 0,
                hover: false,
            },
        ];
        expect(restyleUpdate(paints, [""]).hovertemplate).toEqual([""]);
        expect(restyleUpdate(paints)).not.toHaveProperty("hovertemplate");
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

    it("opens on small multiples above eight curves, overlay at or under", () => {
        expect(openingLayout(8)).toBe("overlay");
        expect(openingLayout(9)).toBe("multiples");
        // No longer special-cased: every curve is its own hue now, so a
        // window with few curves in high slots stays overlay too.
        expect(openingLayout(2)).toBe("overlay");
    });

    it("hovers along X up to twelve curves currently answering hover, the closest curve beyond", () => {
        expect(hoverModeFor(12)).toBe("x unified");
        expect(hoverModeFor(13)).toBe("closest");
    });

    it("counts only the plain and emphasised curves for the hover cap: hidden and dimmed answer no hover", () => {
        expect(
            visibleCurveCount(["plain", "emphasised", "hidden", "dimmed"]),
        ).toBe(2);
        expect(visibleCurveCount([])).toBe(0);
        expect(visibleCurveCount(["plain", "plain"])).toBe(2);
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
    it("lays an energy range as a relayout of the first X axis, which the small-multiples axes follow, and counts it as a zoom", () => {
        const [full, wide, ...windows] = RANGE_PRESETS;
        expect(RANGE_PRESETS.map((preset) => preset.key)).toEqual([
            "full",
            "0-25",
            "1-5",
            "5-15",
        ]);
        expect(rangeUpdate(wide)).toEqual({ "xaxis.range": [0, 25] });
        expect(rangeUpdate(windows[0], true)).toEqual({
            "xaxis.range": [5, 1],
        });
        expect(zoomedAfter(rangeUpdate(windows[1]), false)).toBe(true);
        expect(rangeUpdate(full)).toEqual({ "xaxis.autorange": true });
        expect(rangeUpdate(full, true)).toEqual({
            "xaxis.autorange": "reversed",
        });
        expect(zoomedAfter(rangeUpdate(full), true)).toBe(false);
    });
});
