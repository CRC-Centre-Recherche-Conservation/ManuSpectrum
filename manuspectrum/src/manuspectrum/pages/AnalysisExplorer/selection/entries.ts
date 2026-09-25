import type { FileEntry } from "@/manuspectrum/pages/AnalysisExplorer/api/types.ts";
import type { ItemKey } from "@/manuspectrum/pages/AnalysisExplorer/store/types.ts";

/** The key a whole analysis enters the Selection by, whatever files it holds. */
export function analysisKey(analysisId: string): ItemKey {
    return `an:${analysisId}:-`.toLowerCase();
}

/** The key of one file of an analysis; read, not created, by the interface. */
export function fileKey(analysisId: string, fileId: string): ItemKey {
    return `af:${analysisId}:${fileId}`.toLowerCase();
}

export function characterizationKey(id: string): ItemKey {
    return `ch:${id}:-`.toLowerCase();
}

export interface Holdings {
    spectra: number;
    maps: number;
    microImages: number;
}

/** How many spectra, chemical maps and micro-images a whole analysis in the Selection holds. */
export function holdingsOf(files: readonly FileEntry[]): Holdings {
    return {
        spectra: files.filter((file) => file.dataKind === "xy").length,
        maps: files.filter((file) => file.dataKind === "chemical-imaging")
            .length,
        microImages: files.filter((file) => file.dataKind === "micro-imaging")
            .length,
    };
}
