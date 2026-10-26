import { elementColour } from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/xrf/element-colour.ts";
import {
    escapePlotlyText,
    monoGlyphWidth,
} from "@/manuspectrum/pages/AnalysisExplorer/xy/plot-theme.ts";

import type { InstrumentKind } from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/xrf/identify.ts";
import type { PlotTheme } from "@/manuspectrum/pages/AnalysisExplorer/xy/plot-theme.ts";

import type { Shape } from "plotly.js";

export type LensShape = Partial<Shape>;

/** Most shapes one window carries; beyond it `lensDrawing` sheds marks (`shed`). */
export const MAX_LENS_SHAPES = 320;

const TICK_PX = 14;
const MAJOR_INTENSITY = 0.5;
const OVERLAP_OPACITY = 0.22;
/** An overlap is a few tens of eV wide: its centre line keeps it visible on a wide range. */
const OVERLAP_RULE_WIDTH = 4;
const OVERLAP_RULE_OPACITY = 0.5;
const COMPTON_OPACITY = 0.12;
export const LABEL_SIZE = 11;
/** The height one row of labels takes above its tick tip, and the step between two rows. */
export const ROW_STEP_PX = 14;
/** Plotly's default `label.padding`: the room between a label and the point it anchors on. */
const LABEL_PAD_PX = 3;
/** The room one row of band labels takes above the plot edge, its pad included. */
export const BAND_ROW_PX = ROW_STEP_PX + LABEL_PAD_PX;
/** Rows of the band above the plot area of a stacked chart (declared, line and marker labels), and the room the band takes. */
export const TOP_BAND_ROWS = 2;
export const TOP_BAND_PX = TOP_BAND_ROWS * ROW_STEP_PX + 4;
/** Rows the instrument labels are staggered on at the foot of a panel; one on a panel narrower than `NARROW_PANEL_PX`. */
const INSTRUMENT_ROWS = 2;
const NARROW_PANEL_PX = 250;
/** The room the instrument ticks take at the foot of the plot area with `rows` rows of labels over them. */
function footBandPx(rows: number): number {
    return rows > 0 ? TICK_PX + rows * ROW_STEP_PX + LABEL_SIZE : TICK_PX;
}
/** Width of one glyph of a label, and the gap kept between two labels on a row. */
const GLYPH_PX = monoGlyphWidth(LABEL_SIZE);
const LABEL_GAP_PX = 4;
/** The room kept between a label and a stroke rising past its row. */
const STROKE_GAP_PX = 2;
/** An instrument word already placed within this distance is not placed again. */
const REPEAT_PX = 60;
/** A declared tick and a line this close (keV) are the same line of the table. */
const SAME_LINE_KEV = 1e-6;
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
    /** « Fe Kα1 »: the symbol, a space, the line. */
    label: string;
    intensity: number;
}

/** A pinned element's lines, in the hue of its focus slot. */
export interface FocusLines {
    /** The focus slot hue (0 to 3); out of the palette (-1), the element's own hue takes over. */
    hue: number;
    /** The element, for its own hue when `hue` names no slot. */
    symbol?: string;
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

/** What makes an instrument tick (the Compton band is an `EnergyBand`); a tick without one ranks with the escapes. */
export type TickKind = Exclude<InstrumentKind, "compton">;

/** A dotted bottom tick in muted ink: one per distinct energy, whatever curves carry it. */
export interface InstrumentTick {
    label: string;
    energy: number;
    kind?: TickKind;
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
    /**
     * What the panel shows now, when the reader knows it: the energy range
     * (keV, inside `extent`; reversed when the axis is) and the plot width
     * (px). The labels are spread over this range and this width, and a mark
     * outside the range is left out.
     */
    view?: { range?: [number, number]; width?: number };
    declared: DeclaredTick[];
    instrument: InstrumentTick[];
    bands: EnergyBand[];
}

/** The energy a peak is being identified at: one dashed ink line across every panel that holds it, in front of every other shape. */
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
    /** Width in pixels of a panel's plot area; sets how many labels fit side by side. */
    plotWidth?: number;
    /** Drawn last, so in front of every other shape, and never dropped by the cap. */
    marker?: IdentifiedMarker;
    /** Rows of the band above the plot area; `TOP_BAND_ROWS` when absent. */
    bandRows?: number;
}

