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

    it("carries the French wording in the compiled catalogue", () => {
        expect(catalogue["Studied component"]).toBe("Composant étudié");
        expect(catalogue["Component"]).toBe("Composant");
        expect(catalogue["Analysis year"]).toBe("Année d'analyse");
        expect(catalogue["Zone of the observed component."]).toBe(
            "Zone du composant observé.",
        );
    });
});
