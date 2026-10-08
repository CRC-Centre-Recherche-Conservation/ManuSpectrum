import { describe, expect, it } from "vitest";

import {
    MAX_LENS_SHAPES,
    lensShapes,
    shapesKey,
} from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/xrf/lens-shapes.ts";

import type {
    LensPanel,
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
                    elements: symbols.map((symbol) => ({
                        symbol,
                        lines: [{ energy: 6, label: symbol, intensity: 1 }],
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

    it("keeps the focus and the majors when it caps at 150", () => {
        const declared = Array.from({ length: 200 }, (_, i) => ({
            symbol: `T${i}`,
            energy: 1 + i * 0.05,
            rank: 2,
        }));
        const shapes = lensShapes(
            input({
                panels: [
                    panel("", {
                        declared: [
                            ...declared,
                            { symbol: "Major", energy: 19, rank: 0 },
                        ],
                    }),
                ],
                focus: [
                    {
                        hue: 0,
                        lines: [{ energy: 7, label: "Fe Kα1", intensity: 1 }],
                    },
                ],
            }),
        );
        expect(shapes).toHaveLength(MAX_LENS_SHAPES);
        const texts = shapes.map((s) => s.label?.text);
        expect(texts).toContain("Fe Kα1");
        expect(texts).toContain("Major");
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
                        instrument: [{ label: "i", energy: 4, colour: "#f00" }],
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
});