/** The shapes of the lens and how many marks the cap left out. */
export interface LensDrawing {
    shapes: LensShape[];
    dropped: number;
    /** The height (px) the instrument ticks and band labels take at the foot of the tallest panel; 0 when there are none. */
    footPx: number;
}

/** What the cap sheds between: it never empties a family, and never touches the instrument ticks or the marker. */
type Family =
    | "focus"
    | "lens"
    | "declared"
    | "instrument"
    | "band"
    | "overlap"
    | "marker";

interface Entry {
    family: Family;
    /** The position of its panel in `LensShapesInput.panels`. */
    panel: number;
    /** Within a family, the lowest is shed first. */
    weight: number;
    shapes: LensShape[];
}

/** The families with droppable entries are tried biggest first; at equal size, in this order. */
const SHED_ORDER: readonly Family[] = [
    "lens",
    "focus",
    "declared",
    "overlap",
    "band",
];

/** A label wanting a place on the rows of a band. */
interface BandItem {
    /** Pixels from the left edge of the plot area. */
    x: number;
    text: string;
    /** A shorter text, tried once every full text has been placed. */
    short?: string;
    /** The lowest is placed first. */
    priority: number;
    /** Whether a stroke rises from the plot edge to the label's row (a tick, a stub); a band's label has none. */
    stroke: boolean;
}

type Anchor = "left" | "center" | "right";

/** Where a label landed: its row (0 against the plot), its text (the full or the short one) and its anchor. */
interface Placed {
    row: number;
    text: string;
    xanchor: Anchor;
}

interface Held {
    /** The item placed. */
    index: number;
    text: string;
    row: number;
    x: number;
    lo: number;
    hi: number;
    xanchor: Anchor;
    stroke: boolean;
}

const RANK_DASH = ["solid", "dash", "dot"] as const;
const INSTRUMENT_PRIORITY: Record<TickKind, number> = {
    rayleigh: 0,
    "duane-hunt": 1,
    escape: 3,
    sum: 4,
};
const BAND_PRIORITY = 2;
const UNKNOWN_INSTRUMENT_PRIORITY = 3;
const MARKER_PRIORITY = 0;
const DECLARED_PRIORITY = 1;
const SOLID_LINE_PRIORITY = 4;
const DASHED_LINE_PRIORITY = 5;

function inside(energy: number, extent: [number, number]): boolean {
    return energy >= extent[0] && energy <= extent[1];
}

/**
 * The energy range a panel's marks come from (`shown`: its view clipped to
 * its extent, else its extent) and the one its pixels span (`mapped`: the
 * view itself, which an autorange pads beyond the data; the extent when the
 * view is absent or outside it).
 */
function panelRanges(panel: LensPanel): {
    shown: [number, number];
    mapped: [number, number];
} {
    const range = panel.view?.range;
    if (!range) return { shown: panel.extent, mapped: panel.extent };
    const low = Math.max(Math.min(range[0], range[1]), panel.extent[0]);
    const high = Math.min(Math.max(range[0], range[1]), panel.extent[1]);
    return low < high
        ? {
              shown: [low, high],
              mapped: [
                  Math.min(range[0], range[1]),
                  Math.max(range[0], range[1]),
              ],
          }
        : { shown: panel.extent, mapped: panel.extent };
}

function lineStyle(intensity: number): { width: number; dash: string } {
    return intensity >= MAJOR_INTENSITY
        ? { width: 1.5, dash: "solid" }
        : { width: 1, dash: "dash" };
}

/** A horizontal label at the end of a vertical shape, `xanchor` on its energy. */
function label(
    text: string,
    colour: string,
    theme: LensTheme,
    xanchor: Anchor,
    placing: Record<string, unknown> = {},
): LensShape["label"] {
    return {
        text: escapePlotlyText(text),
        textposition: "end",
        textangle: 0,
        xanchor,
        yanchor: "bottom",
        font: { family: theme.fontMono, size: LABEL_SIZE, color: colour },
        ...placing,
    } as LensShape["label"];
}

