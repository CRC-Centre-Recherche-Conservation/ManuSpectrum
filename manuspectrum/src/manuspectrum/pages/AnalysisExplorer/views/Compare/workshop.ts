import { applyTransforms } from "utils/xy-transforms";
import { viewsFor } from "utils/xy-views";

import {
    hoverModeFor,
    UNIFIED_HOVER_MAX_CURVES,
} from "@/manuspectrum/pages/AnalysisExplorer/xy/plot-theme.ts";

import type { XyView } from "utils/xy-views";
import type { Label } from "@/manuspectrum/pages/AnalysisExplorer/api/types.ts";
import type { NodeId } from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/linked/node-id.ts";
import type { RelationLevel } from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/linked/related.ts";

export { hoverModeFor, UNIFIED_HOVER_MAX_CURVES };

/** How the XY workshop shows its curves; `table` is the accessible equivalent of the chart. */
export type WorkshopLayout = "overlay" | "offset" | "multiples" | "table";

/** Above this many curves, the workshop opens on small multiples. */
export const OVERLAY_MAX_CURVES = 8;
/** The hues of the series palette (`--series-1…12`): an item's slot cycles through them. */
export const SERIES_HUES = 12;
/** The least room between two end-of-curve labels, in pixels. */
export const LABEL_GAP = 12;

/**
 * Line styles in order of use: the first three mark the cycles of an item's
 * hue (solid, dashed, dotted), the others the 2nd, 3rd… file of one item.
 */
const DASHES = [
    "solid",
    "6px,2px",
    "2px,2px",
    "10px,2px,2px,2px",
    "14px,3px",
    "4px,2px",
    "8px,2px,2px,2px,2px,2px",
    "12px,4px",
    "1px,3px",
] as const;
/** The line styles that mark the cycles of a hue. */
const CYCLES = 3;

const MAX_COLUMNS = 4;
const MIN_PANEL_WIDTH = 220;
const MIN_PANEL_HEIGHT = 110;
const PANEL_GAP_X = 44;
/** The room between two rows of panels: the X tick labels of the upper one, then the title of the lower one. */
const PANEL_GAP_Y = 46;
const LINE_WIDTH = 1.5;
const CONTEXT_WIDTH = 1.25;
const EMPHASIS_WIDTH = 2.5;
/** The opacity of a curve dimmed for being unrelated to the focus (« Dim »): the legend's `.unrelated` swatch opacity. */
export const DIM_OPACITY = 0.35;
/** The room between two offset curves, as a share of the widest curve's span. */
const OFFSET_GAP = 0.1;
/** A spreadsheet opens a CSV starting with the UTF-8 byte order mark as UTF-8. */
const UTF8_BOM = "\ufeff";
/** A cell a spreadsheet splitting on `,` or `;` would read as a formula, spaces first included (`views/explorer/series.py` `_FORMULA_CELL`). */
const FORMULA_CELL = /(^|[,;])([ ]*[=+\-@\t\r])/g;
const FIRST_PRINTABLE = 0x20;
const DELETE = 0x7f;

export type Dash = (typeof DASHES)[number];

/**
 * How a curve shows the linked selection: as drawn when nothing is
 * selected, emphasised when the selection or the preview links it, hidden
 * or dimmed (« Dim ») when a selection links it not. A curve the reader hid
 * with the legend's eye is folded into `hidden` before it reaches here
 * (`effectiveStates` in `XyWorkshop.vue`): the eye wins over every state.
 */
export type CurveState = "plain" | "emphasised" | "hidden" | "dimmed";

/** How many curves are `"plain"` or `"emphasised"` — the ones a hover box can answer for; `"hidden"` and `"dimmed"` curves take no hover. */
export function visibleCurveCount(states: readonly CurveState[]): number {
    return states.filter((state) => state === "plain" || state === "emphasised")
        .length;
}

/**
 * A curve's current colour+dash identity: `"series"` is its item's hue
 * and dash (`itemHue`/`itemDash`), unchanged by the focus; `"context"` the
 * grey of a dimmed, unrelated curve.
 */
export type CurveLook =
    | { kind: "series"; hue: number; dash: Dash }
    | { kind: "context"; dash: Dash };

