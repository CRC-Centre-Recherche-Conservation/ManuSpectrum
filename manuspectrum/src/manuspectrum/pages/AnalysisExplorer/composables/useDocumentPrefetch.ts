import { onScopeDispose } from "vue";

import { prefetchJson } from "@/manuspectrum/pages/AnalysisExplorer/api/http.ts";
import {
    DOCUMENT_ROUTE,
    documentRequest,
} from "@/manuspectrum/pages/AnalysisExplorer/composables/useDocument.ts";
import {
    MATCH_ROUTE,
    matchRequest,
} from "@/manuspectrum/pages/AnalysisExplorer/composables/useDocumentMatch.ts";

/** How long a pointer or the keyboard focus rests on a card before its document loads ahead. */
export const INTENT_MS = 150;

export interface DocumentPrefetch {
    /** The reader points at or focuses the card of document `id`. */
    intend: (id: string) => void;
    /** The reader left the card before `INTENT_MS`. */
    drop: () => void;
}

/**
 * Loads the document screen of a card ahead (its payload and its match under
 * `filters`, `filterQuery`) once the reader has rested on it for `INTENT_MS`.
 */
export function useDocumentPrefetch(
    filters: () => URLSearchParams,
): DocumentPrefetch {
    let timer: ReturnType<typeof setTimeout> | null = null;

    function drop(): void {
        if (timer !== null) clearTimeout(timer);
        timer = null;
    }

    function intend(id: string): void {
        drop();
        timer = setTimeout(() => {
            timer = null;
            prefetchJson(DOCUMENT_ROUTE, documentRequest(id));
            prefetchJson(MATCH_ROUTE, matchRequest(id, filters()));
        }, INTENT_MS);
    }

    onScopeDispose(drop);
    return { intend, drop };
}
