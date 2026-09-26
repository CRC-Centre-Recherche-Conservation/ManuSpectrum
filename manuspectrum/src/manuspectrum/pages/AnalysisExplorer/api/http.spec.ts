import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
    ServiceError,
    UnavailableError,
    forgetPayloads,
    getJson,
    getSeries,
    PREFETCHES_IN_FLIGHT,
    peekJson,
    prefetchJson,
} from "@/manuspectrum/pages/AnalysisExplorer/api/http.ts";

vi.mock("@/arches/utils/generate-arches-url.ts", () => ({
    generateArchesURL: (
        name: string,
        parameters: Record<string, string> = {},
    ) =>
        `/en/${name}${parameters.resourceid ? `/${parameters.resourceid}` : ""}`,
}));

function respond(status: number, body: unknown = {}): Response {
    return {
        ok: status >= 200 && status < 300,
        status,
        json: async () => body,
    } as Response;
}

const fetchMock = vi.fn();

/** A fetch answer the test settles by hand, rejecting with AbortError when its signal aborts. */
function pendingFetch(): {
    resolve: (body: unknown) => void;
    signals: AbortSignal[];
} {
    const resolvers: ((response: Response) => void)[] = [];
    const signals: AbortSignal[] = [];
    fetchMock.mockImplementation(
        (_url: string, init: RequestInit) =>
            new Promise<Response>((resolve, reject) => {
                const signal = init.signal as AbortSignal;
                signals.push(signal);
                resolvers.push(resolve);
                signal.addEventListener("abort", () =>
                    reject(new DOMException("aborted", "AbortError")),
                );
            }),
    );
    return {
        resolve: (body) =>
            resolvers.forEach((settle) => settle(respond(200, body))),
        signals,
    };
}

const SEARCH = "manuspectrum:explorer-search";

beforeEach(() => {
    forgetPayloads();
    fetchMock.mockReset();
    vi.stubGlobal("fetch", fetchMock);
});

afterEach(() => {
    vi.useRealTimers();
    vi.unstubAllGlobals();
});

describe("getJson", () => {
    it("builds the URL with its parameters and query", async () => {
        fetchMock.mockResolvedValue(respond(200, { total: 0 }));
        const body = await getJson("manuspectrum:explorer-document", {
            urlParameters: { resourceid: "abc" },
            query: new URLSearchParams([["q", "lead"]]),
        });
        expect(body).toEqual({ total: 0 });
        const [url, init] = fetchMock.mock.calls[0];
        expect(url).toBe("/en/manuspectrum:explorer-document/abc?q=lead");
        expect(init.credentials).toBe("same-origin");
    });

    it("maps 404 to UnavailableError and other failures to ServiceError", async () => {
        fetchMock.mockResolvedValueOnce(respond(404));
        await expect(
            getJson("manuspectrum:explorer-search"),
        ).rejects.toBeInstanceOf(UnavailableError);
        fetchMock.mockResolvedValueOnce(respond(429));
        await expect(
            getJson("manuspectrum:explorer-search"),
        ).rejects.toMatchObject({ status: 429 });
        fetchMock.mockResolvedValueOnce(respond(503));
        await expect(
            getJson("manuspectrum:explorer-search"),
        ).rejects.toBeInstanceOf(ServiceError);
    });

    it("omits the question mark when the query is empty", async () => {
        fetchMock.mockResolvedValue(respond(200, {}));
        await getJson("manuspectrum:explorer-search", {
            query: new URLSearchParams(),
        });
        expect(fetchMock.mock.calls[0][0]).toBe(
            "/en/manuspectrum:explorer-search",
        );
    });
});

