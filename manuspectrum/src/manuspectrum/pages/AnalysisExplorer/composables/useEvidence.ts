import { getJson } from "@/manuspectrum/pages/AnalysisExplorer/api/http.ts";
import { useRequest } from "@/manuspectrum/pages/AnalysisExplorer/composables/useRequest.ts";

import type { AnalysisPayload } from "@/manuspectrum/pages/AnalysisExplorer/api/types.ts";
import type { RequestHandle } from "@/manuspectrum/pages/AnalysisExplorer/composables/useRequest.ts";

/** The evidence analyses of an identified material, read together and aborted together; one failure fails the set. */
export function useEvidence(
    ids: () => readonly string[],
): RequestHandle<AnalysisPayload[]> {
    return useRequest(
        () => (ids().length > 0 ? [...ids()].join(",") : null),
        (joined, signal) =>
            Promise.all(
                joined.split(",").map((resourceid) =>
                    getJson<AnalysisPayload>("manuspectrum:explorer-analysis", {
                        urlParameters: { resourceid },
                        signal,
                    }),
                ),
            ),
    );
}
