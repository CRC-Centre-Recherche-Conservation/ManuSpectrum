import { getJson } from "@/manuspectrum/pages/AnalysisExplorer/api/http.ts";
import { useRequest } from "@/manuspectrum/pages/AnalysisExplorer/composables/useRequest.ts";

import type { DocumentPayload } from "@/manuspectrum/pages/AnalysisExplorer/api/types.ts";
import type { RequestHandle } from "@/manuspectrum/pages/AnalysisExplorer/composables/useRequest.ts";

export function useDocument(
    documentId: () => string | null,
): RequestHandle<DocumentPayload> {
    return useRequest(documentId, (resourceid, signal) =>
        getJson<DocumentPayload>("manuspectrum:explorer-document", {
            urlParameters: { resourceid },
            signal,
        }),
    );
}
