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
    /** The file is over the server's ceiling for the full series (413). */
    tooLarge: boolean;
}

const QUICK_VIEW_POINTS = 4096;
const TOO_MANY_REQUESTS = 429;
const TOO_LARGE = 413;
const SERVER_ERROR = 500;

function isRetryable(error: unknown): boolean {
    return (
        error instanceof ServiceError &&
        (error.status >= SERVER_ERROR || error.status === TOO_MANY_REQUESTS)
    );
}

/** The answer of one file: its series, or why it has none. */
function readOne(
    url: string,
    points: 4096 | "full",
    signal: AbortSignal,
    reload: boolean,
): Promise<SeriesResult> {
    return getSeries(url, points, signal, reload).then(
        (series) => ({
            series,
            failed: false,
            retryable: false,
            tooLarge: false,
        }),
        (error: unknown) => {
            if (signal.aborted) throw error;
            return {
                series: null,
                failed: true,
                retryable: isRetryable(error),
                tooLarge:
                    error instanceof ServiceError && error.status === TOO_LARGE,
            };
        },
    );
}

/**
 * The series of several files, read together and aborted together: the
 * quick view's (`n=4096`, spec D51) by default, every point with `"full"`
 * (the workshop, D61). A file that fails is marked `failed` and leaves the
 * others; `series: null` without `failed` is a file with nothing to draw.
 * A retry asks again only for the files that failed, the others keep their
 * answer.
 */
export function useSeriesSet(
    previewUrls: () => readonly string[],
    points: 4096 | "full" = QUICK_VIEW_POINTS,
): RequestHandle<SeriesResult[]> {
    /** The last answer of each file of the files last read. */
    let answered = new Map<string, SeriesResult>();
    return useRequest(
        () => (previewUrls().length > 0 ? previewUrls().join("\n") : null),
        async (joined, signal, reload) => {
            const urls = joined.split("\n");
            const results = await Promise.all(
                urls.map((url) => {
                    const kept = reload ? answered.get(url) : undefined;
                    return kept && !kept.failed
                        ? kept
                        : readOne(url, points, signal, reload);
                }),
            );
            answered = new Map(urls.map((url, index) => [url, results[index]]));
            return results;
        },
    );
}
