import { elementColour } from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/xrf/element-colour.ts";
import { escapePlotlyText } from "@/manuspectrum/pages/AnalysisExplorer/xy/plot-theme.ts";

import type { PlotTheme } from "@/manuspectrum/pages/AnalysisExplorer/xy/plot-theme.ts";

import type { Shape } from "plotly.js";

export type LensShape = Partial<Shape>;

/** Most shapes one window carries; the least important are dropped beyond it. */
export const MAX_LENS_SHAPES = 150;

const TICK_PX = 14;
const MAJOR_INTENSITY = 0.5;
const OVERLAP_OPACITY = 0.22;
/** An overlap is a few tens of eV wide: its centre line keeps it visible on a wide range. */
const OVERLAP_RULE_WIDTH = 4;
const OVERLAP_RULE_OPACITY = 0.5;
const COMPTON_OPACITY = 0.12;
const LABEL_SIZE = 10;
/** Rows the instrument labels are staggered on, and the height each row adds to its tick. */
const INSTRUMENT_ROWS = 3;
const ROW_STEP_PX = 14;
/** Rows of declared labels in the strip above the plot area, and the room that strip takes above it. */
export const DECLARED_ROWS = 2;
export const DECLARED_STRIP_PX = DECLARED_ROWS * ROW_STEP_PX + 4;
/** Width of one monospace glyph at `LABEL_SIZE`, and the gap kept between two labels on a row. */
const GLYPH_PX = 6.2;
const LABEL_GAP_PX = 4;
/** The panel width assumed when the caller gives none. */
const DEFAULT_PLOT_PX = 640;

/** Colours the lens draws with: the slot hues of `focus` (indexed by `hue`) and the hue of each element (`elementColour`). */
export type LensTheme = Pick<
    PlotTheme,
    "ink" | "inkMuted" | "focus" | "element" | "fontMono"
>;

/** A vertical line across the panel. `intensity` is relative (0 to 1) within its shell. */
export interface LensLine {
    energy: number;
    label: string;
    intensity: number;
}

/** A pinned element's lines, in the hue of its focus slot. */
export interface FocusLines {
    hue: number;
    /** A previewed element draws thin and dashed. */
    preview?: boolean;
    lines: LensLine[];
}

/** A lens element (any symbol, not in the focus), in its own hue. */
export interface LensElementLines {
    symbol: string;
    lines: LensLine[];
}

/** `rank`: 0 major, 1 minor, 2 trace. */
export interface DeclaredTick {
    symbol: string;
    energy: number;
    rank: number;
    /** The focus slot hue of an element the focus pins; the tick takes it, else the element's own hue. */
    focusHue?: number;
}

/** A dotted bottom tick in muted ink: one per distinct energy, whatever curves carry it. */
export interface InstrumentTick {
    label: string;
    energy: number;
}

export interface EnergyBand {
    label: string;
    from: number;
    to: number;
    colour: string;
}

export interface OverlapBand {
    from: number;
    to: number;
    /** Focus hue index of a pinned element of the pair; -1 when none is pinned. */
    hue: number;
    /** The element whose own hue draws the band when none is pinned. */
    symbol: string;
}

/**
 * One Plotly subplot. `suffix` is the axis number (`""` for the first axis,
 * `"2"` for `x2`/`y2`); in overlay there is a single panel.
 */
export interface LensPanel {
    suffix: string;
    /** X extent of the data the panel draws (keV); nothing is drawn outside it. */
    extent: [number, number];
    declared: DeclaredTick[];
    instrument: InstrumentTick[];
    bands: EnergyBand[];
}

/** The energy a peak is being identified at: one dashed ink line across every panel that holds it. */
export interface IdentifiedMarker {
    energy: number;
    label: string;
}

