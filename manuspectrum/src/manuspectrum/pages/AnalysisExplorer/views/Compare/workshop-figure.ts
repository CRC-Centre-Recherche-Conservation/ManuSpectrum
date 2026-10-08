import { annotationLogY, canUseLogScale, logScaleFigure } from "utils/xy-scale";

import { slotLabel } from "@/manuspectrum/pages/AnalysisExplorer/store/basket.ts";
import {
    DIM_OPACITY,
    LABEL_GAP,
    itemCycle,
    itemHue,
    curvePaint,
    endPoint,
    extent,
    hoverModeFor,
    offsetLifts,
    panelGrid,
    panelSpacing,
    spreadLabels,
    visibleCurveCount,
} from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/workshop.ts";
import {
    closestHoverLine,
    escapePlotlyText,
    plotLayout,
    unifiedHoverLine,
} from "@/manuspectrum/pages/AnalysisExplorer/xy/plot-theme.ts";

import { DECLARED_STRIP_PX } from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/xrf/lens-shapes.ts";

import type { Layout, PlotData, Shape } from "plotly.js";
import type {
    CurvePaint,
    CurveState,
    Extent,
} from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/workshop.ts";
import type { PlotTheme } from "@/manuspectrum/pages/AnalysisExplorer/xy/plot-theme.ts";

type Annotation = Partial<Layout["annotations"][number]>;
export type Trace = Partial<PlotData>;

/** One curve as the figure draws it. */
export interface FigureCurve {
    slot: number;
    /** Its order among the curves of its window (0: the first): it picks its hue and dash. */
    order: number;
    /** Its rank among the files of its slot (0: the first); the first file of a slot gets the chart's end-of-curve label and panel-title swatch. */
    rank: number;
    /** « A1 · file name ». */
    label: string;
    /** Its file's name alone, for the hover line of a slot with several files. */
    fileName: string;
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
    /** A logarithmic Y on every Y axis; ignored in Offset and when a curve has no positive value. */
    yLog?: boolean;
    /** Layout shapes drawn over the curves, passed through as given. */
    shapes?: readonly Partial<Shape>[];
    /**
     * The chart carries the XRF lens: its counts axis never goes below zero
     * (linear Y, not Offset) and a stacked chart keeps `DECLARED_STRIP_PX`
     * more above its plot area for the declared labels.
     */
    lens?: boolean;
}

export interface Figure {
    data: Trace[];
    layout: Partial<Layout>;
    /** The curve each trace shows, in trace order (the window's order: every curve is its own hue, none drawn under another). */
    order: number[];
    /** For each annotation, the curves it names; empty for an axis title. */
    follows: number[][];
    /** For each annotation, its opacity while one of its curves shows, and while none does. */
    shown: { on: number; off: number }[];
    /** The height small multiples need beyond the chart's, in pixels; null when they fit. */
    height: number | null;
}

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

/** The stroke glyph of a hue cycle: solid, dashed, dotted. */
const SWATCH_GLYPHS = ["━", "╍", "┈"] as const;

function swatch(colour: string, order: number): string {
    return `<span style="color:${colour}">${SWATCH_GLYPHS[itemCycle(order)]}</span>`;
}

export function paintOf(input: FigureInput, index: number): CurvePaint {
    return curvePaint(input.theme, input.curves[index], input.states[index]);
}

/** The hover mode this figure draws under: unified up to the curves currently answering hover, closest beyond. */
function hoverMode(input: FigureInput): "x unified" | "closest" {
    return hoverModeFor(visibleCurveCount(input.states));
}

/**
 * A curve's short hover name: its slot alone (« A1 »), its file name added
 * (« A1 · file.csv ») only when its slot draws more than one file — the
 * slot alone cannot tell those apart.
 */
function shortLabel(input: FigureInput, index: number): string {
    const curve = input.curves[index];
    const filesInSlot = input.curves.filter(
        (other) => other.slot === curve.slot,
    ).length;
    return filesInSlot > 1
        ? `${slotLabel(curve.slot)} · ${curve.fileName}`
        : slotLabel(curve.slot);
}

/** The hovertemplate of curve `index` for `mode`; empty when the curve does not answer hover. */
function hoverTemplateOf(
    input: FigureInput,
    index: number,
    hoverValue: string,
    mode: "x unified" | "closest",
): string {
    if (!paintOf(input, index).hover) return "";
    const label = shortLabel(input, index);
    const line =
        mode === "closest"
            ? closestHoverLine(
                  label,
                  hoverValue,
                  input.titles.x,
                  input.titles.y,
              )
            : unifiedHoverLine(label, hoverValue);
    return `${line}<extra></extra>`;
}

