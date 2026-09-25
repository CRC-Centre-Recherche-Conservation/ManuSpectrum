import { afterEach, describe, expect, it, vi } from "vitest";

import {
    PLOT_CONFIG,
    plotLayout,
    readPlotTheme,
    resetAxes,
    separatorsFor,
    seriesColour,
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

    it("gives A1…A8 their series colour and later slots the ink", () => {
        setTokens({ "--series-3": "#6d28d9", "--ink": "#1a1a2e" });
        const theme = readPlotTheme();
        expect(seriesColour(theme, 2)).toBe("#6d28d9");
        expect(seriesColour(theme, 8)).toBe("#1a1a2e");
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

    it("restores the reversed x axis on reset", async () => {
        const plotly = { relayout: vi.fn(async () => undefined) };
        await resetAxes(plotly, document.createElement("div"), true);
        expect(plotly.relayout).toHaveBeenCalledWith(expect.any(HTMLElement), {
            "xaxis.autorange": "reversed",
            "yaxis.autorange": true,
        });
    });
});