/** The style attributes of one curve, all of them Plotly `editType: "style"` (`hoverinfo`: `none`). */
export interface CurvePaint {
    colour: string;
    dash: Dash;
    width: number;
    opacity: number;
    /** False: the hover skips the curve. */
    hover: boolean;
}

/** The colours a paint is chosen from (`PlotTheme`). */
export interface CurvePalette {
    series: readonly string[];
    context: string;
}

/** One file of a slot in the workshop's legend. */
export interface LegendEntry {
    id: string;
    name: string;
    slot: number;
    /** Its current colour+dash, as the chart draws it. */
    look: CurveLook;
    /** The node a press toggles in the linked selection. */
    node: NodeId;
    /** The nodes its curve stands for (its file and its analysis), which the focus marks. */
    nodes: readonly NodeId[];
    pressed: boolean;
}

/** One slot in the workshop's legend, its files under it. */
export interface LegendGroup {
    slot: number;
    /** « A3 ». */
    label: string;
    analysis: Label;
    /** The code of its analysis' technique; null without one. */
    technique: string | null;
    /** The component its analysis observes; null when it names none. */
    component: Label | null;
    /** The label of the folio its analysis is placed on; null when unknown. */
    folio: string | null;
    node: NodeId;
    /** The nodes its curves stand for (their files and analysis), which the focus marks. */
    nodes: readonly NodeId[];
    pressed: boolean;
    /** Its first file's current colour and dash: the item's own, whatever the dashes of its other files. */
    look: CurveLook;
    entries: LegendEntry[];
}

/** A point of a curve, in data units. */
export interface DataPoint {
    x: number;
    y: number;
}

/** Smallest and largest finite value, and how many values are finite. */
export interface Extent {
    min: number;
    max: number;
    count: number;
}

/** One curve of the workshop, as its table row shows it. */
export interface CurveRow {
    id: string;
    /** How the linked selection links the curve; undefined while nothing is selected. */
    relation?: RelationLevel | "none";
    /** « A1 · file name ». */
    label: string;
    analysis: Label;
    x: Extent | null;
    y: Extent | null;
    outOfRange: boolean;
}

/** One curve as the CSV holds it: its label and the values drawn, before any offset. */
export interface CsvColumn {
    label: string;
    x: readonly number[];
    y: readonly number[];
}

/** A Plotly dash as an SVG `stroke-dasharray`; empty for a solid line. */
export function dashArray(dash: Dash): string {
    return dash === "solid" ? "" : dash.replaceAll("px", "").replace(/,/g, " ");
}

/** How an item (a Selection slot) is drawn: filled, a ring, a ring with a dot — a marker, a chip, the head of a line. */
export type ItemMarker = "filled" | "ring" | "ring-dot";

/** The item a curve belongs to, and which of that item's files it is (0: the first). */
export interface CurveItem {
    slot: number;
    rank: number;
}

/**
 * The colour of an item, ONE for the whole Compare view: its slot cycling
 * through the twelve hues (`--series-1…12`); the index of the hue.
 */
export function itemHue(slot: number): number {
    return slot % SERIES_HUES;
}

/** How many times the slot has gone round the twelve hues, 0 to 2: it selects the variant (solid line and filled marker, dashed and ring, dotted and ring with a dot). */
export function itemCycle(slot: number): number {
    return Math.floor(slot / SERIES_HUES) % CYCLES;
}

/** The marker of an item's cycle. */
export function itemMarker(slot: number): ItemMarker {
    return (["filled", "ring", "ring-dot"] as const)[itemCycle(slot)];
}

/** The class a chip or a folio marker carries for its hue: `slot-1…12`. */
export function itemTone(slot: number): string {
    return `slot-${itemHue(slot) + 1}`;
}

/** The classes a chip or a folio marker carries: its hue (`slot-1…12`) and its marker (`item-filled`, `item-ring`, `item-ring-dot`). */
export function itemClasses(slot: number): string {
    return `${itemTone(slot)} item-${itemMarker(slot)}`;
}

/**
 * The line style of a curve: its item's cycle for the first file, a style of
 * its own for the 2nd, 3rd… file, drawn from those no cycle uses, spread so
 * that two items of the same hue never share one (`hue`, `dash`) up to two
 * extra files each; beyond, the styles repeat.
 */
