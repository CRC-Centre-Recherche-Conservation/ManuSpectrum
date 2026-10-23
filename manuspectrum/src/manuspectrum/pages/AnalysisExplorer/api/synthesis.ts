import {
    getJson,
    peekJson,
} from "@/manuspectrum/pages/AnalysisExplorer/api/http.ts";

import type { SynthesisResponse } from "@/manuspectrum/pages/AnalysisExplorer/api/types.ts";

export const SYNTHESIS_ROUTE = "manuspectrum:explorer-synthesis";

export interface SynthesisRequest {
    signal?: AbortSignal;
    /** Ask the server again even when this tab holds the payload. */
    reload?: boolean;
}

/** The query of a Selection: one `ids` holding its unique keys, sorted, so one Selection is one URL. */
export function synthesisQuery(keys: readonly string[]): URLSearchParams {
    return new URLSearchParams({ ids: [...new Set(keys)].sort().join(",") });
}

/**
 * The synthesis of at most 30 Selection keys through the tab's memo.
 * The API answers 400 without a key or above 30, 404 (`UnavailableError`)
 * when nothing in the Selection is visible.
 */
export function getSynthesis(
    keys: readonly string[],
    { signal, reload = false }: SynthesisRequest = {},
): Promise<SynthesisResponse> {
    return getJson<SynthesisResponse>(SYNTHESIS_ROUTE, {
        query: synthesisQuery(keys),
        signal,
        reload,
    });
}

/** The synthesis of these keys if the tab holds it, else null; no request. */
export function peekSynthesis(
    keys: readonly string[],
): SynthesisResponse | null {
    return peekJson<SynthesisResponse>(SYNTHESIS_ROUTE, {
        query: synthesisQuery(keys),
    });
}
