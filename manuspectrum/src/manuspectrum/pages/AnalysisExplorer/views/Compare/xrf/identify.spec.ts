import { describe, expect, it } from "vitest";

import { candidates, instrumentPeaks } from "./identify";
import { loadLineTable } from "./line-table";

import type { DeclaredElement } from "./declared";
import type {
    CandidateContext,
    ElementCandidate,
    InstrumentCandidate,
} from "./identify";

const FWHM_MN = 0.14;

/** Counts on 0.5–40 keV: a flat 100 background plus Gaussians of `[keV, height]`. */
function spectrum(peaks: [number, number][], top = 40) {
    const n = Math.round((top - 0.5) / 0.01) + 1;
    const x = Float64Array.from({ length: n }, (_, i) => 0.5 + i * 0.01);
    const y = Float64Array.from(x, (e) => {
        let counts = 100;
        for (const [centre, height] of peaks) {
            counts += height * Math.exp(-((e - centre) ** 2) / (2 * 0.05 ** 2));
        }
        return Math.round(counts);
    });
    return { x, y };
}

const PB_SPECTRUM = spectrum([
    [10.551, 2000],
    [12.614, 1400],
    [14.766, 0],
]);

async function context(
    curve = PB_SPECTRUM,
    over: Partial<CandidateContext> = {},
): Promise<CandidateContext> {
    return {
        table: await loadLineTable(),
        ...curve,
        kV: 40,
        fwhmMn: FWHM_MN,
        declaredForCurve: new Map(),
        declaredInSelection: new Map(),
        lensElements: new Set(),
        instrumentPeaks: [],
        ...over,
    };
}

function elementRows(rows: ReturnType<typeof candidates>) {
    return rows.filter(
        (row): row is ElementCandidate => row.type === "element",
    );
}

const DECLARED: DeclaredElement = {
    rank: 0,
    materials: [{ id: "m", level: null }],
};

describe("candidates", () => {
    it("ranks Pb above As on a Pb spectrum, As Kβ1 absent", async () => {
        const rows = elementRows(candidates(10.55, await context()));
        const symbols = rows.map((r) => r.symbol);
        expect(symbols.indexOf("Pb")).toBeLessThan(symbols.indexOf("As"));
        const pb = rows.find((r) => r.symbol === "Pb")!;
        const as = rows.find((r) => r.symbol === "As")!;
        expect(pb.line.name).toBe("La1");
        expect(pb.confirmations.find((c) => c.line.name === "Lb1")?.state).toBe(
            "present",
        );
        expect(as.confirmations).toEqual([
            expect.objectContaining({
                line: expect.objectContaining({ name: "Kb1" }),
                state: "absent",
            }),
        ]);
        expect(as.score).toBe(0);
    });

    it("ranks As above Pb on an As spectrum although Pb Lα1 is the stronger line", async () => {
        const rows = elementRows(
            candidates(
                10.54,
                await context(
                    spectrum([
                        [10.543, 2000],
                        [11.726, 300],
                    ]),
                ),
            ),
        );
        const symbols = rows.map((r) => r.symbol);
        expect(symbols.indexOf("As")).toBeLessThan(symbols.indexOf("Pb"));
        expect(
            rows.find((r) => r.symbol === "Pb")!.line.intensity,
        ).toBeGreaterThan(rows.find((r) => r.symbol === "As")!.line.intensity);
    });

    it("puts the element declared for the curve first, then the Selection's", async () => {
        const asFirst = elementRows(
            candidates(
                10.55,
                await context(PB_SPECTRUM, {
                    declaredForCurve: new Map([["As", DECLARED]]),
                }),
            ),
        );
        expect(asFirst[0].symbol).toBe("As");
        expect(asFirst[0].declared?.scope).toBe("curve");

        const rows = elementRows(
            candidates(
                10.55,
                await context(PB_SPECTRUM, {
                    declaredInSelection: new Map([["As", DECLARED]]),
                    lensElements: new Set(["Pb"]),
                }),
            ),
        );
        expect(rows[0].symbol).toBe("As");
        expect(rows[0].declared?.scope).toBe("selection");
        expect(rows.find((r) => r.symbol === "Pb")?.inLens).toBe(true);
    });

    it("declared Pb comes first even when its confirmations are absent", async () => {
        const flat = spectrum([[10.543, 2000]]);
        const rows = candidates(
            10.55,
            await context(flat, {
                declaredForCurve: new Map([["Pb", DECLARED]]),
            }),
        );
        expect((rows[0] as ElementCandidate).symbol).toBe("Pb");
    });

    it("recognises the Rayleigh Ag Kα of the tube", async () => {
        const curve = spectrum([[22.163, 3000]]);
        const table = await loadLineTable();
        const peaks = instrumentPeaks(curve, "Ag", 40, table, FWHM_MN);
        const rows = candidates(
            22.16,
            await context(curve, { instrumentPeaks: peaks }),
        );
        const rayleigh = rows.find(
            (r): r is InstrumentCandidate =>
                r.type === "instrument" && r.peak.kind === "rayleigh",
        );
        expect(rayleigh?.peak.source).toBe("Ag");
        expect(rayleigh?.peak.line).toBe("Kα1");
        expect(rows.findIndex((r) => r === rayleigh)).toBeLessThan(
            rows.findIndex((r) => r.type === "element"),
        );
    });

    it("leaves out a line the known kV cannot excite", async () => {
        const lowKv = await context(PB_SPECTRUM, { kV: 20 });
        expect(
            elementRows(candidates(22.16, lowKv)).some(
                (r) => r.symbol === "Ag",
            ),
        ).toBe(false);
        const wide = await context(spectrum([], 100), { kV: 40 });
        expect(
            elementRows(candidates(74.97, wide)).some((r) => r.symbol === "Pb"),
        ).toBe(false);
        const unknown = await context(spectrum([], 100), { kV: null });
        expect(
            elementRows(candidates(74.97, unknown)).some(
                (r) => r.symbol === "Pb",
            ),
        ).toBe(true);
    });

    it("marks a confirmation beyond the data and one the voltage cannot excite", async () => {
        const short = spectrum([[10.55, 2000]], 12);
        const rows = elementRows(candidates(10.55, await context(short)));
        const pb = rows.find((r) => r.symbol === "Pb")!;
        expect(pb.confirmations.find((c) => c.line.name === "Lb1")?.state).toBe(
            "out-of-range",
        );
        const low = elementRows(
            candidates(10.55, await context(PB_SPECTRUM, { kV: 14 })),
        ).find((r) => r.symbol === "Pb")!;
        expect(low.confirmations.map((c) => c.state)).toEqual([
            "not-excited",
            "not-excited",
        ]);
        expect(low.score).toBeNull();
    });

    it("is pure: the same input gives the same rows", async () => {
        const ctx = await context();
        expect(candidates(10.55, ctx)).toEqual(candidates(10.55, ctx));
    });
});

