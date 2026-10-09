import { describe, expect, it } from "vitest";

import {
    channelWidth,
    nearestIndex,
    netSignal,
    snapToPeak,
    strongestPeaks,
} from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/xrf/spectrum.ts";

const FWHM = 0.15;

function energies(n = 2000, step = 0.01): number[] {
    return Array.from({ length: n }, (_, i) => i * step);
}

function spectrum(
    x: number[],
    peaks: { at: number; height: number }[],
    background: (e: number) => number,
    round = true,
): number[] {
    const sigma = FWHM / 2.355;
    return x.map((e) => {
        let v = background(e);
        for (const { at, height } of peaks) {
            v += height * Math.exp(-0.5 * ((e - at) / sigma) ** 2);
        }
        return round ? Math.round(v) : v;
    });
}

const slope = (e: number) => 100 + 10 * e;

describe("channelWidth and nearestIndex", () => {
    it("measures the spacing and finds the nearest channel", () => {
        const x = energies();
        expect(channelWidth(x)).toBeCloseTo(0.01, 9);
        expect(channelWidth([1])).toBe(0);
        expect(nearestIndex(x, 5.004)).toBe(500);
        expect(nearestIndex(x, 5.006)).toBe(501);
        expect(nearestIndex(x, -3)).toBe(0);
        expect(nearestIndex(x, 999)).toBe(x.length - 1);
        expect(nearestIndex([], 1)).toBe(-1);
    });

    it("also reads a descending axis and typed arrays", () => {
        const x = energies().reverse();
        expect(nearestIndex(x, 5.004)).toBe(x.length - 1 - 500);
        expect(nearestIndex(Float64Array.from([1, 2, 3]), 2.4)).toBe(1);
    });
});

describe("snapToPeak", () => {
    it("snaps to the local maximum within the half width", () => {
        const x = energies();
        const y = spectrum(x, [{ at: 6.4, height: 500 }], slope);
        expect(x[snapToPeak(x, y, 6.43, 0.075)]).toBeCloseTo(6.4, 1);
        expect(snapToPeak(x, y, 6.4, 0.075)).toBe(nearestIndex(x, 6.4));
    });

    it("stays on the nearest channel when the window holds no point", () => {
        expect(snapToPeak([0, 1, 2], [1, 2, 3], 0.4, 0.01)).toBe(0);
    });
});

