import { afterEach, describe, expect, it, vi } from "vitest";

import {
    PLOT_CONFIG,
    UNIFIED_HOVER_MAX_CURVES,
    WORKSHOP_CONFIG,
    closestHoverLine,
    escapePlotlyText,
    hoverModeFor,
    plotLayout,
    readPlotTheme,
    resetAxes,
    separatorsFor,
    seriesColour,
    unifiedHoverLine,
    unifiedHoverTitle,
} from "@/manuspectrum/pages/AnalysisExplorer/xy/plot-theme.ts";

function setTokens(tokens: Record<string, string>): void {
    for (const [name, value] of Object.entries(tokens)) {
        document.documentElement.style.setProperty(name, value);
    }
}

afterEach(() => {
    document.documentElement.removeAttribute("style");
});

describe("plot theme", () => {
    it("reads the series colours and inks from the CSS variables", () => {
        setTokens({
            "--series-1": " #1d4ed8",
            "--series-8": "#be185d",
            "--ink": "#1a1a2e",
            "--bg": "#faf9f7",
        });
        const theme = readPlotTheme();
        expect(theme.series[0]).toBe("#1d4ed8");
        expect(theme.series[7]).toBe("#be185d");
        expect(theme.ink).toBe("#1a1a2e");
        expect(theme.background).toBe("#faf9f7");
    });

    it("reads the four focus hues, with the tokens' own values as fallback", () => {
        expect(readPlotTheme().focus).toEqual([
            "#3d2e8d",
            "#1e6256",
            "#93499e",
            "#760a03",
        ]);
        setTokens({ "--focus-2": "#00aa00", "--focus-4": "#aa0000" });
        const { focus } = readPlotTheme();
        expect(focus).toHaveLength(4);
        expect(focus[1]).toBe("#00aa00");
        expect(focus[3]).toBe("#aa0000");
    });

    it("reads the grey of context curves", () => {
        setTokens({ "--series-context": "#8a8999" });
        expect(readPlotTheme().context).toBe("#8a8999");
    });

    it("reads the surface and the elevated border the hover label draws on", () => {
        setTokens({
            "--surface": "#ffffff",
            "--border-hover": "rgba(26,26,46,0.14)",
        });
        const theme = readPlotTheme();
        expect(theme.surface).toBe("#ffffff");
        expect(theme.borderHover).toBe("rgba(26,26,46,0.14)");
    });

    it("styles the hover label like the app's popovers: surface, elevated border, left-aligned", () => {
        setTokens({
            "--surface": "#ffffff",
            "--border-hover": "rgba(26,26,46,0.14)",
            "--ink": "#1a1a2e",
            "--font-mono": "JetBrains Mono",
        });
        const layout = plotLayout(readPlotTheme(), {
            lang: "en",
            xTitle: "Energy (keV)",
            yTitle: "Counts",
            xReversed: false,
        });
        expect(layout.hoverlabel).toMatchObject({
            bgcolor: "#ffffff",
            bordercolor: "rgba(26,26,46,0.14)",
            align: "left",
            font: { family: "JetBrains Mono", size: 12, color: "#1a1a2e" },
        });
    });

    it("draws readable axes: ink titles, outside mono ticks, SI exponents, dotted spikes, margins made to fit", () => {
        setTokens({ "--ink": "#1a1a2e", "--font-mono": "JetBrains Mono" });
        const layout = plotLayout(readPlotTheme(), {
            lang: "en",
            xTitle: "Energy (keV)",
            yTitle: "Counts",
            xReversed: false,
            hovermode: "closest",
        });
        for (const axis of [layout.xaxis, layout.yaxis]) {
            expect(axis).toMatchObject({
                automargin: true,
                ticks: "outside",
                showline: true,
                exponentformat: "SI",
                minexponent: 3,
                showspikes: true,
                spikedash: "dot",
            });
            expect(axis?.title).toMatchObject({
                font: { size: 12, color: "#1a1a2e" },
            });
            expect(axis?.tickfont).toMatchObject({
                family: "JetBrains Mono",
                size: 11,
            });
        }
        expect(layout.hovermode).toBe("closest");
    });

    it("lets the workshop resize its chart itself, a double click resetting the zoom, no wheel zoom", () => {
        expect(WORKSHOP_CONFIG).toMatchObject({
            displayModeBar: false,
            responsive: false,
            doubleClick: "reset",
            scrollZoom: false,
        });
        expect(PLOT_CONFIG.responsive).toBe(true);
    });

    it("gives each of the twelve first positions its series colour, the next ones the colours again, and none the ink", () => {
        setTokens({ "--series-3": "#6d28d9", "--ink": "#1a1a2e" });
        const theme = readPlotTheme();
        expect(seriesColour(theme, 2)).toBe("#6d28d9");
        expect(seriesColour(theme, 12)).toBe(seriesColour(theme, 0));
        expect(seriesColour(theme, null)).toBe("#1a1a2e");
    });

    it("uses the decimal comma in French", () => {
        expect(separatorsFor("fr")).toBe(", ");
        expect(separatorsFor("en")).toBe(".,");
    });

    it("draws a transparent chart with a horizontal grid only and a reversed x when asked", () => {
        setTokens({ "--border": "rgba(26,26,46,0.07)" });
        const layout = plotLayout(readPlotTheme(), {
            lang: "fr",
            xTitle: "Énergie (keV)",
            yTitle: "Coups",
            xReversed: true,
        });
        expect(layout.paper_bgcolor).toBe("rgba(0,0,0,0)");
        expect(layout.xaxis?.showgrid).toBe(false);
        expect(layout.yaxis?.showgrid).toBe(true);
        expect(layout.xaxis?.autorange).toBe("reversed");
        expect(layout.hovermode).toBe("x unified");
        expect(layout.separators).toBe(", ");
        expect(PLOT_CONFIG.displayModeBar).toBe(false);
    });

    it("carries the shared x, with its axis title, in the unified box's header once, built into the axis", () => {
        const layout = plotLayout(readPlotTheme(), {
            lang: "en",
            xTitle: "Energy (keV)",
            yTitle: "Counts",
            xReversed: false,
        });
        expect(
            (layout.xaxis as { unifiedhovertitle?: { text?: string } })
                .unifiedhovertitle?.text,
        ).toBe("%{x:.4~g} · Energy (keV)");
        expect(unifiedHoverTitle("")).toEqual({ text: "%{x:.4~g}" });
    });

    it("hovers along X up to twelve curves, closest beyond", () => {
        expect(UNIFIED_HOVER_MAX_CURVES).toBe(12);
        expect(hoverModeFor(12)).toBe("x unified");
        expect(hoverModeFor(13)).toBe("closest");
    });

    it("escapes a hover label's pseudo-HTML the same way as an axis title", () => {
        expect(escapePlotlyText("A & B <raw>")).toBe("A &amp; B &lt;raw&gt;");
        expect(escapePlotlyText("A %{x} B")).toBe("A %&#123;x} B");
        expect(unifiedHoverLine("A %{x}", "y")).toBe("A %&#123;x} · %{y:.4~g}");
    });

    it("builds one compact line per curve under x unified, its label and value alone", () => {
        expect(unifiedHoverLine("A1", "y")).toBe("A1 · %{y:.4~g}");
        expect(unifiedHoverLine("A & B", "y")).toBe("A &amp; B · %{y:.4~g}");
    });

    it("builds a curve's own x and y line under closest, each with its axis title", () => {
        expect(closestHoverLine("A1", "y", "Energy (keV)", "Counts")).toBe(
            "A1<br>x: %{x:.4~g} Energy (keV) · y: %{y:.4~g} Counts",
        );
        expect(closestHoverLine("A1", "y", "", "")).toBe(
            "A1<br>x: %{x:.4~g} · y: %{y:.4~g}",
        );
    });

    it("restores the reversed x axis on reset", async () => {
        const plotly = { relayout: vi.fn(async () => undefined) };
        await resetAxes(plotly, document.createElement("div"), true);
        expect(plotly.relayout).toHaveBeenCalledWith(expect.any(HTMLElement), {
            "xaxis.autorange": "reversed",
            "yaxis.autorange": true,
        });
    });

    it("resets the axes of every small panel, each reversed x kept reversed", async () => {
        const plotly = { relayout: vi.fn(async () => undefined) };
        await resetAxes(plotly, document.createElement("div"), true, 2);
        expect(plotly.relayout).toHaveBeenCalledWith(expect.any(HTMLElement), {
            "xaxis.autorange": "reversed",
            "yaxis.autorange": true,
            "xaxis2.autorange": "reversed",
            "yaxis2.autorange": true,
        });
    });
});
