import { describe, expect, it } from "vitest";

import { loadLineTable } from "./line-table";
import {
    comptonEnergy,
    escapeOf,
    excitable,
    focusLines,
    fwhmAt,
    lineLabel,
    principalLine,
    tolerance,
} from "./physics";

describe("fwhmAt", () => {
    it("equals the setting at Mn Kα", () => {
        expect(fwhmAt(5.895, 0.14)).toBeCloseTo(0.14, 6);
    });

    it("is about 0.104 keV at 2.3 keV for a 140 eV detector", () => {
        expect(fwhmAt(2.3, 0.14)).toBeCloseTo(0.104, 3);
    });
});

describe("tolerance", () => {
    it("never falls under 0.1 keV, else half the FWHM", () => {
        expect(tolerance(2.3, 0.14)).toBe(0.1);
        expect(tolerance(60, 0.14)).toBeGreaterThan(0.1);
    });
});

describe("comptonEnergy", () => {
    it("moves Ag Kα to 21.24 keV at 90°", () => {
        expect(comptonEnergy(22.163, 90)).toBeCloseTo(21.24, 2);
    });
});

describe("escapeOf", () => {
    it("shifts 6.40 keV to 4.66", () => {
        expect(escapeOf(6.4)).toBeCloseTo(4.66, 2);
    });

    it("gives none at or below 1.839 keV", () => {
        expect(escapeOf(1.839)).toBeNull();
        expect(escapeOf(1.5)).toBeNull();
    });
});

describe("with the line table", () => {
    it("leaves Pb K unexcited at 50 kV, excited with unknown kV", async () => {
        const { Pb } = (await loadLineTable()).elements;
        expect(excitable(Pb.lines.Ka1, Pb.edges, 50)).toBe(false);
        expect(excitable(Pb.lines.Ka1, Pb.edges, 90)).toBe(true);
        expect(excitable(Pb.lines.Ka1, Pb.edges, null)).toBe(true);
        expect(excitable(Pb.lines.La1, Pb.edges, 50)).toBe(true);
    });

    it("reads the first level of a joint initial level", async () => {
        const { Ac } = (await loadLineTable()).elements;
        expect(excitable(Ac.lines.Mz, Ac.edges, 4)).toBe(true);
        expect(excitable(Ac.lines.Mz, Ac.edges, 3)).toBe(false);
    });

    it("takes Lα1 as the principal line of Pb and Kα1 for Fe", async () => {
        const { Pb, Fe } = (await loadLineTable()).elements;
        expect(principalLine(Pb, [1, 40], 50)?.name).toBe("La1");
        expect(principalLine(Fe, [1, 40], 50)?.name).toBe("Ka1");
        expect(principalLine(Fe, [1, 5], 50)).toBeNull();
    });

    it("lists the focus lines present with their labels", async () => {
        const { Fe, Pb } = (await loadLineTable()).elements;
        expect(focusLines(Fe).map((l) => l.label)).toContain("Kα1");
        expect(focusLines(Pb).map((l) => l.label)).toEqual(
            expect.arrayContaining(["Lα1", "Lβ1", "Lγ1", "Mα", "Mβ"]),
        );
    });
});

describe("lineLabel", () => {
    it("writes Siegbahn names with Greek letters", () => {
        expect(lineLabel("Ka1")).toBe("Kα1");
        expect(lineLabel("Lb2,15")).toBe("Lβ2,15");
        expect(lineLabel("Ma")).toBe("Mα");
    });
});
