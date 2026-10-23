import { NEUTRAL_FILTERS } from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/light-table.ts";

import type { PaneFilters } from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/light-table.ts";

const NEUTRAL = 100;

export function isNeutral(filters: PaneFilters): boolean {
    return (
        filters.brightness === NEUTRAL_FILTERS.brightness &&
        filters.contrast === NEUTRAL_FILTERS.contrast &&
        filters.saturation === NEUTRAL_FILTERS.saturation &&
        filters.greyscale === NEUTRAL_FILTERS.greyscale
    );
}

/** The CSS filter of `canvasFilter` in `iiif-viewer.js`; empty when every value is neutral. */
export function filterCss(filters: PaneFilters): string {
    if (isNeutral(filters)) return "";
    return [
        `brightness(${filters.brightness / NEUTRAL})`,
        `contrast(${filters.contrast / NEUTRAL})`,
        `saturate(${filters.saturation / NEUTRAL})`,
        `grayscale(${filters.greyscale ? 1 : 0})`,
    ].join(" ");
}
