// @vitest-environment node
import { describe, expect, it } from "vitest";

import {
    annotationOpacities,
    autorangeX,
    endLabelsFor,
    exportFigure,
    hoverTemplatesFor,
    multiplesFigure,
    panelWidths,
    stackedFigure,
    yFitUpdate,
} from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/workshop-figure.ts";

import type {
    FigureCurve,
    FigureInput,
} from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/workshop-figure.ts";
import type { CurvePaint } from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/workshop.ts";
import type { PlotTheme } from "@/manuspectrum/pages/AnalysisExplorer/xy/plot-theme.ts";

const SERIES = Array.from({ length: 12 }, (_, index) => `#s${index}`);

const THEME: PlotTheme = {
    series: SERIES,
    focus: ["#f1", "#f2", "#f3", "#f4"],
    element: Array.from({ length: 10 }, (_, index) => `#e${index}`),
    context: "#999999",
    ink: "#000000",
    inkMuted: "#444444",
    border: "#eeeeee",
    borderHover: "#dddddd",
    background: "#ffffff",
    surface: "#ffffff",
    fontBody: "Sora",
    fontMono: "JetBrains Mono",
};

interface AnnotationCall {
    text: string;
    showarrow: boolean;
    ay?: number;
    opacity?: number;
}

function curve(
    slot: number,
    y: number[],
    rank = 0,
    file = slot,
    order = slot,
): FigureCurve {
    return {
        slot,
        order,
        rank,
        label: `A${slot + 1} · S${file}.csv`,
        fileName: `S${file}.csv`,
        analysis: `Analysis <${slot}>`,
        x: y.map((_, index) => index),
        y,
        yRange: {
            min: Math.min(...y),
            max: Math.max(...y),
            count: y.length,
        },
    };
}

function input(
    curves: FigureCurve[],
    overrides: Partial<FigureInput> = {},
): FigureInput {
    return {
        curves,
        states: curves.map(() => "plain"),
        theme: THEME,
        lang: "en",
        titles: { x: "Energy (keV)", y: "Counts", offset: "Counts (offset)" },
        xReversed: false,
        width: 800,
        height: 400,
        ...overrides,
    };
}

