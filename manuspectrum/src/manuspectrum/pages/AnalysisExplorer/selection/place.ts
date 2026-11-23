import type {
    AnalysisHit,
    CharacterizationSummary,
    Item,
    Ref,
} from "@/manuspectrum/pages/AnalysisExplorer/api/types.ts";

/** A document screen to open: its folio and the record it focuses. */
export interface DocumentTarget {
    document: string;
    canvas: string | null;
    focus: { kind: "analysis" | "characterization"; id: string };
}

/** Where a record sits: a document and, when known, one of its pages. */
export interface Place {
    document: string;
    canvas: string | null;
}

/** The document and page of an analysis. */
export function analysisPlace(hit: AnalysisHit): Place {
    return { document: hit.document.id, canvas: hit.canvas };
}

/** The objects of an identified material that are documents, not components. */
export function materialDocuments(summary: CharacterizationSummary): Ref[] {
    return summary.objects.filter((object) => object.model !== "component");
}

/**
 * The documents an identified material is placed in, on the page of the
 * material's zone (none without a zone). A material known only through
 * components has no place.
 */
export function materialPlaces(summary: CharacterizationSummary): Place[] {
    const canvas = summary.zone?.canvas ?? null;
    return materialDocuments(summary).map((object) => ({
        document: object.id,
        canvas,
    }));
}

/** Every place of an item, each with the record it focuses; empty when it has none. */
export function placesOf(item: Item): DocumentTarget[] {
    if (item.kind === "characterization") {
        const focus = {
            kind: "characterization",
            id: item.characterization.id,
        } as const;
        return materialPlaces(item.characterization).map((place) => ({
            ...place,
            focus,
        }));
    }
    return [
        {
            ...analysisPlace(item.analysis),
            focus: { kind: "analysis", id: item.analysis.id },
        },
    ];
}

/** The place an item opens in: the first of `placesOf`, null when it has none. */
export function placeOf(item: Item): DocumentTarget | null {
    return placesOf(item)[0] ?? null;
}