function fullLine(
    panel: LensPanel,
    energy: number,
    colour: string,
    style: { width: number; dash: string },
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
    };
}

/**
 * A short line against the top or the bottom edge of the panel.
 *
 * A bottom tick keeps `TICK_PX` inside the plot and rises `row` steps higher,
 * its label horizontal above its tip. A top tick keeps `reach` pixels inside
 * the plot (`TICK_PX` for a declared tick, nothing for the stub of a line
 * already drawn across the plot) and, on `row` 1 and beyond, rises `row`
 * steps above the plot into the band, where its label sits above the tip.
 * A `null` text draws the tick alone.
 */
function tick(
    panel: LensPanel,
    energy: number,
    top: boolean,
    colour: string,
    style: { width: number; dash: string },
    text: string | null,
    theme: LensTheme,
    row = 0,
    xanchor: Anchor = "center",
    reach = TICK_PX,
): LensShape {
    const shape: LensShape = {
        type: "line",
        layer: "above",
        xref: `x${panel.suffix}` as LensShape["xref"],
        yref: `y${panel.suffix} domain` as LensShape["yref"],
        x0: energy,
        x1: energy,
        ysizemode: "pixel",
        yanchor: top ? 1 : 0,
        y0: top && reach > 0 ? -reach : 0,
        y1: top ? row * ROW_STEP_PX : TICK_PX + row * ROW_STEP_PX,
        line: { color: colour, width: style.width, dash: style.dash as "dash" },
    };
    if (text !== null) shape.label = label(text, colour, theme, xanchor);
    return shape;
}

/** The pixel box of a label and the anchor that puts it there. */
interface Fit {
    lo: number;
    hi: number;
    xanchor: Anchor;
}

/**
 * The boxes a label `width` px wide may take on `x`, inside a plot
 * `plotWidth` px wide, in order of preference: centred on `x`, then starting
 * `LABEL_PAD_PX` right of it, then ending `LABEL_PAD_PX` left of it (as
 * Plotly pads an anchored label). None when it is wider than the plot.
 */
function fits(x: number, width: number, plotWidth: number): Fit[] {
    const half = width / 2;
    const candidates: Fit[] = [
        { lo: x - half, hi: x + half, xanchor: "center" },
        { lo: x + LABEL_PAD_PX, hi: x + LABEL_PAD_PX + width, xanchor: "left" },
        {
            lo: x - LABEL_PAD_PX - width,
            hi: x - LABEL_PAD_PX,
            xanchor: "right",
        },
    ];
    return candidates.filter((fit) => fit.lo >= 0 && fit.hi <= plotWidth);
}

/** Whether two boxes on one row keep `LABEL_GAP_PX` between them. */
function apart(one: Fit, other: Fit): boolean {
    return (
        one.hi + LABEL_GAP_PX <= other.lo || other.hi + LABEL_GAP_PX <= one.lo
    );
}

/** Whether a stroke on `x` runs through `fit`, `STROKE_GAP_PX` around it included. */
function crosses(x: number, fit: Fit): boolean {
    return x > fit.lo - STROKE_GAP_PX && x < fit.hi + STROKE_GAP_PX;
}

/**
 * Where each item's label goes on `rowCount` rows over a plot `plotWidth`
 * px wide, null when it fits nowhere. Items go by priority, then by `x`,
 * every full text before any short one, each on the lowest row and first
 * of its `fits` where it touches no label of that row, no stroke from a
 * higher row crosses it, and its own stroke crosses at most one lower
 * label, which then moves to a fit that frees the stroke. A text already
 * placed within `repeatPx` of the item is not placed again (0: never).
 */