export function itemDash(slot: number, rank: number): Dash {
    if (rank === 0) return DASHES[itemCycle(slot)];
    const spare = DASHES.length - CYCLES;
    return DASHES[CYCLES + (((rank - 1) * CYCLES + itemCycle(slot)) % spare)];
}

/**
 * A curve's current identity: its item's hue and its dash, unchanged by the
 * focus, or grey context while dimmed.
 */
export function curveLook(item: CurveItem, state: CurveState): CurveLook {
    const dash = itemDash(item.slot, item.rank);
    if (state === "dimmed") return { kind: "context", dash };
    return { kind: "series", hue: itemHue(item.slot), dash };
}

/** The CSS colour of a curve's current look, for the legend's inline SVG (DOM `var()`, unlike a Plotly trace which needs a resolved colour — see `curveColour`). */
export function curveColourVar(look: CurveLook): string {
    switch (look.kind) {
        case "context":
            return "var(--series-context)";
        case "series":
            return `var(--series-${look.hue + 1})`;
    }
}

/** The resolved colour of a curve's current look, for a Plotly trace (`CurvePalette`, read from the theme). */
export function curveColour(palette: CurvePalette, look: CurveLook): string {
    switch (look.kind) {
        case "context":
            return palette.context;
        case "series":
            return palette.series[look.hue];
    }
}

/** The layout a window opens on: small multiples above eight curves, overlay otherwise. */
export function openingLayout(curves: number): "overlay" | "multiples" {
    return curves > OVERLAY_MAX_CURVES ? "multiples" : "overlay";
}

/**
 * The state of a curve linked at `level` to the selection (null: not
 * linked). A curve the preview links is emphasised even when the
 * selection hides it. `dim`: an unrelated curve dims instead of hiding
 * (the workshop's « Unlinked spectra: Hide | Dim » switch).
 */
export function curveState(
    level: string | null,
    selecting: boolean,
    previewed: boolean,
    dim = false,
): CurveState {
    if (previewed) return "emphasised";
    if (!selecting) return "plain";
    if (level !== null) return "emphasised";
    return dim ? "dimmed" : "hidden";
}

/**
 * Every curve at 1.5 px in its own hue, emphasised (a pin or a preview) at
 * 2.5 px, colour and dash unchanged by the focus (`curveLook`). A hidden
 * curve keeps its line, at opacity 0, out of the hover. A dimmed curve draws
 * in grey context at reduced opacity and width, out of the hover too.
 */
export function curvePaint(
    palette: CurvePalette,
    item: CurveItem,
    state: CurveState,
): CurvePaint {
    const look = curveLook(item, state);
    const colour = curveColour(palette, look);
    if (state === "dimmed") {
        return {
            colour,
            dash: look.dash,
            width: CONTEXT_WIDTH,
            opacity: DIM_OPACITY,
            hover: false,
        };
    }
    const width = state === "emphasised" ? EMPHASIS_WIDTH : LINE_WIDTH;
    return state === "hidden"
        ? { colour, dash: look.dash, width, opacity: 0, hover: false }
        : { colour, dash: look.dash, width, opacity: 1, hover: true };
}

/**
 * The paints of every trace, in trace order, as the arrays of one
 * `Plotly.restyle`; `hovertemplate`, when given, rides along (a curve that
 * does not answer hover needs an empty one for `hoverinfo: "skip"` to hold).
 * `line.dash` is restyled with the rest: a style attribute, no recalc.
 */
export function restyleUpdate(
    paints: readonly CurvePaint[],
    hovertemplate?: readonly string[],
): {
    opacity: number[];
    "line.color": string[];
    "line.width": number[];
    "line.dash": string[];
    hoverinfo: string[];
    hovertemplate?: string[];
} {
    return {
        opacity: paints.map((paint) => paint.opacity),
        "line.color": paints.map((paint) => paint.colour),
        "line.width": paints.map((paint) => paint.width),
        "line.dash": paints.map((paint) => paint.dash),
        hoverinfo: paints.map((paint) => (paint.hover ? "all" : "skip")),
        ...(hovertemplate ? { hovertemplate: [...hovertemplate] } : {}),
    };
}

/**
 * Where a curve ends on screen: its finite point of largest X, of
 * smallest X on a reversed axis. Null when no point is finite.
 */