export interface LensShapesInput {
    panels: LensPanel[];
    focus: FocusLines[];
    elements: LensElementLines[];
    overlaps: OverlapBand[];
    theme: LensTheme;
    /** Width in pixels of a panel's plot area; sets how many instrument labels fit side by side. */
    plotWidth?: number;
    /** Drawn in front of every other shape and never dropped by the cap. */
    marker?: IdentifiedMarker;
    /**
     * Where the declared labels go: `rows` staggered rows, the first `lift`
     * pixels above the plot area. The chart keeps `DECLARED_STRIP_PX` free
     * above its plot area for the default two rows at no lift.
     */
    declaredStrip?: { rows: number; lift: number };
}

interface Ranked {
    priority: number;
    shape: LensShape;
}

const RANK_DASH = ["solid", "dash", "dot"] as const;

function inside(energy: number, extent: [number, number]): boolean {
    return energy >= extent[0] && energy <= extent[1];
}

function lineStyle(intensity: number): { width: number; dash: string } {
    return intensity >= MAJOR_INTENSITY
        ? { width: 1.5, dash: "solid" }
        : { width: 1, dash: "dash" };
}

function label(
    text: string,
    colour: string,
    theme: LensTheme,
    textposition: string,
    placing: Record<string, unknown> = {},
): LensShape["label"] {
    return {
        text: escapePlotlyText(text),
        textposition,
        font: { family: theme.fontMono, size: LABEL_SIZE, color: colour },
        ...placing,
    } as LensShape["label"];
}

function fullLine(
    panel: LensPanel,
    energy: number,
    colour: string,
    style: { width: number; dash: string },
    text: string,
    theme: LensTheme,
): LensShape {
    return {
        type: "line",
        layer: "below",
        xref: `x${panel.suffix}` as LensShape["xref"],
        yref: `y${panel.suffix} domain` as LensShape["yref"],
        x0: energy,
        x1: energy,
        y0: 0,
        y1: 1,
        line: { color: colour, width: style.width, dash: style.dash as "dash" },
        label: label(text, colour, theme, "end"),
    };
}

/**
 * A short line against the top or the bottom edge of the panel.
 *
 * A bottom tick (`row` 0 to `INSTRUMENT_ROWS - 1`) rises `row` steps higher
 * and carries its label horizontally above its tip. A top tick keeps
 * `TICK_PX` inside the plot and, on `row` 1 and beyond, rises `lift` plus
 * `row` steps above it into the strip over the plot area, where its label sits
 * horizontally above the tip. A `null` text draws the tick alone.
 */
function tick(
    panel: LensPanel,
    energy: number,
    top: boolean,
    colour: string,
    dash: string,
    text: string | null,
    theme: LensTheme,
    row = 0,
    lift = 0,
): LensShape {
    const length = TICK_PX + (top ? 0 : row * ROW_STEP_PX);
    const reach = top ? lift + row * ROW_STEP_PX : 0;
    const shape: LensShape = {
        type: "line",
        layer: "above",
        xref: `x${panel.suffix}` as LensShape["xref"],
        yref: `y${panel.suffix} domain` as LensShape["yref"],
        x0: energy,
        x1: energy,
        ysizemode: "pixel",
        yanchor: top ? 1 : 0,
        y0: top ? -length : 0,
        y1: top ? reach : length,
        line: { color: colour, width: 1.5, dash: dash as "dash" },
    };
    if (text !== null) {
        shape.label = label(text, colour, theme, "end", {
            textangle: 0,
            xanchor: "center",
            yanchor: "bottom",
        });
    }
    return shape;
}

/**
 * The row (0 to `rowCount - 1`) each tick's label takes, `null` when it
 * fits on none or repeats the text of a neighbour it would touch.
 */
