import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { effectScope } from "vue";

import {
    forgetPayloads,
    getJson,
} from "@/manuspectrum/pages/AnalysisExplorer/api/http.ts";
import {
    DOCUMENT_ROUTE,
    documentRequest,
} from "@/manuspectrum/pages/AnalysisExplorer/composables/useDocument.ts";
import {
    INTENT_MS,
    useDocumentPrefetch,
} from "@/manuspectrum/pages/AnalysisExplorer/composables/useDocumentPrefetch.ts";

vi.mock("@/arches/utils/generate-arches-url.ts", () => ({
    generateArchesURL: (
        name: string,
        parameters: Record<string, string> = {},
    ) =>
        `/en/${name}${parameters.resourceid ? `/${parameters.resourceid}` : ""}`,
}));

const fetchMock = vi.fn();
const DOCUMENT_URL = "/en/manuspectrum:explorer-document/doc-1";

beforeEach(() => {
    forgetPayloads();
    vi.useFakeTimers();
    fetchMock.mockReset();
    fetchMock.mockImplementation(
        (_url: string, init: RequestInit) =>
            new Promise<Response>((resolve, reject) => {
                const signal = init.signal as AbortSignal;
                signal.addEventListener("abort", () =>
                    reject(new DOMException("aborted", "AbortError")),
                );
                setTimeout(
                    () =>
                        resolve({
                            ok: true,
                            status: 200,
                            json: async () => ({ id: "doc-1" }),
                        } as Response),
                    1000,
                );
            }),
    );
    vi.stubGlobal("fetch", fetchMock);
});

afterEach(() => {
    vi.useRealTimers();
    vi.unstubAllGlobals();
});

describe("useDocumentPrefetch hand-off", () => {
    it("hands its running load to the document screen opened by a click", async () => {
        const results = effectScope();
        const prefetch = results.run(() =>
            useDocumentPrefetch(() => new URLSearchParams()),
        )!;
        prefetch.intend("doc-1");
        vi.advanceTimersByTime(INTENT_MS);
        const signal = fetchMock.mock.calls.find(
            ([url]) => url === DOCUMENT_URL,
        )?.[1]?.signal as AbortSignal;
        expect(signal.aborted).toBe(false);

        results.stop();
        const payload = getJson(DOCUMENT_ROUTE, documentRequest("doc-1"));
        await vi.advanceTimersByTimeAsync(1000);

        await expect(payload).resolves.toEqual({ id: "doc-1" });
        expect(signal.aborted).toBe(false);
        expect(
            fetchMock.mock.calls.filter(([url]) => url === DOCUMENT_URL),
        ).toHaveLength(1);
    });
});