export function endPoint(
    x: readonly number[],
    y: readonly number[],
    reversed: boolean,
): DataPoint | null {
    let found: DataPoint | null = null;
    for (let index = 0; index < x.length; index += 1) {
        const [px, py] = [x[index], y[index]];
        if (!Number.isFinite(px) || !Number.isFinite(py)) continue;
        if (!found || (reversed ? px < found.x : px > found.x)) {
            found = { x: px, y: py };
        }
    }
    return found;
}

/**
 * Label positions at least `gap` apart, as near as they can be to the
 * wanted ones (pixels, any direction), in the same order: overlapping
 * labels gather into a run centred on their mean, runs merging until none
 * overlaps; a run crossing a bound is pushed back inside it.
 */
export function spreadLabels(
    wanted: readonly number[],
    gap: number,
    bounds: { min: number; max: number } | null = null,
): number[] {
    const order = wanted
        .map((position, index) => ({ position, index }))
        .sort((one, other) => one.position - other.position);
    interface Run {
        members: number[];
        sum: number;
        start: number;
    }
    const place = (run: Run): void => {
        const size = run.members.length;
        let start = run.sum / size - ((size - 1) * gap) / 2;
        if (bounds) {
            start = Math.min(start, bounds.max - (size - 1) * gap);
            start = Math.max(start, bounds.min);
        }
        run.start = start;
    };
    const runs: Run[] = [];
    for (const { position, index } of order) {
        const run: Run = { members: [index], sum: position, start: position };
        place(run);
        runs.push(run);
        while (runs.length > 1) {
            const last = runs[runs.length - 1];
            const before = runs[runs.length - 2];
            const beforeEnd = before.start + (before.members.length - 1) * gap;
            if (last.start >= beforeEnd + gap) break;
            before.members.push(...last.members);
            before.sum += last.sum;
            place(before);
            runs.pop();
        }
    }
    const placed: number[] = new Array(wanted.length);
    for (const run of runs) {
        run.members.forEach((member, rank) => {
            placed[member] = run.start + rank * gap;
        });
    }
    return placed;
}

const RANGE_KEY = /^[xy]axis\d*\.range(\[\d\])?$/;
const AUTORANGE_KEY = /^[xy]axis\d*\.autorange$/;

/**
 * Whether the chart is zoomed after a Plotly relayout of `update`: an axis
 * range set zooms, an axis put back on autorange resets, anything else
 * (an annotation, a size) leaves `zoomed` as it was.
 */
export function zoomedAfter(
    update: Readonly<Record<string, unknown>> | null | undefined,
    zoomed: boolean,
): boolean {
    const keys = Object.keys(update ?? {});
    if (keys.some((key) => AUTORANGE_KEY.test(key))) return false;
    if (keys.some((key) => RANGE_KEY.test(key))) return true;
    return zoomed;
}

/** An axis of a drawn chart: its range, its autorange setting, its length in pixels. */
export interface AxisView {
    range: readonly [number, number];
    autorange: boolean | string;
    length: number;
}

/** Plotly's smallest zoom box (its `MINZOOM`), in pixels. */
export const MIN_ZOOM_PX = 20;

const RANGE_PART = /^([xy]axis\d*)\.range(?:\[(\d)\])?$/;

/** The ranges `update` sets, by axis name; an axis given one end only keeps its other end from `before`. */
function zoomRanges(
    update: Readonly<Record<string, unknown>> | null | undefined,
    before: Readonly<Record<string, AxisView>>,
): Map<string, [number, number]> {
    const ranges = new Map<string, [number, number]>();
    for (const [key, value] of Object.entries(update ?? {})) {
        const match = RANGE_PART.exec(key);
        const axis = match ? before[match[1]] : undefined;
        if (!match || !axis) continue;
        const range = ranges.get(match[1]) ?? [...axis.range];
        if (match[2] === undefined && Array.isArray(value)) {
            range[0] = Number(value[0]);
            range[1] = Number(value[1]);
        } else if (match[2] !== undefined) {
            range[Number(match[2])] = Number(value);
        }
        ranges.set(match[1], range as [number, number]);
    }
    return ranges;
}

/**
 * Whether `update` zooms an axis of `before` into a box narrower than
 * `MIN_ZOOM_PX`: Plotly starts a box zoom once a press moves 8 px, so a
 * press on a curve that slips a few pixels zooms into a sliver, and a few
 * of them in a row leave the axes a fraction of a unit wide.
 */