function labelRows(
    texts: readonly string[],
    xs: readonly number[],
    pxPerKev: number,
    rowCount: number,
): (number | null)[] {
    interface Placed {
        text: string;
        row: number;
        lo: number;
        hi: number;
    }
    const order = xs.map((_, index) => index).sort((a, b) => xs[a] - xs[b]);
    const placed: Placed[] = [];
    const rows: (number | null)[] = xs.map(() => null);
    for (const index of order) {
        const x = xs[index] * pxPerKev;
        const half = (texts[index].length * GLYPH_PX + LABEL_GAP_PX) / 2;
        const lo = x - half;
        const hi = x + half;
        const text = texts[index];
        if (
            placed.some(
                (held) => held.text === text && held.hi > lo && hi > held.lo,
            )
        ) {
            continue;
        }
        for (let row = 0; row < rowCount; row++) {
            const clear = placed.every(
                (held) => held.row !== row || held.hi <= lo || hi <= held.lo,
            );
            if (!clear) continue;
            placed.push({ text, row, lo, hi });
            rows[index] = row;
            break;
        }
    }
    return rows;
}

function band(
    panel: LensPanel,
    from: number,
    to: number,
    colour: string,
    opacity: number,
    text: string | null,
    theme: LensTheme,
): LensShape | null {
    const x0 = Math.max(from, panel.extent[0]);
    const x1 = Math.min(to, panel.extent[1]);
    if (!(x1 > x0)) return null;
    const shape: LensShape = {
        type: "rect",
        layer: "below",
        xref: `x${panel.suffix}` as LensShape["xref"],
        yref: `y${panel.suffix} domain` as LensShape["yref"],
        x0,
        x1,
        y0: 0,
        y1: 1,
        fillcolor: colour,
        opacity,
        line: { width: 0 },
    };
    if (text) {
        shape.label = label(text, colour, theme, "top center", {
            textangle: 0,
            yanchor: "bottom",
        });
    }
    return shape;
}

function overlapShapes(
    panel: LensPanel,
    entry: OverlapBand,
    theme: LensTheme,
): LensShape[] {
    const colour = theme.focus[entry.hue] ?? elementColour(theme, entry.symbol);
    const rect = band(
        panel,
        entry.from,
        entry.to,
        colour,
        OVERLAP_OPACITY,
        null,
        theme,
    );
    if (!rect) return [];
    const centre = ((rect.x0 as number) + (rect.x1 as number)) / 2;
    const rule: LensShape = {
        type: "line",
        layer: "below",
        xref: rect.xref,
        yref: rect.yref,
        x0: centre,
        x1: centre,
        y0: 0,
        y1: 1,
        opacity: OVERLAP_RULE_OPACITY,
        line: { color: colour, width: OVERLAP_RULE_WIDTH },
    };
    return [rect, rule];
}

/**
 * The Plotly shapes of the XRF lens for one window.
 *
 * Pure and deterministic: equal input gives an equal array, so
 * `shapesKey` lets a caller skip a relayout. Every shape stays inside its
 * panel's X extent (a shape in data coordinates feeds the axis autorange), is
 * placed by `x`/`y … domain` references and never sets `showlegend` (that
 * flag turns a relayout into a full calc). Beyond `MAX_LENS_SHAPES` the least
 * important are dropped: focus lines, lens elements, declared majors, minors,
 * traces, instrument ticks, then bands; the identified `marker` is never
 * dropped. No shape reads or extends a data axis: the ticks are pixel-sized
 * on the panel's domain. The instrument labels (muted ink) are horizontal and
 * staggered on `INSTRUMENT_ROWS` rows of taller ticks by the width they need
 * at `plotWidth`; the declared labels (the element's colour) are horizontal
 * too, on `declaredStrip.rows` rows above the plot area, their tick staying in
 * the plot. A label that fits on no row is left out and its tick stays. A
 * band's label sits above its panel.
 */
