import { tolerance } from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/xrf/physics.ts";

import type { InstrumentPeak } from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/xrf/identify.ts";

/** Compton bands whose edges both lie closer than this (keV) are one band. */
export const BAND_MERGE_KEV = 0.02;

/** The instrument peaks of one visible curve. */
export interface InstrumentSource {
    slot: number;
    /** The curve's hue order, for the colour of a band it brings. */
    order: number;
    peaks: readonly InstrumentPeak[];
}

/** A peak of the instrument, as the chart ticks, the strip's list and the menu's count say it. */
export interface MergedPeak {
    label: string;
    kind: InstrumentPeak["kind"];
    energy: number;
    /** The slots whose curves carry it, ascending. */
    slots: number[];
}

export interface MergedBand {
    from: number;
    to: number;
    /** The hue order of the first curve that brought it. */
    order: number;
}

export interface MergedInstrument {
    peaks: MergedPeak[];
    bands: MergedBand[];
}

/**
 * The one merge of the instrument peaks of the visible curves. A peak joins
 * an earlier one of the same label whose energy lies within the detector
 * tolerance (`tolerance(energy, fwhmMn)`), and then only adds its slot; two
 * peaks of different nature stay two, however close. Compton bands merge
 * when both edges agree within `BAND_MERGE_KEV`. Peaks come out by energy.
 * `labelOf` names a peak (Rayleigh, escape, sum, Duane–Hunt).
 */
export function mergeInstrument(
    sources: readonly InstrumentSource[],
    fwhmMn: number,
    labelOf: (peak: InstrumentPeak) => string,
): MergedInstrument {
    const peaks: MergedPeak[] = [];
    const bands: MergedBand[] = [];
    for (const { slot, order, peaks: found } of sources) {
        for (const peak of found) {
            if (peak.kind === "compton") {
                if (
                    !bands.some(
                        (held) =>
                            Math.abs(held.from - peak.from) < BAND_MERGE_KEV &&
                            Math.abs(held.to - peak.to) < BAND_MERGE_KEV,
                    )
                ) {
                    bands.push({ from: peak.from, to: peak.to, order });
                }
                continue;
            }
            const label = labelOf(peak);
            const held = peaks.find(
                (entry) =>
                    entry.label === label &&
                    Math.abs(entry.energy - peak.energy) <
                        tolerance(peak.energy, fwhmMn),
            );
            if (!held) {
                peaks.push({
                    label,
                    kind: peak.kind,
                    energy: peak.energy,
                    slots: [slot],
                });
            } else if (!held.slots.includes(slot)) {
                held.slots.push(slot);
            }
        }
    }
    return {
        peaks: peaks
            .map((entry) => ({
                ...entry,
                slots: [...entry.slots].sort((a, b) => a - b),
            }))
            .sort((a, b) => a.energy - b.energy),
        bands,
    };
}
