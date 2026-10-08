import { atomicNumber } from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/periodic.ts";

import type { PlotTheme } from "@/manuspectrum/pages/AnalysisExplorer/xy/plot-theme.ts";

/** The elements an XRF reader meets most, each with its own hue (its index in the palette). */
const COMMON_ELEMENTS = [
    "Pb",
    "Fe",
    "Ca",
    "Cu",
    "Hg",
    "Zn",
    "K",
    "S",
    "Ag",
    "Au",
];
/** Hues of the palette (`PlotTheme.element`). */
export const ELEMENT_HUES = 10;

/**
 * The palette index (0 to 9) of a chemical element, stable whatever the
 * elements drawn with it: the common ones have a hue each, any other takes
 * its atomic number's place in the palette.
 */
export function elementHue(symbol: string): number {
    const common = COMMON_ELEMENTS.indexOf(symbol);
    return common >= 0 ? common : (atomicNumber(symbol) ?? 0) % ELEMENT_HUES;
}

/** The colour of an element's lines, labels and chip. */
export function elementColour(
    theme: Pick<PlotTheme, "element" | "ink">,
    symbol: string,
): string {
    return theme.element[elementHue(symbol)] ?? theme.ink;
}