function placeLabels(
    items: readonly BandItem[],
    rowCount: number,
    plotWidth: number,
    repeatPx: number,
): (Placed | null)[] {
    const held: Held[] = [];
    const placed: (Placed | null)[] = items.map(() => null);
    const order = items
        .map((_, index) => index)
        .sort(
            (a, b) =>
                items[a].priority - items[b].priority ||
                items[a].x - items[b].x,
        );
    /** Whether `fit` on `row` touches no label of that row and no stroke from a higher row, `except` left out. */
    const clearOf = (fit: Fit, row: number, except: Held | null): boolean =>
        held.every(
            (other) =>
                other === except ||
                (other.row === row
                    ? apart(fit, other)
                    : other.row < row ||
                      !other.stroke ||
                      !crosses(other.x, fit)),
        );
    /** The lower labels the stroke of a mark on `x` rising to `row` would cross. */
    const crossed = (x: number, row: number): Held[] =>
        held.filter((other) => other.row < row && crosses(x, other));
    /** Moves `blocker` to a fit of its own that `x` is outside of; false when it has none. */
    const stepAside = (blocker: Held, x: number): boolean => {
        const width = blocker.hi - blocker.lo;
        for (const fit of fits(blocker.x, width, plotWidth)) {
            if (fit.xanchor === blocker.xanchor || crosses(x, fit)) continue;
            if (!clearOf(fit, blocker.row, blocker)) continue;
            blocker.lo = fit.lo;
            blocker.hi = fit.hi;
            blocker.xanchor = fit.xanchor;
            placed[blocker.index] = {
                row: blocker.row,
                text: blocker.text,
                xanchor: fit.xanchor,
            };
            return true;
        }
        return false;
    };
    const tryText = (index: number, text: string): void => {
        const item = items[index];
        if (
            repeatPx > 0 &&
            held.some(
                (other) =>
                    other.text === text &&
                    Math.abs(other.x - item.x) < repeatPx,
            )
        ) {
            return;
        }
        for (let row = 0; row < rowCount; row++) {
            for (const fit of fits(item.x, text.length * GLYPH_PX, plotWidth)) {
                if (!clearOf(fit, row, null)) continue;
                const blockers = item.stroke ? crossed(item.x, row) : [];
                if (blockers.length > 1) continue;
                if (blockers.length === 1 && !stepAside(blockers[0], item.x)) {
                    continue;
                }
                held.push({
                    index,
                    text,
                    row,
                    x: item.x,
                    lo: fit.lo,
                    hi: fit.hi,
                    xanchor: fit.xanchor,
                    stroke: item.stroke,
                });
                placed[index] = { row, text, xanchor: fit.xanchor };
                return;
            }
        }
    };
    for (const index of order) tryText(index, items[index].text);
    for (const index of order) {
        const { short, text } = items[index];
        if (placed[index] === null && short !== undefined && short !== text) {
            tryText(index, short);
        }
    }
    return placed;
}

