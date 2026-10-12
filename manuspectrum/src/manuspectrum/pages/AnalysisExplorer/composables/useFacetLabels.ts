import { inject, ref, watch } from "vue";

import { FACET_LABELS_KEY } from "@/manuspectrum/pages/AnalysisExplorer/injection-keys.ts";

import type { Ref } from "vue";

import type {
    EventsResponse,
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
 * Add the labels an events payload names to `labels`, keyed as the filters
 * store them: `material:<uri>`, `colour:<uri>` and `place:<id>`.
 */
export function recordEventLabels(
    labels: Ref<Map<string, Label>>,
    events: Pick<EventsResponse, "materials" | "colours" | "places">,
): void {
    const next = new Map(labels.value);
    for (const material of Object.values(events.materials)) {
        next.set(`material:${material.uri}`, material.label);
    }
    for (const colour of Object.values(events.colours)) {
        next.set(`colour:${colour.uri}`, colour.label);
    }
    for (const place of Object.values(events.places)) {
        next.set(`place:${place.id}`, place.name);
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

/** Record the material, colour and place labels of each events payload into the map provided under `FACET_LABELS_KEY`. */
export function useEventLabels(
    events: () => Pick<
        EventsResponse,
        "materials" | "colours" | "places"
    > | null,
): void {
    const labels = inject(
        FACET_LABELS_KEY,
        () => ref(new Map<string, Label>()),
        true,
    );
    watch(
        events,
        (current) => {
            if (current) {
                recordEventLabels(labels, current);
            }
        },
        { immediate: true },
    );
}
