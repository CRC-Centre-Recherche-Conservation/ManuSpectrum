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
                overlaps: [{ from: 19.9, to: 22, hue: 1 }],
            }),
        );
        expect(shapes).toHaveLength(2);
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

    it("draws a preview thin and dashed, in the lens ink for lens elements", () => {
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
                    { lines: [{ energy: 6, label: "b", intensity: 1 }] },
                ],
            }),
        );
        expect(shapes[0].line).toMatchObject({
            width: 1,
            dash: "dash",
            color: "#00a",
        });
        expect(shapes[1].line?.color).toBe("#111");
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
                overlaps: [{ from: 3, to: 4, hue: 0 }],
            }),
        );
        expect(shapes.length).toBe(4);
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
