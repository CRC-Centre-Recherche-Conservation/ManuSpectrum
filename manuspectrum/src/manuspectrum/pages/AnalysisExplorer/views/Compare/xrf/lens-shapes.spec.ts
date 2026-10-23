import { describe, expect, it } from "vitest";

import {
    MAX_LENS_SHAPES,
    lensDrawing,
    shapesKey,
} from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/xrf/lens-shapes.ts";

import type {
    LensPanel,
    LensShape,
    LensShapesInput,
} from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/xrf/lens-shapes.ts";

const theme = {
    ink: "#111",
    inkMuted: "#666",
    focus: ["#a00", "#0a0", "#00a", "#aa0"],
    element: [
        "#c2410c",
        "#0e6baa",
        "#b8860b",
        "#14804a",
        "#b912e2",
        "#d0257a",
        "#475569",
        "#8e3329",
        "#3f6212",
        "#6d28d9",
    ],
    fontMono: "monospace",
};

function panel(suffix = "", over: Partial<LensPanel> = {}): LensPanel {
    return {
        suffix,
        extent: [0, 20],
        declared: [],
        instrument: [],
        bands: [],
        ...over,
    };
}

function input(over: Partial<LensShapesInput> = {}): LensShapesInput {
    return {
        panels: [panel()],
        focus: [],
        elements: [],
        overlaps: [],
        theme,
        ...over,
    };
}

const lensShapes = (given: LensShapesInput): LensShape[] =>
    lensDrawing(given).shapes;
const labelled = (shapes: LensShape[]) =>
    shapes.filter((shape) => shape.label !== undefined);
const texts = (shapes: LensShape[]) =>
    shapes.flatMap((shape) => (shape.label ? [shape.label.text] : []));
const anchors = (shapes: LensShape[]) =>
    shapes.map((shape) => shape.label?.xanchor);