function band(
    panel: LensPanel,
    from: number,
    to: number,
    colour: string,
    opacity: number,
): LensShape | null {
    const x0 = Math.max(from, panel.extent[0]);
    const x1 = Math.min(to, panel.extent[1]);
    if (!(x1 > x0)) return null;
    return {
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
}

function overlapShapes(
    panel: LensPanel,
    entry: OverlapBand,
    theme: LensTheme,
): LensShape[] {
    const colour = theme.focus[entry.hue] ?? elementColour(theme, entry.symbol);
    const rect = band(panel, entry.from, entry.to, colour, OVERLAP_OPACITY);
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

/** A line the panel draws across its plot, with what its label says. */
interface LineEntry {
    family: "focus" | "lens";
    energy: number;
    label: string;
    intensity: number;
    colour: string;
    style: { width: number; dash: string };
}

function lineEntries(
    input: LensShapesInput,
    shown: [number, number],
): LineEntry[] {
    const { theme } = input;
    const entries: LineEntry[] = [];
    for (const group of input.focus) {
        const colour =
            theme.focus[group.hue] ??
            (group.symbol ? elementColour(theme, group.symbol) : theme.ink);
        for (const line of group.lines) {
            if (!inside(line.energy, shown)) continue;
            entries.push({
                family: "focus",
                energy: line.energy,
                label: line.label,
                intensity: line.intensity,
                colour,
                style: group.preview
                    ? { width: 1, dash: "dash" }
                    : lineStyle(line.intensity),
            });
        }
    }
    for (const group of input.elements) {
        for (const line of group.lines) {
            if (!inside(line.energy, shown)) continue;
            entries.push({
                family: "lens",
                energy: line.energy,
                label: line.label,
                intensity: line.intensity,
                colour: elementColour(theme, group.symbol),
                style: lineStyle(line.intensity),
            });
        }
    }
    return entries;
}

/** The last word of « Fe Kα1 »: the line alone. */
function shortLabel(text: string): string {
    return text.slice(text.lastIndexOf(" ") + 1);
}

/** The entries of one panel, in drawing order. */
function panelEntries(
    input: LensShapesInput,
    panel: LensPanel,
    position: number,
): { entries: Entry[]; marker: Entry | null; footPx: number } {
    const { theme } = input;
    const { shown, mapped } = panelRanges(panel);
    const span = mapped[1] - mapped[0];
    const width = panel.view?.width ?? input.plotWidth ?? DEFAULT_PLOT_PX;
    const reversed =
        panel.view?.range !== undefined &&
        panel.view.range[0] > panel.view.range[1];
    const px = (energy: number): number =>
        span > 0
            ? ((reversed ? mapped[1] - energy : energy - mapped[0]) / span) *
              width
            : 0;
    const entries: Entry[] = [];

    const lines = lineEntries(input, shown);
    const declared = panel.declared.filter((entry) =>
        inside(entry.energy, shown),
    );
    const twins = declared.map((entry) =>
        lines.findIndex(
            (line) =>
                Math.abs(line.energy - entry.energy) < SAME_LINE_KEV &&
                line.label.startsWith(`${entry.symbol} `),
        ),
    );
    const twinned = new Set(twins.filter((index) => index >= 0));
    const marker =
        input.marker && inside(input.marker.energy, shown)
            ? input.marker
            : null;
    const top: BandItem[] = [];
    if (marker) {
        top.push({
            x: px(marker.energy),
            text: marker.label,
            priority: MARKER_PRIORITY,
            stroke: false,
        });
    }
    const declaredFrom = top.length;
    declared.forEach((entry, index) => {
        const twin = twins[index];
        top.push({
            x: px(entry.energy),
            text: twin >= 0 ? lines[twin].label : entry.symbol,
            ...(twin >= 0 ? { short: entry.symbol } : {}),
            priority: DECLARED_PRIORITY + Math.min(Math.max(entry.rank, 0), 2),
            stroke: true,
        });
    });
    const lineItems = new Map<number, number>();
    lines.forEach((line, index) => {
        if (twinned.has(index)) return;
        lineItems.set(index, top.length);
        top.push({
            x: px(line.energy),
            text: line.label,
            short: shortLabel(line.label),
            priority:
                line.style.dash === "solid"
                    ? SOLID_LINE_PRIORITY
                    : DASHED_LINE_PRIORITY + (1 - line.intensity),
            stroke: true,
        });
    });
    const topPlaced = placeLabels(
        top,
        input.bandRows ?? TOP_BAND_ROWS,
        width,
        0,
    );

    lines.forEach((line, index) => {
        const item = lineItems.get(index);
        const placed = item === undefined ? null : topPlaced[item];
        const shapes = [fullLine(panel, line.energy, line.colour, line.style)];
        if (placed && placed.row === 0) {
            shapes[0].label = label(
                placed.text,
                line.colour,
                theme,
                placed.xanchor,
            );
        } else if (placed) {
            shapes.push(
                tick(
                    panel,
                    line.energy,
                    true,
                    line.colour,
                    line.style,
                    placed.text,
                    theme,
                    placed.row,
                    placed.xanchor,
                    0,
                ),
            );
        }
        entries.push({
            family: line.family,
            panel: position,
            weight:
                line.style.dash === "solid"
                    ? 1 + line.intensity
                    : line.intensity,
            shapes,
        });
    });
    declared.forEach((entry, index) => {
        const rank = Math.min(Math.max(entry.rank, 0), 2);
        const placed = topPlaced[declaredFrom + index];
        const colour =
            entry.focusHue !== undefined && theme.focus[entry.focusHue]
                ? theme.focus[entry.focusHue]
                : elementColour(theme, entry.symbol);
        entries.push({
            family: "declared",
            panel: position,
            weight: 2 - rank,
            shapes: [
                tick(
                    panel,
                    entry.energy,
                    true,
                    colour,
                    { width: 1.5, dash: RANK_DASH[rank] },
                    placed?.text ?? null,
                    theme,
                    placed?.row ?? 0,
                    placed?.xanchor,
                ),
            ],
        });
    });

    const ticks = panel.instrument.filter((entry) =>
        inside(entry.energy, shown),
    );
    const bands = panel.bands.filter((entry) =>
        inside((entry.from + entry.to) / 2, shown),
    );
    const bottom: BandItem[] = [
        ...ticks.map((entry) => ({
            x: px(entry.energy),
            text: entry.label,
            priority:
                entry.kind === undefined
                    ? UNKNOWN_INSTRUMENT_PRIORITY
                    : INSTRUMENT_PRIORITY[entry.kind],
            stroke: true,
        })),
        ...bands.map((entry) => ({
            x: px((entry.from + entry.to) / 2),
            text: entry.label,
            priority: BAND_PRIORITY,
            stroke: false,
        })),
    ];
    const bottomPlaced = placeLabels(
        bottom,
        width < NARROW_PANEL_PX ? 1 : INSTRUMENT_ROWS,
        width,
        REPEAT_PX,
    );
    ticks.forEach((entry, index) => {
        const placed = bottomPlaced[index];
        entries.push({
            family: "instrument",
            panel: position,
            weight: 0,
            shapes: [
                tick(
                    panel,
                    entry.energy,
                    false,
                    theme.inkMuted,
                    { width: 1.5, dash: "dot" },
                    placed?.text ?? null,
                    theme,
                    placed?.row ?? 0,
                    placed?.xanchor,
                ),
            ],
        });
    });
    panel.bands.forEach((entry) => {
        const rect = band(
            panel,
            entry.from,
            entry.to,
            entry.colour,
            COMPTON_OPACITY,
        );
        if (!rect) return;
        const at = bands.indexOf(entry);
        const placed = at >= 0 ? bottomPlaced[ticks.length + at] : null;
        if (placed) {
            rect.label = label(
                placed.text,
                theme.inkMuted,
                theme,
                placed.xanchor,
                {
                    textposition: "bottom center",
                    padding: TICK_PX + LABEL_PAD_PX + placed.row * ROW_STEP_PX,
                },
            );
        }
        entries.push({
            family: "band",
            panel: position,
            weight: 0,
            shapes: [rect],
        });
    });
    for (const entry of input.overlaps) {
        const shapes = overlapShapes(panel, entry, theme);
        if (shapes.length > 0) {
            entries.push({
                family: "overlap",
                panel: position,
                weight: 0,
                shapes,
            });
        }
    }

    let markerEntry: Entry | null = null;
    if (marker) {
        const placed = topPlaced[0];
        const shape: LensShape = {
            ...fullLine(panel, marker.energy, theme.ink, {
                width: 1.5,
                dash: "dash",
            }),
            layer: "above",
        };
        if (placed) {
            shape.label = label(placed.text, theme.ink, theme, placed.xanchor, {
                padding: LABEL_PAD_PX + placed.row * ROW_STEP_PX,
            });
        }
        markerEntry = {
            family: "marker",
            panel: position,
            weight: 0,
            shapes: [shape],
        };
    }
    const rows = bottomPlaced.reduce(
        (most, placed) => (placed ? Math.max(most, placed.row + 1) : most),
        0,
    );
    const footPx = ticks.length + bands.length > 0 ? footBandPx(rows) : 0;
    return { entries, marker: markerEntry, footPx };
}

/**
 * The entries kept under `cap` shapes: while over it, the family with the
 * most entries (`SHED_ORDER` at a tie) sheds one entry from the panel that
 * holds most of it (the latest panel at a tie): that panel's lowest weight,
 * latest entry. A family keeps its first entry on each panel; the
 * instrument ticks and the marker are never dropped.
 */
function shed(
    entries: readonly Entry[],
    cap: number,
): { kept: Entry[]; dropped: number } {
    let total = entries.reduce((sum, entry) => sum + entry.shapes.length, 0);
    if (total <= cap) return { kept: [...entries], dropped: 0 };
    const removed = new Set<number>();
    const byFamily = new Map<Family, Map<number, number[]>>();
    entries.forEach((entry, index) => {
        if (entry.family === "instrument" || entry.family === "marker") return;
        const panels =
            byFamily.get(entry.family) ?? new Map<number, number[]>();
        panels.set(entry.panel, [...(panels.get(entry.panel) ?? []), index]);
        byFamily.set(entry.family, panels);
    });
    for (const panels of byFamily.values()) {
        for (const indices of panels.values()) {
            indices.sort(
                (a, b) => entries[a].weight - entries[b].weight || b - a,
            );
        }
    }
    const size = (panels: Map<number, number[]>): number =>
        [...panels.values()].reduce((sum, indices) => sum + indices.length, 0);
    let dropped = 0;
    while (total > cap) {
        let chosen: Map<number, number[]> | null = null;
        for (const family of SHED_ORDER) {
            const panels = byFamily.get(family);
            if (
                panels &&
                [...panels.values()].some((indices) => indices.length > 1) &&
                (chosen === null || size(panels) > size(chosen))
            ) {
                chosen = panels;
            }
        }
        let fullest: number[] | null = null;
        for (const indices of chosen?.values() ?? []) {
            if (fullest === null || indices.length >= fullest.length) {
                fullest = indices;
            }
        }
        const index =
            fullest && fullest.length > 1 ? fullest.shift() : undefined;
        if (index === undefined) break;
        removed.add(index);
        total -= entries[index].shapes.length;
        dropped += 1;
    }
    return {
        kept: entries.filter((_, index) => !removed.has(index)),
        dropped,
    };
}

/**
 * The Plotly shapes of the XRF lens for one window, and the count of marks
 * `shed` left out beyond `MAX_LENS_SHAPES`. Pure and deterministic, so that
 * `shapesKey` can skip an update.
 *
 * Every shape stays inside its panel's X extent and the range it shows
 * (`view`), sits on its panel's Y domain (no data Y axis) and never sets
 * `showlegend`. Labels are horizontal, `LABEL_SIZE` px, laid out by
 * `placeLabels` over the width shown. Above the plot, on `bandRows` rows:
 * the identified marker, the declared ticks by rank (one on its element's
 * principal line takes that line's label), then the element lines, solid
 * before dashed; a line label falls back to the line alone, then to none.
 * At the foot, on `INSTRUMENT_ROWS` rows (one under `NARROW_PANEL_PX`):
 * the instrument labels by kind and the Compton band's label; `footPx`
 * is the room they take, with the rows actually used. The marker is drawn
 * last, in front of every other shape.
 */
export function lensDrawing(input: LensShapesInput): LensDrawing {
    const entries: Entry[] = [];
    const markers: Entry[] = [];
    let footPx = 0;
    input.panels.forEach((panel, position) => {
        const built = panelEntries(input, panel, position);
        entries.push(...built.entries);
        if (built.marker) markers.push(built.marker);
        footPx = Math.max(footPx, built.footPx);
    });
    const { kept, dropped } = shed([...entries, ...markers], MAX_LENS_SHAPES);
    return { shapes: kept.flatMap((entry) => entry.shapes), dropped, footPx };
}

/** A stable string of `shapes`: equal keys mean the same drawing. */
export function shapesKey(shapes: LensShape[]): string {
    return JSON.stringify(shapes);
}
