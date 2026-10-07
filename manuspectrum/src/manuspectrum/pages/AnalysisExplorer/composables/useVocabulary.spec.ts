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

    it("names the place and the period by what they date and locate", () => {
        const { facetTitle, periodTitle, groupTitle } = useVocabulary();
        expect(facetTitle("place")).toBe("Place of production");
        expect(periodTitle()).toBe("Date of production");
        expect(groupTitle("document")).toBe("Document");
    });

    it("has one Colour title, in the rail and in the active filters", () => {
        const { facetTitle, filterTitle } = useVocabulary();
        expect(facetTitle("colour")).toBe("Colour");
        expect(filterTitle("colour")).toBe("Colour");
    });

    it("names where the colour is recorded, and explains each choice in terms of components and zones", () => {
        const { colourScopeLabel, colourScopeHint } = useVocabulary();
        expect(colourScopeLabel("all")).toBe("Everywhere (default)");
        expect(colourScopeLabel("part")).toBe("Studied component");
        expect(colourScopeLabel("material")).toBe("Identified material");
        expect(colourScopeHint("all")).toBe(
            "Colour of the component or of an identified material",
        );
        expect(colourScopeHint("part")).toBe(
            "Colours described on the studied component, even without analysis",
        );
        expect(colourScopeHint("material")).toBe(
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