export function slipZoom(
    update: Readonly<Record<string, unknown>> | null | undefined,
    before: Readonly<Record<string, AxisView>>,
): boolean {
    for (const [name, range] of zoomRanges(update, before)) {
        const axis = before[name];
        const span = Math.abs(axis.range[1] - axis.range[0]);
        if (span === 0 || axis.length <= 0) continue;
        const pixels = (Math.abs(range[1] - range[0]) / span) * axis.length;
        if (pixels < MIN_ZOOM_PX) return true;
    }
    return false;
}

/**
 * The relayout that puts back the axes `update` zoomed: on their autorange
 * when they followed their data (« reversed » for a reversed range, which
 * Plotly reports as `autorange: true`), else on their range.
 */
export function undoZoom(
    update: Readonly<Record<string, unknown>> | null | undefined,
    before: Readonly<Record<string, AxisView>>,
): Record<string, unknown> {
    const restore: Record<string, unknown> = {};
    for (const name of zoomRanges(update, before).keys()) {
        const axis = before[name];
        if (axis.autorange) {
            restore[`${name}.autorange`] =
                axis.autorange === true && axis.range[0] > axis.range[1]
                    ? "reversed"
                    : axis.autorange;
        } else restore[`${name}.range`] = [...axis.range];
    }
    return restore;
}

/** For each curve in order, how many curves of the same slot come before it. */
export function ranksInSlot(slots: readonly number[]): number[] {
    const seen = new Map<number, number>();
    return slots.map((slot) => {
        const rank = seen.get(slot) ?? 0;
        seen.set(slot, rank + 1);
        return rank;
    });
}

/** The range of the finite values, one pass (a full series can hold 10⁵ points: no spread into `Math.min`); null when none is finite. */
export function extent(values: readonly number[]): Extent | null {
    let min = Infinity;
    let max = -Infinity;
    let count = 0;
    for (const value of values) {
        if (!Number.isFinite(value)) continue;
        if (value < min) min = value;
        if (value > max) max = value;
        count += 1;
    }
    return count === 0 ? null : { min, max, count };
}

/**
 * The treatments offered for spectra of these presets (`utils/xy-views.js`):
 * the views every preset offers, base first. `mixed` is set when the spectra
 * come from more than one preset, a spectrum without preset counting as one.
 */
export function sharedViews(presetKeys: readonly (string | null)[]): {
    views: XyView[];
    mixed: boolean;
} {
    const distinct = [...new Set(presetKeys)];
    const palettes = distinct.map((presetKey) => viewsFor({ presetKey }));
    const [first = viewsFor(null)] = palettes;
    return {
        views: first.filter((view) =>
            palettes.every((palette) =>
                palette.some((other) => other.key === view.key),
            ),
        ),
        mixed: distinct.length > 1,
    };
}

/** The Y values of a spectrum once `view` has run on them; the base view returns them as they are. */
export function treat(x: number[], y: number[], view: XyView | null): number[] {
    if (!view || view.transforms.length === 0) return y;
    return applyTransforms({ x, y }, { transforms: view.transforms }).y;
}

/**
 * How far each offset curve is lifted: every curve starts above the top of
 * the curve before it, lifted, with a gap of a tenth of the widest span (1
 * when no curve spans anything). A curve with no finite value sits at the
 * level of the curve before it.
 */
export function offsetLifts(spans: readonly (Extent | null)[]): number[] {
    let widest = 0;
    for (const span of spans) {
        if (span) widest = Math.max(widest, span.max - span.min);
    }
    const gap = widest > 0 ? widest * OFFSET_GAP : 1;
    const lifts: number[] = [];
    let top: number | null = null;
    let lift = 0;
    for (const span of spans) {
        if (span) {
            lift = top === null ? 0 : top + gap - span.min;
            top = span.max + lift;
        }
        lifts.push(lift);
    }
    return lifts;
}

/**
 * For each curve, whether its X range meets no other curve's: it shares no
 * abscissa with the rest of the chart. Never set with fewer than two ranges.
 */
export function outOfRange(ranges: readonly (Extent | null)[]): boolean[] {
    const known = ranges.filter((range): range is Extent => range !== null);
    if (known.length < 2) return ranges.map(() => false);
    return ranges.map(
        (range) =>
            range !== null &&
            !known.some(
                (other) =>
                    other !== range &&
                    other.min <= range.max &&
                    range.min <= other.max,
            ),
    );
}

