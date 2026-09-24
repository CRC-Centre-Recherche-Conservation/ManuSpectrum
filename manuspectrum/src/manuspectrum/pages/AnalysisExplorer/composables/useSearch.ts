import { getJson } from "@/manuspectrum/pages/AnalysisExplorer/api/http.ts";
import { useRequest } from "@/manuspectrum/pages/AnalysisExplorer/composables/useRequest.ts";
import { LIST_FILTER_KEYS } from "@/manuspectrum/pages/AnalysisExplorer/store/explorer.ts";

import type { SearchResponse } from "@/manuspectrum/pages/AnalysisExplorer/api/types.ts";
import type { RequestHandle } from "@/manuspectrum/pages/AnalysisExplorer/composables/useRequest.ts";
import type { Filters } from "@/manuspectrum/pages/AnalysisExplorer/store/types.ts";

/**
 * Build the search query string for `filters`.
 *
 * `place`, `period` and `eventType` are never sent: the Map & timeline view
 * that reads them is not built yet, and `eventType` filters Map only.
 */
export function searchQuery(filters: Filters, page: number): URLSearchParams {
    const query = new URLSearchParams();
    if (filters.q) query.set("q", filters.q);
    query.set("grain", filters.grain);
    query.set("onlyWithAnalyses", String(filters.onlyWithAnalyses));
    for (const key of LIST_FILTER_KEYS) {
        for (const value of [...filters[key]].sort()) query.append(key, value);
    }
    for (const year of [...filters.year].sort((a, b) => a - b)) {
        query.append("year", String(year));
    }
    if (page > 1) query.set("page", String(page));
    return query;
}

export function useSearch(
    source: () => URLSearchParams | null,
): RequestHandle<SearchResponse> {
    return useRequest(
        () => source()?.toString() ?? null,
        (query, signal) =>
            getJson<SearchResponse>("manuspectrum:explorer-search", {
                query: new URLSearchParams(query),
                signal,
            }),
    );
}
