import {
    getJson,
    peekJson,
} from "@/manuspectrum/pages/AnalysisExplorer/api/http.ts";
import { useRequest } from "@/manuspectrum/pages/AnalysisExplorer/composables/useRequest.ts";

import type { JsonRequestOptions } from "@/manuspectrum/pages/AnalysisExplorer/api/http.ts";
import type {
    Facet,
    FacetKey,
} from "@/manuspectrum/pages/AnalysisExplorer/api/types.ts";
import type { RequestHandle } from "@/manuspectrum/pages/AnalysisExplorer/composables/useRequest.ts";

export const FACET_ROUTE = "manuspectrum:explorer-facet";

/** What one facet request asks for: the filters (`filtersOf`, with `document=` for one document's facets) and the text the values must hold. */
export interface FacetLookup {
    filters: string;
    find: string;
}

/** The request of every value of facet `key` under `lookup` (`GET facet/<key>?<filters>&find=`). */
export function facetRequest(
    key: FacetKey,
    { filters, find }: FacetLookup,
): JsonRequestOptions {
    const query = new URLSearchParams(filters);
    const text = find.trim();
    if (text) query.set("find", text);
    return { urlParameters: { key }, query };
}

function lookupOf(source: string): FacetLookup {
    return JSON.parse(source) as FacetLookup;
}

/**
 * Every value of facet `key` over the whole corpus, or over one document
 * when the filters name it, for a facet sent cut short (its first values
 * and the selected ones) or searched. Idle while
 * `lookup` is null. After the first load, a new lookup (typed text, other
 * filters) waits for the source to settle (`DEBOUNCE_MS`).
 */
export function useFacetValues(
    key: FacetKey,
    lookup: () => FacetLookup | null,
): RequestHandle<Facet> {
    return useRequest(
        () => {
            const current = lookup();
            return current === null
                ? null
                : JSON.stringify({
                      filters: current.filters,
                      find: current.find.trim(),
                  });
        },
        (source, signal, reload) =>
            getJson<Facet>(FACET_ROUTE, {
                ...facetRequest(key, lookupOf(source)),
                signal,
                reload,
            }),
        {
            cached: (source) =>
                peekJson<Facet>(
                    FACET_ROUTE,
                    facetRequest(key, lookupOf(source)),
                ),
            debounce: () => true,
        },
    );
}
