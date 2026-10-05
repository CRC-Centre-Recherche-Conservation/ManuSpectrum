import { describe, expect, it } from "vitest";

import { swatchOf } from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/colour-swatches.ts";

const INHA = "https://thesaurus.inha.fr/thesaurus/resource/ark:/54721/";

describe("swatchOf", () => {
    it("gives the colour of a concept of the colour list by its URI", () => {
        expect(swatchOf(`${INHA}d549884f-ed29-4a28-87c8-07311d9a14ad`)).toBe(
            "#2f55a4",
        );
    });

    it("draws the metallic colours as gradients", () => {
        expect(swatchOf(`${INHA}c1e1850f-9eb1-48f4-b8b8-6154a3a1623c`)).toMatch(
            /^linear-gradient\(/,
        );
    });

    it("gives nothing for a concept outside the list, nor for its bare id", () => {
        expect(swatchOf("http://example.org/ochre")).toBeNull();
        expect(swatchOf("d549884f-ed29-4a28-87c8-07311d9a14ad")).toBeNull();
    });
});
