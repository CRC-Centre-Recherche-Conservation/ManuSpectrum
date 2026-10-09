import { describe, expect, it } from "vitest";

import {
    techniqueClass,
    techniqueStyles,
} from "@/manuspectrum/pages/AnalysisExplorer/folio/techniques.ts";
import {
    label,
    technique,
} from "@/manuspectrum/pages/AnalysisExplorer/testing/fixtures.ts";

const NONE = label("Analysis");

describe("technique styles", () => {
    it("takes code and colour from the technique, ordered by label", () => {
        const styles = techniqueStyles(
            [
                technique("t:xrf", "X-ray fluorescence", 1, "t:xrf", "XRF"),
                technique("t:pxrf", "Portable XRF", 1, "t:pxrf", "pXRF"),
                technique("t:fors", "FORS", 4, "t:fors", "FORS"),
                technique("t:om", "Optical microscopy", null, "t:om", "OM"),
            ],
            NONE,
        );
        expect(
            [...styles.values()].map((s) => [s.label.value, s.code, s.colour]),
        ).toEqual([
            ["FORS", "FORS", 4],
            ["Optical microscopy", "OM", null],
            ["Portable XRF", "pXRF", 1],
            ["X-ray fluorescence", "XRF", 1],
        ]);
    });

    it("gives a technique the same style whatever the other techniques of the document", () => {
        const pxrf = technique("t:pxrf", "Portable XRF", 2, "t:pxrf", "pXRF");
        const alone = techniqueStyles([pxrf], NONE).get("t:pxrf");
        const among = techniqueStyles(
            [
                technique("t:a", "Alpha", 5, "t:a", "A"),
                technique("t:b", "Beta", 6, "t:b", "B"),
                pxrf,
            ],
            NONE,
        ).get("t:pxrf");
        expect(among).toEqual(alone);
    });

    it("gives the same style in English and French", () => {
        const en = techniqueStyles(
            [technique("t:xrf", "X-ray fluorescence", 3, "t:xrf", "XRF")],
            NONE,
        ).get("t:xrf");
        const fr = techniqueStyles(
            [technique("t:xrf", "Fluorescence X", 3, "t:xrf", "XRF")],
            NONE,
        ).get("t:xrf");
        expect([fr?.code, fr?.colour]).toEqual([en?.code, en?.colour]);
    });

    it("keeps one entry per URI and draws an analysis without technique in ink", () => {
        const xrf = technique("t:xrf", "XRF");
        const styles = techniqueStyles([xrf, null, xrf], NONE);
        expect(styles.size).toBe(2);
        expect(styles.get("")).toEqual({
            key: "",
            label: NONE,
            code: "?",
            colour: null,
        });
    });

    it("names the colour class of a style", () => {
        expect(techniqueClass("dot", 7)).toBe("dot--tech-7");
        expect(techniqueClass("dot", null)).toBe("dot--ink");
    });
});
