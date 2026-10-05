import { describe, expect, it } from "vitest";

import {
    PERIODIC_COLUMNS,
    PERIODIC_TABLE,
    atomicNumber,
    placeOf,
} from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/periodic.ts";

describe("periodic table", () => {
    it("holds the 118 elements once each on 18 columns", () => {
        const symbols = PERIODIC_TABLE.map((place) => place.symbol);
        expect(symbols).toHaveLength(118);
        expect(new Set(symbols).size).toBe(118);
        expect(PERIODIC_COLUMNS).toBe(18);
        expect(
            PERIODIC_TABLE.every(
                (place) => place.column >= 1 && place.column <= 18,
            ),
        ).toBe(true);
    });

    it("places elements as the standard table does", () => {
        expect(placeOf("H")).toEqual({ symbol: "H", row: 1, column: 1 });
        expect(placeOf("He")).toEqual({ symbol: "He", row: 1, column: 18 });
        expect(placeOf("Cu")).toEqual({ symbol: "Cu", row: 4, column: 11 });
        expect(placeOf("Pb")).toEqual({ symbol: "Pb", row: 6, column: 14 });
        expect(placeOf("Og")).toEqual({ symbol: "Og", row: 7, column: 18 });
    });

    it("puts the lanthanides and actinides on two rows below, after a gap", () => {
        expect(placeOf("La")).toEqual({ symbol: "La", row: 6, column: 3 });
        expect(placeOf("Ce")).toEqual({ symbol: "Ce", row: 9, column: 4 });
        expect(placeOf("Lu")).toEqual({ symbol: "Lu", row: 9, column: 17 });
        expect(placeOf("Th")).toEqual({ symbol: "Th", row: 10, column: 4 });
    });

    it("places nothing for an unknown symbol", () => {
        expect(placeOf("Xx")).toBeNull();
    });

    it("gives the atomic number of each of the 118 elements, once", () => {
        const numbers = PERIODIC_TABLE.map((place) =>
            atomicNumber(place.symbol),
        );
        expect(new Set(numbers).size).toBe(118);
        expect(Math.min(...(numbers as number[]))).toBe(1);
        expect(Math.max(...(numbers as number[]))).toBe(118);
        expect(atomicNumber("Cu")).toBe(29);
        expect(atomicNumber("Pb")).toBe(82);
        expect(atomicNumber("Xx")).toBeNull();
    });
});
