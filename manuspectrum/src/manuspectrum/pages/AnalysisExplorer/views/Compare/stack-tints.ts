import { layerTag } from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/layer-tags.ts";

import type { FileLayer } from "@/manuspectrum/pages/AnalysisExplorer/api/types.ts";
import type { StackLayer } from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/light-table.ts";

/** `StackLayer.tint` of a layer the reader chose to show untinted; null is « the default ». */
export const NO_TINT = "none";

/**
 * A false-colour hue. `hex` is the value of the `--map-*` token named by
 * `token` in `_ms-chrome.scss` (a spec pins the two equal): an SVG
 * `feColorMatrix` takes numbers, not a custom property, so `rgb` is what the
 * filter uses and the token is what a swatch paints.
 */
export interface Tint {
    key: string;
    token: string;
    hex: string;
    rgb: readonly [number, number, number];
}

const HEX_RADIX = 16;
const HEX_PAIR = 2;

function tint(key: string, token: string, hex: string): Tint {
    const channel = (start: number): number =>
        Number.parseInt(hex.slice(start, start + HEX_PAIR), HEX_RADIX);
    return { key, token, hex, rgb: [channel(1), channel(3), channel(5)] };
}

/** The hue of a single element, by its symbol; a stack of bare layers never meets them. */
export const ELEMENT_TINTS: ReadonlyMap<string, Tint> = new Map(
    (
        [
            ["Pb", "#f1ede0"],
            ["Cu", "#22d3ee"],
            ["Fe", "#fb923c"],
            ["Hg", "#ef4444"],
            ["Ca", "#facc15"],
            ["K", "#a78bfa"],
            ["Mn", "#e879f9"],
            ["Zn", "#4ade80"],
            ["Au", "#e0b020"],
            ["Ag", "#cfd3d8"],
            ["As", "#a3e635"],
            ["S", "#fef08a"],
        ] as const
    ).map(([symbol, hex]) => [
        symbol,
        tint(`el-${symbol}`, `--map-${symbol.toLowerCase()}`, hex),
    ]),
);

/** The default of a layer with no element hue: twelve hues by rank in the stack, light enough to blend with `screen`. */
export const RANK_TINTS: readonly Tint[] = [
    "#60a5fa",
    "#f472b6",
    "#34d399",
    "#fbbf24",
    "#c084fc",
    "#f87171",
    "#2dd4bf",
    "#fb923c",
    "#a3e635",
    "#38bdf8",
    "#e879f9",
    "#fde68a",
].map((hex, index) =>
    tint(`rank-${index + 1}`, `--map-rank-${index + 1}`, hex),
);

/** The palette the reader picks from. */
export const TINT_CHOICES: readonly Tint[] = RANK_TINTS;

const BY_KEY: ReadonlyMap<string, Tint> = new Map(
    [...RANK_TINTS, ...ELEMENT_TINTS.values()].map((entry) => [
        entry.key,
        entry,
    ]),
);

/**
 * The hue a layer of the stack is drawn in, null for none. The reader's
 * choice first; else, from the layer's tag when it has one, the hue of its
 * element (a family of one element that has a hue) or none for a band;
 * else the hue of its rank in the stack. Without a mapping the tag is
 * absent and the rank decides.
 */
export function tintFor(
    layer: StackLayer,
    rank: number,
    fileLayer: FileLayer | null,
): Tint | null {
    if (layer.tint === NO_TINT) return null;
    const chosen = layer.tint ? BY_KEY.get(layer.tint) : undefined;
    if (chosen) return chosen;
    const tag = fileLayer ? layerTag(fileLayer) : null;
    if (tag?.family?.startsWith("band:")) return null;
    if (tag?.family?.startsWith("element:") && tag.parts.symbols.length === 1) {
        const element = ELEMENT_TINTS.get(tag.parts.symbols[0]);
        if (element) return element;
    }
    return RANK_TINTS[rank % RANK_TINTS.length];
}
