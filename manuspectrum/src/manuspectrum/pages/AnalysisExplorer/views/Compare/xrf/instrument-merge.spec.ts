import { describe, expect, it } from "vitest";

import { mergeInstrument } from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/xrf/instrument-merge.ts";

import type { InstrumentPeak } from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/xrf/identify.ts";

const FWHM = 0.14;

function peak(
    kind: InstrumentPeak["kind"],
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

const labelOf = (found: InstrumentPeak) =>
    found.kind === "escape" ? "esc" : found.kind === "sum" ? "sum" : "Rh Kα1";

describe("mergeInstrument", () => {
    it("merges the same peak seen on three spectra a few eV apart into one entry", () => {
        const merged = mergeInstrument(
            [
                { slot: 1, order: 0, peaks: [peak("escape", 8.8)] },
                { slot: 2, order: 1, peaks: [peak("escape", 8.81)] },
                { slot: 3, order: 2, peaks: [peak("escape", 8.82)] },
            ],
            FWHM,
            labelOf,
        );
        expect(merged.peaks).toEqual([
            { label: "esc", kind: "escape", energy: 8.8, slots: [1, 2, 3] },
        ]);
    });

    it("keeps two peaks of different nature apart even when they lie within the tolerance", () => {
        const merged = mergeInstrument(
            [
                {
                    slot: 1,
                    order: 0,
                    peaks: [peak("sum", 20.02), peak("rayleigh", 20.07)],
                },
            ],
            FWHM,
            labelOf,
        );
        expect(merged.peaks.map((entry) => entry.label)).toEqual([
            "sum",
            "Rh Kα1",
        ]);
    });

    it("lists the peaks by energy and the slots in ascending order", () => {
        const merged = mergeInstrument(
            [
                { slot: 2, order: 1, peaks: [peak("sum", 12)] },
                {
                    slot: 1,
                    order: 0,
                    peaks: [peak("escape", 4), peak("sum", 12)],
                },
            ],
            FWHM,
            labelOf,
        );
        expect(merged.peaks).toEqual([
            { label: "esc", kind: "escape", energy: 4, slots: [1] },
            { label: "sum", kind: "sum", energy: 12, slots: [1, 2] },
        ]);
    });

    it("merges Compton bands whose edges agree and keeps the first curve's order", () => {
        const band = (from: number, to: number) =>
            peak("compton", (from + to) / 2, { from, to });
        const merged = mergeInstrument(
            [
                { slot: 1, order: 0, peaks: [band(18.5, 19.2)] },
                { slot: 2, order: 1, peaks: [band(18.505, 19.195)] },
                { slot: 2, order: 1, peaks: [band(10, 11)] },
            ],
            FWHM,
            labelOf,
        );
        expect(merged.bands).toEqual([
            { from: 18.5, to: 19.2, order: 0 },
            { from: 10, to: 11, order: 1 },
        ]);
        expect(merged.peaks).toEqual([]);
    });

    it("gives nothing for no visible curve", () => {
        expect(mergeInstrument([], FWHM, labelOf)).toEqual({
            peaks: [],
            bands: [],
        });
    });
});
