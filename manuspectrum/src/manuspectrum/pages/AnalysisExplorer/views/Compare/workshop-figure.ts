import { slotLabel } from "@/manuspectrum/pages/AnalysisExplorer/store/basket.ts";
import {
    LABEL_GAP,
    curvePaint,
    dashOf,
    endPoint,
    extent,
    hoverModeFor,
    isColoured,
    offsetLifts,
    panelGrid,
    panelSpacing,
    spreadLabels,
} from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/workshop.ts";
import { plotLayout } from "@/manuspectrum/pages/AnalysisExplorer/xy/plot-theme.ts";

import type { Layout, PlotData } from "plotly.js";
import type {
    CurvePaint,
    CurveState,
    Extent,
} from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/workshop.ts";
import type { PlotTheme } from "@/manuspectrum/pages/AnalysisExplorer/xy/plot-theme.ts";

type Annotation = Partial<Layout["annotations"][number]>;
/** A trace with the `meta` its hover template reads (`%{meta[0]}`), which Plotly's types lack. */
export type Trace = Partial<PlotData> & { meta?: string[] };

/** One curve as the figure draws it. */
export interface FigureCurve {
    slot: number;
    /** Its rank among the files of its slot (0: the first). */
    rank: number;
    /** « A1 · file name ». */
    label: string;
    /** The name of its analysis, for a small-multiples panel. */
    analysis: string;
    x: number[];
    /** The values drawn: the series after the treatment, before any offset. */
    y: number[];
    yRange: Extent | null;
}

/** What a figure is built from: the curves and their states, in the same order, and the chart they are drawn in. */
export interface FigureInput {
    curves: readonly FigureCurve[];
    states: readonly CurveState[];
    theme: PlotTheme;
    lang: string;
    titles: { x: string; y: string; offset: string };
    xReversed: boolean;
    /** The chart element's size, in pixels (0 when unknown). */
    width: number;
    height: number;
}

export interface Figure {
    data: Trace[];
    layout: Partial<Layout>;
    /** The curve each trace shows, in trace order: grey context first, under the coloured curves. */
    order: number[];
    /** For each annotation, the curves it names; empty for an axis title. */
    follows: number[][];
    /** For each annotation, its opacity while one of its curves shows, and while none does. */
    shown: { on: number; off: number }[];
    /** The height small multiples need beyond the chart's, in pixels; null when they fit. */
    height: number | null;
}

const HOVER_FORMAT = ".4~g";
const LABEL_FONT_SIZE = 11;
const PANEL_FONT_SIZE = 10;
/** The characters a panel title keeps when the chart's width is unknown. */
const PANEL_TITLE_CHARS = 32;
const PANEL_TITLE_MIN_CHARS = 6;
/** The width of one character of the mono font at 11 px. */
const MONO_CHAR_PX = 6.6;
/** Room on the right of a stacked chart for the end-of-curve labels. */
const LABEL_ROOM = 56;
/** How far a label that moved sits from the end of its curve, in pixels, its leader line between them. */
const LABEL_LEADER = 16;
const LABEL_SHIFT = 4;
/** A label that moved less than this, in pixels, needs no leader. */
const LABEL_MOVED = 1;
/** The top and bottom room a stacked chart keeps around its plotting area, as estimated before Plotly measures it. */
const STACKED_ROOM = 56;
const PANEL_MARGIN = { l: 64, r: 16, t: 28, b: 52 };
const PANEL_X_TITLE_SHIFT = -30;
const PANEL_Y_TITLE_SHIFT = -44;
const PANEL_TITLE_DIMMED = 0.35;
const X_TICKS = 4;
const Y_TICKS = 3;
const TITLE_SIZE = 12;
const EXPORT_TITLE_SIZE = 14;
/** Room above the exported figure for its title and source line. */
export const EXPORT_TITLE_ROOM = 72;

/** Text Plotly would read as its pseudo-HTML, escaped. */
export function escapeText(text: string): string {
    return text
        .replaceAll("&", "&amp;")
        .replaceAll("<", "&lt;")
        .replaceAll(">", "&gt;");
}

function swatch(colour: string): string {
    return `<span style="color:${colour}">━</span>`;
}

