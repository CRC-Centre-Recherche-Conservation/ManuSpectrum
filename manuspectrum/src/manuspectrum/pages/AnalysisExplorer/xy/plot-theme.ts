import type { Config, Layout } from "plotly.js";

const TRANSPARENT = "rgba(0,0,0,0)";
const SERIES = 12;
/** Room under the plot for the legend Plotly draws below it. */
const LEGEND_ROOM = 48;
/** The number format of a hover value: 4 significant digits, no trailing zeros. */
export const HOVER_VALUE_FORMAT = ".4~g";
/**
 * Up to this many curves, "x unified" lists every one of them at the X under
 * the pointer; more falls back to "closest" (one curve, its own box).
 * plotly.js-cartesian-dist 4.0.0 has no per-mode cap on how many traces a
 * unified hover box lists, so this is the fallback once a box would grow
 * past a comfortable read (about a dozen short lines).
 */
export const UNIFIED_HOVER_MAX_CURVES = 12;

export interface PlotTheme {
    series: string[];
    /** The grey of a curve dimmed by the focus's « Dim » switch (unrelated to any pin). */
    context: string;
    ink: string;
    inkMuted: string;
    border: string;
    /** The elevated-surface border the hover label draws on `surface` (`--border-hover`). */
    borderHover: string;
    background: string;
    /** The card/popover surface the hover label draws on (`--surface`). */
    surface: string;
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
        context: token("--series-context", "#8a8999"),
        ink: token("--ink", "#1a1a2e"),
        inkMuted: token("--ink-muted", "#4a4a5e"),
        border: token("--border", "rgba(26,26,46,0.07)"),
        borderHover: token("--border-hover", "rgba(26,26,46,0.14)"),
        background: token("--bg", "#faf9f7"),
        surface: token("--surface", "#ffffff"),
        fontBody: token("--font-body", "Sora, system-ui, sans-serif"),
        fontMono: token("--font-mono", "JetBrains Mono, monospace"),
    };
}

/** A1…A12 take the series colours in order; further slots and unslotted curves are drawn in ink. */
export function seriesColour(theme: PlotTheme, slot: number | null): string {
    return slot !== null && slot >= 0 && slot < SERIES
        ? theme.series[slot]
        : theme.ink;
}

/** Plotly `separators`: decimal mark then thousands mark. */
export function separatorsFor(lang: string): string {
    return lang.toLowerCase().startsWith("fr") ? ", " : ".,";
}

/** "x unified" up to `UNIFIED_HOVER_MAX_CURVES` curves, "closest" beyond. */
export function hoverModeFor(curves: number): "x unified" | "closest" {
    return curves <= UNIFIED_HOVER_MAX_CURVES ? "x unified" : "closest";
}

/** Text Plotly would read as its pseudo-HTML (names, hover templates, annotations), escaped. */
export function escapePlotlyText(text: string): string {
    return text
        .replaceAll("&", "&amp;")
        .replaceAll("<", "&lt;")
        .replaceAll(">", "&gt;");
}

/**
 * The `unifiedhovertitle` of an "x unified" hover box: the shared x, with
 * its axis title once (English, not translated); an empty title omits the
 * « · ».
 */
export function unifiedHoverTitle(xTitle: string): { text: string } {
    const suffix = xTitle ? ` · ${escapePlotlyText(xTitle)}` : "";
    return { text: `%{x:${HOVER_VALUE_FORMAT}}${suffix}` };
}

/**
 * One compact "x unified" hover line: a curve's label and its value alone —
 * the shared x already sits in the box header. `hoverValue` names the field
 * the value is read from (`y`, or a custom field behind a transform).
 */
export function unifiedHoverLine(label: string, hoverValue: string): string {
    return `${escapePlotlyText(label)} · %{${hoverValue}:${HOVER_VALUE_FORMAT}}`;
}

/**
 * A "closest" hover line: no shared header exists there, so it carries its
 * own x and y, each with its axis title as stored.
 */
export function closestHoverLine(
    label: string,
    hoverValue: string,
    xTitle: string,
    yTitle: string,
): string {
    const xUnit = xTitle ? ` ${escapePlotlyText(xTitle)}` : "";
    const yUnit = yTitle ? ` ${escapePlotlyText(yTitle)}` : "";
    return (
        `${escapePlotlyText(label)}<br>` +
        `x: %{x:${HOVER_VALUE_FORMAT}}${xUnit} · ` +
        `y: %{${hoverValue}:${HOVER_VALUE_FORMAT}}${yUnit}`
    );
}