describe("lensShapes", () => {
    it("draws nothing outside the X extent", () => {
        const shapes = lensShapes(
            input({
                focus: [
                    {
                        hue: 0,
                        lines: [
                            { energy: 10, label: "Hg Lα1", intensity: 1 },
                            { energy: 75, label: "Pb Kα1", intensity: 1 },
                        ],
                    },
                ],
                panels: [
                    panel("", {
                        declared: [{ symbol: "Pb", energy: 30, rank: 0 }],
                        bands: [
                            { label: "x", from: 25, to: 30, colour: "#f00" },
                        ],
                    }),
                ],
                overlaps: [{ from: 19.9, to: 22, hue: 1, symbol: "Pb" }],
            }),
        );
        expect(shapes).toHaveLength(3);
        const rect = shapes.find((s) => s.type === "rect");
        expect(rect?.x1).toBe(20);
        expect(shapes.some((s) => s.x0 === 75 || s.x0 === 30)).toBe(false);
    });

    it("references the axes of each panel", () => {
        const lines = [{ energy: 5, label: "Fe Kα1", intensity: 1 }];
        const shapes = lensShapes(
            input({
                panels: [panel(""), panel("2"), panel("3")],
                focus: [{ hue: 1, lines }],
            }),
        );
        expect(shapes.map((s) => [s.xref, s.yref])).toEqual([
            ["x", "y domain"],
            ["x2", "y2 domain"],
            ["x3", "y3 domain"],
        ]);
    });

    it("follows the level dashes and the intensity width", () => {
        const shapes = lensShapes(
            input({
                focus: [
                    {
                        hue: 0,
                        lines: [
                            { energy: 5, label: "a", intensity: 0.5 },
                            { energy: 6, label: "b", intensity: 0.49 },
                        ],
                    },
                ],
                panels: [
                    panel("", {
                        declared: [
                            { symbol: "A", energy: 1, rank: 0 },
                            { symbol: "B", energy: 2, rank: 1 },
                            { symbol: "C", energy: 3, rank: 2 },
                        ],
                    }),
                ],
            }),
        );
        expect(shapes[0].line).toMatchObject({ width: 1.5, dash: "solid" });
        expect(shapes[1].line).toMatchObject({ width: 1, dash: "dash" });
        expect(shapes.slice(2).map((s) => s.line?.dash)).toEqual([
            "solid",
            "dash",
            "dot",
        ]);
        expect(shapes[2]).toMatchObject({
            ysizemode: "pixel",
            yanchor: 1,
            y0: -14,
            y1: 0,
        });
    });

    it("draws a preview thin and dashed, a lens element in its own hue", () => {
        const shapes = lensShapes(
            input({
                focus: [
                    {
                        hue: 2,
                        preview: true,
                        lines: [{ energy: 5, label: "a", intensity: 1 }],
                    },
                ],
                elements: [
                    {
                        symbol: "Pb",
                        lines: [{ energy: 6, label: "b", intensity: 1 }],
                    },
                ],
            }),
        );
        expect(shapes[0].line).toMatchObject({
            width: 1,
            dash: "dash",
            color: "#00a",
        });
        expect(shapes[1].line?.color).toBe("#c2410c");
        expect(shapes[1].label?.font?.color).toBe("#c2410c");
    });

    it("gives each element the same hue whatever else is drawn", () => {
        const colourOf = (symbols: string[], wanted: string) =>
            lensShapes(
                input({
                    elements: symbols.map((symbol, index) => ({
                        symbol,
                        lines: [
                            {
                                energy: 2 + index * 5,
                                label: symbol,
                                intensity: 1,
                            },
                        ],
                    })),
                }),
            ).find((shape) => shape.label?.text === wanted)?.line?.color;
        expect(colourOf(["Hg"], "Hg")).toBe(colourOf(["Ca", "Fe", "Hg"], "Hg"));
        expect(colourOf(["Fe", "Hg"], "Fe")).not.toBe(
            colourOf(["Fe", "Hg"], "Hg"),
        );
    });

    it("draws a declared tick in its element's hue, in the focus hue when the element is pinned", () => {
        const shapes = lensShapes(
            input({
                panels: [
                    panel("", {
                        declared: [
                            { symbol: "Pb", energy: 3, rank: 0 },
                            { symbol: "Fe", energy: 4, rank: 1, focusHue: 2 },
                        ],
                    }),
                ],
            }),
        );
        expect(shapes.map((s) => s.line?.color)).toEqual(["#c2410c", "#00a"]);
    });

    it("draws an overlap as a band and a centre rule that stay visible on a wide range", () => {
        const shapes = lensShapes(
            input({
                overlaps: [{ from: 10.46, to: 10.63, hue: -1, symbol: "As" }],
            }),
        );
        const rect = shapes.find((s) => s.type === "rect");
        const rule = shapes.find((s) => s.type === "line");
        expect(rect?.opacity).toBeGreaterThanOrEqual(0.2);
        expect(rect?.fillcolor).toBe(rule?.line?.color);
        expect(rule?.line?.width).toBeGreaterThanOrEqual(3);
        expect(rule?.x0).toBeCloseTo(10.545, 3);
    });

    it("draws the identified marker as one dashed ink line per panel holding its energy, kept beyond the cap", () => {
        const many = Array.from({ length: MAX_LENS_SHAPES + 20 }, (_, i) => ({
            energy: 1 + i / 20,
            label: `L${i}`,
            intensity: 1,
        }));
        const shapes = lensShapes(
            input({
                panels: [panel(""), panel("2", { extent: [0, 4] })],
                focus: [{ hue: 0, lines: many }],
                marker: { energy: 3, label: "⌖ 3.00 keV" },
            }),
        );
        expect(shapes).toHaveLength(MAX_LENS_SHAPES);
        const marked = shapes.filter((s) => s.label?.text === "⌖ 3.00 keV");
        expect(marked.map((s) => s.xref)).toEqual(["x", "x2"]);
        expect(marked[0].line).toMatchObject({ color: "#111", dash: "dash" });
        expect(marked[0].x0).toBe(3);
    });

    it("draws the identified marker after every other shape, so in front of the ticks", () => {
        const shapes = lensShapes(
            input({
                panels: [
                    panel("", {
                        declared: [{ symbol: "Hg", energy: 3, rank: 0 }],
                        instrument: [{ label: "sum", energy: 4 }],
                    }),
                ],
                focus: [
                    {
                        hue: 0,
                        lines: [{ energy: 5, label: "Pb", intensity: 1 }],
                    },
                ],
                marker: { energy: 3, label: "⌖ 3.00 keV" },
            }),
        );
        expect(shapes.at(-1)?.label?.text).toBe("⌖ 3.00 keV");
        expect(shapes.at(-1)?.layer).toBe("above");
    });

    it("draws no marker outside the panel's extent", () => {
        const shapes = lensShapes(
            input({ marker: { energy: 50, label: "far" } }),
        );
        expect(shapes).toEqual([]);
    });

    it("sets no showlegend", () => {
        const shapes = lensShapes(
            input({
                focus: [
                    {
                        hue: 0,
                        lines: [{ energy: 5, label: "a", intensity: 1 }],
                    },
                ],
                panels: [
                    panel("", {
                        instrument: [{ label: "i", energy: 4 }],
                        bands: [
                            {
                                label: "Compton",
                                from: 1,
                                to: 2,
                                colour: "#f00",
                            },
                        ],
                    }),
                ],
                overlaps: [{ from: 3, to: 4, hue: 0, symbol: "Fe" }],
            }),
        );
        expect(shapes.length).toBe(5);
        expect(shapes.some((s) => "showlegend" in s)).toBe(false);
    });

    it("escapes labels", () => {
        const shapes = lensShapes(
            input({
                panels: [
                    panel("", {
                        declared: [{ symbol: "<b>", energy: 5, rank: 0 }],
                    }),
                ],
            }),
        );
        expect(shapes[0].label?.text).toBe("&lt;b&gt;");
    });

    it("is deterministic, so equal input gives an equal key", () => {
        const make = () =>
            input({
                focus: [
                    {
                        hue: 0,
                        lines: [{ energy: 5, label: "a", intensity: 1 }],
                    },
                ],
            });
        expect(shapesKey(lensShapes(make()))).toBe(
            shapesKey(lensShapes(make())),
        );
        expect(shapesKey([])).toBe("[]");
    });

    describe("the band above the plot", () => {
        /** A 200 px plot over 0–40 keV: 5 px per keV; a glyph is 6.6 px, a gap 4 px, an anchor pad 3 px. */
        const declared = (
            entries: [string, number][],
            over: Partial<LensShapesInput> = {},
        ) =>
            lensShapes(
                input({
                    plotWidth: 200,
                    panels: [
                        panel("", {
                            extent: [0, 40],
                            declared: entries.map(([symbol, energy]) => ({
                                symbol,
                                energy,
                                rank: 0,
                            })),
                        }),
                    ],
                    ...over,
                }),
            );

        it("keeps the tick in the plot and the label horizontal above it, in the element's colour", () => {
            const [shape] = declared([["Hg", 10]]);
            expect(shape).toMatchObject({
                ysizemode: "pixel",
                yanchor: 1,
                y0: -14,
                y1: 0,
            });
            expect(shape.label).toMatchObject({
                text: "Hg",
                textangle: 0,
                xanchor: "center",
                yanchor: "bottom",
            });
            expect(shape.label).not.toHaveProperty("padding");
            expect(shape.label?.font).toMatchObject({ size: 11 });
            expect(shape.label?.font?.color).toBe(shape.line?.color);
        });

        it("raises the second of two touching ticks to the second row, the first stepping aside from its stroke", () => {
            const shapes = declared([
                ["Fe", 10],
                ["Hg", 10.4],
                ["Pb", 14],
            ]);
            expect(texts(shapes)).toEqual(["Fe", "Hg", "Pb"]);
            expect(shapes.map((s) => s.y1)).toEqual([0, 14, 0]);
            expect(shapes.map((s) => s.y0)).toEqual([-14, -14, -14]);
            expect(anchors(shapes)).toEqual(["right", "center", "center"]);
        });

        it("leaves a label out when it fits on no row, the tick stays", () => {
            const shapes = declared([
                ["Fe", 10],
                ["Hg", 10.2],
                ["Pb", 10.4],
                ["Cu", 10.6],
            ]);
            expect(shapes).toHaveLength(4);
            expect(texts(shapes)).toEqual(["Fe", "Hg", "Pb"]);
            expect(shapes[3]).toMatchObject({ y0: -14, y1: 0 });
        });

        it("keeps one row when the caller asks for one, as small multiples do", () => {
            const shapes = declared(
                [
                    ["Fe", 10],
                    ["Hg", 10.4],
                ],
                { bandRows: 1 },
            );
            expect(texts(shapes)).toEqual(["Fe"]);
            expect(shapes.map((s) => s.y1)).toEqual([0, 0]);
        });

        it("places the majors before the minors and the traces", () => {
            const shapes = lensShapes(
                input({
                    plotWidth: 200,
                    bandRows: 1,
                    panels: [
                        panel("", {
                            extent: [0, 40],
                            declared: [
                                { symbol: "Ca", energy: 10, rank: 2 },
                                { symbol: "Fe", energy: 10.4, rank: 0 },
                            ],
                        }),
                    ],
                }),
            );
            expect(texts(shapes)).toEqual(["Fe"]);
        });

        it("anchors a label on the plot edge it would cross", () => {
            const shapes = declared([
                ["Pb", 0.2],
                ["Hg", 39.8],
            ]);
            expect(anchors(shapes)).toEqual(["left", "right"]);
        });

        it("gives a declared tick on its element's principal line that line's one label, the symbol when the line's does not fit", () => {
            const focus = [
                {
                    hue: 0,
                    lines: [{ energy: 6.4, label: "Fe Kα1", intensity: 1 }],
                },
            ];
            const wide = declared([["Fe", 6.4]], { focus });
            expect(wide).toHaveLength(2);
            expect(wide[0].label).toBeUndefined();
            expect(wide[1].label).toMatchObject({
                text: "Fe Kα1",
                xanchor: "center",
            });
            expect(wide[1].y0).toBe(-14);
            const narrow = declared([["Fe", 6.4]], { focus, plotWidth: 30 });
            expect(texts(narrow)).toEqual(["Fe"]);
            expect(narrow[1].label?.xanchor).toBe("left");
        });

        it("lays a line's label on the line itself on the first row, and on a stub rising to the row above", () => {
            const shapes = declared([], {
                focus: [
                    {
                        hue: 0,
                        lines: [
                            { energy: 10, label: "Pb Lα1", intensity: 1 },
                            { energy: 10.4, label: "Hg Lα1", intensity: 1 },
                        ],
                    },
                ],
            });
            expect(shapes).toHaveLength(3);
            expect(shapes[0]).toMatchObject({ y0: 0, y1: 1, layer: "below" });
            expect(shapes[0].label).toMatchObject({
                text: "Pb Lα1",
                xanchor: "right",
                textangle: 0,
            });
            expect(shapes[1].label).toBeUndefined();
            expect(shapes[2]).toMatchObject({
                ysizemode: "pixel",
                yanchor: 1,
                y0: 0,
                y1: 14,
                layer: "above",
            });
            expect(shapes[2].label).toMatchObject({
                text: "Hg Lα1",
                xanchor: "center",
            });
            expect(shapes[2].line).toEqual(shapes[1].line);
        });

        it("falls back to the line alone when the full label fits nowhere, then to no label, the line staying", () => {
            const shapes = declared([], {
                plotWidth: 100,
                focus: [
                    {
                        hue: 0,
                        lines: [
                            { energy: 10, label: "Pb Lα1", intensity: 1 },
                            { energy: 10.4, label: "Hg Lα1", intensity: 1 },
                            { energy: 10.8, label: "Fe Kα1", intensity: 1 },
                            { energy: 11.2, label: "Cu Lβ1", intensity: 1 },
                        ],
                    },
                ],
            });
            expect(shapes.filter((s) => s.y1 === 1)).toHaveLength(4);
            expect(texts(shapes)).toEqual(["Pb Lα1", "Hg Lα1", "Kα1"]);
            expect(labelled(shapes).map((s) => s.label?.xanchor)).toEqual([
                "left",
                "center",
                "right",
            ]);
        });

        it("places the solid lines before the dashed ones, the dashed by intensity", () => {
            const shapes = declared([], {
                bandRows: 1,
                focus: [
                    {
                        hue: 0,
                        lines: [
                            { energy: 10, label: "Pb Lβ2", intensity: 0.1 },
                            { energy: 10.4, label: "Pb Lα1", intensity: 1 },
                            { energy: 20, label: "Hg Lγ1", intensity: 0.1 },
                            { energy: 20.4, label: "Hg Lβ1", intensity: 0.4 },
                        ],
                    },
                ],
            });
            expect(texts(shapes)).toEqual(["Pb Lα1", "Hg Lβ1"]);
        });

        it("places the identified marker's label first, horizontal, a line label never over it", () => {
            const shapes = declared([], {
                marker: { energy: 10, label: "⌖ 10.00 keV" },
                focus: [
                    {
                        hue: 0,
                        lines: [
                            { energy: 10.2, label: "Pb Lα1", intensity: 1 },
                        ],
                    },
                ],
            });
            const marker = shapes.at(-1);
            expect(marker?.label).toMatchObject({
                text: "⌖ 10.00 keV",
                textangle: 0,
                xanchor: "left",
                yanchor: "bottom",
                padding: 3,
            });
            const stub = shapes.find((s) => s.ysizemode === "pixel");
            expect(stub).toMatchObject({ y0: 0, y1: 14 });
            expect(stub?.label?.text).toBe("Pb Lα1");
        });
    });

    describe("data axes", () => {
        it("references no data Y axis: every shape sits on the panel's domain, so no range grows", () => {
            const shapes = lensShapes(
                input({
                    focus: [
                        {
                            hue: 0,
                            lines: [{ energy: 5, label: "a", intensity: 1 }],
                        },
                    ],
                    panels: [
                        panel("", {
                            declared: [{ symbol: "Fe", energy: 6, rank: 0 }],
                            instrument: [{ label: "i", energy: 4 }],
                            bands: [
                                {
                                    label: "Compton",
                                    from: 1,
                                    to: 2,
                                    colour: "#f00",
                                },
                            ],
                        }),
                    ],
                    overlaps: [{ from: 3, to: 4, hue: 0, symbol: "Fe" }],
                }),
            );
            expect(shapes.length).toBe(6);
            expect(shapes.every((s) => s.yref === "y domain")).toBe(true);
        });
    });

    describe("instrument labels", () => {
        it("draws every tick in muted ink, whoever carries it", () => {
            const shapes = lensShapes(
                input({
                    panels: [
                        panel("", {
                            instrument: [
                                { label: "Σ", energy: 4 },
                                { label: "éch.", energy: 8 },
                            ],
                        }),
                    ],
                }),
            );
            expect(shapes.map((s) => s.line?.color)).toEqual(["#666", "#666"]);
            expect(shapes.map((s) => s.label?.font?.color)).toEqual([
                "#666",
                "#666",
            ]);
        });

        /** A 400 px plot over 0–40 keV: 10 px per keV, two instrument rows. */
        const ticks = (
            labels: [
                string,
                number,
                LensPanel["instrument"][number]["kind"]?,
            ][],
            plotWidth = 400,
        ) =>
            lensShapes(
                input({
                    plotWidth,
                    panels: [
                        panel("", {
                            extent: [0, 40],
                            instrument: labels.map(([label, energy, kind]) => ({
                                label,
                                energy,
                                ...(kind ? { kind } : {}),
                            })),
                        }),
                    ],
                }),
            );

        it("keeps a label alone on the first row, horizontal above its tick", () => {
            const [shape] = ticks([["Σ", 10]]);
            expect(shape).toMatchObject({ ysizemode: "pixel", y1: 14 });
            expect(shape.label).toMatchObject({
                text: "Σ",
                textangle: 0,
                xanchor: "center",
                yanchor: "bottom",
            });
        });

        it("staggers labels that would touch on two rows of taller ticks, anchoring aside where that keeps a stroke off a label", () => {
            const shapes = ticks([
                ["éch.", 10],
                ["somme", 10.5],
                ["40 kV", 11],
            ]);
            expect(shapes.map((s) => s.y1)).toEqual([14, 28, 14]);
            expect(texts(shapes)).toEqual(["éch.", "somme", "40 kV"]);
            expect(anchors(shapes)).toEqual(["right", "center", "left"]);
        });

        it("places the tube's lines before the voltage, the escapes and the sums, whatever their order on the axis", () => {
            const crowd: [
                string,
                number,
                LensPanel["instrument"][number]["kind"],
            ][] = [
                ["Σ", 10, "sum"],
                ["éch.", 10.3, "escape"],
                ["40 kV", 10.6, "duane-hunt"],
                ["Ag Kα1", 10.9, "rayleigh"],
            ];
            const onOneRow = (count: number) =>
                texts(ticks(crowd.slice(0, count), 240));
            expect(onOneRow(4)).toEqual(["Ag Kα1"]);
            expect(onOneRow(3)).toEqual(["40 kV"]);
            expect(onOneRow(2)).toEqual(["éch."]);
            expect(onOneRow(1)).toEqual(["Σ"]);
        });

        it("keeps one row of labels on a panel narrower than 250 px", () => {
            const pair: [string, number][] = [
                ["éch.", 10],
                ["somme", 10.5],
            ];
            expect(ticks(pair, 260).map((s) => s.y1)).toEqual([14, 28]);
            expect(ticks(pair, 240).map((s) => s.y1)).toEqual([14, 14]);
            expect(texts(ticks(pair, 240))).toEqual(["éch."]);
        });

        it("does not place the same word again within 60 px, the tick staying", () => {
            const near = ticks([
                ["somme", 10],
                ["somme", 15],
            ]);
            expect(texts(near)).toEqual(["somme"]);
            expect(near.map((s) => s.y1)).toEqual([14, 14]);
            const far = ticks([
                ["somme", 10],
                ["somme", 17],
            ]);
            expect(texts(far)).toEqual(["somme", "somme"]);
        });

        it("anchors a voltage at the right edge on that edge, whole", () => {
            const [shape] = ticks([["40 kV", 39.9, "duane-hunt"]]);
            expect(shape.label).toMatchObject({
                text: "40 kV",
                xanchor: "right",
            });
        });
    });

    describe("the Compton band", () => {
        const drawn = (instrument: LensPanel["instrument"] = []) =>
            lensShapes(
                input({
                    plotWidth: 400,
                    panels: [
                        panel("", {
                            extent: [0, 40],
                            instrument,
                            bands: [
                                {
                                    label: "Compton",
                                    from: 5,
                                    to: 6,
                                    colour: "#f00",
                                },
                            ],
                        }),
                    ],
                }),
            );

        it("labels the band at its foot, in muted ink, on the first instrument row", () => {
            const [rect] = drawn();
            expect(rect.type).toBe("rect");
            expect(rect.fillcolor).toBe("#f00");
            expect(rect.label).toMatchObject({
                text: "Compton",
                textposition: "bottom center",
                textangle: 0,
                xanchor: "center",
                yanchor: "bottom",
                padding: 17,
            });
            expect(rect.label?.font?.color).toBe("#666");
        });

        it("shares the instrument rows with the ticks, before the escapes", () => {
            const shapes = drawn([
                { label: "éch.", energy: 5.6, kind: "escape" },
            ]);
            const [tick, rect] = shapes;
            expect(tick.y1).toBe(28);
            expect(tick.label?.text).toBe("éch.");
            expect(rect.label).toMatchObject({ xanchor: "left", padding: 17 });
        });

        it("draws the band without its label outside the range shown", () => {
            const shapes = lensShapes(
                input({
                    panels: [
                        panel("", {
                            extent: [0, 40],
                            view: { range: [20, 30] },
                            bands: [
                                {
                                    label: "Compton",
                                    from: 5,
                                    to: 6,
                                    colour: "#f00",
                                },
                            ],
                        }),
                    ],
                }),
            );
            expect(shapes).toHaveLength(1);
            expect(shapes[0].label).toBeUndefined();
        });
    });

    describe("the view a panel shows", () => {
        const ticks = (view?: LensPanel["view"], plotWidth = 640) =>
            lensShapes(
                input({
                    plotWidth,
                    panels: [
                        panel("", {
                            extent: [0, 40],
                            view,
                            instrument: [
                                { label: "a", energy: 2.31 },
                                { label: "b", energy: 2.62 },
                                { label: "c", energy: 2.9 },
                                { label: "d", energy: 30 },
                            ],
                        }),
                    ],
                }),
            );

        it("spreads the labels over the energy range shown, not over the data extent", () => {
            const whole = ticks().filter((s) => (s.x0 as number) < 5);
            expect(labelled(whole).length).toBeLessThan(3);
            const zoomed = ticks({ range: [1, 5] });
            expect(zoomed.map((s) => s.y1)).toEqual([14, 14, 14]);
            expect(labelled(zoomed)).toHaveLength(3);
        });

        it("leaves out the marks outside the range shown", () => {
            expect(ticks({ range: [1, 5] }).map((s) => s.x0)).toEqual([
                2.31, 2.62, 2.9,
            ]);
            expect(ticks({ range: [5, 1] }).map((s) => s.x0)).toEqual([
                2.31, 2.62, 2.9,
            ]);
        });

        it("uses the width of the panel itself, a grid cell being narrower than the chart", () => {
            const wide = ticks({ range: [1, 5], width: 640 });
            const narrow = ticks({ range: [1, 5], width: 60 });
            expect(labelled(wide)).toHaveLength(3);
            expect(labelled(narrow).length).toBeLessThan(3);
        });

        it("lays the labels out from the right on a reversed range", () => {
            const edge = (range: [number, number]) =>
                lensShapes(
                    input({
                        plotWidth: 640,
                        panels: [
                            panel("", {
                                extent: [0, 40],
                                view: { range },
                                instrument: [{ label: "40 kV", energy: 1.05 }],
                            }),
                        ],
                    }),
                )[0].label?.xanchor;
            expect(edge([1, 5])).toBe("left");
            expect(edge([5, 1])).toBe("right");
        });

        it("maps the pixels on the range shown, padded past the data by an autorange, and keeps the marks inside the data", () => {
            const shapes = lensShapes(
                input({
                    panels: [
                        panel("", {
                            extent: [0, 40],
                            view: { range: [0, 50], width: 500 },
                            instrument: [
                                { label: "40 kV", energy: 40 },
                                { label: "45 kV", energy: 45 },
                            ],
                        }),
                    ],
                }),
            );
            expect(shapes.map((s) => s.x0)).toEqual([40]);
            expect(shapes[0].label?.xanchor).toBe("center");
        });

        it("falls back to the data extent when the range is empty or outside it", () => {
            expect(ticks({ range: [50, 60] }).map((s) => s.x0)).toEqual(
                ticks().map((s) => s.x0),
            );
        });

        it("leaves out the lines outside the range shown", () => {
            const shapes = lensShapes(
                input({
                    panels: [panel("", { view: { range: [1, 5] } })],
                    focus: [
                        {
                            hue: 0,
                            lines: [
                                { energy: 2, label: "a", intensity: 1 },
                                { energy: 10, label: "b", intensity: 1 },
                            ],
                        },
                    ],
                }),
            );
            expect(shapes.map((s) => s.x0)).toEqual([2]);
        });
    });

    describe("the cap", () => {
        /** A plot too narrow for any label: one shape per mark. */
        const PLOT_PX = 2;

        it("sheds the weakest lines of the biggest family first, keeps every instrument tick and counts what it left out", () => {
            const focus = Array.from({ length: 300 }, (_, i) => ({
                energy: 1 + i * 0.05,
                label: `F${i}`,
                intensity: i / 300,
            }));
            const lens = Array.from({ length: 30 }, (_, i) => ({
                energy: 1 + i * 0.1,
                label: `L${i}`,
                intensity: 1,
            }));
            const { shapes, dropped } = lensDrawing(
                input({
                    plotWidth: PLOT_PX,
                    panels: [
                        panel("", {
                            declared: Array.from({ length: 5 }, (_, i) => ({
                                symbol: `D${i}`,
                                energy: 2 + i,
                                rank: 2,
                            })),
                            instrument: Array.from({ length: 10 }, (_, i) => ({
                                label: "Σ",
                                energy: 1 + i,
                            })),
                            bands: [
                                {
                                    label: "Compton",
                                    from: 1,
                                    to: 2,
                                    colour: "#f00",
                                },
                            ],
                        }),
                    ],
                    focus: [{ hue: 0, lines: focus }],
                    elements: [{ symbol: "Pb", lines: lens }],
                    overlaps: [{ from: 3, to: 4, hue: 1, symbol: "Fe" }],
                }),
            );
            expect(shapes).toHaveLength(MAX_LENS_SHAPES);
            expect(dropped).toBe(28);
            const focusLeft = shapes.filter((s) => s.line?.color === "#a00");
            expect(focusLeft).toHaveLength(272);
            expect(
                Math.min(...focusLeft.map((s) => s.x0 as number)),
            ).toBeCloseTo(1 + 28 * 0.05, 6);
            expect(
                shapes.filter((s) => s.line?.color === "#c2410c" && s.y1 === 1),
            ).toHaveLength(30);
            expect(shapes.filter((s) => s.yanchor === 0)).toHaveLength(10);
            expect(shapes.filter((s) => s.yanchor === 1)).toHaveLength(5);
            expect(shapes.filter((s) => s.type === "rect")).toHaveLength(2);
        });

        it("never empties a family and sheds the dashed lines before the solid ones", () => {
            const focus = [
                ...Array.from({ length: 60 }, (_, i) => ({
                    energy: 1 + i * 0.1,
                    label: `S${i}`,
                    intensity: 1,
                })),
                ...Array.from({ length: 270 }, (_, i) => ({
                    energy: 8 + i * 0.04,
                    label: `W${i}`,
                    intensity: 0.1,
                })),
            ];
            const { shapes, dropped } = lensDrawing(
                input({
                    plotWidth: PLOT_PX,
                    focus: [{ hue: 0, lines: focus }],
                    elements: [
                        {
                            symbol: "Pb",
                            lines: [
                                { energy: 19, label: "Pb", intensity: 0.1 },
                            ],
                        },
                    ],
                }),
            );
            expect(dropped).toBe(11);
            expect(shapes).toHaveLength(MAX_LENS_SHAPES);
            expect(shapes.some((s) => s.x0 === 19)).toBe(true);
            expect(shapes.filter((s) => s.line?.dash === "solid")).toHaveLength(
                60,
            );
        });

        it("sheds evenly across panels, never leaving a panel without the declared ticks the others keep", () => {
            const suffixes = ["", "2", "3", "4", "5", "6", "7", "8", "9"];
            const { shapes, dropped } = lensDrawing(
                input({
                    plotWidth: 300,
                    bandRows: 1,
                    panels: suffixes.map((suffix) =>
                        panel(suffix, {
                            declared: Array.from({ length: 40 }, (_, i) => ({
                                symbol: `D${i}`,
                                energy: 1 + i * 0.4,
                                rank: 0,
                            })),
                        }),
                    ),
                }),
            );
            expect(dropped).toBe(40);
            const counts = suffixes.map(
                (suffix) =>
                    shapes.filter((s) => s.xref === `x${suffix}`).length,
            );
            expect(Math.min(...counts)).toBeGreaterThan(0);
            expect(Math.max(...counts) - Math.min(...counts)).toBeLessThan(2);
        });

        it("sheds the same lines from every panel, so a line shown in one panel is shown in the others", () => {
            const suffixes = ["", "2", "3", "4", "5", "6", "7", "8", "9"];
            const lines = Array.from({ length: 40 }, (_, i) => ({
                energy: 1 + i * 0.4,
                label: `L${i}`,
                intensity: 1,
            }));
            const { shapes } = lensDrawing(
                input({
                    plotWidth: PLOT_PX,
                    panels: suffixes.map((suffix) => panel(suffix)),
                    elements: [{ symbol: "Pb", lines }],
                }),
            );
            const energies = suffixes.map((suffix) =>
                shapes
                    .filter((s) => s.xref === `x${suffix}`)
                    .map((s) => s.x0 as number),
            );
            const counts = energies.map((list) => list.length);
            expect(Math.max(...counts) - Math.min(...counts)).toBeLessThan(2);
            const shortest = Math.min(...counts);
            for (const list of energies) {
                expect(list.slice(0, shortest)).toEqual(
                    energies[0].slice(0, shortest),
                );
            }
        });

        it("reports nothing left out under the cap", () => {
            expect(
                lensDrawing(
                    input({
                        focus: [
                            {
                                hue: 0,
                                lines: [
                                    { energy: 5, label: "a", intensity: 1 },
                                ],
                            },
                        ],
                    }),
                ).dropped,
            ).toBe(0);
        });
    });
});
