import type { EventDate } from "@/manuspectrum/pages/AnalysisExplorer/api/types.ts";

export const BIN_YEARS = 25;
export const WIDE_BIN_YEARS = 50;
export const WIDE_SPAN_YEARS = 800;
const CENTURY = 100;

/** An event on the timeline: its interval, whether it is « circa », and the stacks it counts in. */
export interface DatedItem {
    interval: readonly [number, number];
    approximate: boolean;
    keys: readonly string[];
}
export interface HistogramBin {
    from: number;
    to: number;
    firm: Record<string, number>;
    approx: Record<string, number>;
    total: number;
}
export type HistogramSegment =
    | { kind: "bins"; bins: HistogramBin[] }
    | { kind: "fold"; from: number; to: number };
export interface Histogram {
    binYears: number;
    from: number;
    to: number;
    segments: HistogramSegment[];
    max: number;
}

export function intervalOf(date: EventDate): [number, number] | null {
    const start = date.start ?? date.end;
    const end = date.end ?? date.start;
    if (start === null || end === null) return null;
    return start <= end ? [start, end] : [end, start];
}

export function binYearsFor(span: number): number {
    return span > WIDE_SPAN_YEARS ? WIDE_BIN_YEARS : BIN_YEARS;
}

/** First year of the bin holding `year`: bins start at 1, 26, 51… (or 1, 51…). */
export function binStart(year: number, size: number): number {
    return Math.floor((year - 1) / size) * size + 1;
}

function overlap(
    interval: readonly [number, number],
    from: number,
    to: number,
): number {
    return Math.max(
        0,
        Math.min(interval[1], to) - Math.max(interval[0], from) + 1,
    );
}

function centuryOf(year: number): number {
    return Math.floor((year - 1) / CENTURY);
}

/** Bins, with every whole century without weight folded into one segment (consecutive ones merged). */
function fold(bins: HistogramBin[], size: number): HistogramSegment[] {
    const segments: HistogramSegment[] = [];
    let index = 0;
    while (index < bins.length) {
        const century = centuryOf(bins[index].from);
        const group: HistogramBin[] = [];
        while (index < bins.length && centuryOf(bins[index].from) === century) {
            group.push(bins[index++]);
        }
        const last = segments[segments.length - 1];
        if (
            group.length * size === CENTURY &&
            group.every((bin) => bin.total === 0)
        ) {
            const span = {
                from: century * CENTURY + 1,
                to: (century + 1) * CENTURY,
            };
            if (last?.kind === "fold") last.to = span.to;
            else segments.push({ kind: "fold", ...span });
        } else if (last?.kind === "bins") last.bins.push(...group);
        else segments.push({ kind: "bins", bins: group });
    }
    return segments;
}

/**
 * The aoristic histogram of `items`: each spreads a weight of 1 over its
 * interval, each bin receiving the share of years it covers, once per stack
 * key; an approximate item weighs in the lighter band (`approx`).
 */
export function aoristic(items: readonly DatedItem[]): Histogram | null {
    if (items.length === 0) return null;
    let first = Infinity;
    let last = -Infinity;
    for (const item of items) {
        first = Math.min(first, item.interval[0]);
        last = Math.max(last, item.interval[1]);
    }
    const size = binYearsFor(last - first + 1);
    const from = binStart(first, size);
    const to = binStart(last, size) + size - 1;
    const bins: HistogramBin[] = Array.from(
        { length: (to - from + 1) / size },
        (_, i) => ({
            from: from + i * size,
            to: from + (i + 1) * size - 1,
            firm: {},
            approx: {},
            total: 0,
        }),
    );
    for (const item of items) {
        const duration = item.interval[1] - item.interval[0] + 1;
        const lastIndex = (binStart(item.interval[1], size) - from) / size;
        for (
            let i = (binStart(item.interval[0], size) - from) / size;
            i <= lastIndex;
            i += 1
        ) {
            const bin = bins[i];
            const weight = overlap(item.interval, bin.from, bin.to) / duration;
            const band = item.approximate ? bin.approx : bin.firm;
            for (const key of item.keys) {
                band[key] = (band[key] ?? 0) + weight;
                bin.total += weight;
            }
        }
    }
    return {
        binYears: size,
        from,
        to,
        segments: fold(bins, size),
        max: Math.max(...bins.map((bin) => bin.total)),
    };
}
