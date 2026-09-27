import { generateArchesURL } from "@/arches/utils/generate-arches-url.ts";

import type { Series } from "@/manuspectrum/pages/AnalysisExplorer/api/types.ts";

export type ExplorerRoute =
    | "manuspectrum:explorer-search"
    | "manuspectrum:explorer-document"
    | "manuspectrum:explorer-document-match"
    | "manuspectrum:explorer-facet"
    | "manuspectrum:explorer-home"
    | "manuspectrum:explorer-analysis"
    | "manuspectrum:explorer-items"
    | "manuspectrum:explorer-share"
    | "manuspectrum:explorer-synthesis";

export interface JsonRequestOptions {
    urlParameters?: Record<string, string>;
    query?: URLSearchParams;
}

export interface PrefetchOptions extends JsonRequestOptions {
    /** Aborts the prefetch when nobody waits for it yet. */
    signal?: AbortSignal;
}

export interface GetJsonOptions extends JsonRequestOptions {
    signal?: AbortSignal;
    /** Ask the server again even when this tab holds the payload. */
    reload?: boolean;
}

const NOT_FOUND = 404;
const NO_CONTENT = 204;
const MEMO_ENTRIES = 20;
/** Full series (every point, up to the server's ceiling) kept apart: a Compare view never evicts the Explorer payloads. */
const FULL_SERIES_ENTRIES = 6;
/** The most full series the tab keeps, whatever Compare draws (a full series can weigh a few MB once read). */
const FULL_SERIES_MAX_ENTRIES = 30;
const MEMO_TTL_MS = 5 * 60 * 1000;
/** Prefetches nobody waits for yet that run at once; a new one drops the oldest. */
export const PREFETCHES_IN_FLIGHT = 4;

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

/** Entries by URL, least recently used first, at most `limit`. */
interface Memo {
    entries: Map<string, MemoEntry>;
    limit: number;
}

/** The payloads of this tab. */
const payloads: Memo = { entries: new Map(), limit: MEMO_ENTRIES };
/** The full series of this tab. */
const fullSeries: Memo = { entries: new Map(), limit: FULL_SERIES_ENTRIES };

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

async function fetchJson(url: string, signal?: AbortSignal): Promise<unknown> {
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
    if (response.status === NO_CONTENT) {
        return null;
    }
    return await response.json();
}

function forget(memo: Memo, url: string, entry: MemoEntry): void {
    if (memo.entries.get(url) === entry) memo.entries.delete(url);
}

/** The live entry of `url`, moved to the most recent end; an expired one is dropped. */
function lookup(memo: Memo, url: string): MemoEntry | null {
    const entry = memo.entries.get(url);
    if (!entry) return null;
    memo.entries.delete(url);
    if (entry.arrivedAt !== null && Date.now() - entry.arrivedAt >= MEMO_TTL_MS)
        return null;
    memo.entries.set(url, entry);
    return entry;
}

function start(memo: Memo, url: string, pinned: boolean): MemoEntry {
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
            forget(memo, url, entry);
            throw error;
        },
    );
    entry.promise.catch(() => undefined);
    memo.entries.set(url, entry);
    evict(memo);
    return entry;
}

/**
 * Drops the least recently used answers over the memo's limit. A request
 * still running is never dropped: it counts towards the limit and leaves
 * the memo only when it fails or its last caller aborts it.
 */
function evict(memo: Memo): void {
    for (const [url, entry] of memo.entries) {
        if (memo.entries.size <= memo.limit) return;
        if (entry.arrivedAt !== null) memo.entries.delete(url);
    }
}

/** Aborts `entry` unless a caller waits for it or its answer arrived. */
function abandon(url: string, entry: MemoEntry): void {
    entry.pinned = false;
    if (entry.waiting === 0 && entry.arrivedAt === null) {
        forget(payloads, url, entry);
        entry.controller.abort();
    }
}

