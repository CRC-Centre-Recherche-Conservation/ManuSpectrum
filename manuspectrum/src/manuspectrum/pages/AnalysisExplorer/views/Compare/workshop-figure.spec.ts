// @vitest-environment node
import { describe, expect, it } from "vitest";

import {
    annotationOpacities,
    exportFigure,
    multiplesFigure,
    stackedFigure,
} from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/workshop-figure.ts";

import type {
    FigureCurve,
    FigureInput,
} from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/workshop-figure.ts";
import type { PlotTheme } from "@/manuspectrum/pages/AnalysisExplorer/xy/plot-theme.ts";

const THEME: PlotTheme = {
    series: ["#111111", "#222222", "#333333"],
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

function curve(slot: number, y: number[], rank = 0, file = slot): FigureCurve {
    return {
        slot,
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
            '<span style="color:#111111">━</span> A1 · Analysis &lt;0&gt;',
        );
        expect(texts[11]).toContain('<span style="color:#999999">━</span>');
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
        const many = Array.from({ length: 7 }, (_, slot) =>
            curve(slot, [1, 2]),
        );
        const figure = stackedFigure(input(many), false);
        expect(figure.data[0].hovertemplate).toBe(
            "A1<br>x: %{x:.4~g} Energy (keV) · y: %{y:.4~g} Counts<extra></extra>",
        );
    });

    it("escapes an axis title holding pseudo-HTML under closest", () => {
        const many = Array.from({ length: 7 }, (_, slot) =>
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

    it("exports the curves shown with Plotly's legend, a title and a source line, a hidden curve out of the legend", () => {
        const figure = stackedFigure(
            input([curve(0, [1, 2]), curve(1, [1, 2])]),
            false,
        );
        const exported = exportFigure(
            figure,
            [
                { colour: "#111111", width: 2.5, opacity: 1, hover: true },
                { colour: "#222222", width: 1.5, opacity: 0, hover: false },
            ],
            THEME,
            { title: "Counts <raw>", source: "Source: ManuSpectrum" },
        );
        expect(exported.data.map((trace) => trace.showlegend)).toEqual([
            true,
            false,
        ]);
        expect(exported.data.map((trace) => trace.opacity)).toEqual([1, 0]);
        expect(exported.data[0].line).toMatchObject({ width: 2.5 });
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
});
