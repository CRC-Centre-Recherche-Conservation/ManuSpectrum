import { parseNodeId } from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/linked/node-id.ts";

import type { LinkedGraph } from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/linked/graph.ts";
import type { NodeId } from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/linked/node-id.ts";
import type { RelationLevel } from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/linked/related.ts";

/** A document screen to open: its folio and the record it focuses. */
export interface DocumentTarget {
    document: string;
    canvas: string | null;
    focus: { kind: "analysis" | "characterization"; id: string };
}

const FOCUS_KIND = {
    an: "analysis",
    ch: "characterization",
} as const;

function targetOf(graph: LinkedGraph, id: NodeId): DocumentTarget | null {
    const parsed = parseNodeId(id);
    if (!parsed || (parsed.kind !== "an" && parsed.kind !== "ch")) return null;
    const [recordId] = parsed.parts;
    const place = graph.places.get(id)?.[0];
    if (!recordId || !place) return null;
    return {
        document: place.document,
        canvas: place.canvas,
        focus: { kind: FOCUS_KIND[parsed.kind], id: recordId },
    };
}

/**
 * One document screen per document of the linked records: the selected
 * records first, then those linked directly (never through evidence), in
 * `levels` order; each document opens on the first such record, on its
 * first folio.
 */
export function documentTargets(
    graph: LinkedGraph,
    levels: ReadonlyMap<NodeId, RelationLevel>,
): DocumentTarget[] {
    const entries = [...levels];
    const ordered = [
        ...entries.filter(([, level]) => level === "self"),
        ...entries.filter(([, level]) => level === "direct"),
    ];
    const targets: DocumentTarget[] = [];
    for (const [id] of ordered) {
        const target = targetOf(graph, id);
        if (
            target &&
            !targets.some((entry) => entry.document === target.document)
        ) {
            targets.push(target);
        }
    }
    return targets;
}
