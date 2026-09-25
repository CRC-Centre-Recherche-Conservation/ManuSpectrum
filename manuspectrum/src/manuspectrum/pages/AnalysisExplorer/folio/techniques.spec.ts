import { describe, expect, it } from "vitest";

import { techniqueStyles } from "@/manuspectrum/pages/AnalysisExplorer/folio/techniques.ts";
import {
    label,
    valueRef,
} from "@/manuspectrum/pages/AnalysisExplorer/testing/fixtures.ts";

const NONE = label("Analysis");

describe("technique styles", () => {
    it("orders the techniques by label and gives the first six a colour", () => {
        const names = ["XRF", "FORS", "Raman", "IR", "MALDI", "UV", "XRD"];
        const styles = techniqueStyles(
            names.map((n) => valueRef(`t:${n}`, n)),
            NONE,
        );
        expect(
            [...styles.values()].map((s) => [s.label.value, s.colour]),
        ).toEqual([
            ["FORS", 1],
            ["IR", 2],
            ["MALDI", 3],
            ["Raman", 4],
            ["UV", 5],
            ["XRD", 6],
            ["XRF", null],
        ]);
    });

    it("gives each technique family the same code in every document", () => {
        const first = techniqueStyles(
            [
                valueRef("t:xrf", "X-ray fluorescence"),
                valueRef("t:pxrf", "portable X-ray fluorescence"),
                valueRef("t:fors", "fiber optic reflectance spectrometry"),
            ],
            NONE,
        );
        const second = techniqueStyles(
            [
                valueRef("t:micro-xrf", "Microfluorescence x"),
                valueRef("t:raman", "Spectrométrie Raman"),
                valueRef("t:hsi", "imagerie hyperspectrale"),
                valueRef("t:macro", "Macrophotographie"),
                valueRef("t:ftir", "IRTF"),
                valueRef(
                    "t:maldi",
                    "Spectrométrie de masse par désorption laser",
                ),
                valueRef("t:om", "Microscopie optique"),
            ],
            NONE,
        );
        const codes = (styles: ReturnType<typeof techniqueStyles>) =>
            Object.fromEntries(
                [...styles.values()].map((style) => [style.key, style.code]),
            );
        expect(codes(first)).toEqual({
            "t:xrf": "X",
            "t:pxrf": "X",
            "t:fors": "F",
        });
        expect(codes(second)).toEqual({
            "t:micro-xrf": "X",
            "t:raman": "R",
            "t:hsi": "I",
            "t:macro": "I",
            "t:ftir": "IR",
            "t:maldi": "MS",
            "t:om": "M",
        });
    });

    it("codes a technique outside the families by its first letters, apart from the family codes", () => {
        const styles = techniqueStyles(
            [
                valueRef("t:xrf", "XRF"),
                valueRef("t:xeno", "Xenon lamp test"),
                valueRef("t:xylo", "Xylography"),
            ],
            NONE,
        );
        expect(styles.get("t:xrf")?.code).toBe("X");
        expect(styles.get("t:xeno")?.code).toBe("XE");
        expect(styles.get("t:xylo")?.code).toBe("XY");
    });

    it("keeps one entry per URI and names an analysis without technique", () => {
        const styles = techniqueStyles(
            [valueRef("t:xrf", "XRF"), null, valueRef("t:xrf", "XRF")],
            NONE,
        );
        expect(styles.size).toBe(2);
        expect(styles.get("")?.label).toEqual(NONE);
    });
});
