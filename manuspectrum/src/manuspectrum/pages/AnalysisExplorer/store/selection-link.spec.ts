import { describe, expect, it } from "vitest";

import { parseSelection } from "@/manuspectrum/pages/AnalysisExplorer/store/selection-link.ts";

function key(n: number): string {
    return `ch:00000000-0000-4000-8000-${String(n).padStart(12, "0")}:-`;
}

describe("parseSelection", () => {
    it("answers null for an empty or all-invalid parameter", () => {
        expect(parseSelection(null)).toBeNull();
        expect(parseSelection("")).toBeNull();
        expect(parseSelection("<script>,javascript:alert(1)")).toBeNull();
    });

    it("drops invalid keys, dedupes, sorts and caps at 30 with a truncation count", () => {
        const raw = [
            key(3),
            key(1),
            "junk",
            key(3).toUpperCase(),
            ...Array.from({ length: 32 }, (_, n) => key(100 + n)),
        ].join(",");
        const selection = parseSelection(raw);
        expect(selection?.invalid).toBe(1);
        expect(selection?.keys).toHaveLength(30);
        expect(selection?.keys[0]).toBe(key(1));
        expect(selection?.keys).toEqual([...(selection?.keys ?? [])].sort());
        expect(selection?.truncated).toBe(4);
    });

    it("ignores anything past 4096 characters", () => {
        const raw = `${key(1)},${"a".repeat(5000)},${key(2)}`;
        expect(parseSelection(raw)?.keys).toEqual([key(1)]);
    });
});
