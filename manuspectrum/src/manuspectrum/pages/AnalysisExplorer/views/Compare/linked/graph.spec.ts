import { describe, expect, it } from "vitest";

import {
    AN1,
    AN2,
    BASKET,
    BY_KEY,
    BY_KEY_WITH_COMPONENT,
    C1,
    C2,
    CH1,
    CH2,
    CH3,
    D1,
    F1,
    F2,
    K1,
    SYNTHESIS,
    SYNTHESIS_WITH_COMPONENT,
} from "@/manuspectrum/pages/AnalysisExplorer/testing/linked.ts";
import { buildGraph } from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/linked/graph.ts";
import {
    analysisNode,
    canvasNode,
    cellNode,
    colourNode,
    componentNode,
    documentNode,
    elementNode,
    fileNode,
    layerNode,
    materialNode,
    materialValueNode,
    pairNode,
    slotNode,
    techniqueNode,
} from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/linked/node-id.ts";

function around(graph: ReturnType<typeof buildGraph>, id: string): string[] {
    return [...(graph.around.get(id) ?? [])].sort();
}

describe("buildGraph", () => {
    it("links each analysis of the Selection to its files, layers, elements mapped, technique, document, folio and slot", () => {
        const graph = buildGraph({
            basket: BASKET,
            byKey: BY_KEY,
            synthesis: null,
        });
        expect(around(graph, analysisNode(AN1))).toEqual(
            [
                fileNode(F1),
                fileNode(F2),
                layerNode(F2, 0),
                layerNode(F2, 1),
                elementNode("Fe"),
                elementNode("Pb"),
                techniqueNode("xrf"),
                documentNode(D1),
                canvasNode(C1),
                slotNode(0),
            ].sort(),
        );
        expect(around(graph, elementNode("Fe"))).toEqual([analysisNode(AN1)]);
    });

    it("links an identified material of the Selection to its values, objects, zone and evidence without the synthesis", () => {
        const graph = buildGraph({
            basket: BASKET,
            byKey: BY_KEY,
            synthesis: null,
        });
        const material = materialNode(CH1);
        expect(around(graph, material)).toEqual(
            [
                colourNode(BLUE_ID),
                materialValueNode(AZURITE_ID),
                documentNode(D1),
                canvasNode(C1),
                slotNode(2),
            ].sort(),
        );
        expect([...(graph.evidence.get(material) ?? [])]).toEqual([
            analysisNode(AN1),
        ]);
        expect([...(graph.evidence.get(analysisNode(AN1)) ?? [])]).toEqual([
            material,
        ]);
        expect(graph.nodes.has(elementNode("Cu"))).toBe(false);
        expect(graph.nodes.has(materialNode(CH2))).toBe(false);
    });

    it("adds what the synthesis links: the materials citing the Selection, their elements, pairs, folios and cells", () => {
        const graph = buildGraph({
            basket: BASKET,
            byKey: BY_KEY,
            synthesis: SYNTHESIS,
        });
        expect(around(graph, elementNode("Cu"))).toEqual(
            [materialNode(CH1), materialNode(CH2)].sort(),
        );
        expect(around(graph, pairNode(BLUE_ID, AZURITE_ID))).toEqual(
            [materialNode(CH1), materialNode(CH2)].sort(),
        );
        expect(around(graph, cellNode(C1, null, "xrf"))).toEqual(
            [analysisNode(AN1), materialNode(CH1), materialNode(CH2)].sort(),
        );
        expect(around(graph, cellNode(C2, null, "raman"))).toEqual(
            [analysisNode(AN2), materialNode(CH3)].sort(),
        );
        expect(
            [...(graph.evidence.get(analysisNode(AN1)) ?? [])].sort(),
        ).toEqual([materialNode(CH1), materialNode(CH2)].sort());
        expect(around(graph, materialNode(CH3))).toContain(documentNode(D1));
    });

    it("splits a cell by component: an analysis goes to the cell of its component, a material to the cells of its evidence analyses", () => {
        const graph = buildGraph({
            basket: BASKET,
            byKey: BY_KEY_WITH_COMPONENT,
            synthesis: SYNTHESIS_WITH_COMPONENT,
        });
        expect(around(graph, cellNode(C1, K1, "xrf"))).toEqual(
            [analysisNode(AN1), materialNode(CH1), materialNode(CH2)].sort(),
        );
        expect(graph.nodes.has(cellNode(C1, null, "xrf"))).toBe(false);
        expect(around(graph, cellNode(C2, null, "raman"))).toEqual(
            [analysisNode(AN2), materialNode(CH3)].sort(),
        );
    });

    it("links a component to the analyses observing it and to the materials whose summary names it, never to its cells", () => {
        const graph = buildGraph({
            basket: BASKET,
            byKey: BY_KEY_WITH_COMPONENT,
            synthesis: SYNTHESIS_WITH_COMPONENT,
        });
        expect(around(graph, componentNode(K1))).toEqual(
            [analysisNode(AN1), materialNode(CH3)].sort(),
        );
        expect(graph.labels.get(componentNode(K1))?.value).toBe("Initial T");
        expect(around(graph, materialNode(CH3))).not.toContain(
            documentNode(K1),
        );
    });

    it("places a record on the synthesis canvases first, else where its item says", () => {
        const itemsOnly = buildGraph({
            basket: BASKET,
            byKey: BY_KEY,
            synthesis: null,
        });
        expect(itemsOnly.places.get(analysisNode(AN2))).toEqual([
            { document: D1, canvas: C2 },
        ]);
        const both = buildGraph({
            basket: BASKET,
            byKey: BY_KEY,
            synthesis: {
                ...SYNTHESIS,
                canvases: SYNTHESIS.canvases.map((entry) => ({
                    ...entry,
                    analyses: [AN2],
                })),
            },
        });
        expect(both.places.get(analysisNode(AN2))).toEqual([
            { document: D1, canvas: C1 },
            { document: D1, canvas: C2 },
        ]);
        expect(both.places.get(materialNode(CH2))).toEqual([
            { document: D1, canvas: C1 },
        ]);
    });

    it("reads only the items of the Selection, not those that left it", () => {
        const graph = buildGraph({
            basket: BASKET.slice(1),
            byKey: BY_KEY,
            synthesis: null,
        });
        expect(graph.nodes.has(analysisNode(AN1))).toBe(true);
        expect(graph.nodes.has(fileNode(F1))).toBe(false);
        expect(graph.nodes.has(slotNode(0))).toBe(false);
    });

    it("reads the symbol of each element value the synthesis names with one", () => {
        const graph = buildGraph({
            basket: BASKET,
            byKey: BY_KEY,
            synthesis: SYNTHESIS,
        });
        const copper = SYNTHESIS.pairs[0].elements[0].id;
        expect(graph.symbols.get(copper)).toBe("Cu");
        expect(
            buildGraph({ basket: BASKET, byKey: BY_KEY, synthesis: null })
                .symbols.size,
        ).toBe(0);
    });

    it("is empty for an empty Selection", () => {
        const graph = buildGraph({
            basket: [],
            byKey: BY_KEY,
            synthesis: null,
        });
        expect(graph.nodes.size).toBe(0);
    });
});

const BLUE_ID = "http://example.org/blue";
const AZURITE_ID = "http://example.org/azurite";
