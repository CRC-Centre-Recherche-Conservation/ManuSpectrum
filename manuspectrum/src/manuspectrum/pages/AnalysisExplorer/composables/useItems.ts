import { getJson } from "@/manuspectrum/pages/AnalysisExplorer/api/http.ts";
import { useRequest } from "@/manuspectrum/pages/AnalysisExplorer/composables/useRequest.ts";

import type { ItemsResponse } from "@/manuspectrum/pages/AnalysisExplorer/api/types.ts";
import type { RequestHandle } from "@/manuspectrum/pages/AnalysisExplorer/composables/useRequest.ts";

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
        (ids, signal) =>
            getJson<ItemsResponse>("manuspectrum:explorer-items", {
                query: new URLSearchParams(
                    ids.split(",").map((id) => ["ids", id]),
                ),
                signal,
            }),
    );
}
