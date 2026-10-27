import { describe, it, expect } from "vitest";
import {
    annotationLogY,
    canUseLogScale,
    logScaleFigure,
    smallestPositive,
} from "./xy-scale";

const trace = (y, extra = {}) => ({ x: y.map((_, i) => i), y, ...extra });

describe("logScaleFigure", () => {
    it("lays zeros and negatives on the curve smallest positive value", () => {
        const { traces } = logScaleFigure([trace([0, 5, -3, 2, 10])]);
        expect(traces[0].y).toEqual([2, 5, 2, 2, 10]);
    });

    it("keeps the real values for the hover", () => {
        const { traces } = logScaleFigure([trace([0, 5, -3])]);
        expect(traces[0].customdata).toEqual([0, 5, -3]);
        expect(traces[0].hovertemplate).toContain("%{customdata}");
    });

    it("floors each curve on its own minimum", () => {
        const { traces } = logScaleFigure([trace([0, 100]), trace([0, 0.5])]);
        expect(traces[0].y).toEqual([100, 100]);
        expect(traces[1].y).toEqual([0.5, 0.5]);
    });

    it("asks Plotly for a log axis and leaves the input untouched", () => {
        const input = [trace([0, 4])];
        const { yaxis } = logScaleFigure(input);
        expect(yaxis).toEqual({ type: "log" });
        expect(input[0].y).toEqual([0, 4]);
        expect(input[0].customdata).toBeUndefined();
    });

    it("leaves a curve on the right axis linear", () => {
        const right = trace([0, 3], { yaxis: "y2" });
        const { traces } = logScaleFigure([right]);
        expect(traces[0]).toBe(right);
    });

    it("reads typed arrays", () => {
        const { traces } = logScaleFigure([trace(new Float32Array([0, 2]))]);
        expect(traces[0].y).toEqual([2, 2]);
    });
});

describe("canUseLogScale", () => {
    it("is true when every curve has a positive value", () => {
        expect(canUseLogScale([trace([0, 1]), trace([-1, 7])])).toBe(true);
    });

    it("is false when a curve has no positive value", () => {
        expect(canUseLogScale([trace([1, 2]), trace([0, -4, 0])])).toBe(false);
        expect(canUseLogScale([trace([null, NaN])])).toBe(false);
    });

    it("is false with nothing to draw", () => {
        expect(canUseLogScale([])).toBe(false);
        expect(canUseLogScale(null)).toBe(false);
    });

    it("ignores a right-axis curve", () => {
        const right = trace([0, 0], { yaxis: "y2" });
        expect(canUseLogScale([trace([1]), right])).toBe(true);
    });
});

describe("annotationLogY", () => {
    it("converts to log10, which Plotly reads on a log axis", () => {
        expect(annotationLogY(1000)).toBeCloseTo(3);
        expect(annotationLogY(0.01)).toBeCloseTo(-2);
    });

    it("refuses a value a log axis cannot place", () => {
        expect(annotationLogY(0)).toBeNull();
        expect(annotationLogY(-5)).toBeNull();
        expect(annotationLogY(undefined)).toBeNull();
    });
});

describe("smallestPositive", () => {
    it("is null without a positive value", () => {
        expect(smallestPositive([0, -1])).toBeNull();
    });
});
