import {
    getSeries,
    ServiceError,
} from "@/manuspectrum/pages/AnalysisExplorer/api/http.ts";
import { useRequest } from "@/manuspectrum/pages/AnalysisExplorer/composables/useRequest.ts";

import type { Series } from "@/manuspectrum/pages/AnalysisExplorer/api/types.ts";
import type { RequestHandle } from "@/manuspectrum/pages/AnalysisExplorer/composables/useRequest.ts";

export interface SeriesResult {
    series: Series | null;
    failed: boolean;
    /** A server error (5xx, 429) another try may get past; never set for a missing or refused file. */
    retryable: boolean;
}

const QUICK_VIEW_POINTS = 4096;
const TOO_MANY_REQUESTS = 429;
const SERVER_ERROR = 500;

function isRetryable(error: unknown): boolean {
    return (
        error instanceof ServiceError &&
        (error.status >= SERVER_ERROR || error.status === TOO_MANY_REQUESTS)
    );
}

/**
 * The quick-view series (`n=4096`, spec D51) of several files, read together
 * and aborted together. A file that fails is marked `failed` and leaves the
 * others; `series: null` without `failed` is a file with nothing to draw.
 */
export function useSeriesSet(
    previewUrls: () => readonly string[],
): RequestHandle<SeriesResult[]> {
    return useRequest(
        () => (previewUrls().length > 0 ? previewUrls().join("\n") : null),
        (joined, signal) =>
            Promise.all(
                joined.split("\n").map((url) =>
                    getSeries(url, QUICK_VIEW_POINTS, signal).then(
                        (series) => ({
                            series,
                            failed: false,
                            retryable: false,
                        }),
                        (error: unknown) => {
                            if (signal.aborted) throw error;
                            return {
                                series: null,
                                failed: true,
                                retryable: isRetryable(error),
                            };
                        },
                    ),
                ),
            ),
    );
}
