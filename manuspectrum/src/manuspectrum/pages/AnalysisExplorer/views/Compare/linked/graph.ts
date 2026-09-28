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

import type {
    AnalysisHit,
    CharacterizationSummary,
    FileEntry,
    Item,
    Label,
    Ref,
    SynthesisResponse,
} from "@/manuspectrum/pages/AnalysisExplorer/api/types.ts";
import type { BasketItem } from "@/manuspectrum/pages/AnalysisExplorer/store/types.ts";
import type { NodeId } from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/linked/node-id.ts";

/** A page a record is placed on: the document whose manifest lists it, the canvas when known. */
export interface NodePlace {
    document: string;
    canvas: string | null;
}

/**
 * What Compare links, as two kinds of edges. `around` joins each record
 * (analysis, identified material) to the things surrounding it (files,
 * layers, elements, technique, folios, document, values, pairs, cells,
 * slots) and each of those back to its records; `evidence` joins an
 * identified material to the analyses it cites. Records are never joined
 * to one another through `around`, nor surroundings to surroundings.
 */
export interface LinkedGraph {
    nodes: ReadonlySet<NodeId>;
    around: ReadonlyMap<NodeId, ReadonlySet<NodeId>>;
    evidence: ReadonlyMap<NodeId, ReadonlySet<NodeId>>;
    /** Names given by the payloads; `nodeLabel` composes the others. */
    labels: ReadonlyMap<NodeId, Label>;
    /** Where each record is placed, in document then page order. */
    places: ReadonlyMap<NodeId, readonly NodePlace[]>;
}

export interface GraphInput {
    basket: readonly BasketItem[];
    byKey: ReadonlyMap<string, Item>;
    synthesis: SynthesisResponse | null;
}

class GraphBuilder {
    readonly nodes = new Set<NodeId>();
    readonly around = new Map<NodeId, Set<NodeId>>();
    readonly evidence = new Map<NodeId, Set<NodeId>>();
    readonly labels = new Map<NodeId, Label>();
    /** Names used only when no payload names the node. */
    readonly fallbackLabels = new Map<NodeId, Label>();
    readonly places = new Map<NodeId, NodePlace[]>();
    readonly itemPlaces = new Map<NodeId, NodePlace[]>();
    readonly techniqueOf = new Map<string, string>();
    readonly components = new Set<string>();

    add(id: NodeId, name?: Label | null): NodeId {
        this.nodes.add(id);
        if (name && !this.labels.has(id)) this.labels.set(id, name);
        return id;
    }

    link(record: NodeId, other: NodeId, name?: Label | null): void {
        this.add(record);
        this.add(other, name);
        edge(this.around, record, other);
    }

    cite(analysis: NodeId, material: NodeId): void {
        this.add(analysis);
        this.add(material);
        edge(this.evidence, analysis, material);
    }

    place(
        into: Map<NodeId, NodePlace[]>,
        record: NodeId,
        where: NodePlace,
    ): void {
        const list = into.get(record) ?? [];
        if (
            !list.some(
                (entry) =>
                    entry.document === where.document &&
                    entry.canvas === where.canvas,
            )
        ) {
            list.push(where);
        }
        into.set(record, list);
    }

    finish(): LinkedGraph {
        for (const [id, name] of this.fallbackLabels) {
            if (!this.labels.has(id)) this.labels.set(id, name);
        }
        const places = new Map<NodeId, readonly NodePlace[]>(this.itemPlaces);
        for (const [id, list] of this.places) places.set(id, list);
        return {
            nodes: this.nodes,
            around: this.around,
            evidence: this.evidence,
            labels: this.labels,
            places,
        };
    }
}

function edge(edges: Map<NodeId, Set<NodeId>>, from: NodeId, to: NodeId): void {
    if (!edges.has(from)) edges.set(from, new Set());
    if (!edges.has(to)) edges.set(to, new Set());
    edges.get(from)!.add(to);
    edges.get(to)!.add(from);
}

function objectNode(object: Ref): NodeId {
    return object.model === "component"
        ? componentNode(object.id)
        : documentNode(object.id);
}

function addAnalysis(builder: GraphBuilder, hit: AnalysisHit): NodeId {
    const record = builder.add(analysisNode(hit.id), hit.name);
    if (hit.technique) {
        builder.techniqueOf.set(hit.id, hit.technique.id);
        builder.link(
            record,
            techniqueNode(hit.technique.id),
            hit.technique.label,
        );
    }
    builder.link(record, documentNode(hit.document.id), hit.document.name);
    if (hit.component) {
        builder.components.add(hit.component.id);
        builder.link(
            record,
            componentNode(hit.component.id),
            hit.component.name,
        );
    }
    if (hit.canvas) builder.link(record, canvasNode(hit.canvas));
    for (const material of hit.materials) {
        builder.link(record, materialValueNode(material.id), material.label);
    }
    builder.place(builder.itemPlaces, record, {
        document: hit.document.id,
        canvas: hit.canvas,
    });
    return record;
}

