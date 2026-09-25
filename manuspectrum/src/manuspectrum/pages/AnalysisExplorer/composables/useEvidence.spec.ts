import { flushPromises } from "@vue/test-utils";
import { afterEach, describe, expect, it, vi } from "vitest";
import { effectScope } from "vue";

import { useEvidence } from "@/manuspectrum/pages/AnalysisExplorer/composables/useEvidence.ts";
import { evidenceEntries } from "@/manuspectrum/pages/AnalysisExplorer/selection/entries.ts";
import {
    analysisPayload,
    fileEntry,
    uuid,
} from "@/manuspectrum/pages/AnalysisExplorer/testing/fixtures.ts";
import { jsonResponse } from "@/manuspectrum/pages/AnalysisExplorer/testing/responses.ts";

vi.mock("@/arches/utils/generate-arches-url.ts", () => ({
    generateArchesURL: (_route: string, params: Record<string, string>) =>
        `/en/api/explorer/analysis/${params.resourceid}`,
}));

afterEach(() => vi.unstubAllGlobals());

describe("evidence of an identified material", () => {
    it("reads every evidence analysis and keys those with data", async () => {
        const withData = analysisPayload({
            id: uuid(101),
            files: [fileEntry({ id: uuid(8) })],
        });
        const without = analysisPayload({ id: uuid(102), files: [] });
        vi.stubGlobal(
            "fetch",
            vi.fn(async (url: string) =>
                jsonResponse(url.endsWith(uuid(101)) ? withData : without),
            ),
        );
        const scope = effectScope();
        const handle = scope.run(() =>
            useEvidence(() => [uuid(101), uuid(102)]),
        )!;
        await flushPromises();

        expect(handle.data.value?.map((a) => a.id)).toEqual([
            uuid(101),
            uuid(102),
        ]);
        expect(evidenceEntries(handle.data.value!)).toEqual({
            keys: [`af:${uuid(101)}:${uuid(8)}`],
            withoutData: [uuid(102)],
        });
        scope.stop();
    });

    it("is in error when one analysis cannot be read", async () => {
        vi.stubGlobal(
            "fetch",
            vi.fn(async () => jsonResponse({}, 503)),
        );
        const scope = effectScope();
        const handle = scope.run(() => useEvidence(() => [uuid(101)]))!;
        await flushPromises();
        expect(handle.status.value).toBe("error");
        scope.stop();
    });

    it("stays idle without evidence", async () => {
        const scope = effectScope();
        const handle = scope.run(() => useEvidence(() => []))!;
        await flushPromises();
        expect(handle.status.value).toBe("idle");
        scope.stop();
    });
});
