import { tickNumber } from "@/manuspectrum/pages/AnalysisExplorer/xy/plot-theme.ts";

/** The explicit ticks of a log axis, as Plotly takes them (`tickmode: "array"`, `minor.tickvals`). */
export interface LogTicks {
    tickmode: "array";
    tickvals: number[];
    ticktext: string[];
    minor: { tickmode: "array"; tickvals: number[] };
}

/** From this many decades shown, only the powers of ten are labelled. */
const DECADES_ONLY = 2;
/** From this many decades shown (and under `DECADES_ONLY`), 1, 2 and 5 times each power of ten are labelled. */
const ONE_TWO_FIVE = 1;
const ONE_TWO_FIVE_LABELLED = [1, 2, 5];
const ONE_TWO_FIVE_MINOR = [3, 4, 6, 7, 8, 9];
const DECADE_MINOR = [2, 3, 4, 5, 6, 7, 8, 9];
/** Most powers of ten labelled; past it, one power in every n is. */
const MAX_DECADE_LABELS = 7;
/** Most labels of a range under one decade, at round steps of `LINEAR_STEPS` × 10^k. */
const MAX_LINEAR_LABELS = 7;
const LINEAR_STEPS = [1, 2, 2.5, 5];
/** The decades kept on each side of a range of no height. */
const FLAT_PAD = 0.5;
/** The decades ticked when the range is not known: Plotly draws only the ticks inside the range it shows. */
const UNKNOWN_RANGE: [number, number] = [-6, 12];
/** Significant digits a tick value is rounded to, so that 3 × 0.1 is 0.3. */
const TICK_PRECISION = 12;

function exact(value: number): number {
    return Number(value.toPrecision(TICK_PRECISION));
}

/** The range as [low, high] in log10; null when an end is not a finite number. */
function ordered(
    range: readonly [number, number] | null,
): [number, number] | null {
    if (!range || !range.every(Number.isFinite)) return null;
    const low = Math.min(range[0], range[1]);
    const high = Math.max(range[0], range[1]);
    return low === high ? [low - FLAT_PAD, high + FLAT_PAD] : [low, high];
}

/** Powers of ten (every `step`-th labelled) with `minor` multiples of each between `from` and `to` (exponents). */
function decadeTicks(
    from: number,
    to: number,
    step: number,
): { major: number[]; minor: number[] } {
    const major: number[] = [];
    const minor: number[] = [];
    for (let power = from; power <= to; power += 1) {
        const base = 10 ** power;
        if (((power % step) + step) % step === 0) major.push(exact(base));
        else minor.push(exact(base));
        if (step === 1) {
            for (const factor of DECADE_MINOR) minor.push(exact(factor * base));
        }
    }
    return { major, minor };
}

function oneTwoFiveTicks(
    from: number,
    to: number,
): { major: number[]; minor: number[] } {
    const major: number[] = [];
    const minor: number[] = [];
    for (let power = from; power <= to; power += 1) {
        const base = 10 ** power;
        for (const factor of ONE_TWO_FIVE_LABELLED) {
            major.push(exact(factor * base));
        }
        for (const factor of ONE_TWO_FIVE_MINOR) {
            minor.push(exact(factor * base));
        }
    }
    return { major, minor };
}

/** The smallest round step (1, 2, 2.5 or 5 × 10^k) that puts at most `MAX_LINEAR_LABELS` ticks between `low` and `high`. */
function linearStep(low: number, high: number): number {
    let power = Math.floor(Math.log10((high - low) / MAX_LINEAR_LABELS)) - 1;
    for (;;) {
        for (const factor of LINEAR_STEPS) {
            const step = factor * 10 ** power;
            const count = Math.floor(high / step) - Math.ceil(low / step) + 1;
            if (count <= MAX_LINEAR_LABELS) return step;
        }
        power += 1;
    }
}

/** Multiples of a round step over a range under one decade, one more on each side for the autorange's padding. */
function linearTicks(low: number, high: number): number[] {
    const step = linearStep(low, high);
    const ticks: number[] = [];
    for (
        let index = Math.ceil(low / step) - 1;
        index <= Math.floor(high / step) + 1;
        index += 1
    ) {
        const value = exact(index * step);
        if (value > 0) ticks.push(value);
    }
    return ticks;
}

/**
 * The ticks of a log axis showing `range` (log10, either order), as
 * spectroscopists read a counts axis:
 * - two decades or more: the powers of ten labelled (one in every n past
 *   `MAX_DECADE_LABELS`), 2…9 × 10ⁿ as unlabelled minor ticks;
 * - one to two decades: 1, 2 and 5 × 10ⁿ labelled, the other integers
 *   minor;
 * - under one decade: round linear steps (1, 2, 2.5 or 5 × 10ᵏ, at most
 *   `MAX_LINEAR_LABELS`), labelled, no minor tick.
 * Every label is the whole value (`tickNumber`: « 200 », « 1000 »,
 * « 10k »), never a bare mantissa. The ticks reach past the range, which
 * Plotly crops. A range of no height takes `FLAT_PAD` decades on each side;
 * an unknown one (null, NaN, infinite) takes the powers of ten.
 */
export function logTicks(
    range: readonly [number, number] | null,
    separators: string,
): LogTicks {
    const shown = ordered(range);
    let major: number[];
    let minor: number[] = [];
    if (shown === null) {
        ({ major, minor } = decadeTicks(...UNKNOWN_RANGE, 1));
    } else {
        const [low, high] = shown;
        const span = high - low;
        const from = Math.floor(low) - 1;
        const to = Math.ceil(high) + 1;
        if (span >= DECADES_ONLY) {
            const powers = Math.floor(high) - Math.ceil(low) + 1;
            const step = Math.max(1, Math.ceil(powers / MAX_DECADE_LABELS));
            ({ major, minor } = decadeTicks(from, to, step));
        } else if (span >= ONE_TWO_FIVE) {
            ({ major, minor } = oneTwoFiveTicks(from, to));
        } else {
            major = linearTicks(exact(10 ** low), exact(10 ** high));
        }
    }
    return {
        tickmode: "array",
        tickvals: major,
        ticktext: major.map((value) => tickNumber(value, separators)),
        minor: { tickmode: "array", tickvals: minor },
    };
}
