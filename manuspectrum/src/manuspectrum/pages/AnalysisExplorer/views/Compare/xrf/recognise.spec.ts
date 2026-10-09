import { describe, expect, it } from "vitest";

import { isXrfViewer } from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/xrf/recognise.ts";

describe("isXrfViewer", () => {
    it("recognises the xrf preset", () => {
        expect(isXrfViewer({ presetKey: "xrf", axisKey: null })).toBe(true);
    });

    it("recognises an energy axis in keV", () => {
        expect(
            isXrfViewer({
                presetKey: null,
                axisKey: "counts|energy (kev)|asc",
            }),
        ).toBe(true);
        expect(
            isXrfViewer({ presetKey: null, axisKey: "|Energy (keV)|asc" }),
        ).toBe(true);
    });

    it("refuses other spectra", () => {
        expect(
            isXrfViewer({
                presetKey: "ftir",
                axisKey: "absorbance|wavenumber (cm-1)|desc",
            }),
        ).toBe(false);
        expect(isXrfViewer({ presetKey: null, axisKey: null })).toBe(false);
        expect(
            isXrfViewer({
                presetKey: null,
                axisKey: "energy (kev)|counts|asc",
            }),
        ).toBe(false);
    });
});
