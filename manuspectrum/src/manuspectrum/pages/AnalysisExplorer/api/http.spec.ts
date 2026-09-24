import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
    ServiceError,
    UnavailableError,
    getJson,
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

beforeEach(() => {
    fetchMock.mockReset();
    vi.stubGlobal("fetch", fetchMock);
});

afterEach(() => vi.unstubAllGlobals());

describe("getJson", () => {
    it("builds the URL with its parameters and query and forwards the signal", async () => {
        fetchMock.mockResolvedValue(respond(200, { total: 0 }));
        const controller = new AbortController();
        const body = await getJson("manuspectrum:explorer-document", {
            urlParameters: { resourceid: "abc" },
            query: new URLSearchParams([["q", "lead"]]),
            signal: controller.signal,
        });
        expect(body).toEqual({ total: 0 });
        const [url, init] = fetchMock.mock.calls[0];
        expect(url).toBe("/en/manuspectrum:explorer-document/abc?q=lead");
        expect(init.signal).toBe(controller.signal);
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