describe("netSignal", () => {
    const x = energies();

    it("sees a line well above 3 sigma on a counting series", () => {
        const y = spectrum(x, [{ at: 6.4, height: 400 }], slope);
        const result = netSignal(x, y, 6.4, FWHM);
        expect(result.present).toBe(true);
        expect(result.net).toBeGreaterThan(350);
        expect(result.sigma).toBeCloseTo(Math.sqrt(100 + 64), 0);
    });

    it("rejects a bump under 3 sigma", () => {
        const y = spectrum(x, [{ at: 6.4, height: 20 }], slope);
        expect(netSignal(x, y, 6.4, FWHM).present).toBe(false);
    });

    it("rejects an empty position", () => {
        const y = spectrum(x, [{ at: 6.4, height: 400 }], slope);
        expect(netSignal(x, y, 9, FWHM).present).toBe(false);
    });

    it("takes the local deviation of a non-count series", () => {
        const noise = (i: number) => 0.5 * Math.sin(i * 12.9898) ** 3;
        const y = spectrum(x, [{ at: 6.4, height: 8 }], slope, false).map(
            (v, i) => v + noise(i) + 0.3,
        );
        const result = netSignal(x, y, 6.4, FWHM);
        expect(result.sigma).toBeGreaterThan(0);
        expect(result.sigma).toBeLessThan(1);
        expect(result.present).toBe(true);
    });

    it("keeps √max(bg,1) off a series with a negative value", () => {
        const y = spectrum(x, [], () => 4);
        y[10] = -1;
        expect(netSignal(x, y, 6.4, FWHM).sigma).toBe(0);
    });

    it("works at the edges of the series", () => {
        const y = spectrum(x, [{ at: 0.05, height: 500 }], slope);
        const start = netSignal(x, y, 0.05, FWHM);
        expect(start.present).toBe(true);
        const end = netSignal(x, y, x[x.length - 1], FWHM);
        expect(end.present).toBe(false);
        expect(netSignal([], [], 1, FWHM).present).toBe(false);
    });

    describe("next to a neighbouring peak", () => {
        const NEIGHBOUR = { energy: 2.3, fwhm: FWHM, height: 1000 };
        const x = energies(500);
        const withLine = spectrum(
            x,
            [
                { at: 2.3, height: 1000 },
                { at: 2.5, height: 90 },
            ],
            () => 100,
        );
        const without = spectrum(x, [{ at: 2.3, height: 1000 }], () => 100);

        it("sees a line its neighbour's tail sits under, once the tail is modelled out", () => {
            const found = netSignal(x, withLine, 2.5, FWHM, NEIGHBOUR);
            expect(found.present).toBe(true);
            expect(found.net).toBeGreaterThan(80);
        });

        it("does not take the neighbour's tail for a line", () => {
            expect(netSignal(x, without, 2.5, FWHM, NEIGHBOUR).present).toBe(
                false,
            );
        });

        it("leaves a window centred on the neighbour out and reads the other side", () => {
            const found = netSignal(x, withLine, 2.45, FWHM, NEIGHBOUR);
            expect(found.sigma).toBeCloseTo(10, 0);
        });
    });

    it("calls an absent line present in at most 5 % of seeded Poisson runs on a plain slope", () => {
        let seed = 12345;
        const uniform = () => {
            seed = (seed * 1664525 + 1013904223) >>> 0;
            return (seed + 1) / 4294967297;
        };
        const gauss = () =>
            Math.sqrt(-2 * Math.log(uniform())) *
            Math.cos(2 * Math.PI * uniform());
        const x = energies(500, 0.01);
        let falsePresent = 0;
        const runs = 400;
        for (let run = 0; run < runs; run += 1) {
            const y = x.map((e) => {
                const mean = 2000 - 400 * (e - 2);
                return Math.max(
                    0,
                    Math.round(mean + Math.sqrt(mean) * gauss()),
                );
            });
            if (netSignal(x, y, 2.5, FWHM).present) falsePresent += 1;
        }
        expect(falsePresent / runs).toBeLessThanOrEqual(0.05);
    });
});

describe("strongestPeaks", () => {
    const x = energies();
    const y = spectrum(
        x,
        [
            { at: 3.7, height: 300 },
            { at: 6.4, height: 900 },
            { at: 10.55, height: 500 },
            { at: 14, height: 40 },
        ],
        slope,
    );

    it("returns the strongest peaks in prominence order", () => {
        const peaks = strongestPeaks(x, y, 3, FWHM);
        expect(peaks.map((p) => Math.round(p.x * 10) / 10)).toEqual([
            6.4, 10.6, 3.7,
        ]);
        expect(peaks[0].prominence).toBeGreaterThan(peaks[1].prominence);
    });

    it("returns the same array for the same arguments", () => {
        expect(strongestPeaks(x, y, 3, FWHM)).toBe(
            strongestPeaks(x, y, 3, FWHM),
        );
        expect(strongestPeaks(x, y, 2, FWHM)).not.toBe(
            strongestPeaks(x, y, 3, FWHM),
        );
    });

    it("finds a peak on the first or last channel and handles nothing", () => {
        const edge = spectrum(x, [{ at: 0, height: 800 }], slope);
        expect(strongestPeaks(x, edge, 1, FWHM)[0].index).toBe(0);
        expect(strongestPeaks([], [], 3, FWHM)).toEqual([]);
        expect(strongestPeaks(x, new Array(x.length).fill(5), 3, FWHM)).toEqual(
            [],
        );
    });
});
