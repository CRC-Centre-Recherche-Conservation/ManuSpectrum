import { generateArchesURL } from "@/arches/utils/generate-arches-url.ts";

import type { Series } from "@/manuspectrum/pages/AnalysisExplorer/api/types.ts";

export type ExplorerRoute =
    | "manuspectrum:explorer-search"
    | "manuspectrum:explorer-document"
    | "manuspectrum:explorer-document-match"
    | "manuspectrum:explorer-facet"
    | "manuspectrum:explorer-home"
    | "manuspectrum:explorer-analysis"
    | "manuspectrum:explorer-items";

export interface GetJsonOptions {
    urlParameters?: Record<string, string>;
    query?: URLSearchParams;
    signal?: AbortSignal;
}

const NOT_FOUND = 404;
const NO_CONTENT = 204;

/** The API answered 404: unknown and refused look the same (spec §4). */
export class UnavailableError extends Error {
    constructor() {
        super("unavailable");
        this.name = "UnavailableError";
    }
}

/** Any other non-2xx answer; 429 and 5xx keep a retryable error state. */
export class ServiceError extends Error {
    readonly status: number;

    constructor(status: number) {
        super(`HTTP ${status}`);
        this.name = "ServiceError";
        this.status = status;
    }
}

/** GET a localized explorer payload. An aborted request rejects with the browser's AbortError. */
export async function getJson<T>(
    route: ExplorerRoute,
    { urlParameters = {}, query, signal }: GetJsonOptions = {},
): Promise<T> {
    const base = generateArchesURL(route, urlParameters);
    const search = query?.toString();
    const response = await fetch(search ? `${base}?${search}` : base, {
        credentials: "same-origin",
        headers: { Accept: "application/json" },
        signal,
    });
    if (response.status === NOT_FOUND) {
        throw new UnavailableError();
    }
    if (!response.ok) {
        throw new ServiceError(response.status);
    }
    return (await response.json()) as T;
}

/**
 * The series of one readable file at a point budget of the server's tiers.
 * The preview URL of the payload is absolute on `PUBLIC_SERVER_ADDRESS`; only
 * its path is fetched, on the page's own origin. `null` means nothing to draw.
 */
export async function getSeries(
    previewUrl: string,
    n: 200 | 4096,
    signal?: AbortSignal,
): Promise<Series | null> {
    const path = new URL(previewUrl, window.location.origin).pathname;
    const response = await fetch(`${path}?n=${n}`, {
        credentials: "same-origin",
        headers: { Accept: "application/json" },
        signal,
    });
    if (response.status === NOT_FOUND) {
        throw new UnavailableError();
    }
    if (!response.ok) {
        throw new ServiceError(response.status);
    }
    if (response.status === NO_CONTENT) {
        return null;
    }
    return (await response.json()) as Series;
}