describe("workshop figure", () => {
    it("moves apart the labels of curves ending together, a leader line joining a moved label to its curve", () => {
        const figure = stackedFigure(
            input([curve(0, [0, 50]), curve(1, [0, 49]), curve(2, [0, 100])]),
            false,
        );
        const labels = figure.layout.annotations as AnnotationCall[];
        expect(labels.map((label) => label.showarrow)).toEqual([
            true,
            true,
            false,
        ]);
        expect(labels[0].ay).toBeLessThan(0);
        expect(labels[1].ay).toBeGreaterThan(0);
        expect(figure.follows).toEqual([[0], [1], [2]]);
    });

    it("grows small multiples that would be under 110 px high, and names each panel with its analysis escaped", () => {
        const curves = Array.from({ length: 12 }, (_, slot) =>
            curve(slot, [1, 2]),
        );
        const figure = multiplesFigure(input(curves, { height: 300 }));
        expect(figure.height).toBe(4 * 110 + 3 * 46 + 28 + 52);
        const texts = (figure.layout.annotations as AnnotationCall[]).map(
            (note) => note.text,
        );
        expect(texts[0]).toBe(
            '<span style="color:#s0">━</span> A1 · Analysis &lt;0&gt;',
        );
        // Every panel is its own hue, the 12th (window position 11) included — no grey fallback.
        expect(texts[11]).toContain('<span style="color:#s11">━</span>');
    });

    it("never sets hoversubplots on the grid: verified a no-op for matches-linked panels in plotly.js-cartesian-dist 4.0.0", () => {
        const curves = [curve(0, [1, 2]), curve(1, [1, 2])];
        const figure = multiplesFigure(input(curves));
        expect(figure.layout).not.toHaveProperty("hoversubplots");
    });

    it("cuts a panel title to the width of its panel", () => {
        const long = { ...curve(0, [1, 2]), analysis: "x".repeat(80) };
        const curves = [long, curve(1, [1, 2]), curve(2, [1, 2])];
        const narrow = multiplesFigure(input(curves, { width: 500 }));
        const title = (narrow.layout.annotations as AnnotationCall[])[0].text;
        const kept = title.split(" · ")[1];
        expect(kept.endsWith("…")).toBe(true);
        expect(kept.length).toBeLessThan(25);
        expect(kept.length).toBeGreaterThan(6);
    });

    it("dims a panel title when the selection hides every curve of the panel, never an axis title", () => {
        const curves = [curve(0, [1, 2]), curve(1, [1, 2])];
        const figure = multiplesFigure(input(curves));
        expect(annotationOpacities(figure, ["hidden", "emphasised"])).toEqual([
            0.35, 1, 1, 1,
        ]);
        const stacked = stackedFigure(input(curves), false);
        expect(annotationOpacities(stacked, ["hidden", "plain"])).toEqual([
            0, 1,
        ]);
    });

    it("fades an end label to the dim opacity while its curve is dimmed, like the line", () => {
        const curves = [curve(0, [1, 2]), curve(1, [3, 4])];
        const stacked = stackedFigure(input(curves), false);
        expect(annotationOpacities(stacked, ["dimmed", "plain"])).toEqual([
            0.35, 1,
        ]);
        expect(annotationOpacities(stacked, ["dimmed", "hidden"])).toEqual([
            0.35, 0,
        ]);
    });

    it("carries the shared x, with its axis title, in the unified box's header once", () => {
        const figure = stackedFigure(input([curve(0, [1, 2])]), false);
        const layout = figure.layout as {
            xaxis?: { unifiedhovertitle?: { text?: string } };
        };
        expect(layout.xaxis?.unifiedhovertitle?.text).toBe(
            "%{x:.4~g} · Energy (keV)",
        );
    });

    it("hovers one compact line per curve under x unified: its slot and its value alone, no repeated name or axis title", () => {
        const figure = stackedFigure(
            input([curve(0, [1, 2]), curve(1, [3, 4])]),
            false,
        );
        expect(figure.data.map((trace) => trace.hovertemplate)).toEqual([
            "A1 · %{y:.4~g}<extra></extra>",
            "A2 · %{y:.4~g}<extra></extra>",
        ]);
    });

    it("hovers the real value behind an offset curve, still one compact line", () => {
        const figure = stackedFigure(
            input([curve(0, [1, 2]), curve(1, [3, 4])]),
            true,
        );
        expect(figure.data[1].hovertemplate).toBe(
            "A2 · %{customdata:.4~g}<extra></extra>",
        );
    });

    it("leaves the hovertemplate of a curve that does not answer hover empty, drawn or restyled, so its hoverinfo skip holds", () => {
        const hidden = input([curve(0, [1, 2]), curve(1, [3, 4])], {
            states: ["hidden", "plain"],
        });
        expect(
            stackedFigure(hidden, false).data.map(
                (trace) => trace.hovertemplate,
            ),
        ).toEqual(["", "A2 · %{y:.4~g}<extra></extra>"]);
        expect(hoverTemplatesFor(hidden, [0, 1], "y", "x unified")).toEqual([
            "",
            "A2 · %{y:.4~g}<extra></extra>",
        ]);
    });

    it("adds the file name only to disambiguate two files sharing a slot", () => {
        const figure = stackedFigure(
            input([curve(0, [1, 2], 0, 1), curve(0, [3, 4], 1, 2)]),
            false,
        );
        expect(figure.data.map((trace) => trace.hovertemplate)).toEqual([
            "A1 · S1.csv · %{y:.4~g}<extra></extra>",
            "A1 · S2.csv · %{y:.4~g}<extra></extra>",
        ]);
    });

    it("escapes an axis title holding pseudo-HTML in the unified header", () => {
        const figure = stackedFigure(
            input([curve(0, [1, 2])], {
                titles: { x: "A & B", y: "<Counts>", offset: "" },
            }),
            false,
        );
        const layout = figure.layout as {
            xaxis?: { unifiedhovertitle?: { text?: string } };
        };
        expect(layout.xaxis?.unifiedhovertitle?.text).toBe(
            "%{x:.4~g} · A &amp; B",
        );
    });

    it("hovers its own x and y, each with its axis title, under closest — no shared header there", () => {
        const many = Array.from({ length: 13 }, (_, slot) =>
            curve(slot, [1, 2]),
        );
        const figure = stackedFigure(input(many), false);
        expect(figure.data[0].hovertemplate).toBe(
            "A1<br>x: %{x:.4~g} Energy (keV) · y: %{y:.4~g} Counts<extra></extra>",
        );
    });

    it("escapes an axis title holding pseudo-HTML under closest", () => {
        const many = Array.from({ length: 13 }, (_, slot) =>
            curve(slot, [1, 2]),
        );
        const figure = stackedFigure(
            input(many, { titles: { x: "A & B", y: "<Counts>", offset: "" } }),
            false,
        );
        expect(figure.data[0].hovertemplate).toContain(
            "x: %{x:.4~g} A &amp; B · y: %{y:.4~g} &lt;Counts&gt;",
        );
    });

    it("hovers along X from the curves actually shown, not the total: hidden and dimmed curves don't count against the cap", () => {
        const many = Array.from({ length: 13 }, (_, slot) =>
            curve(slot, [1, 2]),
        );
        const mostlyHidden = many.map((_, index) =>
            index < 12 ? "plain" : "hidden",
        ) as FigureInput["states"];
        const figure = stackedFigure(
            input(many, { states: mostlyHidden }),
            false,
        );
        // 12 shown (the 13th hidden): still unified, one compact line, no header repeated per curve.
        expect(figure.data[0].hovertemplate).toBe(
            "A1 · %{y:.4~g}<extra></extra>",
        );
    });

    it("keeps an emphasised curve's own hue and dash, only thicker: the focus never recolours it", () => {
        const figure = stackedFigure(
            input([curve(0, [1, 2]), curve(1, [3, 4]), curve(2, [5, 6])], {
                states: ["emphasised", "emphasised", "plain"],
            }),
            false,
        );
        expect(figure.data.map((trace) => trace.line)).toMatchObject([
            { color: "#s0", dash: "solid", width: 2.5 },
            { color: "#s1", dash: "solid", width: 2.5 },
            { color: "#s2", dash: "solid", width: 1.5 },
        ]);
    });

    it("colours a curve by its order in the window, not by its slot: a slot-20 curve alone is solid in the first hue, the 13th curve is dashed", () => {
        const alone = stackedFigure(
            input([curve(20, [1, 2], 0, 20, 0)]),
            false,
        );
        expect(alone.data[0].line).toMatchObject({
            color: "#s0",
            dash: "solid",
        });
        const many = stackedFigure(
            input(
                Array.from({ length: 13 }, (_, index) =>
                    curve(30 + index, [1, 2], 0, index, index),
                ),
            ),
            false,
        );
        expect(many.data[12].line).toMatchObject({
            color: "#s0",
            dash: "6px,2px",
        });
        const notes = (many.layout.annotations as AnnotationCall[]).map(
            (note) => note.text,
        );
        expect(notes[0]).toContain('color:#s0">━');
        expect(notes[12]).toContain('color:#s0">╍');
    });

    it("exports the curves shown with Plotly's legend, a title and a source line, a hidden curve out of the legend", () => {
        const figure = stackedFigure(
            input([curve(0, [1, 2]), curve(1, [1, 2])]),
            false,
        );
        const exported = exportFigure(
            figure,
            [
                {
                    colour: "#111111",
                    dash: "solid",
                    width: 2.5,
                    opacity: 1,
                    hover: true,
                },
                {
                    colour: "#222222",
                    dash: "6px,2px",
                    width: 1.5,
                    opacity: 0,
                    hover: false,
                },
            ],
            THEME,
            { title: "Counts <raw>", source: "Source: ManuSpectrum" },
        );
        expect(exported.data.map((trace) => trace.showlegend)).toEqual([
            true,
            false,
        ]);
        expect(exported.data.map((trace) => trace.opacity)).toEqual([1, 0]);
        expect(exported.data[0].line).toMatchObject({
            width: 2.5,
            dash: "solid",
        });
        expect(exported.data[1].line).toMatchObject({ dash: "6px,2px" });
        expect(exported.data.map((trace) => trace.legendgroup)).toEqual([
            "slot-0",
            "slot-1",
        ]);
        expect(
            exported.data.map((trace) => trace.legendgrouptitle?.text),
        ).toEqual(["A1", "A2"]);
        expect(exported.layout).toMatchObject({
            showlegend: true,
            paper_bgcolor: "#ffffff",
            title: {
                text: "Counts &lt;raw&gt;",
                subtitle: { text: "Source: ManuSpectrum" },
            },
        });
    });
    describe("logarithmic Y", () => {
        const curves = () => [curve(0, [0, 10, 1000]), curve(1, [5, 0, 50])];

        it("sets a log type on the Y axis, and on every panel of the grid", () => {
            const stacked = stackedFigure(
                input(curves(), { yLog: true }),
                false,
            );
            expect((stacked.layout.yaxis as { type?: string }).type).toBe(
                "log",
            );
            const grid = multiplesFigure(input(curves(), { yLog: true }));
            const layout = grid.layout as Record<string, { type?: string }>;
            expect(layout.yaxis.type).toBe("log");
            expect(layout.yaxis2.type).toBe("log");
            const linear = stackedFigure(input(curves()), false);
            expect(linear.layout.yaxis).not.toHaveProperty("type");
        });

        it("clamps non-positive values to the curve's smallest positive and keeps the real ones for the hover", () => {
            for (const figure of [
                stackedFigure(input(curves(), { yLog: true }), false),
                multiplesFigure(input(curves(), { yLog: true })),
            ]) {
                expect(figure.data[0].y).toEqual([10, 10, 1000]);
                expect(figure.data[0].customdata).toEqual([0, 10, 1000]);
                expect(figure.data[1].y).toEqual([5, 5, 50]);
                expect(figure.data[0].hovertemplate).toContain("%{customdata");
            }
        });

        it("puts the end label at the log10 of the curve's end", () => {
            const figure = stackedFigure(
                input(curves(), { yLog: true }),
                false,
            );
            const labels = figure.layout.annotations as { y: number }[];
            expect(labels[0].y).toBeCloseTo(3);
            expect(labels[1].y).toBeCloseTo(Math.log10(50));
        });

        it("stays linear in Offset and when a curve has no positive value", () => {
            const offset = stackedFigure(input(curves(), { yLog: true }), true);
            expect(offset.layout.yaxis).not.toHaveProperty("type", "log");
            expect(offset.data[0].customdata).toEqual([0, 10, 1000]);
            const flat = stackedFigure(
                input([curve(0, [0, 0])], { yLog: true }),
                false,
            );
            expect(flat.layout.yaxis).not.toHaveProperty("type");
        });
    });

    describe("shapes", () => {
        const shapes = [
            { type: "line", x0: 1, x1: 1, y0: 0, y1: 1, yref: "paper" },
        ] as FigureInput["shapes"];

        it("passes the shapes of the input through, and none by default", () => {
            const given = input([curve(0, [1, 2])], { shapes });
            expect(stackedFigure(given, false).layout.shapes).toEqual(shapes);
            expect(multiplesFigure(given).layout.shapes).toEqual(shapes);
            expect(
                stackedFigure(input([curve(0, [1, 2])]), false).layout,
            ).not.toHaveProperty("shapes");
        });

        it("keeps the shapes it is given in the export", () => {
            const figure = stackedFigure(input([curve(0, [1, 2])]), false);
            const paints: CurvePaint[] = [
                {
                    colour: "#111111",
                    dash: "solid",
                    width: 2,
                    opacity: 1,
                    hover: true,
                },
            ];
            const text = { title: "t", source: "s" };
            expect(
                exportFigure(figure, paints, THEME, text, shapes).layout.shapes,
            ).toEqual(shapes);
            const withShapes = stackedFigure(
                input([curve(0, [1, 2])], { shapes }),
                false,
            );
            expect(
                exportFigure(withShapes, paints, THEME, text).layout.shapes,
            ).toEqual(shapes);
        });
    });

    describe("XRF lens", () => {
        it("ticks a log axis explicitly, by the decades its data spans, its minor ticks short and unlabelled", () => {
            const stacked = stackedFigure(
                input([curve(0, [1, 500, 20])], { yLog: true }),
                false,
            );
            const yaxis = stacked.layout.yaxis as Record<string, unknown>;
            expect(yaxis).toMatchObject({
                type: "log",
                tickmode: "array",
                minor: {
                    tickmode: "array",
                    ticks: "outside",
                    showgrid: false,
                },
            });
            expect(yaxis).not.toHaveProperty("dtick");
            expect(yaxis.ticktext).toEqual(
                expect.arrayContaining(["1", "10", "100"]),
            );
            expect(yaxis.tickvals).not.toContain(2);
            expect((yaxis.minor as { tickvals: number[] }).tickvals).toContain(
                200,
            );
            expect(
                stackedFigure(input([curve(0, [1, 5, 2])]), false).layout.yaxis,
            ).not.toHaveProperty("tickmode");
        });

        it("ticks each panel of the grid by its own curves: decades, then round steps inside one decade", () => {
            const grid = multiplesFigure(
                input([curve(0, [1, 50000]), curve(1, [1500, 9000])], {
                    yLog: true,
                }),
            );
            const layout = grid.layout as Record<
                string,
                { tickvals: number[]; ticktext: string[] }
            >;
            expect(layout.yaxis.ticktext).toEqual(
                expect.arrayContaining(["1", "10", "100", "1000", "10k"]),
            );
            expect(layout.yaxis.tickvals).not.toContain(2000);
            expect(layout.yaxis2.ticktext).toEqual(
                expect.arrayContaining(["2000", "4000", "6000", "8000"]),
            );
            expect(layout.yaxis2.ticktext).not.toContain("10");
        });

        it("writes the tick labels of a log axis with the page's decimal mark", () => {
            const figure = stackedFigure(
                input([curve(0, [12000, 14000])], { yLog: true, lang: "fr" }),
                false,
            );
            expect(
                (figure.layout.yaxis as { ticktext: string[] }).ticktext,
            ).toContain("12,5k");
        });

        it("lifts a panel's title one row above its plot for the label band, with the lens only", () => {
            const curves = [curve(0, [1, 2]), curve(1, [1, 2])];
            const titleOf = (figure: ReturnType<typeof multiplesFigure>) =>
                (figure.layout.annotations as AnnotationCall[])[0];
            expect(
                titleOf(multiplesFigure(input(curves, { lens: true }))),
            ).toMatchObject({ y: 1, yanchor: "bottom", yshift: 17 });
            expect(titleOf(multiplesFigure(input(curves)))).not.toHaveProperty(
                "yshift",
            );
        });

        it("keeps the end labels of a stacked chart above the instrument band, only when the lens draws one", () => {
            const low = curve(0, [10, 0]);
            const high = curve(1, [10, 10]);
            const lowest = (figure: ReturnType<typeof stackedFigure>) =>
                (figure.layout.annotations as AnnotationCall[])
                    .filter((note) => note.text.includes("A1"))
                    .map((note) => note.ay ?? 0)[0];
            const plain = stackedFigure(
                input([low, high], { height: 400 }),
                false,
            );
            const lens = stackedFigure(
                input([low, high], {
                    height: 400,
                    lens: true,
                    instrumentBandPx: 53,
                }),
                false,
            );
            const oneRow = stackedFigure(
                input([low, high], {
                    height: 400,
                    lens: true,
                    instrumentBandPx: 39,
                }),
                false,
            );
            const bare = stackedFigure(
                input([low, high], { height: 400, lens: true }),
                false,
            );
            expect(lowest(plain)).toBe(0);
            expect(lowest(lens)).toBeLessThan(-40);
            expect(lowest(oneRow)).toBeCloseTo(lowest(lens) + 14);
            expect(lowest(bare)).toBe(0);
        });

        it("lays the end labels out again for a new foot band, as a figure built with it has them", () => {
            const curves = [curve(0, [10, 0]), curve(1, [10, 10])];
            for (const offset of [false, true]) {
                const kind = offset ? "offset" : "overlay";
                const bare = stackedFigure(
                    input(curves, { height: 400, lens: true }),
                    offset,
                );
                const banded = input(curves, {
                    height: 400,
                    lens: true,
                    instrumentBandPx: 53,
                });
                expect(endLabelsFor(banded, bare, kind)).toEqual(
                    stackedFigure(banded, offset).layout.annotations,
                );
            }
            const grid = multiplesFigure(input(curves, { lens: true }));
            expect(endLabelsFor(input(curves), grid, "multiples")).toBeNull();
        });

        it("keeps a linear counts axis at zero and a stacked chart's top margin for the declared labels", () => {
            const plain = stackedFigure(input([curve(0, [0, 5, 2])]), false);
            const lens = stackedFigure(
                input([curve(0, [0, 5, 2])], { lens: true }),
                false,
            );
            expect(plain.layout.yaxis).not.toHaveProperty("rangemode");
            expect(lens.layout.yaxis).toMatchObject({ rangemode: "tozero" });
            expect(
                (lens.layout.margin as { t: number }).t -
                    (plain.layout.margin as { t: number }).t,
            ).toBe(32);
        });

        it("sets no zero floor on a log axis or in Offset, and gives the grid's margin the band's room only", () => {
            const log = stackedFigure(
                input([curve(0, [1, 5, 2])], { lens: true, yLog: true }),
                false,
            );
            expect(log.layout.yaxis).not.toHaveProperty("rangemode");
            const offset = stackedFigure(
                input([curve(0, [1, 5, 2])], { lens: true }),
                true,
            );
            expect(offset.layout.yaxis).not.toHaveProperty("rangemode");
            const grid = multiplesFigure(
                input([curve(0, [1, 5]), curve(1, [1, 5])], { lens: true }),
            );
            const layout = grid.layout as Record<string, unknown>;
            expect(layout.yaxis).toMatchObject({ rangemode: "tozero" });
            expect(layout.yaxis2).toMatchObject({ rangemode: "tozero" });
            expect((layout.margin as { t: number }).t).toBe(31);
            const plain = multiplesFigure(
                input([curve(0, [1, 5]), curve(1, [1, 5])]),
            );
            expect((plain.layout.margin as { t: number }).t).toBe(28);
        });
    });

    describe("panelWidths", () => {
        it("gives the single panel of a stacked chart the width less its margins", () => {
            const figure = stackedFigure(input([curve(0, [0, 5])]), false);
            const margin = figure.layout.margin as { l: number; r: number };
            expect(panelWidths(figure, 1000)).toEqual({
                "": 1000 - margin.l - margin.r,
            });
        });

        it("shares the plot width between the columns of a grid by Plotly's formula (the gap is a fraction of the step), for its own export width", () => {
            const curves = [0, 1, 2, 3].map((slot) => curve(slot, [0, 5]));
            const figure = multiplesFigure(input(curves, { width: 900 }));
            const grid = figure.layout.grid as {
                columns: number;
                xgap: number;
            };
            const margin = figure.layout.margin as { l: number; r: number };
            const widths = panelWidths(figure, 1140);
            expect(Object.keys(widths).sort()).toEqual(["", "2", "3", "4"]);
            const plot = 1140 - margin.l - margin.r;
            const step = plot / (grid.columns - grid.xgap);
            expect(widths[""]).toBeCloseTo(step * (1 - grid.xgap));
            expect(grid.columns * step - grid.xgap * step).toBeCloseTo(plot);
            expect(panelWidths(figure, 1140)[""]).toBeGreaterThan(
                panelWidths(figure, 900)[""],
            );
        });

        it("takes the margins Plotly drew when given, which the Y labels widened", () => {
            const figure = stackedFigure(input([curve(0, [0, 5])]), false);
            expect(panelWidths(figure, 640, { l: 61, r: 56 })).toEqual({
                "": 640 - 61 - 56,
            });
        });
    });

    describe("autorangeX", () => {
        it("spans every panel's curves, as the matched X axes of a grid show them, high to low on a reversed axis", () => {
            const wide = { ...curve(0, [1, 2, 3]), x: [0, 20, 40] };
            const narrow = { ...curve(1, [1, 2, 3]), x: [0, 10, 20] };
            const figure = multiplesFigure(input([wide, narrow]));
            expect(autorangeX(figure, false)).toEqual([0, 40]);
            expect(autorangeX(figure, true)).toEqual([40, 0]);
            const empty = multiplesFigure(input([{ ...wide, x: [], y: [] }]));
            expect(autorangeX(empty, false)).toBeNull();
        });
    });

    describe("yFitUpdate", () => {
        it("fits a linear axis from zero to the highest value inside the window, plus 5 %", () => {
            const flat = curve(0, [0, 10, 100, 40, 90, 3]);
            const update = yFitUpdate(input([flat]), "overlay", [2, 4]);
            expect(update["yaxis.range"]).toEqual([0, 105]);
        });

        it("ignores a hidden curve and the values outside the window", () => {
            const loud = curve(0, [500, 500, 500, 500]);
            const quiet = curve(1, [0, 20, 40, 10]);
            const given = input([loud, quiet], {
                states: ["hidden", "plain"],
            });
            expect(yFitUpdate(given, "overlay", [1, 2])["yaxis.range"]).toEqual(
                [0, 42],
            );
        });

        it("goes back to the autorange for the whole spectrum, and for a window holding no value", () => {
            const given = input([curve(0, [1, 2, 3])]);
            expect(yFitUpdate(given, "overlay", null)).toEqual({
                "yaxis.autorange": true,
            });
            expect(yFitUpdate(given, "overlay", [50, 60])).toEqual({
                "yaxis.autorange": true,
            });
        });

        it("lowers the floor under a negative value, with the same headroom", () => {
            const given = input([curve(0, [-10, 0, 30])]);
            const [from, to] = yFitUpdate(given, "overlay", [0, 2])[
                "yaxis.range"
            ] as number[];
            expect(from).toBeCloseTo(-12);
            expect(to).toBeCloseTo(32.1);
        });

        it("fits a log axis from the smallest positive to the highest, in log10", () => {
            const given = input([curve(0, [0, 10, 1000, 100])], { yLog: true });
            const [from, to] = yFitUpdate(given, "overlay", [0, 3])[
                "yaxis.range"
            ] as number[];
            expect(from).toBeCloseTo(1 - 0.1);
            expect(to).toBeCloseTo(3 + 0.1);
        });

        it("ticks a fitted log window inside one decade by round steps, and a wider one by its decades", () => {
            const given = input([curve(0, [10, 1500, 9000, 2000, 100000])], {
                yLog: true,
            });
            const narrow = yFitUpdate(given, "overlay", [1, 3]);
            expect(narrow["yaxis.tickmode"]).toBe("array");
            expect(narrow["yaxis.ticktext"]).toEqual(
                expect.arrayContaining(["2000", "4000", "6000", "8000"]),
            );
            expect(narrow["yaxis.minor.tickvals"]).toEqual([]);
            const wide = yFitUpdate(given, "overlay", [0, 4]);
            expect(wide["yaxis.ticktext"]).toEqual(
                expect.arrayContaining(["10", "100", "1000", "10k", "100k"]),
            );
            expect(wide["yaxis.tickvals"]).not.toContain(2000);
            expect(wide).not.toHaveProperty("yaxis.dtick");
        });

        it("gives an autorange log axis the ticks of its whole data", () => {
            const given = input(
                [curve(0, [1, 50000]), curve(1, [1500, 9000])],
                { yLog: true },
            );
            const update = yFitUpdate(given, "multiples", null);
            expect(update).toMatchObject({
                "yaxis.autorange": true,
                "yaxis.tickmode": "array",
                "yaxis2.autorange": true,
                "yaxis2.tickmode": "array",
            });
            expect(update["yaxis.ticktext"]).toContain("10k");
            expect(update["yaxis.tickvals"]).not.toContain(2000);
            expect(update["yaxis2.ticktext"]).toContain("4000");
            expect(
                yFitUpdate(input([curve(0, [1, 50])]), "overlay", [0, 1]),
            ).not.toHaveProperty("yaxis.tickmode");
        });

        it("fits each panel of the grid to its own curves", () => {
            const given = input([
                curve(0, [0, 10, 20]),
                curve(1, [0, 100, 200]),
            ]);
            const update = yFitUpdate(given, "multiples", [0, 2]);
            expect(update["yaxis.range"]).toEqual([0, 21]);
            expect(update["yaxis2.range"]).toEqual([0, 210]);
        });

        it("adds each curve's lift in Offset", () => {
            const given = input([curve(0, [0, 10]), curve(1, [0, 10])]);
            const range = yFitUpdate(given, "offset", [0, 1])[
                "yaxis.range"
            ] as number[];
            expect(range[1]).toBeGreaterThan(10);
            expect(range[0]).toBeLessThan(0);
        });

        it("never touches the curves it reads, nor the figures built from them", () => {
            const frozen = curve(0, [0, 10, 100]);
            Object.freeze(frozen.x);
            Object.freeze(frozen.y);
            const given = input([frozen], { lens: true, yLog: true });
            expect(() => {
                yFitUpdate(given, "overlay", [0, 2]);
                stackedFigure(given, false);
                stackedFigure(given, true);
                multiplesFigure(given);
            }).not.toThrow();
            expect(frozen.y).toEqual([0, 10, 100]);
        });
    });
});
