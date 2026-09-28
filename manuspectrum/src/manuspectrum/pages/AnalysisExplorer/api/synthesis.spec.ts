import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
    forgetPayloads,
    UnavailableError,
} from "@/manuspectrum/pages/AnalysisExplorer/api/http.ts";
import {
    getSynthesis,
    peekSynthesis,
    synthesisQuery,
} from "@/manuspectrum/pages/AnalysisExplorer/api/synthesis.ts";
import { jsonResponse } from "@/manuspectrum/pages/AnalysisExplorer/testing/responses.ts";

import type { SynthesisResponse } from "@/manuspectrum/pages/AnalysisExplorer/api/types.ts";

vi.mock("@/arches/utils/generate-arches-url.ts", () => ({
    generateArchesURL: (name: string) => `/en/${name}`,
}));

const EMPTY: SynthesisResponse = {
    coverage: [],
    canvases: [],
    techniques: [],
    pairs: [],
    elements: [],
    unpublishedCount: 0,
};
const fetchMock = vi.fn();

beforeEach(() => {
    forgetPayloads();
    fetchMock.mockReset();
    fetchMock.mockImplementation(async () => jsonResponse(EMPTY));
    vi.stubGlobal("fetch", fetchMock);
});

afterEach(() => vi.unstubAllGlobals());

describe("synthesis API", () => {
    it("names one Selection by its unique keys, sorted", () => {
        expect(synthesisQuery(["ch:b:-", "an:a:-", "ch:b:-"]).toString()).toBe(
            "ids=an%3Aa%3A-%2Cch%3Ab%3A-",
        );
    });

    it("asks the synthesis route once per Selection whatever the key order", async () => {
        await getSynthesis(["ch:b:-", "an:a:-"]);
        await getSynthesis(["an:a:-", "ch:b:-"]);

        expect(fetchMock).toHaveBeenCalledTimes(1);
        expect(String(fetchMock.mock.calls[0][0])).toBe(
            "/en/manuspectrum:explorer-synthesis?ids=an%3Aa%3A-%2Cch%3Ab%3A-",
        );
        expect(peekSynthesis(["an:a:-", "ch:b:-"])).toEqual(EMPTY);
    });

    it("rejects with UnavailableError when nothing in the Selection is visible", async () => {
        fetchMock.mockImplementation(async () => jsonResponse(null, 404));

        await expect(getSynthesis(["an:a:-"])).rejects.toBeInstanceOf(
            UnavailableError,
        );
    });
});