/**
 * Rows and columns of a small-multiples grid for `panels` panels: at most
 * four columns, no more than a square, each at least 220 px wide when the
 * width is known (`width` > 0).
 */
export function panelGrid(
    panels: number,
    width = 0,
): { rows: number; columns: number } {
    let columns = Math.min(MAX_COLUMNS, Math.ceil(Math.sqrt(panels)));
    if (width > 0) {
        columns = Math.min(columns, Math.floor(width / MIN_PANEL_WIDTH));
    }
    columns = Math.max(1, columns);
    return { rows: Math.max(1, Math.ceil(panels / columns)), columns };
}

/**
 * The gaps of a small-multiples grid, 44 px across and 46 px down, as the
 * share of one cell Plotly's `grid.xgap`/`ygap` take, for a plotting area
 * of `width` × `height` px; `height` grows so that every panel is at least
 * 110 px high.
 */
export function panelSpacing(
    grid: { rows: number; columns: number },
    width: number,
    height: number,
): { xgap: number; ygap: number; height: number } {
    const needed = grid.rows * MIN_PANEL_HEIGHT + (grid.rows - 1) * PANEL_GAP_Y;
    const total = Math.max(height, needed);
    const cellWidth = width / grid.columns;
    const cellHeight = total / grid.rows;
    return {
        xgap:
            grid.columns > 1 && cellWidth > 0
                ? Math.min(0.9, PANEL_GAP_X / cellWidth)
                : 0,
        ygap: grid.rows > 1 ? Math.min(0.9, PANEL_GAP_Y / cellHeight) : 0,
        height: total,
    };
}

/** Each run of control characters as one space (`views/explorer/series.py` `_CONTROL`). */
function spacedControls(text: string): string {
    let spaced = "";
    let inRun = false;
    for (const character of text) {
        const code = character.charCodeAt(0);
        const control = code < FIRST_PRINTABLE || code === DELETE;
        if (!control) spaced += character;
        else if (!inRun) spaced += " ";
        inRun = control;
    }
    return spaced;
}

/**
 * Curator text made safe for a spreadsheet, by the rule of
 * `views/explorer/series.py` (`neutralise`): control characters become one
 * space, double quotes single quotes, and a leading `'` goes before any
 * part a spreadsheet splitting on `,` or `;` would read as a formula (`=`,
 * `+`, `-`, `@`, tab or carriage return, after optional spaces; OWASP CSV
 * injection). Both sides are pinned by `tests/fixtures/csv/formula-cells.json`.
 */
export function neutraliseText(text: string): string {
    return spacedControls(text)
        .replace(/^ +| +$/g, "")
        .replaceAll('"', "'")
        .replace(FORMULA_CELL, "$1'$2");
}

/** A header cell: neutralised curator text, quoted when it holds a comma. */
function csvCell(text: string): string {
    const safe = neutraliseText(text);
    return safe.includes(",") ? `"${safe}"` : safe;
}

function csvNumber(value: number | undefined): string {
    return value !== undefined && Number.isFinite(value) ? String(value) : "";
}

/**
 * The curves as CSV, after the UTF-8 byte order mark: `note`, when given,
 * on a first line starting with `#`, then one pair of columns per curve,
 * headed « label · X title » and « label · Y title »; a shorter curve
 * leaves its cells empty.
 */
export function workshopCsv(
    columns: readonly CsvColumn[],
    xTitle: string,
    yTitle: string,
    note = "",
): string {
    const header = columns.flatMap((column) => [
        csvCell(`${column.label} · ${xTitle}`),
        csvCell(`${column.label} · ${yTitle}`),
    ]);
    let rows = 0;
    for (const column of columns) rows = Math.max(rows, column.x.length);
    const lines = note ? [`# ${neutraliseText(note)}`] : [];
    lines.push(header.join(","));
    for (let row = 0; row < rows; row += 1) {
        lines.push(
            columns
                .flatMap((column) => [
                    csvNumber(column.x[row]),
                    csvNumber(column.y[row]),
                ])
                .join(","),
        );
    }
    return `${UTF8_BOM}${lines.join("\r\n")}\r\n`;
}
