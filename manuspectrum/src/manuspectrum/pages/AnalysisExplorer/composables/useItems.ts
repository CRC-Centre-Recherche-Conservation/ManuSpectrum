import {
    getJson,
    peekJson,
} from "@/manuspectrum/pages/AnalysisExplorer/api/http.ts";
import { useRequest } from "@/manuspectrum/pages/AnalysisExplorer/composables/useRequest.ts";

import type { ItemsResponse } from "@/manuspectrum/pages/AnalysisExplorer/api/types.ts";
import type { RequestHandle } from "@/manuspectrum/pages/AnalysisExplorer/composables/useRequest.ts";

const ITEMS_ROUTE = "manuspectrum:explorer-items";

function itemsQuery(ids: string): URLSearchParams {
    return new URLSearchParams(ids.split(",").map((id) => ["ids", id]));
}

/** Summaries of at most 30 Selection keys (the API answers 400 above). */
export function useItems(
    keys: () => readonly string[] | null,
): RequestHandle<ItemsResponse> {
    return useRequest(
        () => {
            const current = keys();
            return current && current.length > 0
                ? [...current].sort().join(",")
                : null;
        },
        (ids, signal, reload) =>
            getJson<ItemsResponse>(ITEMS_ROUTE, {
                query: itemsQuery(ids),
                signal,
                reload,
            }),
        {
            cached: (ids) =>
                peekJson<ItemsResponse>(ITEMS_ROUTE, {
                    query: itemsQuery(ids),
                }),
        },
    );
}
