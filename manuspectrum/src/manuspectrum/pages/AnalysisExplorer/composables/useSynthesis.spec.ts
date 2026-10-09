import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { effectScope, ref } from "vue";
import { flushPromises } from "@vue/test-utils";

import { forgetPayloads } from "@/manuspectrum/pages/AnalysisExplorer/api/http.ts";
import { useSynthesis } from "@/manuspectrum/pages/AnalysisExplorer/composables/useSynthesis.ts";
import { jsonResponse } from "@/manuspectrum/pages/AnalysisExplorer/testing/responses.ts";

import type { EffectScope } from "vue";
import type { SynthesisResponse } from "@/manuspectrum/pages/AnalysisExplorer/api/types.ts";

vi.mock("@/arches/utils/generate-arches-url.ts", () => ({
    generateArchesURL: () => "/en/api/explorer/synthesis",
}));

const EMPTY: SynthesisResponse = {
    coverage: [],
    canvases: [],
    techniques: [],
    pairs: [],
    elements: [],
    materials: [],
    unpublishedCount: 0,
};

let fetchMock: ReturnType<typeof vi.fn>;
let scope: EffectScope;

function asked(call: number): string | null {
    const url = String(fetchMock.mock.calls[call][0]);
    return new URLSearchParams(url.split("?")[1]).get("ids");
}

beforeEach(() => {
    forgetPayloads();
    fetchMock = vi.fn(async () => jsonResponse(EMPTY));
    vi.stubGlobal("fetch", fetchMock);
    scope = effectScope();
});

afterEach(() => {
    scope.stop();
    vi.unstubAllGlobals();
});

describe("useSynthesis", () => {
    it("asks nothing for an empty Selection", async () => {
        const synthesis = scope.run(() => useSynthesis(() => []))!;
        await flushPromises();
        expect(fetchMock).not.toHaveBeenCalled();
        expect(synthesis.status.value).toBe("idle");
    });

    it("asks once per Selection, whatever the order of its keys", async () => {
        const keys = ref(["ch:b:-", "an:a:-"]);
        const synthesis = scope.run(() => useSynthesis(() => keys.value))!;
        await flushPromises();
        keys.value = ["an:a:-", "ch:b:-"];
        await flushPromises();
        expect(fetchMock).toHaveBeenCalledTimes(1);
        expect(asked(0)).toBe("an:a:-,ch:b:-");
        expect(synthesis.status.value).toBe("ready");
        expect(synthesis.data.value).toEqual(EMPTY);
    });

    it("aborts the request of a Selection that changed before its answer", async () => {
        const keys = ref(["an:a:-"]);
        fetchMock.mockImplementationOnce(
            (_url: string, init: RequestInit) =>
                new Promise<Response>((_resolve, reject) =>
                    init.signal?.addEventListener("abort", () =>
                        reject(new DOMException("aborted", "AbortError")),
                    ),
                ),
        );
        scope.run(() => useSynthesis(() => keys.value));
        await flushPromises();
        const first = fetchMock.mock.calls[0][1] as RequestInit;
        keys.value = ["an:a:-", "an:c:-"];
        await flushPromises();
        expect(first.signal?.aborted).toBe(true);
        expect(asked(1)).toBe("an:a:-,an:c:-");
    });

    it("takes the synthesis the tab already holds without a request", async () => {
        const first = scope.run(() => useSynthesis(() => ["an:a:-"]))!;
        await flushPromises();
        const again = scope.run(() => useSynthesis(() => ["an:a:-"]))!;
        expect(again.status.value).toBe("ready");
        expect(first.data.value).toEqual(again.data.value);
        expect(fetchMock).toHaveBeenCalledTimes(1);
    });

    it("says a failure, and asks the server again on retry", async () => {
        fetchMock.mockImplementationOnce(async () =>
            jsonResponse({ error: "down" }, 500),
        );
        const synthesis = scope.run(() => useSynthesis(() => ["an:a:-"]))!;
        await flushPromises();
        expect(synthesis.status.value).toBe("error");
        synthesis.retry();
        await flushPromises();
        expect(synthesis.status.value).toBe("ready");
        expect(fetchMock).toHaveBeenCalledTimes(2);
    });

    it("says unavailable when nothing in the Selection is visible", async () => {
        fetchMock.mockImplementationOnce(async () => jsonResponse(null, 404));
        const synthesis = scope.run(() => useSynthesis(() => ["an:a:-"]))!;
        await flushPromises();
        expect(synthesis.status.value).toBe("unavailable");
    });
});
