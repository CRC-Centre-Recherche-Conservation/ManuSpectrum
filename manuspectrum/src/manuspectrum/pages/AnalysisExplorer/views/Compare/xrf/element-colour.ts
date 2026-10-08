import { atomicNumber } from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/periodic.ts";

import type { PlotTheme } from "@/manuspectrum/pages/AnalysisExplorer/xy/plot-theme.ts";

/** Hues of the palette (`PlotTheme.element`, `--element-1…12`). */
export const ELEMENT_HUES = 12;

/**
 * The palette index (0 to 11) of the elements a pigment study meets most.
 * The table is fixed, so an element keeps its hue whatever is drawn with it,
 * and the elements that travel together in a pigment or share a line region
 * (Pb and Sn, Cu and As, S and Cl, Ca and Ti, Hg and S…) never share one
 * (`element-colour.spec.ts` pins the pairs).
 */
export const PIGMENT_HUES: Readonly<Record<string, number>> = {
    Pb: 0,
    Fe: 1,
    Ca: 2,
    Cu: 3,
    Hg: 4,
    Zn: 5,
    K: 6,
    S: 7,
    Ag: 8,
    Au: 9,
    Sn: 9,
    As: 1,
    Ti: 4,
    Cl: 4,
    Mn: 0,
    Co: 11,
    Cr: 4,
    Ba: 1,
    Sr: 4,
    Sb: 3,
    Bi: 3,
    Cd: 7,
    Se: 1,
    Al: 10,
    Si: 5,
};

/**
 * The palette index of a chemical element, stable whatever the elements drawn
 * with it: the table above for the pigment elements, any other takes its
 * atomic number's place in the palette (a collision with a listed element is
 * possible there and tolerated).
 */
export function elementHue(symbol: string): number {
    return PIGMENT_HUES[symbol] ?? (atomicNumber(symbol) ?? 0) % ELEMENT_HUES;
}

/** The colour of an element's lines, labels and chip. */
export function elementColour(
    theme: Pick<PlotTheme, "element" | "ink">,
    symbol: string,
): string {
    return theme.element[elementHue(symbol)] ?? theme.ink;
}
