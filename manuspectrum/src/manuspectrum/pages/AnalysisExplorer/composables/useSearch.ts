import {
    getJson,
    peekJson,
    prefetchJson,
} from "@/manuspectrum/pages/AnalysisExplorer/api/http.ts";
import { useRequest } from "@/manuspectrum/pages/AnalysisExplorer/composables/useRequest.ts";
import {
    LIST_FILTER_KEYS,
    PAGE_SIZES,
} from "@/manuspectrum/pages/AnalysisExplorer/store/explorer.ts";

import type { SearchResponse } from "@/manuspectrum/pages/AnalysisExplorer/api/types.ts";
import type { RequestHandle } from "@/manuspectrum/pages/AnalysisExplorer/composables/useRequest.ts";
import type { Filters } from "@/manuspectrum/pages/AnalysisExplorer/store/types.ts";

export const SEARCH_ROUTE = "manuspectrum:explorer-search";

export interface SearchScope {
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
    if (page > 1) query.set("page", String(page));
    return query;
}

const DISPLAY_KEYS = ["grain", "size", "empty", "page", "facets"];

/** The filters of a search query string alone: no grain, page size, page nor `facets`. */
export function filtersOf(query: string): string {
    const filters = new URLSearchParams(query);
    for (const key of DISPLAY_KEYS) filters.delete(key);
    return filters.toString();
}

/** The filters of `filters` alone, as the document match reads them: no grain, page size nor page. */
export function filterQuery(filters: Filters): URLSearchParams {
    return new URLSearchParams(filtersOf(searchQuery(filters, 1).toString()));
}

export interface SearchOptions {
    /** Whether the client holds the facets of these filters (`filtersOf`): the search then asks for none (`facets=0`). */
    holdsFacets?: (filters: string) => boolean;
    /** A change of filters waits for them to settle (`DEBOUNCE_MS`); a page, grain or size change asks at once. */
    debounceFilters?: boolean;
}

export interface SearchHandle extends RequestHandle<SearchResponse> {
    /** Starts loading the search of `query` ahead, as this handle would ask for it. */
    prefetch: (query: URLSearchParams) => void;
}

/** The search for `source`, answered from the tab memo when it holds it. */
export function useSearch(
    source: () => URLSearchParams | null,
    { holdsFacets, debounceFilters = false }: SearchOptions = {},
): SearchHandle {
    function sent(query: string): URLSearchParams {
        const params = new URLSearchParams(query);
        if (holdsFacets?.(filtersOf(query))) params.set("facets", "0");
        return params;
    }

    function held(query: string): SearchResponse | null {
        return (
            peekJson<SearchResponse>(SEARCH_ROUTE, {
                query: new URLSearchParams(query),
            }) ??
            peekJson<SearchResponse>(SEARCH_ROUTE, {
                query: sent(query),
            })
        );
    }

    const handle = useRequest(
        () => source()?.toString() ?? null,
        (query, signal, reload) =>
            getJson<SearchResponse>(SEARCH_ROUTE, {
                query: sent(query),
                signal,
                reload,
            }),
        {
            cached: held,
            debounce: debounceFilters
                ? (next, previous) => filtersOf(next) !== filtersOf(previous)
                : undefined,
        },
    );
    return {
        ...handle,
        prefetch: (query) =>
            prefetchJson(SEARCH_ROUTE, {
                query: sent(query.toString()),
            }),
    };
}
