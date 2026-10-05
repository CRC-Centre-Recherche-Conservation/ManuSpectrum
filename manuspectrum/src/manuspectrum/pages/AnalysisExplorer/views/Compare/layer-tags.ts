import { atomicNumber } from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/periodic.ts";

import type {
    FileLayer,
    Label,
} from "@/manuspectrum/pages/AnalysisExplorer/api/types.ts";

/** What a tag is made of; the short text (« Cu Lα », « 650 nm ») is composed by the component. */
export interface TagParts {
    symbols: string[];
    line: Label | null;
    band: {
        value: number | null;
        lower: number | null;
        upper: number | null;
    } | null;
    unit: string | null;
    index: number | null;
    contentLabel: Label;
}

/**
 * `family` pairs layers across manifests (null for a content alone: a badge,
 * no pairing); `key` tells layers of one family apart (an emission line).
 */
export type LayerTag = {
    key: string;
    family: string | null;
    parts: TagParts;
} | null;

function symbolOf(layer: FileLayer): string[] {
    return layer.elements
        .flatMap((element) => (element.symbol ? [element.symbol] : []))
        .sort();
}

function bandKey(band: NonNullable<FileLayer["band"]>): string | null {
    const unit = band.unit ? unitSymbol(band.unit) : "";
    if (band.value !== null) return `band:${Number(band.value)}:${unit}`;
    if (band.lower !== null && band.upper !== null) {
        return `band:${Number(band.lower)}-${Number(band.upper)}:${unit}`;
    }
    return null;
}

/** The unit's symbol: the server sends it as the label of the unit value (« nm »). */
function unitSymbol(
    unit: NonNullable<NonNullable<FileLayer["band"]>["unit"]>,
): string {
    return unit.label.value;
}

/**
 * The one matching rule of the imaging layers, read off the shape of the
 * tile's fields and never off the stored label: null for a canvas without a
 * tile, an element family for declared elements, a band, a component, else a
 * content alone (a kind, no family).
 */
export function layerTag(layer: FileLayer): LayerTag {
    const content = layer.content;
    if (!content) return null;
    const symbols = symbolOf(layer);
    const parts: TagParts = {
        symbols,
        line: layer.emissionLine?.label ?? null,
        band: layer.band
            ? {
                  value: layer.band.value,
                  lower: layer.band.lower,
                  upper: layer.band.upper,
              }
            : null,
        unit: layer.band?.unit ? unitSymbol(layer.band.unit) : null,
        index: layer.processing?.index ?? null,
        contentLabel: content.label,
    };
    if (symbols.length) {
        const family = `element:${symbols.join("+")}`;
        const line = layer.emissionLine?.label.value;
        return { key: line ? `${family}:${line}` : family, family, parts };
    }
    const band = layer.band ? bandKey(layer.band) : null;
    if (band) return { key: band, family: band, parts };
    if (layer.processing && layer.processing.index !== null) {
        const family = `component:${layer.processing.method?.id ?? "?"}:${layer.processing.index}`;
        return { key: family, family, parts };
    }
    return { key: `kind:${content.id}`, family: null, parts };
}

const KIND_RANK: Readonly<Record<string, number>> = {
    element: 0,
    band: 1,
    component: 2,
};

/** The number a family sorts by inside its kind: Z of its first element, the band's value, the component's index. */
function rankOf(family: string): number {
    const [kind, ...rest] = family.split(":");
    if (kind === "element") {
        return atomicNumber(rest.join(":").split("+")[0]) ?? Infinity;
    }
    if (kind === "band") return Number.parseFloat(rest[0]) || 0;
    if (kind === "component") return Number(rest[rest.length - 1]) || 0;
    return 0;
}

/** Orders families: elements by Z, bands by value, components by index, the rest by name. */
export function compareFamilies(a: string, b: string): number {
    const kindA = KIND_RANK[a.split(":")[0]] ?? 3;
    const kindB = KIND_RANK[b.split(":")[0]] ?? 3;
    if (kindA !== kindB) return kindA - kindB;
    const byRank = rankOf(a) - rankOf(b);
    if (byRank !== 0 && !Number.isNaN(byRank)) return byRank;
    return a.localeCompare(b);
}