export function paintOf(input: FigureInput, index: number): CurvePaint {
    return curvePaint(
        input.theme,
        input.curves[index].slot,
        input.states[index],
    );
}

/** Context curves first, drawn under the coloured ones; curve order otherwise. */
function traceOrder(curves: readonly FigureCurve[]): number[] {
    return curves
        .map((curve, index) => ({ curve, index }))
        .sort(
            (one, other) =>
                Number(isColoured(one.curve.slot)) -
                    Number(isColoured(other.curve.slot)) ||
                one.index - other.index,
        )
        .map(({ index }) => index);
}

/** A trace's line, its name for the hover and the legend of the PNG, and its current paint. */
function traceOf(input: FigureInput, index: number, hoverValue: string): Trace {
    const curve = input.curves[index];
    const paint = paintOf(input, index);
    return {
        type: "scatter",
        mode: "lines",
        x: curve.x,
        name: escapeText(curve.label),
        meta: [escapeText(curve.label)],
        hovertemplate: `%{meta[0]}: %{${hoverValue}:${HOVER_FORMAT}}<extra></extra>`,
        hoverinfo: paint.hover ? "all" : "skip",
        opacity: paint.opacity,
        // Plotly takes a dash length list (« 6px,2px »); its types list only the named dashes.
        line: {
            color: paint.colour,
            width: paint.width,
            dash: dashOf(curve.rank),
        } as PlotData["line"],
        legendgroup: `slot-${curve.slot}`,
        legendgrouptitle: { text: slotLabel(curve.slot) },
        legendrank: curve.slot,
    };
}

function baseLayout(input: FigureInput): Record<string, unknown> {
    const base = plotLayout(input.theme, {
        lang: input.lang,
        xTitle: input.titles.x,
        yTitle: input.titles.y,
        xReversed: input.xReversed,
        hovermode: hoverModeFor(input.curves.length),
    });
    return {
        ...base,
        xaxis: {
            ...base.xaxis,
            unifiedhovertitle: { text: `%{x:${HOVER_FORMAT}}` },
        },
    };
}

/**
 * The label « ━ A3 » at the visual end of the first curve of each slot in
 * colour, spread at least 12 px apart over the estimated plotting height, a
 * leader line joining a label that moved to its curve.
 */
function endLabels(
    input: FigureInput,
    ys: readonly number[][],
): { annotations: Annotation[]; follows: number[][] } {
    const { theme } = input;
    const ends = input.curves.flatMap((curve, index) => {
        if (!isColoured(curve.slot) || curve.rank > 0) return [];
        const point = endPoint(curve.x, ys[index], input.xReversed);
        return point ? [{ index, point }] : [];
    });
    const span = extent(ys.flat());
    const plotHeight = Math.max(0, input.height - STACKED_ROOM);
    const wanted = ends.map(({ point }) =>
        span && span.max > span.min
            ? plotHeight * (1 - (point.y - span.min) / (span.max - span.min))
            : plotHeight / 2,
    );
    const placed =
        plotHeight > 0
            ? spreadLabels(wanted, LABEL_GAP, { min: 0, max: plotHeight })
            : wanted;
    const annotations = ends.map(({ index, point }, rank): Annotation => {
        const slot = input.curves[index].slot;
        const shift = placed[rank] - wanted[rank];
        const moved = Math.abs(shift) >= LABEL_MOVED;
        return {
            x: point.x,
            y: point.y,
            text: `${swatch(theme.series[slot])} ${slotLabel(slot)}`,
            xanchor: "left",
            yanchor: "middle",
            font: {
                family: theme.fontMono,
                size: LABEL_FONT_SIZE,
                color: theme.ink,
            },
            ...(moved
                ? {
                      showarrow: true,
                      arrowhead: 0,
                      arrowwidth: 1,
                      arrowcolor: theme.inkMuted,
                      standoff: 2,
                      ax: LABEL_LEADER,
                      ay: shift,
                  }
                : { showarrow: false, xshift: LABEL_SHIFT }),
        };
    });
    return { annotations, follows: ends.map(({ index }) => [index]) };
}

