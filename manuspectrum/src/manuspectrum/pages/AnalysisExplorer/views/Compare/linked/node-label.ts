import { slotLabel } from "@/manuspectrum/pages/AnalysisExplorer/store/basket.ts";
import {
    canvasNode,
    colourNode,
    componentNode,
    materialValueNode,
    parseNodeId,
    techniqueNode,
} from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/linked/node-id.ts";

import type { Label } from "@/manuspectrum/pages/AnalysisExplorer/api/types.ts";
import type { LinkedGraph } from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/linked/graph.ts";

const PART_JOINER = " · ";
const COMPONENT_JOINER = " › ";

/**
 * The name of a node: the one a payload gave it; an element by its
 * symbol, a slot by its label (A1…); a pair by its colour (when stated)
 * and material, a cell by its folio, its component when it has one and
 * its technique (« f. 5 › Initial T · XRF »). Null for a node the
 * graph does not hold or cannot name.
 */
export function nodeLabel(graph: LinkedGraph, id: string): Label | null {
    const named = graph.labels.get(id);
    if (named) return named;
    const parsed = parseNodeId(id);
    if (!parsed || !graph.nodes.has(id)) return null;
    const [first, second, third] = parsed.parts;
    switch (parsed.kind) {
        case "el":
            return first ? { value: first, lang: "" } : null;
        case "slot":
            return first ? { value: slotLabel(Number(first)), lang: "" } : null;
        case "pair": {
            const material = second
                ? graph.labels.get(materialValueNode(second))
                : undefined;
            if (!material) return null;
            const colour = first
                ? graph.labels.get(colourNode(first))
                : undefined;
            return colour
                ? {
                      value: `${colour.value}${PART_JOINER}${material.value}`,
                      lang: material.lang,
                  }
                : material;
        }
        case "cell": {
            const canvas = first
                ? graph.labels.get(canvasNode(first))
                : undefined;
            const component = second
                ? graph.labels.get(componentNode(second))
                : undefined;
            const technique = third
                ? graph.labels.get(techniqueNode(third))
                : undefined;
            if (!canvas || !technique || (second && !component)) return null;
            const place = component
                ? `${canvas.value}${COMPONENT_JOINER}${component.value}`
                : canvas.value;
            return {
                value: `${place}${PART_JOINER}${technique.value}`,
                lang: technique.lang,
            };
        }
        default:
            return null;
    }
}
