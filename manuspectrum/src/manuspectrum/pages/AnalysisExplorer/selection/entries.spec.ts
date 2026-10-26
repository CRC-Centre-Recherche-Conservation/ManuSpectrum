import { describe, expect, it } from "vitest";

import {
    analysisKey,
    characterizationKey,
    fileKey,
} from "@/manuspectrum/pages/AnalysisExplorer/selection/entries.ts";
import { uuid } from "@/manuspectrum/pages/AnalysisExplorer/testing/fixtures.ts";

describe("Selection keys", () => {
    it("enters a whole analysis by its own key", () => {
        expect(analysisKey(uuid(1).toUpperCase())).toBe(`an:${uuid(1)}:-`);
    });

    it("writes the file and material key shapes", () => {
        expect(fileKey(uuid(1), uuid(2))).toBe(`af:${uuid(1)}:${uuid(2)}`);
        expect(characterizationKey(uuid(1))).toBe(`ch:${uuid(1)}:-`);
    });
});