/** Overlaid, or offset: each curve lifted above the one before it, no Y tick labels, its real values kept for the hover. */
export function stackedFigure(input: FigureInput, offset: boolean): Figure {
    const lifts = offset
        ? offsetLifts(input.curves.map((curve) => curve.yRange))
        : [];
    const ys = input.curves.map((curve, index) => {
        const lift = lifts[index] ?? 0;
        return offset ? curve.y.map((value) => value + lift) : curve.y;
    });
    const order = traceOrder(input.curves);
    const data = order.map(
        (index): Trace => ({
            ...traceOf(input, index, offset ? "customdata" : "y"),
            y: ys[index],
            ...(offset ? { customdata: input.curves[index].y } : {}),
        }),
    );
    const { annotations, follows } = endLabels(input, ys);
    const base = baseLayout(input);
    const yaxis = base.yaxis as Record<string, unknown>;
    return {
        data,
        layout: {
            ...base,
            margin: { ...(base.margin as object), r: LABEL_ROOM },
            yaxis: offset
                ? {
                      ...yaxis,
                      title: {
                          ...(yaxis.title as object),
                          text: input.titles.offset,
                      },
                      showticklabels: false,
                      ticks: "",
                      showgrid: false,
                      showspikes: false,
                  }
                : yaxis,
            annotations,
        } as Partial<Layout>,
        order,
        follows,
        shown: follows.map(() => ({ on: 1, off: 0 })),
        height: null,
    };
}

/** « ━ A5 · analysis », the analysis cut to `chars` characters. */
function panelTitle(input: FigureInput, slot: number, chars: number): string {
    const name = input.curves.find((curve) => curve.slot === slot)?.analysis;
    const text = name ?? "";
    const short = text.length > chars ? `${text.slice(0, chars - 1)}…` : text;
    const colour = isColoured(slot)
        ? input.theme.series[slot]
        : input.theme.context;
    return `${swatch(colour)} ${slotLabel(slot)} · ${escapeText(short)}`;
}

/**
 * One panel per slot, in slot order, 44 px apart across and 30 px down,
 * each at least 110 px high, its title cut to its width; the X axes zoom
 * together; one X title and one Y title for the whole grid.
 */
export function multiplesFigure(input: FigureInput): Figure {
    const { theme } = input;
    const base = baseLayout(input);
    const slots = [...new Set(input.curves.map((curve) => curve.slot))].sort(
        (one, other) => one - other,
    );
    const grid = panelGrid(slots.length, input.width);
    const margin = PANEL_MARGIN;
    const spacing = panelSpacing(
        grid,
        Math.max(0, input.width - margin.l - margin.r),
        Math.max(0, input.height - margin.t - margin.b),
    );
    const needed = spacing.height + margin.t + margin.b;
    const cellWidth =
        ((input.width - margin.l - margin.r) / grid.columns) *
        (1 - spacing.xgap);
    const titleChars =
        input.width > 0
            ? Math.max(
                  PANEL_TITLE_MIN_CHARS,
                  Math.floor(cellWidth / MONO_CHAR_PX) -
                      `━ ${slotLabel(slots[slots.length - 1])} · `.length,
              )
            : PANEL_TITLE_CHARS;
    const height = needed > input.height ? needed : null;
    const titleFont = {
        family: theme.fontBody,
        size: TITLE_SIZE,
        color: theme.ink,
    };
    const layout: Record<string, unknown> = {
        ...base,
        grid: {
            rows: grid.rows,
            columns: grid.columns,
            pattern: "independent",
            roworder: "top to bottom",
            xgap: spacing.xgap,
            ygap: spacing.ygap,
        },
        margin,
        ...(height === null ? {} : { height }),
    };
    const baseX = base.xaxis as Record<string, unknown>;
    const baseY = base.yaxis as Record<string, unknown>;
    const annotations: Annotation[] = [];
    const follows: number[][] = [];
    const shown: { on: number; off: number }[] = [];
    slots.forEach((slot, panel) => {
        const suffix = panel === 0 ? "" : String(panel + 1);
        layout[`xaxis${suffix}`] = {
            ...baseX,
            title: { text: "" },
            automargin: false,
            nticks: X_TICKS,
            tickfont: { ...(baseX.tickfont as object), size: PANEL_FONT_SIZE },
            ...(panel === 0 ? {} : { matches: "x" }),
        };
        layout[`yaxis${suffix}`] = {
            ...baseY,
            title: { text: "" },
            automargin: false,
            nticks: Y_TICKS,
            tickfont: { ...(baseY.tickfont as object), size: PANEL_FONT_SIZE },
        };
        annotations.push({
            xref: `x${suffix} domain` as Annotation["xref"],
            yref: `y${suffix} domain` as Annotation["yref"],
            x: 0,
            y: 1,
            xanchor: "left",
            yanchor: "bottom",
            showarrow: false,
            text: panelTitle(input, slot, titleChars),
            font: {
                family: theme.fontMono,
                size: LABEL_FONT_SIZE,
                color: theme.ink,
            },
        });
        follows.push(
            input.curves.flatMap((curve, index) =>
                curve.slot === slot ? [index] : [],
            ),
        );
        shown.push({ on: 1, off: PANEL_TITLE_DIMMED });
    });
    annotations.push(
        {
            xref: "paper",
            yref: "paper",
            x: 0.5,
            y: 0,
            xanchor: "center",
            yanchor: "top",
            yshift: PANEL_X_TITLE_SHIFT,
            showarrow: false,
            text: escapeText(input.titles.x),
            font: titleFont,
        },
        {
            xref: "paper",
            yref: "paper",
            x: 0,
            y: 0.5,
            xanchor: "right",
            yanchor: "middle",
            xshift: PANEL_Y_TITLE_SHIFT,
            textangle: "-90",
            showarrow: false,
            text: escapeText(input.titles.y),
            font: titleFont,
        },
    );
    follows.push([], []);
    shown.push({ on: 1, off: 1 }, { on: 1, off: 1 });
    const order = traceOrder(input.curves);
    const data = order.map((index): Trace => {
        const curve = input.curves[index];
        const panel = slots.indexOf(curve.slot);
        const suffix = panel === 0 ? "" : String(panel + 1);
        return {
            ...traceOf(input, index, "y"),
            y: curve.y,
            xaxis: `x${suffix}`,
            yaxis: `y${suffix}`,
        };
    });
    return {
        data,
        layout: { ...layout, annotations } as Partial<Layout>,
        order,
        follows,
        shown,
        height,
    };
}

