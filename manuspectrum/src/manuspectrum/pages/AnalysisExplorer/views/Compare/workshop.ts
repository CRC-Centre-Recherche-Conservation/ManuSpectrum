import { applyTransforms } from "utils/xy-transforms";
import { viewsFor } from "utils/xy-views";

import type { XyView } from "utils/xy-views";
import type { Label } from "@/manuspectrum/pages/AnalysisExplorer/api/types.ts";

/** How the XY workshop shows its curves; `table` is the accessible equivalent of the chart. */
export type WorkshopLayout = "overlay" | "offset" | "multiples" | "table";

/** Above this many curves, the workshop opens on small multiples. */
export const OVERLAY_MAX_CURVES = 8;

/** Line styles of the 1st, 2nd, 3rd… file of one slot. */
const DASHES = [
    "solid",
    "dash",
    "dot",
    "dashdot",
    "longdash",
    "longdashdot",
] as const;

const MAX_COLUMNS = 4;
/** The room between two offset curves, as a share of the widest curve's span. */
const OFFSET_GAP = 0.1;
/** A spreadsheet opens a CSV starting with the UTF-8 byte order mark as UTF-8. */
const UTF8_BOM = "\ufeff";
/** A cell a spreadsheet splitting on `,` or `;` would read as a formula, spaces first included (`views/explorer/series.py` `_FORMULA_CELL`). */
const FORMULA_CELL = /(^|[,;])([ ]*[=+\-@\t\r])/g;
const FIRST_PRINTABLE = 0x20;
const DELETE = 0x7f;

export type Dash = (typeof DASHES)[number];

/** Smallest and largest finite value, and how many values are finite. */
export interface Extent {
    min: number;
    max: number;
    count: number;
}

/** One curve of the workshop, as its table row shows it. */
export interface CurveRow {
    id: string;
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

/** Rows and columns of a small-multiples grid for `panels` panels, at most four columns. */
export function panelGrid(panels: number): { rows: number; columns: number } {
    const columns = Math.max(
        1,
        Math.min(MAX_COLUMNS, Math.ceil(Math.sqrt(panels))),
    );
    return { rows: Math.max(1, Math.ceil(panels / columns)), columns };
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
 * The curves as CSV, after the UTF-8 byte order mark: one pair of columns
 * per curve, headed « label · X title » and « label · Y title »; a shorter
 * curve leaves its cells empty.
 */
export function workshopCsv(
    columns: readonly CsvColumn[],
    xTitle: string,
    yTitle: string,
): string {
    const header = columns.flatMap((column) => [
        csvCell(`${column.label} · ${xTitle}`),
        csvCell(`${column.label} · ${yTitle}`),
    ]);
    let rows = 0;
    for (const column of columns) rows = Math.max(rows, column.x.length);
    const lines = [header.join(",")];
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
