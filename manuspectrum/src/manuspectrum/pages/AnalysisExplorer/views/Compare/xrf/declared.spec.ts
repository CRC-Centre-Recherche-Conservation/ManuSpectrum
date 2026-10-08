import { describe, expect, it } from "vitest";

import {
    declaredByAnalysis,
    declaredParts,
    declaredText,
    mergeDeclared,
} from "./declared";

import type {
    CharacterizationSummary,
    RankedValue,
    SynthesisMaterial,
    ValueRef,
} from "@/manuspectrum/pages/AnalysisExplorer/api/types.ts";
import type { BasketItem } from "@/manuspectrum/pages/AnalysisExplorer/store/types.ts";

const HG_ID = "value-hg";
const S_ID = "value-s";
const PB_ID = "value-pb";
const SYMBOLS = new Map([
    [HG_ID, "Hg"],
    [S_ID, "S"],
    [PB_ID, "Pb"],
]);

const AN_A = "11111111-1111-4111-8111-111111111111";
const AN_B = "22222222-2222-4222-8222-222222222222";
const CH_V = "33333333-3333-4333-8333-333333333333";
const CH_W = "44444444-4444-4444-8444-444444444444";
const CH_NONE = "55555555-5555-4555-8555-555555555555";

function value(id: string): ValueRef {
    return { id, uri: id, label: { value: id, lang: "en" } };
}

function level(name: string, rank: number): RankedValue {
    return {
        ...value(`level-${name}`),
        label: { value: name, lang: "en" },
        rank,
    };
}

function material(
    id: string,
    name: string,
    evidence: string[],
    elements: { level: RankedValue | null; ids: string[] }[],
): SynthesisMaterial {
    return {
        id,
        evidence,
        canvases: [],
        objects: [],
        selected: false,
        summary: {
            id,
            name: { value: name, lang: "en" },
            elements: elements.map((e) => ({
                level: e.level,
                values: e.ids.map(value),
            })),
        } as unknown as CharacterizationSummary,
    };
}

const MAJOR = level("Major", 0);
const MINOR = level("Minor", 1);

const SYNTHESIS = {
    materials: [
        material(
            CH_V,
            "Vermilion",
            [AN_A],
            [
                { level: MAJOR, ids: [HG_ID, S_ID] },
                { level: MINOR, ids: [HG_ID] },
            ],
        ),
        material(
            CH_W,
            "Cinnabar",
            [AN_A, AN_B],
            [{ level: MINOR, ids: [HG_ID] }],
        ),
        material(CH_NONE, "Orpiment", [], [{ level: MAJOR, ids: [PB_ID] }]),
    ],
};

describe("declaredByAnalysis", () => {
    it("keeps the best rank of a material, not the best across materials", () => {
        const a = declaredByAnalysis(SYNTHESIS, SYMBOLS).get(AN_A)!.get("Hg")!;
        expect(a.materials).toEqual([
            { id: CH_V, level: MAJOR },
            { id: CH_W, level: MINOR },
        ]);
        expect(a.rank).toBe(0);
        const b = declaredByAnalysis(SYNTHESIS, SYMBOLS).get(AN_B)!.get("Hg")!;
        expect(b.materials).toEqual([{ id: CH_W, level: MINOR }]);
        expect(b.rank).toBe(1);
    });

    it("ignores a material without evidence and an element without symbol", () => {
        const map = declaredByAnalysis(SYNTHESIS, SYMBOLS);
        expect([...map.keys()].sort()).toEqual([AN_A, AN_B].sort());
        expect(map.get(AN_A)!.has("Pb")).toBe(false);
        expect(declaredByAnalysis(SYNTHESIS, new Map()).size).toBe(2);
        expect(declaredByAnalysis(SYNTHESIS, new Map()).get(AN_A)!.size).toBe(
            0,
        );
    });

    it("ranks a material without level after one with a level", () => {
        const map = declaredByAnalysis(
            {
                materials: [
                    material(
                        CH_V,
                        "Vermilion",
                        [AN_A],
                        [{ level: null, ids: [S_ID] }],
                    ),
                    material(
                        CH_W,
                        "Cinnabar",
                        [AN_A],
                        [{ level: MINOR, ids: [S_ID] }],
                    ),
                ],
            },
            SYMBOLS,
        );
        const entry = map.get(AN_A)!.get("S")!;
        expect(entry.rank).toBe(1);
        expect(entry.materials.map((m) => m.id)).toEqual([CH_W, CH_V]);
    });
});

describe("mergeDeclared", () => {
    it("keeps the best rank per symbol and each material once", () => {
        const map = declaredByAnalysis(SYNTHESIS, SYMBOLS);
        const merged = mergeDeclared([map.get(AN_A), map.get(AN_B), undefined]);
        expect(merged.get("Hg")!.rank).toBe(0);
        expect(merged.get("Hg")!.materials.map((m) => m.id)).toEqual([
            CH_V,
            CH_W,
        ]);
    });
});

const TEXT = {
    $gettext: (msgid: string) => msgid,
    interpolate: (msgid: string, values: Record<string, string>) =>
        msgid.replace(/%\{(\w+)\}/g, (_, key: string) => values[key]),
};

function item(key: string, slot: number, kind: BasketItem["kind"]): BasketItem {
    return { key: key as BasketItem["key"], kind, slot };
}

describe("declaredParts and declaredText", () => {
    const entry = declaredByAnalysis(SYNTHESIS, SYMBOLS).get(AN_A)!.get("Hg")!;

    it("names the material's own slot", () => {
        const parts = declaredParts(entry, AN_A, SYNTHESIS, [
            item(`ch:${CH_V}:-`, 29, "characterization"),
            item(`an:${AN_A}:-`, 2, "analysis"),
        ]);
        expect(parts?.slot).toBe("A30");
        expect(declaredText(parts!, TEXT)).toBe(
            "declared Major in Vermilion (A30)",
        );
    });

    it("says what the material cites when it has no slot", () => {
        const parts = declaredParts(entry, AN_A, SYNTHESIS, [
            item(`an:${AN_A}:-`, 2, "analysis"),
        ]);
        expect(parts?.slot).toBeNull();
        expect(declaredText(parts!, TEXT)).toBe(
            "declared Major in Vermilion (cites A3)",
        );
    });

    it("drops the level and the bracket when there is none", () => {
        const bare = { rank: null, materials: [{ id: CH_V, level: null }] };
        const parts = declaredParts(bare, AN_A, SYNTHESIS, []);
        expect(declaredText(parts!, TEXT)).toBe("declared in Vermilion");
    });

    it("gives null for a material the synthesis does not hold", () => {
        const lost = { rank: 0, materials: [{ id: "x", level: MAJOR }] };
        expect(declaredParts(lost, AN_A, SYNTHESIS, [])).toBeNull();
    });
});
