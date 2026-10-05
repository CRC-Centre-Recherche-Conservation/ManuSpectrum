import { describe, expect, it } from "vitest";

import {
    AN1,
    AN2,
    BASKET,
    BY_KEY,
    C1,
    C2,
    CH1,
    D1,
    SYNTHESIS,
} from "@/manuspectrum/pages/AnalysisExplorer/testing/linked.ts";
import { uuid } from "@/manuspectrum/pages/AnalysisExplorer/testing/fixtures.ts";
import { documentTargets } from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/linked/document-targets.ts";
import { buildGraph } from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/linked/graph.ts";
import {
    analysisNode,
    elementNode,
    materialNode,
} from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/linked/node-id.ts";
import { related } from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/linked/related.ts";

const GRAPH = buildGraph({
    basket: BASKET,
    byKey: BY_KEY,
    synthesis: SYNTHESIS,
});

function targetsOf(selection: string[], graph = GRAPH) {
    return documentTargets(graph, related(graph, new Set(selection)));
}

describe("documentTargets", () => {
    it("opens the document of a selected record on its first folio, focused on it", () => {
        expect(targetsOf([analysisNode(AN2)])).toEqual([
            {
                document: D1,
                canvas: C2,
                focus: { kind: "analysis", id: AN2 },
            },
        ]);
        expect(targetsOf([materialNode(CH1)])).toEqual([
            {
                document: D1,
                canvas: C1,
                focus: { kind: "characterization", id: CH1 },
            },
        ]);
    });

    it("opens on the first record directly linked when no record is selected, never on evidence", () => {
        expect(targetsOf([elementNode("Cu")])).toEqual([
            {
                document: D1,
                canvas: C1,
                focus: { kind: "characterization", id: CH1 },
            },
        ]);
        expect(targetsOf([elementNode("Zz")])).toEqual([]);
    });

    it("gives one target per document, selected records first", () => {
        const other = uuid(2);
        const graph = buildGraph({
            basket: BASKET,
            byKey: BY_KEY,
            synthesis: {
                ...SYNTHESIS,
                canvases: [
                    ...SYNTHESIS.canvases,
                    {
                        canvas: "https://iiif.example/other",
                        label: "f. 1",
                        document: other,
                        selected: true,
                        analyses: [],
                        materials: [],
                    },
                ].map((entry) =>
                    entry.document === other
                        ? { ...entry, analyses: [AN1] }
                        : {
                              ...entry,
                              analyses: entry.analyses.filter(
                                  (id) => id !== AN1,
                              ),
                          },
                ),
            },
        });
        expect(
            targetsOf([analysisNode(AN2), analysisNode(AN1)], graph).map(
                (target) => [target.document, target.focus.id],
            ),
        ).toEqual([
            [D1, AN2],
            [other, AN1],
        ]);
    });
});
