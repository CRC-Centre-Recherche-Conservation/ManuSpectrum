import { describe, expect, it } from "vitest";

import { loadLineTable } from "./line-table";
import { overlaps, tellApart, usableLines } from "./overlaps";
import { fwhmAt, lineRef } from "./physics";

import type { OverlapLine } from "./overlaps";

const FWHM = (energy: number) => fwhmAt(energy, 0.14);
const CONTEXT = { fwhmAt: FWHM, range: [0.5, 40] as [number, number], kV: 40 };

async function lines(symbol: string, names: string[]): Promise<OverlapLine[]> {
    const { elements } = await loadLineTable();
    return names.map((name) => ({
        symbol,
        line: lineRef(name, elements[symbol].lines[name]),
    }));
}

describe("overlaps", () => {
    it("finds As Kα1 under Pb Lα1 and nothing for Pb Lβ1", async () => {
        const as = await lines("As", ["Ka1", "Kb1"]);
        const pb = await lines("Pb", ["La1", "Lb1"]);
        const found = overlaps(as, pb, FWHM);
        expect(found).toHaveLength(1);
        expect(found[0].a.line.name).toBe("Ka1");
        expect(found[0].b.line.name).toBe("La1");
        expect(found[0].separation).toBeCloseTo(0.008, 3);
        expect(found[0].centre).toBeCloseTo(10.547, 3);
        expect(found[0].width).toBeCloseTo(FWHM(10.547), 6);
    });

    it("finds S Kα, Pb Mα and Mo Lα overlapping each other", async () => {
        const s = await lines("S", ["Ka1"]);
        const pb = await lines("Pb", ["Ma"]);
        const mo = await lines("Mo", ["La1"]);
        expect(overlaps(s, pb, FWHM)).toHaveLength(1);
        expect(overlaps(s, mo, FWHM)).toHaveLength(1);
        expect(overlaps(mo, pb, FWHM)).toHaveLength(1);
    });

    it("never pairs two lines of one element", async () => {
        const pb = await lines("Pb", ["La1", "La2"]);
        expect(overlaps(pb, pb, FWHM)).toEqual([]);
    });
});

describe("tellApart", () => {
    it("tells As Kα1 from Pb Lα1 by As Kβ1 against Pb Lβ1", async () => {
        const { elements } = await loadLineTable();
        const [as] = await lines("As", ["Ka1"]);
        const [pb] = await lines("Pb", ["La1"]);
        const apart = tellApart(
            { symbol: "As", element: elements.As },
            as.line,
            { symbol: "Pb", element: elements.Pb },
            pb.line,
            CONTEXT,
        );
        expect(apart.a?.name).toBe("Kb1");
        expect(apart.a?.energy).toBeCloseTo(11.726, 3);
        expect(apart.b?.name).toBe("Lb1");
        expect(apart.b?.energy).toBeCloseTo(12.614, 3);
    });

    it("gives null for S, whose only other line is just as close", async () => {
        const { elements } = await loadLineTable();
        const [s] = await lines("S", ["Ka1"]);
        const [pb] = await lines("Pb", ["Ma"]);
        const apart = tellApart(
            { symbol: "S", element: elements.S },
            s.line,
            { symbol: "Pb", element: elements.Pb },
            pb.line,
            CONTEXT,
        );
        expect(apart.a).toBeNull();
        expect(apart.b?.name).not.toBe("Ma");
    });

    it("skips a line the data range or the voltage rules out", async () => {
        const { elements } = await loadLineTable();
        const [as] = await lines("As", ["Ka1"]);
        const [pb] = await lines("Pb", ["La1"]);
        const apart = tellApart(
            { symbol: "As", element: elements.As },
            as.line,
            { symbol: "Pb", element: elements.Pb },
            pb.line,
            { ...CONTEXT, range: [0.5, 11] },
        );
        expect(apart.a).toBeNull();
        expect(apart.b).toBeNull();
        expect(
            usableLines(elements.As, [0.5, 40], 10).map((l) => l.name),
        ).not.toContain("Ka1");
    });
});
