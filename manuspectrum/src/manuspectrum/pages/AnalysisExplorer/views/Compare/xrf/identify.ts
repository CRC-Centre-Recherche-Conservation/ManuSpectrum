import { netSignal, strongestPeaks } from "./spectrum";
import {
    comptonEnergy,
    escapeOf,
    excitable,
    focusLines,
    fwhmAt,
    lineRef,
    tolerance,
} from "./physics";

import type { DeclaredElement } from "./declared";
import type { XrfLineTable } from "./line-table";
import type { LineRef } from "./physics";
import type { Series } from "./spectrum";

/** Weakest confirmation line, as a relative intensity within its shell. */
const MIN_CONFIRMATION = 0.05;
/** Confirmations closer than this many FWHM to the clicked line cannot be told from it. */
const UNRESOLVED_FWHM = 1.25;
/** A present line this many times stronger than the candidate line cannot confirm it. */
const MAX_STRONGER = 3;
const COMPTON_ANGLES: [number, number] = [90, 150];
const STRONGEST_PEAKS = 3;
const UNDECIDED_SCORE = 0.5;

export type ConfirmationState =
    | "present"
    | "absent"
    | "unresolved"
    | "out-of-range"
    | "not-excited";

export interface Confirmation {
    line: LineRef;
    state: ConfirmationState;
}

export type InstrumentKind =
    | "rayleigh"
    | "compton"
    | "escape"
    | "sum"
    | "duane-hunt";

/** A peak the instrument makes; a band (Compton) spans `from`–`to`. */
export interface InstrumentPeak {
    kind: InstrumentKind;
    energy: number;
    from: number;
    to: number;
    /** Anode symbol for Rayleigh and Compton. */
    source: string | null;
    /** Anode line label (« Kα1 ») for Rayleigh and Compton. */
    line: string | null;
    /** Energies of the peaks an escape or a sum comes from. */
    parents: number[];
}

export interface ElementCandidate {
    type: "element";
    symbol: string;
    line: LineRef;
    /** Line energy minus the clicked energy (keV). */
    delta: number;
    confirmations: Confirmation[];
    /** Share of the present confirmations (weighted by intensity) among those tested; null when none was testable. */
    score: number | null;
    declared: { scope: "curve" | "selection"; entry: DeclaredElement } | null;
    /** Whether the reader added the element to the lens. */
    inLens: boolean;
}

export interface InstrumentCandidate {
    type: "instrument";
    peak: InstrumentPeak;
    delta: number;
}

export type Candidate = ElementCandidate | InstrumentCandidate;

export interface CandidateContext {
    table: XrfLineTable;
    /** Raw series of the curve under the pointer. */
    x: Series;
    y: Series;
    kV: number | null;
    /** Detector FWHM at Mn Kα (keV). */
    fwhmMn: number;
    /** Declared on this curve's analysis, by symbol. */
    declaredForCurve: ReadonlyMap<string, DeclaredElement>;
    /** Declared on any analysis of the Selection, by symbol. */
    declaredInSelection: ReadonlyMap<string, DeclaredElement>;
    lensElements: ReadonlySet<string>;
    instrumentPeaks: readonly InstrumentPeak[];
}

function extent(x: Series): [number, number] {
    const first = x[0];
    const last = x[x.length - 1];
    return first <= last ? [first, last] : [last, first];
}

function peak(
    kind: InstrumentKind,
    energy: number,
    extra: Partial<InstrumentPeak> = {},
): InstrumentPeak {
    return {
        kind,
        energy,
        from: energy,
        to: energy,
        source: null,
        line: null,
        parents: [],
        ...extra,
    };
}

/**
 * The peaks the instrument makes on a curve: the anode's lines as Rayleigh
 * (K lines when `kV` is above the K edge or unknown, else L lines, with the
 * L lines of a K anode), the Compton band of its principal line (90°–150°),
 * the Duane–Hunt limit at `kV`, and the Si escape and the sum peaks of the
 * curve's three strongest peaks. Anything outside the curve's X extent is
 * left out.
 */
export function instrumentPeaks(
    curve: { x: Series; y: Series },
    anode: string | null,
    kV: number | null,
    table: XrfLineTable,
    fwhmMn: number,
): InstrumentPeak[] {
    if (curve.x.length === 0) {
        return [];
    }
    const [low, high] = extent(curve.x);
    const peaks: InstrumentPeak[] = [];
    const element = anode ? table.elements[anode] : undefined;
    if (anode && element) {
        const lineNames = (shell: string) =>
            focusLines(element).filter(
                (l) =>
                    l.name.charAt(0) === shell &&
                    (l.name === "Ka1" ||
                        l.name === "La1" ||
                        l.name === "Kb1" ||
                        l.name === "Lb1") &&
                    excitable(element.lines[l.name], element.edges, kV),
            );
        const kLines = lineNames("K").filter(
            (l) => l.energy >= low && l.energy <= high,
        );
        const lLines = lineNames("L");
        const main = kLines.length > 0 ? kLines : lLines;
        for (const line of [
            ...main,
            ...(kLines.length > 0 ? lLines.slice(0, 1) : []),
        ]) {
            peaks.push(
                peak("rayleigh", line.energy, {
                    source: anode,
                    line: line.label,
                }),
            );
        }
        const principal = main.find((l) => l.name.endsWith("a1"));
        if (principal) {
            const from = comptonEnergy(principal.energy, COMPTON_ANGLES[1]);
            const to = comptonEnergy(principal.energy, COMPTON_ANGLES[0]);
            peaks.push(
                peak("compton", (from + to) / 2, {
                    from,
                    to,
                    source: anode,
                    line: principal.label,
                }),
            );
        }
    }
    if (kV !== null) {
        peaks.push(peak("duane-hunt", kV));
    }
    const strongest = strongestPeaks(
        curve.x,
        curve.y,
        STRONGEST_PEAKS,
        fwhmAt(5.895, fwhmMn),
    );
    strongest.forEach((a, index) => {
        const escape = escapeOf(a.x);
        if (escape !== null) {
            peaks.push(peak("escape", escape, { parents: [a.x] }));
        }
        for (const b of strongest.slice(index)) {
            peaks.push(peak("sum", a.x + b.x, { parents: [a.x, b.x] }));
        }
    });
    return peaks.filter((p) => p.to >= low && p.from <= high);
}

