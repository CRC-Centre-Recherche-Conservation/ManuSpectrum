import {
    getJson,
    peekJson,
} from "@/manuspectrum/pages/AnalysisExplorer/api/http.ts";
import { useRequest } from "@/manuspectrum/pages/AnalysisExplorer/composables/useRequest.ts";

import type { JsonRequestOptions } from "@/manuspectrum/pages/AnalysisExplorer/api/http.ts";
import type { AnalysisPayload } from "@/manuspectrum/pages/AnalysisExplorer/api/types.ts";
import type { RequestHandle } from "@/manuspectrum/pages/AnalysisExplorer/composables/useRequest.ts";

export const ANALYSIS_ROUTE = "manuspectrum:explorer-analysis";

/** The request of the payload of analysis `resourceid`. */
export function analysisRequest(resourceid: string): JsonRequestOptions {
    return { urlParameters: { resourceid } };
}

export function useAnalysis(
    analysisId: () => string | null,
): RequestHandle<AnalysisPayload> {
    return useRequest(
        analysisId,
        (resourceid, signal, reload) =>
            getJson<AnalysisPayload>(ANALYSIS_ROUTE, {
                ...analysisRequest(resourceid),
                signal,
                reload,
            }),
        {
            cached: (resourceid) =>
                peekJson<AnalysisPayload>(
                    ANALYSIS_ROUTE,
                    analysisRequest(resourceid),
                ),
        },
    );
}
