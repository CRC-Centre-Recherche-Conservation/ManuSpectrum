import { describe, expect, it } from "vitest";

import { useVocabulary } from "@/manuspectrum/pages/AnalysisExplorer/composables/useVocabulary.ts";
import fr from "../../../../../locale/fr.json";

const catalogue = fr.fr as unknown as Record<string, string>;

describe("useVocabulary", () => {
    it("names the studied component, never the part or the area", () => {
        const { groupTitle, facetTitle, filterTitle } = useVocabulary();
        expect(groupTitle("part")).toBe("Studied component");
        expect(facetTitle("part")).toBe("Component");
        expect(filterTitle("part")).toBe("Studied component");
    });

    it("calls the year facet the analysis year", () => {
        expect(useVocabulary().facetTitle("year")).toBe("Analysis year");
    });

    it("explains the colour levels in terms of components and zones", () => {
        const { levelHint } = useVocabulary();
        expect(levelHint("partColour")).toBe(
            "Colours described on the studied component, even without analysis",
        );
        expect(levelHint("colour")).toBe(
            "Colour of the zone where a material was identified from the analyses",
        );
    });

    it("carries the French wording in the compiled catalogue", () => {
        expect(catalogue["Studied component"]).toBe("Composant étudié");
        expect(catalogue["Component"]).toBe("Composant");
        expect(catalogue["Analysis year"]).toBe("Année d'analyse");
        expect(catalogue["Zone of the observed component."]).toBe(
            "Zone du composant observé.",
        );
        expect(
            catalogue[
                "Colours described on the studied component, even without analysis"
            ],
        ).toBe("Couleurs décrites sur le composant étudié, même sans analyse");
    });
});
