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

    it("gives each technique a distinct code", () => {
        const styles = techniqueStyles(
            [
                valueRef("t:xrf", "XRF"),
                valueRef("t:xrd", "XRD"),
                valueRef("t:xrf2", "XRF"),
            ],
            NONE,
        );
        const codes = [...styles.values()].map((s) => s.code);
        expect(new Set(codes).size).toBe(codes.length);
        expect(codes[0]).toBe("X");
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