export function lensShapes(input: LensShapesInput): LensShape[] {
    const { theme } = input;
    const ranked: Ranked[] = [];
    const add = (priority: number, shape: LensShape | null) => {
        if (shape) ranked.push({ priority, shape });
    };

    for (const panel of input.panels) {
        if (input.marker && inside(input.marker.energy, panel.extent)) {
            add(-1, {
                ...fullLine(
                    panel,
                    input.marker.energy,
                    theme.ink,
                    { width: 1.5, dash: "dash" },
                    input.marker.label,
                    theme,
                ),
                layer: "above",
            });
        }
        for (const group of input.focus) {
            const colour = theme.focus[group.hue] ?? theme.ink;
            for (const line of group.lines) {
                if (!inside(line.energy, panel.extent)) continue;
                const style = group.preview
                    ? { width: 1, dash: "dash" }
                    : lineStyle(line.intensity);
                add(
                    0,
                    fullLine(
                        panel,
                        line.energy,
                        colour,
                        style,
                        line.label,
                        theme,
                    ),
                );
            }
        }
        for (const group of input.elements) {
            for (const line of group.lines) {
                if (!inside(line.energy, panel.extent)) continue;
                add(
                    1,
                    fullLine(
                        panel,
                        line.energy,
                        elementColour(theme, group.symbol),
                        lineStyle(line.intensity),
                        line.label,
                        theme,
                    ),
                );
            }
        }
        const inPanel = panel.declared.filter((entry) =>
            inside(entry.energy, panel.extent),
        );
        const span = panel.extent[1] - panel.extent[0];
        const pxPerKev =
            span > 0 ? (input.plotWidth ?? DEFAULT_PLOT_PX) / span : 0;
        const strip = input.declaredStrip ?? {
            rows: DECLARED_ROWS,
            lift: 0,
        };
        const declaredRows = labelRows(
            inPanel.map((entry) => entry.symbol),
            inPanel.map((entry) => entry.energy),
            pxPerKev,
            strip.rows,
        );
        inPanel.forEach((entry, index) => {
            const rank = Math.min(Math.max(entry.rank, 0), 2);
            const row = declaredRows[index];
            add(
                2 + rank,
                tick(
                    panel,
                    entry.energy,
                    true,
                    entry.focusHue !== undefined && theme.focus[entry.focusHue]
                        ? theme.focus[entry.focusHue]
                        : elementColour(theme, entry.symbol),
                    RANK_DASH[rank],
                    row === null ? null : entry.symbol,
                    theme,
                    row ?? 0,
                    strip.lift,
                ),
            );
        });
        const shown = panel.instrument.filter((entry) =>
            inside(entry.energy, panel.extent),
        );
        const rows = labelRows(
            shown.map((entry) => entry.label),
            shown.map((entry) => entry.energy),
            pxPerKev,
            INSTRUMENT_ROWS,
        );
        shown.forEach((entry, index) => {
            const row = rows[index];
            add(
                5,
                tick(
                    panel,
                    entry.energy,
                    false,
                    theme.inkMuted,
                    "dot",
                    row === null ? null : entry.label,
                    theme,
                    row ?? 0,
                ),
            );
        });
        for (const entry of panel.bands) {
            add(
                6,
                band(
                    panel,
                    entry.from,
                    entry.to,
                    entry.colour,
                    COMPTON_OPACITY,
                    entry.label,
                    theme,
                ),
            );
        }
        for (const entry of input.overlaps) {
            for (const shape of overlapShapes(panel, entry, theme)) {
                add(6, shape);
            }
        }
    }

    if (ranked.length <= MAX_LENS_SHAPES) return ranked.map((r) => r.shape);
    const kept = ranked
        .map((entry, index) => ({ ...entry, index }))
        .sort((a, b) => a.priority - b.priority || a.index - b.index)
        .slice(0, MAX_LENS_SHAPES)
        .sort((a, b) => a.index - b.index);
    return kept.map((r) => r.shape);
}

/** A stable string of `shapes`: equal keys mean the same drawing. */
export function shapesKey(shapes: LensShape[]): string {
    return JSON.stringify(shapes);
}