function confirm(
    symbol: string,
    line: LineRef,
    ctx: CandidateContext,
    range: [number, number],
): Confirmation[] {
    const element = ctx.table.elements[symbol];
    const width = fwhmAt(line.energy, ctx.fwhmMn);
    return focusLines(element)
        .filter(
            (other) =>
                other.name !== line.name &&
                other.name.charAt(0) === line.name.charAt(0) &&
                other.intensity >= MIN_CONFIRMATION &&
                Math.abs(other.energy - line.energy) >= width,
        )
        .map((other) => {
            let state: ConfirmationState;
            if (other.energy < range[0] || other.energy > range[1]) {
                state = "out-of-range";
            } else if (
                !excitable(element.lines[other.name], element.edges, ctx.kV)
            ) {
                state = "not-excited";
            } else if (
                Math.abs(other.energy - line.energy) <
                UNRESOLVED_FWHM * width
            ) {
                state = "unresolved";
            } else {
                state = netSignal(
                    ctx.x,
                    ctx.y,
                    other.energy,
                    fwhmAt(other.energy, ctx.fwhmMn),
                ).present
                    ? "present"
                    : "absent";
            }
            return { line: other, state };
        });
}

function scoreOf(line: LineRef, confirmations: Confirmation[]): number | null {
    let present = 0;
    let tested = 0;
    for (const { line: other, state } of confirmations) {
        if (state !== "present" && state !== "absent") continue;
        if (
            state === "present" &&
            other.intensity > MAX_STRONGER * line.intensity
        )
            continue;
        const weight = other.intensity / line.intensity;
        tested += weight;
        if (state === "present") present += weight;
    }
    return tested > 0 ? present / tested : null;
}

function elementCandidates(
    energy: number,
    ctx: CandidateContext,
    range: [number, number],
): ElementCandidate[] {
    const tol = tolerance(energy, ctx.fwhmMn);
    const found: ElementCandidate[] = [];
    for (const [symbol, element] of Object.entries(ctx.table.elements)) {
        let best: LineRef | null = null;
        for (const [name, entry] of Object.entries(element.lines)) {
            if (
                entry[1] >= MIN_CONFIRMATION &&
                Math.abs(entry[0] - energy) <= tol &&
                excitable(entry, element.edges, ctx.kV) &&
                (best === null || entry[1] > best.intensity)
            ) {
                best = lineRef(name, entry);
            }
        }
        if (best === null) continue;
        const confirmations = confirm(symbol, best, ctx, range);
        const onCurve = ctx.declaredForCurve.get(symbol);
        const inSelection = ctx.declaredInSelection.get(symbol);
        let declared: ElementCandidate["declared"] = null;
        if (onCurve) declared = { scope: "curve", entry: onCurve };
        else if (inSelection)
            declared = { scope: "selection", entry: inSelection };
        found.push({
            type: "element",
            symbol,
            line: best,
            delta: best.energy - energy,
            confirmations,
            score: scoreOf(best, confirmations),
            declared,
            inLens: ctx.lensElements.has(symbol),
        });
    }
    return found;
}

function group(candidate: Candidate): number {
    if (candidate.type === "instrument") return 2;
    if (candidate.declared?.scope === "curve") return 0;
    return candidate.declared ? 1 : 3;
}

function compare(a: Candidate, b: Candidate): number {
    const byGroup = group(a) - group(b);
    if (byGroup !== 0) return byGroup;
    if (a.type === "element" && b.type === "element") {
        return (
            (b.score ?? UNDECIDED_SCORE) - (a.score ?? UNDECIDED_SCORE) ||
            b.line.intensity - a.line.intensity ||
            Math.abs(a.delta) - Math.abs(b.delta)
        );
    }
    return Math.abs(a.delta) - Math.abs(b.delta);
}

/**
 * What a peak at `energy` (keV) may be, best first: the table lines within
 * the tolerance (one row per element, its strongest such line; lines the
 * known kV cannot excite are left out) and the curve's instrument peaks.
 * Order: declared for the curve, declared in the Selection, instrument
 * peaks, then by confirmation score (present among tested confirmation
 * lines, a strong absent one pulls it down), relative intensity and |ΔE|.
 * A candidate line is at least `MIN_CONFIRMATION` strong. A confirmation
 * line is another focus line of the same shell, a FWHM or more from the
 * clicked line (under 1.25 FWHM it is « unresolved » and not scored); a present line
 * much stronger than the candidate does not count as a confirmation. Pure: nothing is pinned.
 */
export function candidates(energy: number, ctx: CandidateContext): Candidate[] {
    const tol = tolerance(energy, ctx.fwhmMn);
    const range = extent(ctx.x);
    const instrument: InstrumentCandidate[] = ctx.instrumentPeaks
        .filter((p) => energy >= p.from - tol && energy <= p.to + tol)
        .map((p) => ({
            type: "instrument",
            peak: p,
            delta: energy >= p.from && energy <= p.to ? 0 : p.energy - energy,
        }));
    return [...elementCandidates(energy, ctx, range), ...instrument].sort(
        compare,
    );
}