describe("the tab memo", () => {
    it("shares one request between the callers of one URL", async () => {
        const pending = pendingFetch();
        const first = getJson(SEARCH, { query: new URLSearchParams("q=a") });
        const second = getJson(SEARCH, { query: new URLSearchParams("q=a") });
        pending.resolve({ total: 1 });
        expect(await first).toEqual({ total: 1 });
        expect(await second).toEqual({ total: 1 });
        expect(fetchMock).toHaveBeenCalledTimes(1);
    });

    it("answers a URL again from the memo, and peeks at it without a request", async () => {
        fetchMock.mockResolvedValue(respond(200, { total: 2 }));
        await getJson(SEARCH);
        expect(peekJson(SEARCH)).toEqual({ total: 2 });
        expect(await getJson(SEARCH)).toEqual({ total: 2 });
        expect(fetchMock).toHaveBeenCalledTimes(1);
        expect(peekJson(SEARCH, { query: new URLSearchParams("q=b") })).toBe(
            null,
        );
    });

    it("keeps the request running while another caller still waits", async () => {
        const pending = pendingFetch();
        const leaving = new AbortController();
        const gone = getJson(SEARCH, { signal: leaving.signal });
        const staying = getJson(SEARCH);
        leaving.abort();
        await expect(gone).rejects.toMatchObject({ name: "AbortError" });
        expect(pending.signals[0].aborted).toBe(false);
        pending.resolve({ total: 3 });
        expect(await staying).toEqual({ total: 3 });
    });

    it("aborts the request when its last caller leaves, and asks again next time", async () => {
        const pending = pendingFetch();
        const leaving = new AbortController();
        const gone = getJson(SEARCH, { signal: leaving.signal });
        leaving.abort();
        await expect(gone).rejects.toMatchObject({ name: "AbortError" });
        expect(pending.signals[0].aborted).toBe(true);
        void getJson(SEARCH);
        expect(fetchMock).toHaveBeenCalledTimes(2);
    });

    it("forgets a payload after five minutes", async () => {
        vi.useFakeTimers();
        fetchMock.mockResolvedValue(respond(200, { total: 4 }));
        await getJson(SEARCH);
        vi.advanceTimersByTime(5 * 60 * 1000 - 1);
        expect(peekJson(SEARCH)).toEqual({ total: 4 });
        vi.advanceTimersByTime(1);
        expect(peekJson(SEARCH)).toBe(null);
        await getJson(SEARCH);
        expect(fetchMock).toHaveBeenCalledTimes(2);
    });

    it("holds the twenty most recently used URLs", async () => {
        fetchMock.mockImplementation(async () => respond(200, {}));
        for (let page = 1; page <= 21; page += 1) {
            await getJson(SEARCH, {
                query: new URLSearchParams([["page", String(page)]]),
            });
        }
        expect(peekJson(SEARCH, { query: new URLSearchParams("page=1") })).toBe(
            null,
        );
        expect(
            peekJson(SEARCH, { query: new URLSearchParams("page=2") }),
        ).toEqual({});
    });

    it("forgets a failed answer, 404 included, and reloads on demand", async () => {
        fetchMock.mockResolvedValueOnce(respond(404));
        await expect(getJson(SEARCH)).rejects.toBeInstanceOf(UnavailableError);
        fetchMock.mockResolvedValueOnce(respond(200, { total: 5 }));
        expect(await getJson(SEARCH)).toEqual({ total: 5 });
        fetchMock.mockResolvedValueOnce(respond(200, { total: 6 }));
        expect(await getJson(SEARCH, { reload: true })).toEqual({ total: 6 });
        expect(fetchMock).toHaveBeenCalledTimes(3);
    });

    it("lets a prefetch run with nobody waiting and serves it to the next caller", async () => {
        const pending = pendingFetch();
        prefetchJson(SEARCH);
        const leaving = new AbortController();
        const gone = getJson(SEARCH, { signal: leaving.signal });
        leaving.abort();
        await expect(gone).rejects.toMatchObject({ name: "AbortError" });
        expect(pending.signals[0].aborted).toBe(false);
        pending.resolve({ total: 7 });
        expect(await getJson(SEARCH)).toEqual({ total: 7 });
        expect(fetchMock).toHaveBeenCalledTimes(1);
    });

    it("never evicts a request still running for a caller", async () => {
        const pending = pendingFetch();
        const first = getJson(SEARCH, {
            query: new URLSearchParams("page=0"),
        });
        for (let page = 1; page <= 25; page += 1) {
            void getJson(SEARCH, {
                query: new URLSearchParams([["page", String(page)]]),
            });
        }
        const again = getJson(SEARCH, {
            query: new URLSearchParams("page=0"),
        });
        const asked = fetchMock.mock.calls.filter(
            (call) => call[0] === "/en/manuspectrum:explorer-search?page=0",
        );
        expect(asked).toHaveLength(1);
        pending.resolve({ total: 1 });
        expect(await first).toEqual({ total: 1 });
        expect(await again).toEqual({ total: 1 });
    });
});

describe("prefetchJson", () => {
    it("aborts a prefetch nobody waits for when its signal aborts", () => {
        const pending = pendingFetch();
        const intent = new AbortController();
        prefetchJson(SEARCH, { signal: intent.signal });
        intent.abort();
        expect(pending.signals[0].aborted).toBe(true);
        void getJson(SEARCH);
        expect(fetchMock).toHaveBeenCalledTimes(2);
    });

    it("keeps an aborted prefetch running for a caller that waits", async () => {
        const pending = pendingFetch();
        const intent = new AbortController();
        prefetchJson(SEARCH, { signal: intent.signal });
        const waiting = getJson(SEARCH);
        intent.abort();
        expect(pending.signals[0].aborted).toBe(false);
        pending.resolve({ total: 2 });
        expect(await waiting).toEqual({ total: 2 });
    });

    it("runs a bounded number of prefetches, dropping the oldest", () => {
        const pending = pendingFetch();
        for (let page = 1; page <= PREFETCHES_IN_FLIGHT + 2; page += 1) {
            prefetchJson(SEARCH, {
                query: new URLSearchParams([["page", String(page)]]),
            });
        }
        const running = pending.signals.filter((signal) => !signal.aborted);
        expect(running).toHaveLength(PREFETCHES_IN_FLIGHT);
        expect(pending.signals[0].aborted).toBe(true);
        expect(pending.signals[1].aborted).toBe(true);
    });
});

describe("getSeries", () => {
    it("maps 404 to UnavailableError", async () => {
        fetchMock.mockResolvedValueOnce(respond(404));
        await expect(
            getSeries("http://testserver/api/spectrum-preview/abc", 4096),
        ).rejects.toBeInstanceOf(UnavailableError);
    });
});