function addFile(builder: GraphBuilder, record: NodeId, file: FileEntry): void {
    builder.link(record, fileNode(file.id), { value: file.name, lang: "" });
    for (const layer of file.layers) {
        builder.link(record, layerNode(file.id, layer.index), {
            value: layer.label,
            lang: "",
        });
        if (layer.kind === "element" && layer.element) {
            builder.link(record, elementNode(layer.element));
        }
    }
}

function addCharacterization(
    builder: GraphBuilder,
    summary: CharacterizationSummary,
): NodeId {
    const record = builder.add(materialNode(summary.id), summary.name);
    for (const colour of summary.colours) {
        builder.link(record, colourNode(colour.id), colour.label);
    }
    for (const { value } of summary.materials) {
        builder.link(record, materialValueNode(value.id), value.label);
    }
    for (const object of summary.objects) {
        if (object.model === "component") builder.components.add(object.id);
        builder.link(record, objectNode(object), object.name);
    }
    for (const analysis of summary.evidence) {
        builder.add(analysisNode(analysis.id), analysis.name);
        builder.cite(analysisNode(analysis.id), record);
    }
    const canvas = summary.zone?.canvas ?? null;
    if (canvas) builder.link(record, canvasNode(canvas));
    for (const object of summary.objects) {
        if (object.model !== "component") {
            builder.place(builder.itemPlaces, record, {
                document: object.id,
                canvas,
            });
        }
    }
    return record;
}

function addItem(builder: GraphBuilder, item: Item, slot: number): void {
    if (item.kind === "characterization") {
        const record = addCharacterization(builder, item.characterization);
        builder.link(record, slotNode(slot));
        return;
    }
    const record = addAnalysis(builder, item.analysis);
    builder.link(record, slotNode(slot));
    if (item.kind === "analysis") {
        for (const file of item.files) addFile(builder, record, file);
    } else {
        addFile(builder, record, item.file);
    }
}

function addSynthesis(
    builder: GraphBuilder,
    synthesis: SynthesisResponse,
): void {
    for (const technique of synthesis.techniques) {
        builder.add(techniqueNode(technique.id), technique.label);
    }
    for (const entry of synthesis.canvases) {
        const canvas = builder.add(canvasNode(entry.canvas), {
            value: entry.label,
            lang: "",
        });
        const where = { document: entry.document, canvas: entry.canvas };
        for (const id of entry.analyses) {
            const record = analysisNode(id);
            builder.link(record, canvas);
            builder.place(builder.places, record, where);
            const technique = builder.techniqueOf.get(id);
            if (technique) {
                builder.link(record, cellNode(entry.canvas, technique));
            }
        }
        for (const id of entry.materials) {
            builder.link(materialNode(id), canvas);
            builder.place(builder.places, materialNode(id), where);
        }
    }
    for (const pair of synthesis.pairs) {
        const node = pairNode(pair.colour?.id ?? null, pair.material.id);
        for (const id of pair.materials) {
            const record = materialNode(id);
            builder.link(record, node);
            builder.link(
                record,
                materialValueNode(pair.material.id),
                pair.material.label,
            );
            if (pair.colour) {
                builder.link(
                    record,
                    colourNode(pair.colour.id),
                    pair.colour.label,
                );
            }
            if (!builder.fallbackLabels.has(record)) {
                builder.fallbackLabels.set(record, pair.material.label);
            }
        }
    }
    for (const element of synthesis.elements) {
        for (const id of element.materials) {
            builder.link(materialNode(id), elementNode(element.symbol));
        }
    }
    for (const material of synthesis.materials) {
        const record = builder.add(materialNode(material.id));
        for (const id of material.evidence) {
            builder.cite(analysisNode(id), record);
        }
        for (const [canvas, technique] of material.cells) {
            builder.link(record, cellNode(canvas, technique));
        }
        for (const id of material.objects) {
            builder.link(
                record,
                builder.components.has(id)
                    ? componentNode(id)
                    : documentNode(id),
            );
        }
    }
}

/**
 * The links of the Selection's items (read items only, in slot order),
 * then those the synthesis adds when there is one: every canvas of an
 * analysis, the identified materials citing the Selection with their
 * evidence, folios, cells, objects, pairs and elements. A record is placed
 * on the synthesis canvases when it names any, else where its item says.
 */
export function buildGraph({
    basket,
    byKey,
    synthesis,
}: GraphInput): LinkedGraph {
    const builder = new GraphBuilder();
    for (const { key, slot } of basket) {
        const item = byKey.get(key);
        if (item) addItem(builder, item, slot);
    }
    if (synthesis) addSynthesis(builder, synthesis);
    return builder.finish();
}
