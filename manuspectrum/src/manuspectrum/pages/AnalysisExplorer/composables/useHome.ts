import {
    getJson,
    peekJson,
} from "@/manuspectrum/pages/AnalysisExplorer/api/http.ts";
import { useRequest } from "@/manuspectrum/pages/AnalysisExplorer/composables/useRequest.ts";

import type { JsonRequestOptions } from "@/manuspectrum/pages/AnalysisExplorer/api/http.ts";
import type { HomeResponse } from "@/manuspectrum/pages/AnalysisExplorer/api/types.ts";
import type { RequestHandle } from "@/manuspectrum/pages/AnalysisExplorer/composables/useRequest.ts";

export const HOME_ROUTE = "manuspectrum:explorer-home";

/** The request of the home of `day` (`YYYY-MM-DD`, the reader's local day). */
export function homeRequest(day: string): JsonRequestOptions {
    return { query: new URLSearchParams([["day", day]]) };
}

/** The explorer home of `day`: the overview doors and the document of the day, in one request. */
export function useHome(day: () => string): RequestHandle<HomeResponse> {
    return useRequest(
        day,
        (current, signal, reload) =>
            getJson<HomeResponse>(HOME_ROUTE, {
                ...homeRequest(current),
                signal,
                reload,
            }),
        {
            cached: (current) =>
                peekJson<HomeResponse>(HOME_ROUTE, homeRequest(current)),
        },
    );
}
