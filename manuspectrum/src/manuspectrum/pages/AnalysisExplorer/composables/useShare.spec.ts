import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { effectScope } from "vue";
import { flushPromises } from "@vue/test-utils";

import { forgetPayloads } from "@/manuspectrum/pages/AnalysisExplorer/api/http.ts";
import { useShare } from "@/manuspectrum/pages/AnalysisExplorer/composables/useShare.ts";
import {
    sharePayload,
    uuid,
} from "@/manuspectrum/pages/AnalysisExplorer/testing/fixtures.ts";
import { jsonResponse } from "@/manuspectrum/pages/AnalysisExplorer/testing/responses.ts";

import type { OfferedScope } from "@/manuspectrum/pages/AnalysisExplorer/share/scope.ts";

vi.mock("@/arches/utils/generate-arches-url.ts", () => ({
    generateArchesURL: (name: string) => `/en/${name}`,
}));

const fetchMock = vi.fn();
const DOCUMENT: OfferedScope = { kind: "document", id: uuid(1) };

beforeEach(() => {
    forgetPayloads();
    fetchMock.mockReset();
    fetchMock.mockImplementation(async () => jsonResponse(sharePayload()));
    vi.stubGlobal("fetch", fetchMock);
});

afterEach(() => vi.unstubAllGlobals());

function askedUrls(): string[] {
    return fetchMock.mock.calls.map((call) => String(call[0]));
}

describe("useShare", () => {
    it("asks the share route with the scope query", async () => {
        const scope = effectScope();
        const handle = scope.run(() => useShare(() => DOCUMENT));
        await flushPromises();

        expect(askedUrls()).toEqual([
            `/en/manuspectrum:explorer-share?document=${uuid(1)}`,
        ]);
        expect(handle?.status.value).toBe("ready");
        expect(handle?.data.value?.scope.kind).toBe("document");
        scope.stop();
    });

    it("does not ask without a scope", async () => {
        const scope = effectScope();
        const handle = scope.run(() => useShare(() => null));
        await flushPromises();

        expect(fetchMock).not.toHaveBeenCalled();
        expect(handle?.status.value).toBe("idle");
        scope.stop();
    });

    it("shares one request between two callers", async () => {
        const scope = effectScope();
        const [first, second] = scope.run(() => [
            useShare(() => DOCUMENT),
            useShare(() => DOCUMENT),
        ]) ?? [null, null];
        await flushPromises();

        expect(fetchMock).toHaveBeenCalledTimes(1);
        expect(first?.data.value).toEqual(second?.data.value);
        scope.stop();
    });
});