/** A trace's line, its name for the legend of the PNG, and its current paint. */
function traceOf(
    input: FigureInput,
    index: number,
    hoverValue: string,
    mode: "x unified" | "closest",
): Trace {
    const curve = input.curves[index];
    const paint = paintOf(input, index);
    return {
        type: "scatter",
        mode: "lines",
        x: curve.x,
        name: escapePlotlyText(curve.label),
        hovertemplate: hoverTemplateOf(input, index, hoverValue, mode),
        hoverinfo: paint.hover ? "all" : "skip",
        opacity: paint.opacity,
        // Plotly takes a dash length list (« 6px,2px »); its types list only the named dashes.
        line: {
            color: paint.colour,
            width: paint.width,
            dash: paint.dash,
        } as PlotData["line"],
        // A legend group on a live trace shows as a second name line in the unified hover box.
        legendrank: curve.slot,
    };
}

/**
 * The hovertemplates of every trace, in trace order, for `mode`, restyled
 * (`XyWorkshop.vue`'s `restyle`) with the curve states and the hovermode
 * without a redraw. A curve that does not answer hover gets an empty one:
 * plotly.js-cartesian-dist 4.0.0 reads `hoverinfo: "skip"` into the
 * trace only while its `hovertemplate` is empty.
 */
export function hoverTemplatesFor(
    input: FigureInput,
    order: readonly number[],
    hoverValue: string,
    mode: "x unified" | "closest",
): string[] {
    return order.map((index) =>
        hoverTemplateOf(input, index, hoverValue, mode),
    );
}

/** Whether this figure draws a logarithmic Y: asked for, not Offset, and every curve has a positive value. */
function logY(input: FigureInput, offset: boolean): boolean {
    return (
        input.yLog === true &&
        !offset &&
        canUseLogScale(input.curves.map((curve) => ({ y: curve.y })))
    );
}

/**
 * The field a hovertemplate reads its value from: `customdata` where the
 * traces carry the real values apart from the laid ones (Offset, a log axis),
 * else `y`.
 */
export function hoverValueFor(input: FigureInput, offset: boolean): string {
    return offset || logY(input, offset) ? "customdata" : "y";
}

/** A trace laid on a log axis by the shared rule: non-positive values clamped, the real ones in `customdata` for the hover template. */
function logTrace(trace: Trace): Trace {
    const [laid] = logScaleFigure([{ y: trace.y as number[] }]).traces;
    return { ...trace, y: laid.y, customdata: laid.customdata } as Trace;
}

function shapesOf(input: FigureInput): { shapes?: Partial<Shape>[] } {
    return input.shapes ? { shapes: [...input.shapes] } : {};
}

function baseLayout(input: FigureInput): Record<string, unknown> {
    return plotLayout(input.theme, {
        lang: input.lang,
        xTitle: input.titles.x,
        yTitle: input.titles.y,
        xReversed: input.xReversed,
        hovermode: hoverMode(input),
    });
}

/**
 * The label « ━ A3 » at the visual end of the first curve of each slot in
 * colour, spread at least 12 px apart over the estimated plotting height, a
 * leader line joining a label that moved to its curve.
 */
