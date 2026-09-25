import type {
    DataKind,
    DocumentMatch,
    DocumentPayload,
    Label,
    Shape,
    Technique,
} from "@/manuspectrum/pages/AnalysisExplorer/api/types.ts";

/** One zone of an analysis on one page, as the folio, the page list and the strip read it. */
export interface Annotation {
    /** `an:<analysis>:<n>`, n the position of the zone among the analysis's zones. */
    key: string;
    analysis: string;
    name: Label;
    /** Id of the page's canvas. */
    canvas: string;
    shape: Shape;
    technique: Technique | null;
    dataKind: DataKind;
    unpublished: boolean;
    /** Whether the Corpus filters keep the analysis. */
    match: boolean;
}

/** An analysis of the document with no zone on its pages. */
export interface UnlocatedAnalysis {
    analysis: string;
    name: Label;
    technique: Technique | null;
    dataKind: DataKind;
    unpublished: boolean;
    match: boolean;
}

/** The document as the screen shows it: its payload with each analysis spread over its zones and marked by the match. */
export interface DocumentView
    extends Omit<DocumentPayload, "analyses" | "techniques"> {
    annotations: Annotation[];
    unlocated: UnlocatedAnalysis[];
    /** Ids of the identified materials the Corpus filters keep. */
    keptCharacterizations: ReadonlySet<string>;
}

/**
 * The view of `payload` under `match`: one annotation per zone, in the order
 * of the analyses and of their zones, on the canvas its position names; an
 * analysis without zones is unlocated. Without a match, every analysis and
 * identified material is kept.
 */
export function documentView(
    payload: DocumentPayload,
    match: DocumentMatch | null,
): DocumentView {
    const { analyses, techniques, ...rest } = payload;
    const kept = match ? new Set(match.kept.analyses) : null;
    const annotations: Annotation[] = [];
    const unlocated: UnlocatedAnalysis[] = [];
    for (const analysis of analyses) {
        const common = {
            analysis: analysis.id,
            name: analysis.name,
            technique:
                analysis.technique === null
                    ? null
                    : techniques[analysis.technique] ?? null,
            dataKind: analysis.dataKind,
            unpublished: analysis.unpublished,
            match: kept?.has(analysis.id) ?? true,
        };
        if (analysis.zones.length === 0) {
            unlocated.push(common);
            continue;
        }
        analysis.zones.forEach((zone, index) => {
            const canvas = payload.canvases[zone.canvas];
            if (!canvas) return;
            annotations.push({
                ...common,
                key: `an:${analysis.id}:${index}`,
                canvas: canvas.id,
                shape: zone.shape,
            });
        });
    }
    return {
        ...rest,
        annotations,
        unlocated,
        keptCharacterizations: new Set(
            match
                ? match.kept.characterizations
                : payload.characterizations.map((summary) => summary.id),
        ),
    };
}
