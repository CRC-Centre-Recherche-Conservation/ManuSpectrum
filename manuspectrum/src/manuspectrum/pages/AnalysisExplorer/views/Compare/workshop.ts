import { applyTransforms } from "utils/xy-transforms";
import { viewsFor } from "utils/xy-views";

import type { XyView } from "utils/xy-views";
import type { Label } from "@/manuspectrum/pages/AnalysisExplorer/api/types.ts";
import type { NodeId } from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/linked/node-id.ts";
import type { RelationLevel } from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/linked/related.ts";

/** How the XY workshop shows its curves; `table` is the accessible equivalent of the chart. */
export type WorkshopLayout = "overlay" | "offset" | "multiples" | "table";

/** Above this many curves, the workshop opens on small multiples. */
export const OVERLAY_MAX_CURVES = 8;
/** Slots A1…A8 are drawn in the series colours; the later ones are grey context. */
export const COLOURED_SLOTS = 8;
/** Up to this many curves, the hover lists every curve at the X under the pointer. */
export const UNIFIED_HOVER_MAX_CURVES = 6;
/** The least room between two end-of-curve labels, in pixels. */
export const LABEL_GAP = 12;

/** Line styles of the 1st, 2nd, 3rd… file of one slot: short dashes that stay apart at 1.5 px. */
const DASHES = [
    "solid",
    "6px,2px",
    "2px,2px",
    "10px,2px,2px,2px",
    "14px,3px",
] as const;

const MAX_COLUMNS = 4;
const MIN_PANEL_WIDTH = 220;
const MIN_PANEL_HEIGHT = 110;
const PANEL_GAP_X = 44;
const PANEL_GAP_Y = 30;
const LINE_WIDTH = 1.5;
const CONTEXT_WIDTH = 1.25;
const CONTEXT_OPACITY = 0.85;
const EMPHASIS_WIDTH = 2.5;
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
 * when a selection links it not.
 */
export type CurveState = "plain" | "emphasised" | "hidden";

/** The style attributes of one curve, all of them Plotly `editType: "style"` (`hoverinfo`: `none`). */
export interface CurvePaint {
    colour: string;
    width: number;
    opacity: number;
    /** False: the hover skips the curve. */
    hover: boolean;
}

/** The colours a paint is chosen from (`PlotTheme`). */
export interface CurvePalette {
    series: readonly string[];
    context: string;
    ink: string;
}

/** One file of a slot in the workshop's legend. */
export interface LegendEntry {
    id: string;
    name: string;
    slot: number;
    dash: Dash;
    /** The node a press toggles in the linked selection. */
    node: NodeId;
    pressed: boolean;
    relation: RelationLevel | null;
}

/** One slot in the workshop's legend, its files under it. */
export interface LegendGroup {
    slot: number;
    /** « A3 ». */
    label: string;
    analysis: Label;
    node: NodeId;
    pressed: boolean;
    relation: RelationLevel | null;
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

/** The line style of the file at `rank` among the files of its slot (0: the first). */
export function dashOf(rank: number): Dash {
    return DASHES[rank % DASHES.length];
}

/** A Plotly dash as an SVG `stroke-dasharray`; empty for a solid line. */
export function dashArray(dash: Dash): string {
    return dash === "solid" ? "" : dash.replaceAll("px", "").replace(/,/g, " ");
}

export function isColoured(slot: number): boolean {
    return slot >= 0 && slot < COLOURED_SLOTS;
}

/** The layout a window opens on: small multiples above eight curves, or when several slots are all grey context. */
export function openingLayout(
    curves: number,
    slots: readonly number[],
): "overlay" | "multiples" {
    if (curves > OVERLAY_MAX_CURVES) return "multiples";
    return slots.length > 1 && !slots.some(isColoured)
        ? "multiples"
        : "overlay";
}

export function hoverModeFor(curves: number): "x unified" | "closest" {
    return curves <= UNIFIED_HOVER_MAX_CURVES ? "x unified" : "closest";
}

/**
 * The state of a curve linked at `level` to the selection (null: not
 * linked). A curve the preview links is emphasised even when the
 * selection hides it.
 */
export function curveState(
    level: string | null,
    selecting: boolean,
    previewed: boolean,
): CurveState {
    if (previewed) return "emphasised";
    if (!selecting) return "plain";
    return level === null ? "hidden" : "emphasised";
}

/**
 * A1…A8 in their series colour at 1.5 px; later slots in grey context at
 * 1.25 px and 0.85 opacity, drawn in ink when emphasised; every
 * emphasised curve at 2.5 px. A hidden curve keeps its line, at opacity 0,
 * out of the hover.
 */
export function curvePaint(
    palette: CurvePalette,
    slot: number,
    state: CurveState,
): CurvePaint {
    const coloured = isColoured(slot);
    if (state === "emphasised") {
        return {
            colour: coloured ? palette.series[slot] : palette.ink,
            width: EMPHASIS_WIDTH,
            opacity: 1,
            hover: true,
        };
    }
    const plain: CurvePaint = coloured
        ? {
              colour: palette.series[slot],
              width: LINE_WIDTH,
              opacity: 1,
              hover: true,
          }
        : {
              colour: palette.context,
              width: CONTEXT_WIDTH,
              opacity: CONTEXT_OPACITY,
              hover: true,
          };
    return state === "hidden" ? { ...plain, opacity: 0, hover: false } : plain;
}

/** The paints of every trace, in trace order, as the arrays of one `Plotly.restyle`. */
export function restyleUpdate(paints: readonly CurvePaint[]): {
    opacity: number[];
    "line.color": string[];
    "line.width": number[];
    hoverinfo: string[];
} {
    return {
        opacity: paints.map((paint) => paint.opacity),
        "line.color": paints.map((paint) => paint.colour),
        "line.width": paints.map((paint) => paint.width),
        hoverinfo: paints.map((paint) => (paint.hover ? "all" : "skip")),
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
 * The gaps of a small-multiples grid, 44 px across and 30 px down, as the
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
