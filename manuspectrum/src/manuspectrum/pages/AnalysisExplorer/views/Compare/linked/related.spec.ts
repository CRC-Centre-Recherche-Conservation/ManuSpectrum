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
    F3,
    K1,
    SYNTHESIS,
    SYNTHESIS_WITH_COMPONENT,
} from "@/manuspectrum/pages/AnalysisExplorer/testing/linked.ts";
import { buildGraph } from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/linked/graph.ts";
import {
    analysisNode,
    canvasNode,
    cellNode,
    componentNode,
    documentNode,
    elementNode,
    fileNode,
    materialNode,
    pairNode,
    slotNode,
    techniqueNode,
} from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/linked/node-id.ts";
import { related } from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/linked/related.ts";

const GRAPH = buildGraph({
    basket: BASKET,
    byKey: BY_KEY,
    synthesis: SYNTHESIS,
});

describe("related", () => {
    it("marks an analysis itself, its surroundings direct, the materials citing it and theirs as evidence", () => {
        const levels = related(GRAPH, new Set([analysisNode(AN1)]));
        expect(levels.get(analysisNode(AN1))).toBe("self");
        for (const id of [
            fileNode(F1),
            fileNode(F2),
            elementNode("Fe"),
            techniqueNode("xrf"),
            canvasNode(C1),
            documentNode(D1),
            slotNode(0),
        ]) {
            expect(levels.get(id)).toBe("direct");
        }
        expect(levels.get(materialNode(CH1))).toBe("evidence");
        expect(levels.get(materialNode(CH2))).toBe("evidence");
        expect(levels.get(elementNode("Cu"))).toBe("evidence");
        expect(levels.get(pairNode(BLUE_ID, AZURITE_ID))).toBe("evidence");
    });

    it("never follows a link beyond one evidence hop", () => {
        const levels = related(GRAPH, new Set([elementNode("Cu")]));
        expect(levels.get(elementNode("Cu"))).toBe("self");
        expect(levels.get(materialNode(CH1))).toBe("direct");
        expect(levels.get(materialNode(CH2))).toBe("direct");
        expect(levels.get(analysisNode(AN1))).toBe("evidence");
        expect(levels.get(fileNode(F1))).toBe("evidence");
        expect(levels.has(analysisNode(AN2))).toBe(false);
        expect(levels.has(fileNode(F3))).toBe(false);
        expect(levels.has(materialNode(CH3))).toBe(false);
        expect(levels.has(elementNode("Ca"))).toBe(false);
        expect(levels.has(canvasNode(C2))).toBe(false);
    });

    it("is the union of what each selected node links, at the strongest level", () => {
        const levels = related(
            GRAPH,
            new Set([elementNode("Cu"), elementNode("Ca")]),
        );
        expect(levels.get(elementNode("Ca"))).toBe("self");
        expect(levels.get(materialNode(CH3))).toBe("direct");
        expect(levels.get(analysisNode(AN2))).toBe("evidence");
        expect(levels.get(analysisNode(AN1))).toBe("evidence");
        const mixed = related(
            GRAPH,
            new Set([analysisNode(AN1), elementNode("Cu")]),
        );
        expect(mixed.get(analysisNode(AN1))).toBe("self");
        expect(mixed.get(materialNode(CH1))).toBe("direct");
        expect(mixed.get(elementNode("Cu"))).toBe("self");
    });

    it("links a coverage cell to its analyses and the materials placed there citing its technique", () => {
        const levels = related(GRAPH, new Set([cellNode(C1, null, "xrf")]));
        expect(levels.get(analysisNode(AN1))).toBe("direct");
        expect(levels.get(materialNode(CH1))).toBe("direct");
        expect(levels.has(analysisNode(AN2))).toBe(false);
    });

    it("lights a component's cells through its records, and a component cell lights its component", () => {
        const graph = buildGraph({
            basket: BASKET,
            byKey: BY_KEY_WITH_COMPONENT,
            synthesis: SYNTHESIS_WITH_COMPONENT,
        });
        const component = related(graph, new Set([componentNode(K1)]));
        expect(component.get(cellNode(C1, K1, "xrf"))).toBe("direct");
        expect(component.get(analysisNode(AN1))).toBe("direct");
        const cell = related(graph, new Set([cellNode(C1, K1, "xrf")]));
        expect(cell.get(componentNode(K1))).toBe("direct");
        expect(cell.has(cellNode(C2, null, "raman"))).toBe(false);
    });

    it("links nothing for a node the graph does not hold", () => {
        expect(related(GRAPH, new Set(["el:Zz"])).size).toBe(0);
        expect(related(GRAPH, new Set(["garbage"])).size).toBe(0);
        const levels = related(GRAPH, new Set(["el:Zz", elementNode("Ca")]));
        expect(levels.get(elementNode("Ca"))).toBe("self");
        expect(levels.has("el:Zz")).toBe(false);
        expect(related(GRAPH, new Set()).size).toBe(0);
    });

    it("links through the items alone when there is no synthesis", () => {
        const graph = buildGraph({
            basket: BASKET,
            byKey: BY_KEY,
            synthesis: null,
        });
        const levels = related(graph, new Set([elementNode("Fe")]));
        expect(levels.get(analysisNode(AN1))).toBe("direct");
        expect(levels.get(materialNode(CH1))).toBe("evidence");
        expect(levels.has(materialNode(CH2))).toBe(false);
        expect(related(graph, new Set([elementNode("Cu")])).size).toBe(0);
    });
});

const BLUE_ID = "http://example.org/blue";
const AZURITE_ID = "http://example.org/azurite";
