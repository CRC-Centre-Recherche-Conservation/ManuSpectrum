import { inject, ref, watch } from "vue";

import {
    FACET_LABELS_KEY,
    FACET_NARROWER_KEY,
} from "@/manuspectrum/pages/AnalysisExplorer/injection-keys.ts";

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
 * Record in `narrower` which values of `facets` have a narrower term in their
 * facet, keyed `${facetKey}:${valueId}`; a value now listed without one is
 * dropped, a value not listed keeps what was seen.
 */
export function recordFacetNarrower(
    narrower: Ref<Set<string>>,
    facets: readonly Facet[],
): void {
    const next = new Set(narrower.value);
    for (const facet of facets) {
        for (const value of facet.values) {
            const key = `${facet.key}:${value.id}`;
            if (value.narrower) {
                next.add(key);
            } else {
                next.delete(key);
            }
        }
    }
    narrower.value = next;
}

/**
 * Add the labels an events payload names to `labels`, keyed as the filters
 * store them: `material:<uri>` (listed and covering materials),
 * `colour:<uri>` and `place:<id>`.
 */
export function recordEventLabels(
    labels: Ref<Map<string, Label>>,
    events: Pick<
        EventsResponse,
        "materials" | "coveringMaterials" | "colours" | "places"
    >,
): void {
    const next = new Map(labels.value);
    for (const material of Object.values(events.materials)) {
        next.set(`material:${material.uri}`, material.label);
    }
    for (const [uri, covering] of Object.entries(events.coveringMaterials)) {
        next.set(`material:${uri}`, covering);
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
 * provided under `FACET_LABELS_KEY`, and the values with narrower terms into
 * the set under `FACET_NARROWER_KEY`. Labels seen earlier are kept, so an
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
    const narrower = inject(
        FACET_NARROWER_KEY,
        () => ref(new Set<string>()),
        true,
    );
    watch(
        facets,
        (current) => {
            if (current) {
                recordFacetLabels(labels, current);
                recordFacetNarrower(narrower, current);
            }
        },
        { immediate: true },
    );
}

/** Record the material, colour and place labels of each events payload into the map provided under `FACET_LABELS_KEY`. */
export function useEventLabels(
    events: () => Pick<
        EventsResponse,
        "materials" | "coveringMaterials" | "colours" | "places"
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
