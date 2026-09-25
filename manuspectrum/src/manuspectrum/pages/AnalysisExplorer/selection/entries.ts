import type { AnalysisPayload } from "@/manuspectrum/pages/AnalysisExplorer/api/types.ts";
import type { ItemKey } from "@/manuspectrum/pages/AnalysisExplorer/store/types.ts";

export function fileKey(analysisId: string, fileId: string): ItemKey {
    return `af:${analysisId}:${fileId}`.toLowerCase();
}

export function layerKey(analysisId: string, index: number): ItemKey {
    return `im:${analysisId}:${index}`.toLowerCase();
}

export function characterizationKey(id: string): ItemKey {
    return `ch:${id}:-`.toLowerCase();
}

/**
 * The key an analysis enters the Selection by: its first readable spectrum,
 * else the first layer of its first imaging manifest, else its first
 * micro-image; null when it has nothing the Explorer can show.
 */
export function entryKeyOf(analysis: AnalysisPayload): ItemKey | null {
    const spectrum = analysis.files.find(
        (file) => file.role === "readable" && file.dataKind === "xy",
    );
    if (spectrum) return fileKey(analysis.id, spectrum.id);
    const imaging = analysis.files.find(
        (file) =>
            file.dataKind === "chemical-imaging" && file.layers.length > 0,
    );
    if (imaging)
        return layerKey(
            analysis.id,
            Math.min(...imaging.layers.map((layer) => layer.index)),
        );
    const micro = analysis.files.find(
        (file) => file.dataKind === "micro-imaging",
    );
    if (micro) return fileKey(analysis.id, micro.id);
    return null;
}

/** The Selection keys of analyses, in the order given, and the ids of those with nothing to show. */
export function evidenceEntries(analyses: readonly AnalysisPayload[]): {
    keys: ItemKey[];
    withoutData: string[];
} {
    const keys: ItemKey[] = [];
    const withoutData: string[] = [];
    for (const analysis of analyses) {
        const key = entryKeyOf(analysis);
        if (key === null) withoutData.push(analysis.id);
        else keys.push(key);
    }
    return { keys, withoutData };
}
