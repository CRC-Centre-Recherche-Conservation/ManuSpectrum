import { techniqueKey } from "@/manuspectrum/pages/AnalysisExplorer/folio/techniques.ts";

import type {
    CharacterizationSummary,
    DataKind,
    DocumentComponent,
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

/** An identified material linked to one Component, as its card lists it. */
export interface ComponentMaterial {
    id: string;
    name: Label;
    /** The first colour of the material that has a display colour. */
    swatch: string | null;
    /** The label of the highest certainty level any of its materials states. */
    certainty: Label | null;
    unpublished: boolean;
    /** Whether the Corpus filters keep the identified material. */
    match: boolean;
}

/**
 * The identified materials of `view` linked to `componentId`, in the order of
 * the payload: those whose `components` (the server's rule: they observe it
 * or cite one of its analyses) name it.
 */
export function componentMaterials(
    view: DocumentView,
    componentId: string,
): ComponentMaterial[] {
    return view.characterizations
        .filter((summary) =>
            summary.components.some((entry) => entry.id === componentId),
        )
        .map((summary) => {
            const levels = summary.materials
                .map((entry) => entry.confidence)
                .filter((level) => level !== null);
            levels.sort((first, second) => first.rank - second.rank);
            return {
                id: summary.id,
                name: summary.name,
                swatch:
                    summary.colours.find((colour) => colour.swatch)?.swatch ??
                    null,
                certainty: levels[0]?.label ?? null,
                unpublished: summary.unpublished,
                match: view.keptCharacterizations.has(summary.id),
            };
        });
}

/**
 * The Components of `view` that `summary` is linked to (its `components`),
 * in the order of the payload.
 */
export function characterizationComponents(
    view: DocumentView,
    summary: CharacterizationSummary,
): DocumentComponent[] {
    const linked = new Set(summary.components.map((entry) => entry.id));
    return view.components.filter((component) => linked.has(component.id));
}
