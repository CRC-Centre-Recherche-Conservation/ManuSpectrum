import {
    getJson,
    peekJson,
} from "@/manuspectrum/pages/AnalysisExplorer/api/http.ts";
import { useRequest } from "@/manuspectrum/pages/AnalysisExplorer/composables/useRequest.ts";

import type { JsonRequestOptions } from "@/manuspectrum/pages/AnalysisExplorer/api/http.ts";
import type { DocumentMatch } from "@/manuspectrum/pages/AnalysisExplorer/api/types.ts";
import type { RequestHandle } from "@/manuspectrum/pages/AnalysisExplorer/composables/useRequest.ts";

export const MATCH_ROUTE = "manuspectrum:explorer-document-match";

/** A document match with the id of the document it answers for. */
export interface DocumentMatchOf {
    documentId: string;
    match: DocumentMatch;
}

/** The request of what the filters `query` (`filterQuery`) keep in document `resourceid`. */
export function matchRequest(
    resourceid: string,
    query: URLSearchParams,
): JsonRequestOptions {
    return { urlParameters: { resourceid }, query };
}

/** The query of `GET facet/<key>` for the facets of the match `source` answers: its filters, scoped to its document (`document=`). */
export function facetQueryOf(source: string): string {
    const [resourceid, search] = source.split("?");
    const query = new URLSearchParams(search);
    query.set("document", resourceid);
    return query.toString();
}

function requestOf(source: string): JsonRequestOptions {
    const [resourceid, search] = source.split("?");
    return matchRequest(resourceid, new URLSearchParams(search));
}

function documentOf(source: string): string {
    return source.split("?")[0];
}

/**
 * What the Corpus filters of `query` keep in a document, with its facets
 * (`GET document/<id>/match`). A change of filters on the same document
 * waits for them to settle (`DEBOUNCE_MS`); another document asks at once.
 */
export function useDocumentMatch(
    documentId: () => string | null,
    query: () => URLSearchParams,
): RequestHandle<DocumentMatchOf> {
    return useRequest(
        () => {
            const id = documentId();
            return id === null ? null : `${id}?${query().toString()}`;
        },
        async (source, signal, reload) => ({
            documentId: documentOf(source),
            match: await getJson<DocumentMatch>(MATCH_ROUTE, {
                ...requestOf(source),
                signal,
                reload,
            }),
        }),
        {
            cached: (source) => {
                const match = peekJson<DocumentMatch>(
                    MATCH_ROUTE,
                    requestOf(source),
                );
                return match ? { documentId: documentOf(source), match } : null;
            },
            debounce: (next, previous) =>
                documentOf(next) === documentOf(previous),
        },
    );
}
