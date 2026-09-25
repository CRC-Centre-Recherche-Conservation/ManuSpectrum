import { flushPromises } from "@vue/test-utils";
import { afterEach, describe, expect, it, vi } from "vitest";
import { effectScope } from "vue";

import { useSeriesSet } from "@/manuspectrum/pages/AnalysisExplorer/composables/useSeriesSet.ts";
import { jsonResponse } from "@/manuspectrum/pages/AnalysisExplorer/testing/responses.ts";

const SERIES = {
    x: [1, 2],
    y: [3, 4],
    n_source: 2,
    decimated: false,
    x_reversed: false,
};

afterEach(() => vi.unstubAllGlobals());

function run(urls: string[]) {
    const scope = effectScope();
    const handle = scope.run(() => useSeriesSet(() => urls))!;
    return { handle, stop: () => scope.stop() };
}

describe("useSeriesSet", () => {
    it("asks the quick-view tier of each file on the page's own origin", async () => {
        const fetchMock = vi.fn(async (_url: string) => jsonResponse(SERIES));
        vi.stubGlobal("fetch", fetchMock);
        const { handle, stop } = run([
            "http://192.168.122.250/api/spectrum-preview/a",
            "/api/spectrum-preview/b",
        ]);
        await flushPromises();
        expect(fetchMock.mock.calls.map(([url]) => url)).toEqual([
            "/api/spectrum-preview/a?n=4096",
            "/api/spectrum-preview/b?n=4096",
        ]);
        expect(handle.data.value?.map((r) => r.series?.y)).toEqual([
            [3, 4],
            [3, 4],
        ]);
        stop();
    });

    it("keeps the other files when one fails, and reads a 204 as nothing to draw", async () => {
        vi.stubGlobal(
            "fetch",
            vi.fn(async (url: string) =>
                url.startsWith("/api/spectrum-preview/a?")
                    ? jsonResponse({}, 503)
                    : url.startsWith("/api/spectrum-preview/b?")
                      ? ({
                            ok: true,
                            status: 204,
                            json: async () => ({}),
                        } as Response)
                      : jsonResponse(SERIES),
            ),
        );
        const { handle, stop } = run([
            "/api/spectrum-preview/a",
            "/api/spectrum-preview/b",
            "/api/spectrum-preview/c",
        ]);
        await flushPromises();
        expect(handle.status.value).toBe("ready");
        expect(handle.data.value).toEqual([
            { series: null, failed: true },
            { series: null, failed: false },
            { series: SERIES, failed: false },
        ]);
        stop();
    });

    it("stays idle without a file", async () => {
        const fetchMock = vi.fn();
        vi.stubGlobal("fetch", fetchMock);
        const { handle, stop } = run([]);
        await flushPromises();
        expect(fetchMock).not.toHaveBeenCalled();
        expect(handle.status.value).toBe("idle");
        stop();
    });
});
