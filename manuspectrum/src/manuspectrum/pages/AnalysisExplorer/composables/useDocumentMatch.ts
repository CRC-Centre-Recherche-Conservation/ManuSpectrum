import { getJson } from "@/manuspectrum/pages/AnalysisExplorer/api/http.ts";
import { useRequest } from "@/manuspectrum/pages/AnalysisExplorer/composables/useRequest.ts";

import type { DocumentMatch } from "@/manuspectrum/pages/AnalysisExplorer/api/types.ts";
import type { RequestHandle } from "@/manuspectrum/pages/AnalysisExplorer/composables/useRequest.ts";

/** A document match with the id of the document it answers for. */
export interface DocumentMatchOf {
    documentId: string;
    match: DocumentMatch;
}

/** What the Corpus filters of `query` keep in a document, with its facets (`GET document/<id>/match`). */
export function useDocumentMatch(
    documentId: () => string | null,
    query: () => URLSearchParams,
): RequestHandle<DocumentMatchOf> {
    return useRequest(
        () => {
            const id = documentId();
            return id === null ? null : `${id}?${query().toString()}`;
        },
        async (source, signal) => {
            const [resourceid, search] = source.split("?");
            const match = await getJson<DocumentMatch>(
                "manuspectrum:explorer-document-match",
                {
                    urlParameters: { resourceid },
                    query: new URLSearchParams(search),
                    signal,
                },
            );
            return { documentId: resourceid, match };
        },
    );
}
