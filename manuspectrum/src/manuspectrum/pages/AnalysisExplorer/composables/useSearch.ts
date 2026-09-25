import { getJson } from "@/manuspectrum/pages/AnalysisExplorer/api/http.ts";
import { useRequest } from "@/manuspectrum/pages/AnalysisExplorer/composables/useRequest.ts";
import {
    LIST_FILTER_KEYS,
    PAGE_SIZES,
} from "@/manuspectrum/pages/AnalysisExplorer/store/explorer.ts";

import type { SearchResponse } from "@/manuspectrum/pages/AnalysisExplorer/api/types.ts";
import type { RequestHandle } from "@/manuspectrum/pages/AnalysisExplorer/composables/useRequest.ts";
import type { Filters } from "@/manuspectrum/pages/AnalysisExplorer/store/types.ts";

export interface SearchScope {
    /** Limits the search to the analyses of one document. */
    document?: string;
    /** A page size of its own, instead of `filters.size`. */
    size?: number;
}

/**
 * Build the search query string for `filters`.
 *
 * `place`, `period` and `eventType` are never sent: the Map & timeline view
 * that reads them is not built yet, and `eventType` filters Map only. The
 * default page size (10) is not sent; documents without analyses are asked
 * for in the documents grain only.
 */
export function searchQuery(
    filters: Filters,
    page: number,
    scope: SearchScope = {},
): URLSearchParams {
    const query = new URLSearchParams();
    if (filters.q) query.set("q", filters.q);
    query.set("grain", filters.grain);
    const size = scope.size ?? filters.size;
    if (size !== PAGE_SIZES[0]) query.set("size", String(size));
    if (filters.empty && filters.grain === "documents") query.set("empty", "1");
    for (const key of LIST_FILTER_KEYS) {
        for (const value of [...filters[key]].sort()) query.append(key, value);
    }
    for (const year of [...filters.year].sort((a, b) => a - b)) {
        query.append("year", String(year));
    }
    if (scope.document) query.set("document", scope.document);
    if (page > 1) query.set("page", String(page));
    return query;
}

/** The search for `source`; `cached` may answer a query string without a request. */
export function useSearch(
    source: () => URLSearchParams | null,
    cached?: (query: string) => SearchResponse | null,
): RequestHandle<SearchResponse> {
    return useRequest(
        () => source()?.toString() ?? null,
        (query, signal) =>
            getJson<SearchResponse>("manuspectrum:explorer-search", {
                query: new URLSearchParams(query),
                signal,
            }),
        cached,
    );
}
