import { describe, expect, it } from "vitest";

import { allSymbols, loadLineTable } from "./line-table";

describe("loadLineTable", () => {
    it("memoises one promise", () => {
        expect(loadLineTable()).toBe(loadLineTable());
    });

    it("resolves the table of elements 11 to 92", async () => {
        const table = await loadLineTable();
        expect(table.elements.Fe.lines.Ka1[0]).toBeCloseTo(6.405, 3);
        expect(Object.keys(table.elements)).toHaveLength(82);
    });
});

describe("allSymbols", () => {
    it("lists Na to U by atomic number", async () => {
        const symbols = allSymbols(await loadLineTable());
        expect(symbols[0]).toBe("Na");
        expect(symbols.at(-1)).toBe("U");
    });
});
