import { describe, expect, it } from "vitest";

import { foldText } from "@/manuspectrum/pages/AnalysisExplorer/format.ts";
import { colourSwatch } from "@/manuspectrum/pages/AnalysisExplorer/views/Corpus/components/facet-swatches.ts";

describe("foldText", () => {
    it("drops accents and case", () => {
        expect(foldText("Orangé ÉTAIN")).toBe("orange etain");
    });
});

describe("colourSwatch", () => {
    it("names a display colour for a colour word in English or French", () => {
        expect(colourSwatch("Bleu")).toBe(colourSwatch("blue"));
        expect(colourSwatch("Rouge")).toBe(colourSwatch("red"));
        expect(colourSwatch("Doré")).toBe(colourSwatch("gold"));
        expect(colourSwatch("orangé")).toBe(colourSwatch("Orange"));
        expect(colourSwatch("Blanc")).not.toBeNull();
    });

    it("reads the first colour word of a longer label", () => {
        expect(colourSwatch("Vert-de-gris")).toBe(colourSwatch("vert"));
        expect(colourSwatch("bleu clair")).toBe(colourSwatch("blue"));
    });

    it("gives no colour to an unknown name", () => {
        expect(colourSwatch("Polychrome")).toBeNull();
        expect(colourSwatch("")).toBeNull();
    });
});
