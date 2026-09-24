import type { Config, Layout } from "plotly.js";

const TRANSPARENT = "rgba(0,0,0,0)";
const SERIES = 8;

export interface PlotTheme {
    series: string[];
    ink: string;
    inkMuted: string;
    border: string;
    background: string;
    fontBody: string;
    fontMono: string;
}

/** The subset of Plotly the theme helpers call; the real module satisfies it. */
export interface PlotlyLike {
    relayout(
        element: HTMLElement,
        update: Record<string, unknown>,
    ): Promise<unknown>;
}

/** Colours and fonts of the charts, read from the CSS variables of `_ms-chrome.scss` (§10.1). */
export function readPlotTheme(
    root: Element = document.documentElement,
): PlotTheme {
    const computed = getComputedStyle(root);
    const token = (name: string, fallback: string): string =>
        (
            computed.getPropertyValue(name) ||
            (root as HTMLElement).style?.getPropertyValue(name) ||
            fallback
        ).trim();
    return {
        series: Array.from({ length: SERIES }, (_, index) =>
            token(`--series-${index + 1}`, "#1a1a2e"),
        ),
        ink: token("--ink", "#1a1a2e"),
        inkMuted: token("--ink-muted", "#4a4a5e"),
        border: token("--border", "rgba(26,26,46,0.07)"),
        background: token("--bg", "#faf9f7"),
        fontBody: token("--font-body", "Sora, system-ui, sans-serif"),
        fontMono: token("--font-mono", "JetBrains Mono, monospace"),
    };
}

/** A1…A8 take the series colours in order; A9…A30 and unslotted curves are drawn in ink. */
export function seriesColour(theme: PlotTheme, slot: number | null): string {
    return slot !== null && slot >= 0 && slot < SERIES
        ? theme.series[slot]
        : theme.ink;
}

/** Plotly `separators`: decimal mark then thousands mark. */
export function separatorsFor(lang: string): string {
    return lang.toLowerCase().startsWith("fr") ? ", " : ".,";
}

export function plotLayout(
    theme: PlotTheme,
    options: {
        lang: string;
        xTitle: string;
        yTitle: string;
        xReversed: boolean;
        legend?: boolean;
    },
): Partial<Layout> {
    const axisFont = {
        family: theme.fontBody,
        size: 12,
        color: theme.inkMuted,
    };
    const tickFont = {
        family: theme.fontMono,
        size: 11,
        color: theme.inkMuted,
    };
    return {
        paper_bgcolor: TRANSPARENT,
        plot_bgcolor: TRANSPARENT,
        font: { family: theme.fontBody, color: theme.ink },
        separators: separatorsFor(options.lang),
        hovermode: "x unified",
        hoverlabel: {
            bgcolor: theme.background,
            bordercolor: theme.border,
            font: { family: theme.fontMono, color: theme.ink },
        },
        margin: { l: 56, r: 16, t: 16, b: 48 },
        showlegend: options.legend ?? false,
        legend: {
            orientation: "h",
            x: 0,
            y: -0.25,
            font: { family: theme.fontBody, size: 12, color: theme.ink },
        },
        xaxis: {
            title: { text: options.xTitle, font: axisFont },
            tickfont: tickFont,
            showgrid: false,
            zeroline: false,
            linecolor: theme.border,
            autorange: options.xReversed ? "reversed" : true,
        },
        yaxis: {
            title: { text: options.yTitle, font: axisFont },
            tickfont: tickFont,
            showgrid: true,
            gridcolor: theme.border,
            zeroline: false,
        },
    };
}

export const PLOT_CONFIG: Partial<Config> = {
    displayModeBar: false,
    displaylogo: false,
    responsive: true,
};

/** Puts both axes back to their full range; a reversed x stays reversed. */
export async function resetAxes(
    plotly: PlotlyLike,
    element: HTMLElement,
    xReversed: boolean,
): Promise<void> {
    await plotly.relayout(element, {
        "xaxis.autorange": xReversed ? "reversed" : true,
        "yaxis.autorange": true,
    });
}

/** Resolves once the web fonts are loaded, so the first drawing measures Sora and JetBrains Mono. */
export function whenFontsReady(): Promise<void> {
    const fonts = (
        document as Document & { fonts?: { ready: Promise<unknown> } }
    ).fonts;
    return fonts ? fonts.ready.then(() => undefined) : Promise.resolve();
}
