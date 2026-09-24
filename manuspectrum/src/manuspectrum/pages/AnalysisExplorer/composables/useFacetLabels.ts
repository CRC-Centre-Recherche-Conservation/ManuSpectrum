import { inject, ref, watch } from "vue";

import { FACET_LABELS_KEY } from "@/manuspectrum/pages/AnalysisExplorer/injection-keys.ts";

import type { Ref } from "vue";

import type {
    Facet,
    Label,
} from "@/manuspectrum/pages/AnalysisExplorer/api/types.ts";

/** Add the label of every value of `facets` to `labels`, keyed `${facetKey}:${valueId}`. */
export function recordFacetLabels(
    labels: Ref<Map<string, Label>>,
    facets: readonly Facet[],
): void {
    const next = new Map(labels.value);
    for (const facet of facets) {
        for (const value of facet.values) {
            next.set(`${facet.key}:${value.id}`, value.label);
        }
    }
    labels.value = next;
}

/**
 * Record the facet value labels of each payload `facets` returns into the map
 * provided under `FACET_LABELS_KEY`. Labels seen earlier are kept, so an
 * active filter stays named after its value leaves the current facets.
 */
export function useFacetLabels(
    facets: () => readonly Facet[] | null | undefined,
): void {
    const labels = inject(
        FACET_LABELS_KEY,
        () => ref(new Map<string, Label>()),
        true,
    );
    watch(
        facets,
        (current) => {
            if (current) {
                recordFacetLabels(labels, current);
            }
        },
        { immediate: true },
    );
}
