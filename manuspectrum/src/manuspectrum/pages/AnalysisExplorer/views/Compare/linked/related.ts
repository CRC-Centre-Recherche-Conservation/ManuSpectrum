import { isRecordNode } from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/linked/node-id.ts";

import type { LinkedGraph } from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/linked/graph.ts";
import type { NodeId } from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/linked/node-id.ts";

/** How a node is linked to the selection: selected itself, linked directly, or through one evidence hop. */
export type RelationLevel = "self" | "direct" | "evidence";

const RANK: Record<RelationLevel, number> = {
    self: 3,
    direct: 2,
    evidence: 1,
};

function mark(
    levels: Map<NodeId, RelationLevel>,
    id: NodeId,
    level: RelationLevel,
): void {
    const current = levels.get(id);
    if (!current || RANK[level] > RANK[current]) levels.set(id, level);
}

/**
 * What the selection links, as the union over its nodes at the strongest
 * level. For one node: its records R0 (itself when it is a record, else
 * the records around it) and their surroundings are `direct`; the records
 * one evidence hop from R0 and their surroundings are `evidence`; the node
 * is `self`. Nothing is followed further. A node the graph does not hold
 * links nothing.
 */
export function related(
    graph: LinkedGraph,
    selection: Iterable<NodeId>,
): Map<NodeId, RelationLevel> {
    const levels = new Map<NodeId, RelationLevel>();
    for (const selected of selection) {
        if (!graph.nodes.has(selected)) continue;
        mark(levels, selected, "self");
        const records = isRecordNode(selected)
            ? [selected]
            : [...(graph.around.get(selected) ?? [])].filter(isRecordNode);
        const firstHop = new Set(records);
        const secondHop = new Set<NodeId>();
        for (const record of records) {
            for (const cited of graph.evidence.get(record) ?? []) {
                if (!firstHop.has(cited)) secondHop.add(cited);
            }
        }
        for (const record of firstHop) {
            mark(levels, record, "direct");
            for (const id of graph.around.get(record) ?? []) {
                mark(levels, id, "direct");
            }
        }
        for (const record of secondHop) {
            mark(levels, record, "evidence");
            for (const id of graph.around.get(record) ?? []) {
                mark(levels, id, "evidence");
            }
        }
    }
    return levels;
}