/** The opacity of each annotation of `figure` under `states`: a label goes with its curve, a panel title dims with its panel. */
export function annotationOpacities(
    figure: Figure,
    states: readonly CurveState[],
): number[] {
    return figure.follows.map((curves, index) =>
        curves.length === 0 ||
        curves.some((curve) => states[curve] !== "hidden")
            ? figure.shown[index].on
            : figure.shown[index].off,
    );
}

/**
 * The figure as exported: `paints` (in trace order) applied, a hidden
 * curve kept transparent and out of the legend (a panel with no trace
 * drawn would get no axis line), on the page background, Plotly's legend
 * on the right, a title and a source line above.
 */
export function exportFigure(
    figure: Figure,
    paints: readonly CurvePaint[],
    theme: PlotTheme,
    text: { title: string; source: string },
): { data: Trace[]; layout: Partial<Layout> } {
    const data = figure.data.map((trace, position) => {
        const paint = paints[position];
        return {
            ...trace,
            opacity: paint.opacity,
            showlegend: paint.opacity > 0,
            line: { ...trace.line, color: paint.colour, width: paint.width },
        };
    });
    const margin = (figure.layout.margin ?? {}) as Record<string, number>;
    const font = { family: theme.fontBody, color: theme.ink };
    return {
        data,
        layout: {
            ...figure.layout,
            paper_bgcolor: theme.background,
            plot_bgcolor: theme.background,
            showlegend: true,
            legend: {
                orientation: "v",
                x: 1.02,
                xanchor: "left",
                y: 1,
                yanchor: "top",
                font: { ...font, size: TITLE_SIZE },
            },
            title: {
                text: escapeText(text.title),
                x: 0,
                xanchor: "left",
                xref: "paper",
                font: { ...font, size: EXPORT_TITLE_SIZE },
                subtitle: {
                    text: escapeText(text.source),
                    font: {
                        family: theme.fontBody,
                        size: LABEL_FONT_SIZE,
                        color: theme.inkMuted,
                    },
                },
            },
            margin: { ...margin, t: (margin.t ?? 0) + EXPORT_TITLE_ROOM },
        } as Partial<Layout>,
    };
}