/**
 * The layout of an Explorer chart: transparent, ink axis titles, mono tick
 * labels outside a visible axis line, SI exponents from 10³, a horizontal
 * grid only, dotted spikes, and margins that grow to fit the labels.
 */
export function plotLayout(
    theme: PlotTheme,
    options: {
        lang: string;
        xTitle: string;
        yTitle: string;
        xReversed: boolean;
        legend?: boolean;
        hovermode?: "x unified" | "closest";
    },
): Partial<Layout> {
    const titleFont = {
        family: theme.fontBody,
        size: 12,
        color: theme.ink,
    };
    const tickFont = {
        family: theme.fontMono,
        size: 11,
        color: theme.inkMuted,
    };
    const axis = {
        tickfont: tickFont,
        automargin: true,
        ticks: "outside" as const,
        ticklen: 4,
        tickcolor: theme.inkMuted,
        showline: true,
        linecolor: theme.inkMuted,
        zeroline: false,
        exponentformat: "SI" as const,
        minexponent: 3,
        showspikes: true,
        spikemode: "across" as const,
        spikedash: "dot",
        spikethickness: 1,
        spikecolor: theme.inkMuted,
        spikesnap: "cursor" as const,
    };
    return {
        paper_bgcolor: TRANSPARENT,
        plot_bgcolor: TRANSPARENT,
        font: { family: theme.fontBody, color: theme.ink },
        separators: separatorsFor(options.lang),
        hovermode: options.hovermode ?? "x unified",
        hoverlabel: {
            bgcolor: theme.surface,
            bordercolor: theme.borderHover,
            font: { family: theme.fontMono, size: 12, color: theme.ink },
            align: "left",
        },
        margin: { l: 8, r: 16, t: 16, b: options.legend ? LEGEND_ROOM : 8 },
        showlegend: options.legend ?? false,
        legend: {
            orientation: "h",
            x: 0,
            y: -0.25,
            font: { family: theme.fontBody, size: 12, color: theme.ink },
        },
        xaxis: {
            ...axis,
            title: { text: options.xTitle, font: titleFont, standoff: 8 },
            showgrid: false,
            autorange: options.xReversed ? "reversed" : true,
            // `unifiedhovertitle` is real Plotly (the "x/y unified" box header)
            // but missing from @types/plotly.js's LayoutAxis.
            unifiedhovertitle: unifiedHoverTitle(options.xTitle),
        } as Layout["xaxis"],
        yaxis: {
            ...axis,
            title: { text: options.yTitle, font: titleFont, standoff: 8 },
            showgrid: true,
            gridcolor: theme.border,
        },
    };
}

export const PLOT_CONFIG: Partial<Config> = {
    displayModeBar: false,
    displaylogo: false,
    responsive: true,
};

/** Compare's workshop resizes its chart on its window's signal: Plotly does not follow the browser window. */
export const WORKSHOP_CONFIG: Partial<Config> = {
    ...PLOT_CONFIG,
    responsive: false,
    doubleClick: "reset",
    scrollZoom: false,
};

/**
 * Puts the axes of every panel back to their full range (`xaxis`, `yaxis`,
 * then `xaxis2`, `yaxis2`… for small multiples); a reversed x stays reversed.
 */
export async function resetAxes(
    plotly: PlotlyLike,
    element: HTMLElement,
    xReversed: boolean,
    panels = 1,
): Promise<void> {
    const update: Record<string, unknown> = {};
    for (let panel = 1; panel <= panels; panel += 1) {
        const suffix = panel === 1 ? "" : String(panel);
        update[`xaxis${suffix}.autorange`] = xReversed ? "reversed" : true;
        update[`yaxis${suffix}.autorange`] = true;
    }
    await plotly.relayout(element, update);
}

/** Resolves once the web fonts are loaded, so the first drawing measures Sora and JetBrains Mono. */
export function whenFontsReady(): Promise<void> {
    const fonts = (
        document as Document & { fonts?: { ready: Promise<unknown> } }
    ).fonts;
    return fonts ? fonts.ready.then(() => undefined) : Promise.resolve();
}
