import {
    getJson,
    peekJson,
} from "@/manuspectrum/pages/AnalysisExplorer/api/http.ts";
import { useRequest } from "@/manuspectrum/pages/AnalysisExplorer/composables/useRequest.ts";

import type { JsonRequestOptions } from "@/manuspectrum/pages/AnalysisExplorer/api/http.ts";
import type { DocumentPayload } from "@/manuspectrum/pages/AnalysisExplorer/api/types.ts";
import type { RequestHandle } from "@/manuspectrum/pages/AnalysisExplorer/composables/useRequest.ts";

export const DOCUMENT_ROUTE = "manuspectrum:explorer-document";

/** The request of the payload of document `resourceid`. */
export function documentRequest(resourceid: string): JsonRequestOptions {
    return { urlParameters: { resourceid } };
}

/** The document payload, the same whatever the Corpus filters (`useDocumentMatch` says what they keep). */
export function useDocument(
    documentId: () => string | null,
): RequestHandle<DocumentPayload> {
    return useRequest(
        documentId,
        (resourceid, signal, reload) =>
            getJson<DocumentPayload>(DOCUMENT_ROUTE, {
                ...documentRequest(resourceid),
                signal,
                reload,
            }),
        {
            cached: (resourceid) =>
                peekJson<DocumentPayload>(
                    DOCUMENT_ROUTE,
                    documentRequest(resourceid),
                ),
        },
    );
}
