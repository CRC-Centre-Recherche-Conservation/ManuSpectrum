import { excitable, lineRef } from "./physics";

import type { LineRef } from "./physics";
import type { XrfElement } from "./line-table";

/** Weakest relative intensity a line may have to tell two elements apart. */
const MIN_INTENSITY = 0.05;

export interface OverlapLine {
    symbol: string;
    line: LineRef;
}

export interface Overlap {
    a: OverlapLine;
    b: OverlapLine;
    /** |E1 − E2| in keV. */
    separation: number;
    /** Mean energy, the centre of the band drawn. */
    centre: number;
    /** FWHM at the centre: the width of the band drawn. */
    width: number;
}

export interface ElementLines {
    symbol: string;
    element: XrfElement;
}

export interface TellApartContext {
    fwhmAt: (energy: number) => number;
    /** X extent of the drawn data (keV). */
    range: [number, number];
    /** Known tube voltage; null when unknown. */
    kV: number | null;
}

function closeTo(
    e1: number,
    e2: number,
    fwhmAt: (energy: number) => number,
): boolean {
    return Math.abs(e1 - e2) < fwhmAt((e1 + e2) / 2) / 2;
}

/**
 * Pairs of lines, one from each side, closer than half the FWHM at their
 * mean energy; lines of the same element never pair. Ordered by centre.
 */
export function overlaps(
    linesA: readonly OverlapLine[],
    linesB: readonly OverlapLine[],
    fwhmAt: (energy: number) => number,
): Overlap[] {
    const found: Overlap[] = [];
    for (const a of linesA) {
        for (const b of linesB) {
            if (
                a.symbol === b.symbol ||
                !closeTo(a.line.energy, b.line.energy, fwhmAt)
            ) {
                continue;
            }
            const centre = (a.line.energy + b.line.energy) / 2;
            found.push({
                a,
                b,
                separation: Math.abs(a.line.energy - b.line.energy),
                centre,
                width: fwhmAt(centre),
            });
        }
    }
    return found.sort((x, y) => x.centre - y.centre);
}

/** The lines of an element inside `range`, excitable at `kV`, with a relative intensity worth a test. */
export function usableLines(
    element: XrfElement,
    range: [number, number],
    kV: number | null,
): LineRef[] {
    return Object.entries(element.lines)
        .filter(
            ([, line]) =>
                line[1] >= MIN_INTENSITY &&
                line[0] >= range[0] &&
                line[0] <= range[1] &&
                excitable(line, element.edges, kV),
        )
        .map(([name, line]) => lineRef(name, line));
}

function strongestApart(
    own: ElementLines,
    subject: LineRef,
    other: ElementLines,
    context: TellApartContext,
): LineRef | null {
    const rivals = usableLines(other.element, context.range, context.kV);
    const shell = subject.name.charAt(0);
    const apart = usableLines(own.element, context.range, context.kV).filter(
        (line) =>
            line.name.charAt(0) === shell &&
            line.name !== subject.name &&
            !rivals.some((rival) =>
                closeTo(line.energy, rival.energy, context.fwhmAt),
            ),
    );
    return apart.reduce<LineRef | null>(
        (best, line) =>
            best === null || line.intensity > best.intensity ? line : best,
        null,
    );
}

/**
 * For two overlapping lines (`aLine` of `a`, `bLine` of `b`), the line each
 * element can be told apart by: its strongest other line of the same shell
 * that overlaps no usable line of the other element; null when none does.
 */
export function tellApart(
    a: ElementLines,
    aLine: LineRef,
    b: ElementLines,
    bLine: LineRef,
    context: TellApartContext,
): { a: LineRef | null; b: LineRef | null } {
    return {
        a: strongestApart(a, aLine, b, context),
        b: strongestApart(b, bLine, a, context),
    };
}
