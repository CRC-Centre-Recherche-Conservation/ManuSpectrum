// @vitest-environment node
import { describe, expect, it } from "vitest";

import { logTicks } from "@/manuspectrum/pages/AnalysisExplorer/xy/log-ticks.ts";

const EN = ".,";
const FR = ", ";

/** The labels of the ticks inside `range` (log10), as Plotly shows them. */
function shown(range: [number, number], separators = EN): string[] {
    const ticks = logTicks(range, separators);
    const [low, high] = [Math.min(...range), Math.max(...range)];
    return ticks.tickvals.flatMap((value, index) =>
        Math.log10(value) >= low - 1e-9 && Math.log10(value) <= high + 1e-9
            ? [ticks.ticktext[index]]
            : [],
    );
}

/** The minor ticks of the axis showing `range` that fall inside `window` (log10). */
function minorInside(
    range: [number, number],
    window: [number, number] = range,
): number[] {
    return logTicks(range, EN).minor.tickvals.filter(
        (value) =>
            Math.log10(value) >= window[0] && Math.log10(value) <= window[1],
    );
}

describe("logTicks", () => {
    it("labels only the powers of ten over two decades or more, 2…9 × 10ⁿ as unlabelled minor ticks", () => {
        const ticks = logTicks([0, 4.3], EN);
        expect(ticks.tickmode).toBe("array");
        expect(ticks.minor.tickmode).toBe("array");
        expect(shown([0, 4.3])).toEqual(["1", "10", "100", "1000", "10k"]);
        expect(minorInside([0, 4.3], [2, 3])).toEqual([
            200, 300, 400, 500, 600, 700, 800, 900,
        ]);
        expect(ticks.tickvals).not.toContain(200);
        expect(shown([1.2, 3.3])).toEqual(["100", "1000"]);
    });

    it("labels one power in every n past seven decades, the others minor", () => {
        const labels = shown([0, 12]);
        expect(labels.length).toBeLessThanOrEqual(7);
        expect(labels).toEqual(["1", "100", "10k", "1M", "100M", "10G", "1T"]);
        expect(minorInside([0, 12], [0, 2])).toEqual([10]);
    });

    it("labels 1, 2 and 5 × 10ⁿ between one and two decades, the other integers minor", () => {
        expect(shown([2.1, 3.9])).toEqual([
            "200",
            "500",
            "1000",
            "2000",
            "5000",
        ]);
        expect(shown([3.2, 4.7])).toEqual([
            "2000",
            "5000",
            "10k",
            "20k",
            "50k",
        ]);
        expect(minorInside([2.1, 3.3], [2.1, 2.7])).toEqual([300, 400]);
    });

    it("labels round linear steps inside one decade, between four and seven of them", () => {
        // Counts 1 500 to 9 000: the Fe K window of a box zoom.
        const range: [number, number] = [Math.log10(1500), Math.log10(9000)];
        expect(shown(range)).toEqual(["2000", "4000", "6000", "8000"]);
        expect(minorInside(range)).toEqual([]);
        expect(shown([Math.log10(1500), Math.log10(2500)])).toEqual([
            "1600",
            "1800",
            "2000",
            "2200",
            "2400",
        ]);
        expect(shown([Math.log10(12000), Math.log10(14000)])).toEqual([
            "12k",
            "12.5k",
            "13k",
            "13.5k",
            "14k",
        ]);
        for (const labels of [
            shown([3, 3.95]),
            shown([0.1, 0.9]),
            shown([-2, -1.2]),
        ]) {
            expect(labels.length).toBeGreaterThanOrEqual(3);
            expect(labels.length).toBeLessThanOrEqual(7);
        }
    });

    it("never labels a bare mantissa, and writes the decimal mark of the page", () => {
        const read = (label: string) =>
            Number(label.replace(/k$/, "e3").replace(/M$/, "e6"));
        for (const range of [
            [0, 5],
            [1.3, 2.9],
            [3.1, 3.6],
            [4.2, 4.9],
        ] as [number, number][]) {
            const ticks = logTicks(range, EN);
            ticks.ticktext.forEach((label, index) => {
                expect(read(label)).toBeCloseTo(ticks.tickvals[index], 6);
            });
        }
        expect(shown([1.3, 2.9])).toEqual(["20", "50", "100", "200", "500"]);
        expect(shown([Math.log10(12000), Math.log10(14000)], FR)).toContain(
            "12,5k",
        );
        expect(shown([-1.6, -0.1])).toEqual(["0.05", "0.1", "0.2", "0.5"]);
    });

    it("reads a reversed range, pads one of no height and takes the powers of ten for an unknown one", () => {
        expect(shown([4.3, 0])).toEqual(shown([0, 4.3]));
        expect(
            logTicks([3, 3], EN).tickvals.filter(
                (value) => value > 10 ** 2.5 && value < 10 ** 3.5,
            ),
        ).toEqual([500, 1000, 2000]);
        for (const range of [
            null,
            [Number.NaN, 3],
            [0, Number.POSITIVE_INFINITY],
        ] as ([number, number] | null)[]) {
            const ticks = logTicks(range, EN);
            expect(ticks.tickvals).toContain(1000);
            expect(ticks.tickvals).not.toContain(2000);
            expect(ticks.ticktext[ticks.tickvals.indexOf(10000)]).toBe("10k");
        }
    });

    it("gives every tick value its label, in the same order", () => {
        const ticks = logTicks([0.5, 6.5], EN);
        expect(ticks.ticktext).toHaveLength(ticks.tickvals.length);
        expect(ticks.tickvals).toEqual(
            [...ticks.tickvals].sort((a, b) => a - b),
        );
    });
});
