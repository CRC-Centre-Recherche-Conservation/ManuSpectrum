import { describe, expect, it } from "vitest";

import {
    AN1,
    BASKET,
    BY_KEY,
    C1,
    CH1,
    CH2,
    D1,
    F1,
    F2,
    SYNTHESIS,
} from "@/manuspectrum/pages/AnalysisExplorer/testing/linked.ts";
import { buildGraph } from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/linked/graph.ts";
import {
    analysisNode,
    canvasNode,
    cellNode,
    documentNode,
    elementNode,
    fileNode,
    layerNode,
    materialNode,
    pairNode,
    slotNode,
    techniqueNode,
} from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/linked/node-id.ts";
import { nodeLabel } from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/linked/node-label.ts";

const GRAPH = buildGraph({
    basket: BASKET,
    byKey: BY_KEY,
    synthesis: SYNTHESIS,
});

function text(id: string): string | null {
    return nodeLabel(GRAPH, id)?.value ?? null;
}

describe("nodeLabel", () => {
    it("names records, files, layers and places as the payloads name them", () => {
        expect(text(analysisNode(AN1))).toBe("MS1_f12_XRF_03");
        expect(nodeLabel(GRAPH, materialNode(CH1))).toEqual({
            value: "Blue of the mantle",
            lang: "en",
        });
        expect(text(fileNode(F1))).toBe("F1.csv");
        expect(text(layerNode(F2, 1))).toBe("Pb La");
        expect(text(canvasNode(C1))).toBe("f. 12r");
        expect(text(documentNode(D1))).toBe("Manuscript 1");
        expect(text(techniqueNode("xrf"))).toBe("XRF");
    });

    it("names an identified material outside the Selection by its material", () => {
        expect(text(materialNode(CH2))).toBe("Azurite");
    });

    it("names an element by its symbol, a slot by its label, a pair and a cell by their parts", () => {
        expect(text(elementNode("Cu"))).toBe("Cu");
        expect(text(slotNode(2))).toBe("A3");
        expect(
            text(
                pairNode(
                    "http://example.org/blue",
                    "http://example.org/azurite",
                ),
            ),
        ).toBe("Blue · Azurite");
        expect(text(pairNode(null, "http://example.org/chalk"))).toBe("Chalk");
        expect(text(cellNode(C1, "xrf"))).toBe("f. 12r · XRF");
    });

    it("has no name for a node it does not know", () => {
        expect(nodeLabel(GRAPH, analysisNode("unknown"))).toBeNull();
        expect(nodeLabel(GRAPH, "garbage")).toBeNull();
        expect(nodeLabel(GRAPH, cellNode("nowhere", "xrf"))).toBeNull();
    });
});
