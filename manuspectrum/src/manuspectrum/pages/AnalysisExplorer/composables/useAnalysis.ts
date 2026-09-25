import { getJson } from "@/manuspectrum/pages/AnalysisExplorer/api/http.ts";
import { useRequest } from "@/manuspectrum/pages/AnalysisExplorer/composables/useRequest.ts";

import type { AnalysisPayload } from "@/manuspectrum/pages/AnalysisExplorer/api/types.ts";
import type { RequestHandle } from "@/manuspectrum/pages/AnalysisExplorer/composables/useRequest.ts";

export function useAnalysis(
    analysisId: () => string | null,
): RequestHandle<AnalysisPayload> {
    return useRequest(analysisId, (resourceid, signal) =>
        getJson<AnalysisPayload>("manuspectrum:explorer-analysis", {
            urlParameters: { resourceid },
            signal,
        }),
    );
}
