import { getJson } from "@/manuspectrum/pages/AnalysisExplorer/api/http.ts";
import { useRequest } from "@/manuspectrum/pages/AnalysisExplorer/composables/useRequest.ts";

import type { DocumentPayload } from "@/manuspectrum/pages/AnalysisExplorer/api/types.ts";
import type { RequestHandle } from "@/manuspectrum/pages/AnalysisExplorer/composables/useRequest.ts";

/** The document payload for the Corpus filters of `query`; each analysis says whether they keep it (`match`). */
export function useDocument(
    documentId: () => string | null,
    query: () => URLSearchParams = () => new URLSearchParams(),
): RequestHandle<DocumentPayload> {
    return useRequest(
        () => {
            const id = documentId();
            return id === null ? null : `${id}?${query().toString()}`;
        },
        (source, signal) => {
            const [resourceid, search] = source.split("?");
            return getJson<DocumentPayload>("manuspectrum:explorer-document", {
                urlParameters: { resourceid },
                query: new URLSearchParams(search),
                signal,
            });
        },
    );
}