describe("instrumentPeaks", () => {
    it("lists the K lines, the Compton band and the Duane–Hunt limit of a 40 kV Ag tube", async () => {
        const table = await loadLineTable();
        const peaks = instrumentPeaks(spectrum([]), "Ag", 40, table, FWHM_MN);
        const kinds = (kind: string) => peaks.filter((p) => p.kind === kind);
        expect(kinds("rayleigh").map((p) => p.line)).toEqual([
            "Kα1",
            "Kβ1",
            "Lα1",
        ]);
        const [compton] = kinds("compton");
        expect(compton.from).toBeLessThan(compton.to);
        expect(compton.to).toBeCloseTo(21.24, 2);
        expect(kinds("duane-hunt")[0].energy).toBe(40);
    });

    it("uses the L lines when kV is under the K edge, none without an anode", async () => {
        const table = await loadLineTable();
        const rh = instrumentPeaks(spectrum([], 20), "Ag", 20, table, FWHM_MN);
        expect(
            rh.filter((p) => p.kind === "rayleigh").map((p) => p.line),
        ).toEqual(["Lα1", "Lβ1"]);
        const none = instrumentPeaks(spectrum([]), null, null, table, FWHM_MN);
        expect(
            none.filter((p) => p.kind !== "escape" && p.kind !== "sum"),
        ).toEqual([]);
    });

    it("derives the Si escape and the sum peaks of the strongest peaks", async () => {
        const table = await loadLineTable();
        const curve = spectrum([[6.4, 5000]]);
        const peaks = instrumentPeaks(curve, null, null, table, FWHM_MN);
        const escape = peaks.find((p) => p.kind === "escape");
        expect(escape?.energy).toBeCloseTo(4.66, 1);
        expect(escape?.parents[0]).toBeCloseTo(6.4, 1);
        expect(peaks.find((p) => p.kind === "sum")?.energy).toBeCloseTo(
            12.8,
            1,
        );
    });

    it("drops what falls outside the curve", async () => {
        const table = await loadLineTable();
        const peaks = instrumentPeaks(
            spectrum([], 10),
            "Ag",
            40,
            table,
            FWHM_MN,
        );
        expect(peaks.some((p) => p.kind === "rayleigh" && p.energy > 10)).toBe(
            false,
        );
        expect(peaks.some((p) => p.kind === "duane-hunt")).toBe(false);
    });
});
