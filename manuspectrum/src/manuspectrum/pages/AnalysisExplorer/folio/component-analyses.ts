import { techniqueKey } from "@/manuspectrum/pages/AnalysisExplorer/folio/techniques.ts";

import type {
    DataKind,
    Label,
} from "@/manuspectrum/pages/AnalysisExplorer/api/types.ts";
import type { DocumentView } from "@/manuspectrum/pages/AnalysisExplorer/folio/document-view.ts";
import type { TechniqueStyle } from "@/manuspectrum/pages/AnalysisExplorer/folio/techniques.ts";

/** An analysis of a document that observes one Component, as its card lists it. */
export interface ComponentAnalysis {
    id: string;
    name: Label;
    style: TechniqueStyle | null;
    unpublished: boolean;
    /** Whether the Corpus filters keep the analysis. */
    match: boolean;
    dataKind: DataKind;
}

/**
 * The analyses of `view` that observe `componentId`, once each, the located
 * ones first (in the order of their zones) then those without a zone. A
 * technique absent from `styles` leaves `style` null.
 */
export function componentAnalyses(
    view: DocumentView,
    componentId: string,
    styles: ReadonlyMap<string, TechniqueStyle>,
): ComponentAnalysis[] {
    const seen = new Set<string>();
    const entries: ComponentAnalysis[] = [];
    for (const entry of [...view.annotations, ...view.unlocated]) {
        if (entry.component !== componentId || seen.has(entry.analysis)) {
            continue;
        }
        seen.add(entry.analysis);
        entries.push({
            id: entry.analysis,
            name: entry.name,
            style: styles.get(techniqueKey(entry.technique)) ?? null,
            unpublished: entry.unpublished,
            match: entry.match,
            dataKind: entry.dataKind,
        });
    }
    return entries;
}
