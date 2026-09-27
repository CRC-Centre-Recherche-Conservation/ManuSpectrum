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
 * The step between two offset curves: the widest span of the curves, so a
 * lifted curve clears the one below it; 1 when no curve spans anything.
 */
export function offsetStep(spans: readonly (Extent | null)[]): number {
    let widest = 0;
    for (const span of spans) {
        if (span) widest = Math.max(widest, span.max - span.min);
    }
    return widest > 0 ? widest : 1;
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

/** A CSV cell: curator text is neutralised against formula injection (OWASP) and quoted when needed. */
function csvCell(text: string): string {
    const safe = /^[=+\-@\t\r]/.test(text) ? `'${text}` : text;
    return /[",\r\n]/.test(safe) ? `"${safe.replaceAll('"', '""')}"` : safe;
}

function csvNumber(value: number | undefined): string {
    return value !== undefined && Number.isFinite(value) ? String(value) : "";
}

/**
 * The curves as CSV: one pair of columns per curve, headed « label · X
 * title » and « label · Y title »; a shorter curve leaves its cells empty.
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
    return `${lines.join("\r\n")}\r\n`;
}
