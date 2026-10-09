import type {
    Label,
    RankedValue,
    SynthesisResponse,
} from "@/manuspectrum/pages/AnalysisExplorer/api/types.ts";
import type { BasketItem } from "@/manuspectrum/pages/AnalysisExplorer/store/types.ts";
import type { TagTranslate } from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/layer-tag-text.ts";

import { slotLabel } from "@/manuspectrum/pages/AnalysisExplorer/store/basket.ts";

type MaterialsOf = Pick<SynthesisResponse, "materials">;

export interface DeclaredMaterial {
    id: string;
    /** The material's best level for the element; null when it gives none. */
    level: RankedValue | null;
}

export interface DeclaredElement {
    /** Best rank over the materials (0 strongest); null when none gives a level. */
    rank: number | null;
    /** Best level first, then by id. */
    materials: DeclaredMaterial[];
}

/** Analysis id → element symbol → what the materials citing it declare. */
export type DeclaredMap = Map<string, Map<string, DeclaredElement>>;

/** Whether `a` is a stronger level than `b` (a missing level is the weakest). */
function stronger(a: number | null, b: number | null): boolean {
    if (a === null) return false;
    return b === null || a < b;
}

function bestRank(a: number | null, b: number | null): number | null {
    return stronger(b, a) ? b : a;
}

/** The best level of each symbol a material declares. */
function levelsOf(
    material: SynthesisResponse["materials"][number],
    symbols: ReadonlyMap<string, string>,
): Map<string, RankedValue | null> {
    const levels = new Map<string, RankedValue | null>();
    for (const element of material.summary.elements) {
        for (const value of element.values) {
            const symbol = symbols.get(value.id);
            if (symbol === undefined) continue;
            const held = levels.get(symbol);
            if (
                held === undefined ||
                stronger(element.level?.rank ?? null, held?.rank ?? null)
            ) {
                levels.set(symbol, element.level);
            }
        }
    }
    return levels;
}

/**
 * The elements declared on each analysis: for every identified material of
 * the synthesis, on every analysis its evidence cites, each of its elements
 * by symbol (`symbols`: element value id → symbol, `graph.symbols`). A
 * material keeps the best rank it gives an element; across materials the
 * entry keeps the best rank and lists every material. A material without
 * evidence on an analysis says nothing about it.
 */
export function declaredByAnalysis(
    synthesis: MaterialsOf,
    symbols: ReadonlyMap<string, string>,
): DeclaredMap {
    const result: DeclaredMap = new Map();
    for (const material of synthesis.materials) {
        const levels = levelsOf(material, symbols);
        for (const analysis of material.evidence) {
            let bySymbol = result.get(analysis);
            if (bySymbol === undefined) {
                bySymbol = new Map();
                result.set(analysis, bySymbol);
            }
            for (const [symbol, level] of levels) {
                const entry = bySymbol.get(symbol) ?? {
                    rank: null,
                    materials: [],
                };
                entry.rank = bestRank(entry.rank, level?.rank ?? null);
                entry.materials.push({ id: material.id, level });
                bySymbol.set(symbol, entry);
            }
        }
    }
    for (const bySymbol of result.values()) {
        for (const entry of bySymbol.values()) {
            entry.materials.sort(
                (a, b) =>
                    (a.level?.rank ?? Infinity) - (b.level?.rank ?? Infinity) ||
                    a.id.localeCompare(b.id),
            );
        }
    }
    return result;
}

/** What several analyses declare together: the best rank per symbol, every material once. */
export function mergeDeclared(
    maps: Iterable<Map<string, DeclaredElement> | undefined>,
): Map<string, DeclaredElement> {
    const merged = new Map<string, DeclaredElement>();
    for (const bySymbol of maps) {
        for (const [symbol, entry] of bySymbol ?? []) {
            const held = merged.get(symbol) ?? { rank: null, materials: [] };
            held.rank = bestRank(held.rank, entry.rank);
            for (const material of entry.materials) {
                if (!held.materials.some((m) => m.id === material.id)) {
                    held.materials.push(material);
                }
            }
            merged.set(symbol, held);
        }
    }
    return merged;
}

/** The parts of « declared major in Vermilion (A30) » / « … (cites A3) ». */
export interface DeclaredParts {
    /** The level as stored; null when the material gives none. */
    level: Label | null;
    material: Label;
    /** The material's own Selection slot (« A30 »), else null. */
    slot: string | null;
    /** The Selection slots of the analysis it cites, used when it has no slot of its own. */
    cites: string[];
}

/**
 * The parts of the sentence for the best material of `entry` on `analysis`;
 * null when the synthesis does not hold that material.
 */
export function declaredParts(
    entry: DeclaredElement,
    analysis: string,
    synthesis: MaterialsOf,
    basket: readonly BasketItem[],
): DeclaredParts | null {
    const best = entry.materials[0];
    const material = best
        ? synthesis.materials.find((m) => m.id === best.id)
        : undefined;
    if (!best || !material) return null;
    const slotOf = (match: (item: BasketItem) => boolean) =>
        basket
            .filter(match)
            .map((item) => item.slot)
            .sort((a, b) => a - b)
            .map(slotLabel);
    const own = slotOf((item) => item.key === `ch:${best.id}:-`);
    return {
        level: best.level?.label ?? null,
        material: material.summary.name,
        slot: own[0] ?? null,
        cites: slotOf(
            (item) =>
                item.kind !== "characterization" &&
                item.key.split(":")[1] === analysis,
        ),
    };
}

/** « declared major in Vermilion (A30) », « declared in Vermilion (cites A3) ». */
export function declaredText(
    parts: DeclaredParts,
    { $gettext, interpolate }: TagTranslate,
): string {
    const values = {
        level: parts.level?.value ?? "",
        material: parts.material.value,
    };
    const base = parts.level
        ? interpolate($gettext("declared %{level} in %{material}"), values)
        : interpolate($gettext("declared in %{material}"), values);
    if (parts.slot) return `${base} (${parts.slot})`;
    if (parts.cites.length > 0) {
        return `${base} (${interpolate($gettext("cites %{slots}"), {
            slots: parts.cites.join(", "),
        })})`;
    }
    return base;
}