/** Aborts the oldest prefetches nobody waits for beyond `PREFETCHES_IN_FLIGHT`. */
function capPrefetches(): void {
    const idle = [...payloads.entries].filter(
        ([, entry]) =>
            entry.pinned && entry.arrivedAt === null && entry.waiting === 0,
    );
    for (const [url, entry] of idle.slice(
        0,
        Math.max(0, idle.length - PREFETCHES_IN_FLIGHT),
    )) {
        abandon(url, entry);
    }
}

function wait<T>(
    memo: Memo,
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
                forget(memo, url, entry);
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
 * The memo holds the last `MEMO_ENTRIES` answers for `MEMO_TTL_MS` from
 * their arrival, in memory only; a request still running is never evicted.
 * Callers of one URL share one request: a caller that aborts leaves it, and
 * it is aborted when nobody waits any more. A failed
 * request (404 included) is forgotten; `reload` replaces the entry. An aborted
 * call rejects with the browser's AbortError.
 */
export function getJson<T>(
    route: ExplorerRoute,
    { signal, reload = false, ...request }: GetJsonOptions = {},
): Promise<T> {
    const url = explorerUrl(route, request);
    if (reload) payloads.entries.delete(url);
    const entry = lookup(payloads, url) ?? start(payloads, url, false);
    return wait<T>(payloads, url, entry, signal);
}

/** The payload of this route if the tab holds its answer, else null; no request. */
export function peekJson<T>(
    route: ExplorerRoute,
    request: JsonRequestOptions = {},
): T | null {
    const entry = lookup(payloads, explorerUrl(route, request));
    return entry?.arrivedAt != null ? (entry.value as T) : null;
}

/**
 * Starts loading a payload a screen will probably ask for; a failure is
 * forgotten silently. At most `PREFETCHES_IN_FLIGHT` prefetches nobody waits
 * for run at once, the oldest aborted first; `signal` aborts this one unless
 * a caller already waits for it.
 */
export function prefetchJson(
    route: ExplorerRoute,
    { signal, ...request }: PrefetchOptions = {},
): void {
    const url = explorerUrl(route, request);
    if (signal?.aborted || lookup(payloads, url)) return;
    const entry = start(payloads, url, true);
    capPrefetches();
    signal?.addEventListener("abort", () => abandon(url, entry), {
        once: true,
    });
}

/** Empties the tab's memo, full series included, and gives the full series their default room. */
export function forgetPayloads(): void {
    payloads.entries.clear();
    fullSeries.entries.clear();
    fullSeries.limit = FULL_SERIES_ENTRIES;
}

/**
 * Sizes the memo of full series for `spectra` series drawn at once: at
 * least `FULL_SERIES_ENTRIES`, at most `FULL_SERIES_MAX_ENTRIES`. A smaller
 * room drops the least recently used answers at once.
 */
export function setFullSeriesRoom(spectra: number): void {
    fullSeries.limit = Math.min(
        FULL_SERIES_MAX_ENTRIES,
        Math.max(FULL_SERIES_ENTRIES, spectra),
    );
    evict(fullSeries);
}

/**
 * The series of one readable file at a point budget of the server's tiers, or
 * every point with `"full"` (the workshop; a file over the server's ceiling
 * rejects with a 413 `ServiceError`).
 * The preview URL of the payload is absolute on `PUBLIC_SERVER_ADDRESS`; only
 * its path is fetched, on the page's own origin. `null` means nothing to draw.
 * The full series goes through a memo of its own, the last
 * `FULL_SERIES_ENTRIES` files or the room Compare asks (`setFullSeriesRoom`), with the rules of the payloads' memo (TTL,
 * shared requests, `reload` replaces the entry): a Compare view drawing many
 * spectra never evicts an Explorer payload. The tiers are asked each time.
 */
export async function getSeries(
    previewUrl: string,
    n: 200 | 4096 | "full",
    signal?: AbortSignal,
    reload = false,
): Promise<Series | null> {
    const path = new URL(previewUrl, window.location.origin).pathname;
    const url = `${path}?n=${n}`;
    if (n === "full") {
        if (reload) fullSeries.entries.delete(url);
        const entry = lookup(fullSeries, url) ?? start(fullSeries, url, false);
        return wait<Series | null>(fullSeries, url, entry, signal);
    }
    return (await fetchJson(url, signal)) as Series | null;
}
