import { computed, inject, ref } from "vue";
import { useGettext } from "vue3-gettext";

import { useVocabulary } from "@/manuspectrum/pages/AnalysisExplorer/composables/useVocabulary.ts";
import { FACET_LABELS_KEY } from "@/manuspectrum/pages/AnalysisExplorer/injection-keys.ts";
import {
    LIST_FILTER_KEYS,
    useExplorerStore,
} from "@/manuspectrum/pages/AnalysisExplorer/store/explorer.ts";

import type { ComputedRef } from "vue";

import type { Label } from "@/manuspectrum/pages/AnalysisExplorer/api/types.ts";

export interface ActiveFilter {
    id: string;
    label: string;
    clear: () => void;
}

/**
 * Every active filter as a removable entry (D42), in a stable order.
 *
 * A facet value shows the label recorded under `FACET_LABELS_KEY`, or its id
 * when no payload has named it yet. Event types count only in the Map view.
 */
export function useActiveFilters(): {
    activeFilters: ComputedRef<ActiveFilter[]>;
    clearAll: () => void;
} {
    const store = useExplorerStore();
    const facetLabels = inject(
        FACET_LABELS_KEY,
        () => ref(new Map<string, Label>()),
        true,
    );
    const { $gettext, interpolate } = useGettext();
    const { facetTitle } = useVocabulary();

    function named(facet: string, value: string): string {
        return interpolate($gettext("%{facet}: %{value}"), { facet, value });
    }

    const activeFilters = computed<ActiveFilter[]>(() => {
        const filters = store.filters;
        const entries: ActiveFilter[] = [];
        if (filters.q) {
            entries.push({
                id: "q",
                label: interpolate($gettext("Text: %{text}"), {
                    text: filters.q,
                }),
                clear: () => store.clearFilter("q"),
            });
        }
        for (const key of LIST_FILTER_KEYS) {
            for (const value of filters[key]) {
                const valueLabel =
                    facetLabels.value.get(`${key}:${value}`)?.value ?? value;
                entries.push({
                    id: `${key}:${value}`,
                    label: named(facetTitle(key), valueLabel),
                    clear: () => store.clearFilter(key, value),
                });
            }
        }
        for (const year of filters.year) {
            entries.push({
                id: `year:${year}`,
                label: named(facetTitle("year"), String(year)),
                clear: () => store.clearFilter("year", year),
            });
        }
        if (filters.place) {
            entries.push({
                id: "place",
                label: named($gettext("Place"), filters.place),
                clear: () => store.clearFilter("place"),
            });
        }
        if (filters.period) {
            entries.push({
                id: "period",
                label: interpolate($gettext("Period: %{start}–%{end}"), {
                    start: filters.period[0],
                    end: filters.period[1],
                }),
                clear: () => store.clearFilter("period"),
            });
        }
        if (store.view === "map") {
            for (const type of filters.eventType) {
                entries.push({
                    id: `eventType:${type}`,
                    label: named($gettext("Event"), type),
                    clear: () => store.clearFilter("eventType", type),
                });
            }
        }
        return entries;
    });

    return { activeFilters, clearAll: () => store.clearFilters() };
}
