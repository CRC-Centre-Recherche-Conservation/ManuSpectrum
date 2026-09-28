/**
 * The things of Compare a reader can select and see linked, one id each:
 * `<kind>:<part>|<part>…`, every part URI-encoded (a missing part is
 * empty). Records are the analyses (`an:`) and the identified materials
 * (`ch:`); everything else surrounds them.
 */
export const NODE_KINDS = [
    "an",
    "ch",
    "file",
    "layer",
    "tech",
    "cv",
    "doc",
    "comp",
    "mv",
    "co",
    "el",
    "pair",
    "cell",
    "slot",
] as const;

export type NodeKind = (typeof NODE_KINDS)[number];
export type NodeId = string;

export interface ParsedNode {
    kind: NodeKind;
    parts: (string | null)[];
}

const PART_SEPARATOR = "|";
const RECORD_KINDS: ReadonlySet<NodeKind> = new Set(["an", "ch"]);

export function nodeId(
    kind: NodeKind,
    ...parts: readonly (string | number | null)[]
): NodeId {
    const encoded = parts.map((part) =>
        part === null ? "" : encodeURIComponent(String(part)),
    );
    return `${kind}:${encoded.join(PART_SEPARATOR)}`;
}

/** The kind and parts of `id`; null for a kind it does not know or a part that is not URI-encoded. */
export function parseNodeId(id: string): ParsedNode | null {
    const colon = id.indexOf(":");
    if (colon < 0) return null;
    const kind = NODE_KINDS.find((known) => known === id.slice(0, colon));
    if (!kind) return null;
    try {
        const parts = id
            .slice(colon + 1)
            .split(PART_SEPARATOR)
            .map((part) => (part === "" ? null : decodeURIComponent(part)));
        return { kind, parts };
    } catch {
        return null;
    }
}

export function kindOfNode(id: string): NodeKind | null {
    return parseNodeId(id)?.kind ?? null;
}

export function isRecordNode(id: string): boolean {
    const kind = kindOfNode(id);
    return kind !== null && RECORD_KINDS.has(kind);
}

export function analysisNode(id: string): NodeId {
    return nodeId("an", id);
}

export function materialNode(id: string): NodeId {
    return nodeId("ch", id);
}

export function fileNode(id: string): NodeId {
    return nodeId("file", id);
}

export function layerNode(fileId: string, index: number): NodeId {
    return nodeId("layer", fileId, index);
}

export function techniqueNode(id: string): NodeId {
    return nodeId("tech", id);
}

export function canvasNode(id: string): NodeId {
    return nodeId("cv", id);
}

export function documentNode(id: string): NodeId {
    return nodeId("doc", id);
}

export function componentNode(id: string): NodeId {
    return nodeId("comp", id);
}

/** A material value (the thesaurus concept), not an identified material. */
export function materialValueNode(id: string): NodeId {
    return nodeId("mv", id);
}

export function colourNode(id: string): NodeId {
    return nodeId("co", id);
}

export function elementNode(symbol: string): NodeId {
    return nodeId("el", symbol);
}

/** A colour × material pair of the synthesis; `colour` null when none is stated. */
export function pairNode(colour: string | null, material: string): NodeId {
    return nodeId("pair", colour, material);
}

/** A cell of the coverage matrix: a canvas and a technique id. */
export function cellNode(canvas: string, technique: string): NodeId {
    return nodeId("cell", canvas, technique);
}

/** A slot of the Selection, 0-based (A1 is 0). */
export function slotNode(slot: number): NodeId {
    return nodeId("slot", slot);
}