function endLabels(
    input: FigureInput,
    ys: readonly number[][],
    log: boolean,
): { annotations: Annotation[]; follows: number[][] } {
    const { theme } = input;
    const ends = input.curves.flatMap((curve, index) => {
        if (curve.rank > 0) return [];
        const point = endPoint(curve.x, ys[index], input.xReversed);
        return point ? [{ index, point }] : [];
    });
    // On a log axis the labels are spread and placed in log10, which Plotly reads for an annotation.
    const heightOf = (value: number) =>
        log ? annotationLogY(value) ?? 0 : value;
    const span = extent(ys.flat().map(heightOf));
    const plotHeight = Math.max(0, input.height - STACKED_ROOM);
    const wanted = ends.map(({ point }) =>
        span && span.max > span.min
            ? plotHeight *
              (1 - (heightOf(point.y) - span.min) / (span.max - span.min))
            : plotHeight / 2,
    );
    const placed =
        plotHeight > 0
            ? spreadLabels(wanted, LABEL_GAP, { min: 0, max: plotHeight })
            : wanted;
    const annotations = ends.map(({ index, point }, rank): Annotation => {
        const { slot, order } = input.curves[index];
        const shift = placed[rank] - wanted[rank];
        const moved = Math.abs(shift) >= LABEL_MOVED;
        return {
            x: point.x,
            y: heightOf(point.y),
            text: `${swatch(theme.series[itemHue(order)], order)} ${slotLabel(slot)}`,
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
    // Every curve is its own hue: trace order is the window's order, none drawn under another.
    const order = input.curves.map((_, index) => index);
    const mode = hoverMode(input);
    const log = logY(input, offset);
    const data = order.map((index): Trace => {
        const trace: Trace = {
            ...traceOf(input, index, offset || log ? "customdata" : "y", mode),
            y: ys[index],
            ...(offset ? { customdata: input.curves[index].y } : {}),
        };
        return log ? logTrace(trace) : trace;
    });
    const laid = data.map((trace) => trace.y as number[]);
    const { annotations, follows } = endLabels(input, laid, log);
    const base = baseLayout(input);
    const yaxis: Record<string, unknown> = {
        ...(base.yaxis as Record<string, unknown>),
        ...(log ? { type: "log" } : {}),
        ...(input.lens && !log && !offset ? { rangemode: "tozero" } : {}),
    };
    const margin = base.margin as { t: number };
    return {
        data,
        layout: {
            ...base,
            margin: {
                ...margin,
                r: LABEL_ROOM,
                ...(input.lens ? { t: margin.t + DECLARED_STRIP_PX } : {}),
            },
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
            ...shapesOf(input),
        } as Partial<Layout>,
        order,
        follows,
        shown: follows.map(() => ({ on: 1, off: 0 })),
        height: null,
    };
}

/** « ━ A5 · analysis », the analysis cut to `chars` characters, in the hue of its first curve. */
function panelTitle(input: FigureInput, slot: number, chars: number): string {
    const index = input.curves.findIndex((curve) => curve.slot === slot);
    const text = index === -1 ? "" : input.curves[index].analysis;
    const short = text.length > chars ? `${text.slice(0, chars - 1)}…` : text;
    const order = index === -1 ? 0 : input.curves[index].order;
    const colour = input.theme.series[itemHue(order)];
    return `${swatch(colour, order)} ${slotLabel(slot)} · ${escapePlotlyText(short)}`;
}

/**
 * One panel per slot, in slot order, 44 px apart across and 46 px down,
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
        // Each panel answers its own hover box: `hoversubplots` does not link `matches` panels.
        margin,
        ...(height === null ? {} : { height }),
    };
    const baseX = base.xaxis as Record<string, unknown>;
    const baseY: Record<string, unknown> = {
        ...(base.yaxis as Record<string, unknown>),
        ...(logY(input, false) ? { type: "log" } : {}),
        ...(input.lens && !logY(input, false) ? { rangemode: "tozero" } : {}),
    };
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
            text: escapePlotlyText(input.titles.x),
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
            text: escapePlotlyText(input.titles.y),
            font: titleFont,
        },
    );
    follows.push([], []);
    shown.push({ on: 1, off: 1 }, { on: 1, off: 1 });
    const order = input.curves.map((_, index) => index);
    const mode = hoverMode(input);
    const log = logY(input, false);
    const data = order.map((index): Trace => {
        const curve = input.curves[index];
        const panel = slots.indexOf(curve.slot);
        const suffix = panel === 0 ? "" : String(panel + 1);
        const trace: Trace = {
            ...traceOf(input, index, log ? "customdata" : "y", mode),
            y: curve.y,
        };
        return {
            ...(log ? logTrace(trace) : trace),
            xaxis: `x${suffix}`,
            yaxis: `y${suffix}`,
        };
    });
    return {
        data,
        layout: {
            ...layout,
            annotations,
            ...shapesOf(input),
        } as Partial<Layout>,
        order,
        follows,
        shown,
        height,
    };
}

/** How far above the highest value the fitted Y range goes, as a share of its height. */
const FIT_HEADROOM = 0.05;
/** The decades kept on each side of a log axis whose window holds one value. */
const LOG_FLAT_PAD = 0.5;

/**
 * The relayout that fits the counts axes to the energy window `xRange`: for
 * each Y axis, from zero (or the lowest value when negative) to the highest
 * value of the curves shown there inside the window, plus `FIT_HEADROOM`;
 * on a log axis from the smallest positive value to the highest, in log10, with
 * the same share on both ends. Offset adds each curve's lift first. A curve
 * hidden by its state is ignored. `null` or a window holding no value gives
 * every axis back its autorange. A relayout of `yaxis*.range` only: no data
 * is redrawn.
 */
export function yFitUpdate(
    input: FigureInput,
    kind: "overlay" | "offset" | "multiples",
    xRange: readonly [number, number] | null,
): Record<string, unknown> {
    const offset = kind === "offset";
    const log = logY(input, offset);
    const lifts = offset
        ? offsetLifts(input.curves.map((curve) => curve.yRange))
        : [];
    const slots =
        kind === "multiples"
            ? [...new Set(input.curves.map((curve) => curve.slot))].sort(
                  (one, other) => one - other,
              )
            : [null];
    const [low, high] = xRange
        ? [Math.min(...xRange), Math.max(...xRange)]
        : [0, 0];
    const update: Record<string, unknown> = {};
    slots.forEach((slot, panel) => {
        const name = `yaxis${panel === 0 ? "" : panel + 1}`;
        let min = Infinity;
        let max = -Infinity;
        input.curves.forEach((curve, index) => {
            if (slot !== null && curve.slot !== slot) return;
            if (input.states[index] === "hidden" || !xRange) return;
            const lift = lifts[index] ?? 0;
            for (let at = 0; at < curve.x.length; at += 1) {
                const x = curve.x[at];
                const y = curve.y[at] + lift;
                if (!(x >= low && x <= high) || !Number.isFinite(y)) continue;
                if (log && !(y > 0)) continue;
                if (y < min) min = y;
                if (y > max) max = y;
            }
        });
        if (max === -Infinity || (!log && !(max > 0 || min < 0))) {
            update[`${name}.autorange`] = true;
            return;
        }
        if (log) {
            const [from, to] = [Math.log10(min), Math.log10(max)];
            const pad = to > from ? (to - from) * FIT_HEADROOM : LOG_FLAT_PAD;
            update[`${name}.range`] = [from - pad, to + pad];
            return;
        }
        const span = max > min ? max - min : Math.abs(max) || 1;
        const floor = offset || min < 0 ? min - span * FIT_HEADROOM : 0;
        update[`${name}.range`] = [floor, max + (max - floor) * FIT_HEADROOM];
    });
    return update;
}

/**
 * The opacity of each annotation of `figure` under `states`: a label goes
 * with its curve, a panel title dims with its panel; a label or title whose
 * live curves are all `"dimmed"` fades to the dim opacity like the line. A small-multiples
 * panel whose only curve is `"hidden"` (the selection, or the legend's eye
 * folded in by `effectiveStates`) keeps its axes and dims only its title,
 * empty otherwise: the panel is never dropped, which would reflow the grid
 * (`panelGrid`) and force a redraw; this needs none.
 */
export function annotationOpacities(
    figure: Figure,
    states: readonly CurveState[],
): number[] {
    return figure.follows.map((curves, index) => {
        const { on, off } = figure.shown[index];
        if (curves.length === 0) return on;
        const live = curves.filter((curve) => states[curve] !== "hidden");
        if (live.length === 0) return off;
        return live.every((curve) => states[curve] === "dimmed")
            ? Math.min(on, DIM_OPACITY)
            : on;
    });
}

/**
 * The figure as exported: `paints` (in trace order) applied, a hidden
 * curve kept transparent and out of the legend (a panel with no trace
 * drawn would get no axis line), on the page background, Plotly's legend
 * on the right grouped by slot (`legendgroup`/`legendgrouptitle`, rebuilt
 * here from `legendrank` — the live chart's traces carry neither, so the
 * interactive hover box never shows a slot as its own group title), a
 * title and a source line above.
 */
export function exportFigure(
    figure: Figure,
    paints: readonly CurvePaint[],
    theme: PlotTheme,
    text: { title: string; source: string },
    shapes?: readonly Partial<Shape>[],
): { data: Trace[]; layout: Partial<Layout> } {
    const data = figure.data.map((trace, position) => {
        const paint = paints[position];
        const slot = trace.legendrank as number;
        return {
            ...trace,
            opacity: paint.opacity,
            showlegend: paint.opacity > 0,
            legendgroup: `slot-${slot}`,
            legendgrouptitle: { text: slotLabel(slot) },
            // Plotly takes a dash length list (« 6px,2px »); its types list only the named dashes.
            line: {
                ...trace.line,
                color: paint.colour,
                width: paint.width,
                dash: paint.dash,
            } as PlotData["line"],
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
                text: escapePlotlyText(text.title),
                x: 0,
                xanchor: "left",
                xref: "paper",
                font: { ...font, size: EXPORT_TITLE_SIZE },
                subtitle: {
                    text: escapePlotlyText(text.source),
                    font: {
                        family: theme.fontBody,
                        size: LABEL_FONT_SIZE,
                        color: theme.inkMuted,
                    },
                },
            },
            margin: { ...margin, t: (margin.t ?? 0) + EXPORT_TITLE_ROOM },
            ...(shapes ? { shapes: [...shapes] } : {}),
        } as Partial<Layout>,
    };
}
