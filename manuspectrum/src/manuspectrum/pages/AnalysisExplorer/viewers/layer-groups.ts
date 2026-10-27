import { tagText } from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/layer-tag-text.ts";
import {
    compareFamilies,
    layerTag,
} from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/layer-tags.ts";

import type { TagTranslate } from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/layer-tag-text.ts";
import type { FileLayer } from "@/manuspectrum/pages/AnalysisExplorer/api/types.ts";

/** The layers of one file that share a declared element, band or component (or a bare content kind). */
export interface LayerGroup {
    id: string;
    /** The tag's short text; null for the layers that declare nothing. */
    title: string | null;
    /** Positions in `file.layers`, in file order. */
    positions: number[];
}

/**
 * The layers of one file grouped by what they declare (`layerTag`): families
 * first (elements by Z, bands by value, components by index), then bare
 * content kinds, then the layers with no tag.
 */
export function groupLayers(
    layers: readonly FileLayer[],
    translate: TagTranslate,
): LayerGroup[] {
    const families = new Map<string, LayerGroup>();
    const kinds = new Map<string, LayerGroup>();
    const bare: LayerGroup = { id: "none", title: null, positions: [] };
    layers.forEach((layer, position) => {
        const tag = layerTag(layer);
        if (!tag) {
            bare.positions.push(position);
            return;
        }
        const target = tag.family ? families : kinds;
        const key = tag.family ?? tag.key;
        const group = target.get(key) ?? {
            id: key,
            title: tagText(tag.parts, translate),
            positions: [],
        };
        group.positions.push(position);
        target.set(key, group);
    });
    return [
        ...[...families.entries()]
            .sort(([first], [second]) => compareFamilies(first, second))
            .map(([, group]) => group),
        ...kinds.values(),
        ...(bare.positions.length > 0 ? [bare] : []),
    ];
}
