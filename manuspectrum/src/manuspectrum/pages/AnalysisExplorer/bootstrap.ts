import AnalysisExplorer from "@/manuspectrum/pages/AnalysisExplorer/AnalysisExplorer.vue";

import { mountPublicApp } from "@/manuspectrum/public/mountPublicApp.ts";
import { prefetchJson } from "@/manuspectrum/pages/AnalysisExplorer/api/http.ts";
import {
    ANALYSIS_ROUTE,
    analysisRequest,
} from "@/manuspectrum/pages/AnalysisExplorer/composables/useAnalysis.ts";
import {
    DOCUMENT_ROUTE,
    documentRequest,
} from "@/manuspectrum/pages/AnalysisExplorer/composables/useDocument.ts";
import {
    MATCH_ROUTE,
    matchRequest,
} from "@/manuspectrum/pages/AnalysisExplorer/composables/useDocumentMatch.ts";
import {
    HOME_ROUTE,
    homeRequest,
} from "@/manuspectrum/pages/AnalysisExplorer/composables/useHome.ts";
import {
    SEARCH_ROUTE,
    filterQuery,
    searchQuery,
} from "@/manuspectrum/pages/AnalysisExplorer/composables/useSearch.ts";
import { fromQuery } from "@/manuspectrum/pages/AnalysisExplorer/store/url.ts";
import { localDay } from "@/manuspectrum/pages/AnalysisExplorer/views/Corpus/document-of-the-day.ts";

// Looked for by check_explorer_bundle.sh: it must appear in the lazy
// analysis-explorer chunk and in no initial file of another entry.
export const EXPLORER_CHUNK_MARKER = "__MS_EXPLORER_CHUNK__";
const MOUNT_POINT_ID = "ms-explorer-app";

/**
 * Starts the requests of the Corpus screen the address `search` opens on, as
 * that screen will ask for them, so they run while the application starts
 * (translations included); the screen then shares them through the tab memo.
 */
export function prefetchFirstScreen(search: string): void {
    const snapshot = fromQuery(new URLSearchParams(search));
    if (snapshot.view !== "corpus") return;
    if (snapshot.document) {
        const id = snapshot.document.id;
        prefetchJson(DOCUMENT_ROUTE, documentRequest(id));
        prefetchJson(
            MATCH_ROUTE,
            matchRequest(id, filterQuery(snapshot.filters)),
        );
        if (snapshot.focus?.kind === "analysis") {
            prefetchJson(ANALYSIS_ROUTE, analysisRequest(snapshot.focus.id));
        }
    } else if (snapshot.corpusScreen === "results") {
        prefetchJson(SEARCH_ROUTE, {
            query: searchQuery(snapshot.filters, 1),
        });
    } else {
        prefetchJson(HOME_ROUTE, homeRequest(localDay(new Date())));
    }
}

export async function startAnalysisExplorer(): Promise<void> {
    const mountPoint = document.getElementById(MOUNT_POINT_ID);
    if (!mountPoint) {
        return;
    }
    mountPoint.dataset.bundle = EXPLORER_CHUNK_MARKER;
    try {
        prefetchFirstScreen(window.location.search);
    } catch {
        // The screen asks for its payloads itself once mounted.
    }
    await mountPublicApp({
        component: AnalysisExplorer,
        mountPoint,
        initialProps: {
            miradorUrl: mountPoint.dataset.miradorUrl ?? "",
        },
    });
}
