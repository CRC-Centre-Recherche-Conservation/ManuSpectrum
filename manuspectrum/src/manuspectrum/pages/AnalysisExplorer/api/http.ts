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

export interface JsonRequestOptions {
    urlParameters?: Record<string, string>;
    query?: URLSearchParams;
}

export interface GetJsonOptions extends JsonRequestOptions {
    signal?: AbortSignal;
    /** Ask the server again even when this tab holds the payload. */
    reload?: boolean;
}

const NOT_FOUND = 404;
const NO_CONTENT = 204;
const MEMO_ENTRIES = 20;
const MEMO_TTL_MS = 5 * 60 * 1000;

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

interface MemoEntry {
    promise: Promise<unknown>;
    controller: AbortController;
    /** Callers waiting for the answer; the request is aborted when the last one leaves before it. */
    waiting: number;
    /** A prefetch keeps running with nobody waiting. */
    pinned: boolean;
    /** When the payload arrived; null while the request runs. */
    arrivedAt: number | null;
    value: unknown;
}

/** The payloads of this tab by URL, least recently used first. */
const memo = new Map<string, MemoEntry>();

/** The URL of a localized explorer route. */
export function explorerUrl(
    route: ExplorerRoute,
    { urlParameters = {}, query }: JsonRequestOptions = {},
): string {
    const base = generateArchesURL(route, urlParameters);
    const search = query?.toString();
    return search ? `${base}?${search}` : base;
}

function abortError(signal: AbortSignal): unknown {
    return (
        signal.reason ??
        new DOMException("The operation was aborted.", "AbortError")
    );
}

async function fetchJson(url: string, signal: AbortSignal): Promise<unknown> {
    const response = await fetch(url, {
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
    return await response.json();
}

function forget(url: string, entry: MemoEntry): void {
    if (memo.get(url) === entry) memo.delete(url);
}

/** The live entry of `url`, moved to the most recent end; an expired one is dropped. */
function lookup(url: string): MemoEntry | null {
    const entry = memo.get(url);
    if (!entry) return null;
    memo.delete(url);
    if (entry.arrivedAt !== null && Date.now() - entry.arrivedAt >= MEMO_TTL_MS)
        return null;
    memo.set(url, entry);
    return entry;
}

function start(url: string, pinned: boolean): MemoEntry {
    const controller = new AbortController();
    const entry: MemoEntry = {
        promise: Promise.resolve(),
        controller,
        waiting: 0,
        pinned,
        arrivedAt: null,
        value: null,
    };
    entry.promise = fetchJson(url, controller.signal).then(
        (value) => {
            entry.value = value;
            entry.arrivedAt = Date.now();
            return value;
        },
        (error: unknown) => {
            forget(url, entry);
            throw error;
        },
    );
    entry.promise.catch(() => undefined);
    memo.set(url, entry);
    while (memo.size > MEMO_ENTRIES) {
        memo.delete(memo.keys().next().value as string);
    }
    return entry;
}

function wait<T>(
    url: string,
    entry: MemoEntry,
    signal: AbortSignal | undefined,
): Promise<T> {
    if (signal?.aborted) return Promise.reject(abortError(signal));
    entry.waiting += 1;
    return new Promise<T>((resolve, reject) => {
        let left = false;
        function leave(): boolean {
            if (left) return false;
            left = true;
            entry.waiting -= 1;
            signal?.removeEventListener("abort", onAbort);
            return true;
        }
        function onAbort(): void {
            if (!leave()) return;
            if (
                entry.waiting === 0 &&
                !entry.pinned &&
                entry.arrivedAt === null
            ) {
                forget(url, entry);
                entry.controller.abort();
            }
            reject(abortError(signal as AbortSignal));
        }
        signal?.addEventListener("abort", onAbort);
        entry.promise.then(
            (value) => {
                if (leave()) resolve(value as T);
            },
            (error: unknown) => {
                if (leave()) reject(error);
            },
        );
    });
}

/**
 * GET a localized explorer payload through the tab's memo.
 *
 * The memo holds the last `MEMO_ENTRIES` URLs for `MEMO_TTL_MS` from their
 * answer, in memory only. Callers of one URL share one request: a caller that
 * aborts leaves it, and it is aborted when nobody waits any more. A failed
 * request (404 included) is forgotten; `reload` replaces the entry. An aborted
 * call rejects with the browser's AbortError.
 */
export function getJson<T>(
    route: ExplorerRoute,
    { signal, reload = false, ...request }: GetJsonOptions = {},
): Promise<T> {
    const url = explorerUrl(route, request);
    if (reload) memo.delete(url);
    const entry = lookup(url) ?? start(url, false);
    return wait<T>(url, entry, signal);
}

/** The payload of this route if the tab holds its answer, else null; no request. */
export function peekJson<T>(
    route: ExplorerRoute,
    request: JsonRequestOptions = {},
): T | null {
    const entry = lookup(explorerUrl(route, request));
    return entry?.arrivedAt != null ? (entry.value as T) : null;
}

/** Starts loading a payload a screen will probably ask for; a failure is forgotten silently. */
export function prefetchJson(
    route: ExplorerRoute,
    request: JsonRequestOptions = {},
): void {
    const url = explorerUrl(route, request);
    if (!lookup(url)) start(url, true);
}

/** Empties the tab's memo. */
export function forgetPayloads(): void {
    memo.clear();
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
