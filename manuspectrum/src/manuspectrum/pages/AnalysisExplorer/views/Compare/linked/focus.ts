import { related } from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/linked/related.ts";

import type { LinkedGraph } from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/linked/graph.ts";
import type { NodeId } from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/linked/node-id.ts";
import type { RelationLevel } from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/linked/related.ts";

/** What the focus lights: what relates to any pinned node, or only what relates to all of them. */
export type FocusMode = "any" | "all";

/** A pinned node and its slot, 1-based. */
export interface PinnedNode {
    id: NodeId;
    slot: number;
}

/** How a node stands to the node of one slot. */
export interface SlotRelation {
    slot: number;
    level: RelationLevel;
}

/** How a node stands to the focus: its strongest level, and its slots (its own first, then in slot order). */
export interface NodeRelations {
    best: RelationLevel;
    slots: readonly SlotRelation[];
}

/** The most nodes the focus holds, each slot with its own hue (`--focus-1` … `--focus-4`). */
export const FOCUS_MAX = 4;

const RANK: Record<RelationLevel, number> = {
    self: 3,
    direct: 2,
    evidence: 1,
};

/** The pinned nodes of `slots` (holes left out), in slot order. */
export function pinnedOf(slots: readonly (NodeId | null)[]): PinnedNode[] {
    return slots.flatMap((id, index) =>
        id === null ? [] : [{ id, slot: index + 1 }],
    );
}

/** The slot a new pin takes: the lowest hole, else the one after the last; null once `FOCUS_MAX` nodes are pinned. */
export function nextFreeSlot(slots: readonly (NodeId | null)[]): number | null {
    const hole = slots.indexOf(null);
    const slot = (hole < 0 ? slots.length : hole) + 1;
    return slot > FOCUS_MAX ? null : slot;
}

/** `slots` with `id` pinned in the lowest free slot; unchanged when the focus is full. */
export function pinInSlots(
    slots: readonly (NodeId | null)[],
    id: NodeId,
): (NodeId | null)[] {
    const next = [...slots];
    const slot = nextFreeSlot(next);
    if (slot !== null) next[slot - 1] = id;
    return next;
}

/** `slots` with the nodes `drop` accepts left as holes, trailing holes trimmed. */
export function unpinFromSlots(
    slots: readonly (NodeId | null)[],
    drop: (id: NodeId) => boolean,
): (NodeId | null)[] {
    const next = slots.map((id) => (id !== null && drop(id) ? null : id));
    while (next.length > 0 && next[next.length - 1] === null) next.pop();
    return next;
}

/**
 * How every node stands to each pinned node (`related` run per slot).
 * Under `all` with two pinned nodes or more, only the nodes related to
 * every pinned node are kept, and each pinned node with its own slot at
 * least (`self`), so it stays shown as pinned.
 */
export function focusRelations(
    graph: LinkedGraph,
    pinned: readonly PinnedNode[],
    mode: FocusMode,
): Map<NodeId, NodeRelations> {
    const collected = new Map<NodeId, SlotRelation[]>();
    for (const { id, slot } of pinned) {
        for (const [node, level] of related(graph, [id])) {
            const entry = collected.get(node) ?? [];
            entry.push({ slot, level });
            collected.set(node, entry);
        }
    }
    const requireAll = mode === "all" && pinned.length > 1;
    const relations = new Map<NodeId, NodeRelations>();
    for (const [node, found] of collected) {
        let slots = found;
        if (requireAll && slots.length < pinned.length) {
            slots = slots.filter(({ level }) => level === "self");
            if (slots.length === 0) continue;
        }
        slots.sort(
            (left, right) =>
                Number(right.level === "self") -
                    Number(left.level === "self") || left.slot - right.slot,
        );
        let best: RelationLevel = slots[0].level;
        for (const { level } of slots) {
            if (RANK[level] > RANK[best]) best = level;
        }
        relations.set(node, { best, slots });
    }
    return relations;
}

/** The strongest relations among `ids`: the best level over them, and the union of their slots (own first, then slot order). */
export function mergeRelations(
    relations: ReadonlyMap<NodeId, NodeRelations>,
    ids: NodeId | readonly NodeId[],
): NodeRelations | null {
    const list = typeof ids === "string" ? [ids] : ids;
    if (list.length === 1) return relations.get(list[0]) ?? null;
    const bySlot = new Map<number, RelationLevel>();
    let best: RelationLevel | null = null;
    for (const id of list) {
        const found = relations.get(id);
        if (!found) continue;
        if (!best || RANK[found.best] > RANK[best]) best = found.best;
        for (const { slot, level } of found.slots) {
            const current = bySlot.get(slot);
            if (!current || RANK[level] > RANK[current])
                bySlot.set(slot, level);
        }
    }
    if (!best) return null;
    const slots = [...bySlot].map(([slot, level]) => ({ slot, level }));
    slots.sort(
        (left, right) =>
            Number(right.level === "self") - Number(left.level === "self") ||
            left.slot - right.slot,
    );
    return { best, slots };
}

/** The ids whose slots under `after` hold a slot they did not hold under `before`. */
export function gainedSlots(
    before: ReadonlyMap<NodeId, NodeRelations>,
    after: ReadonlyMap<NodeId, NodeRelations>,
): Set<NodeId> {
    const gained = new Set<NodeId>();
    for (const [id, relations] of after) {
        const had = new Set(before.get(id)?.slots.map(({ slot }) => slot));
        if (relations.slots.some(({ slot }) => !had.has(slot))) gained.add(id);
    }
    return gained;
}

/** The circled digit ① naming the first slot. */
const CIRCLED_FIRST = 0x2460;

/** A slot as a circled digit (③); a number outside 1 … `FOCUS_MAX` stays plain. */
export function circled(slot: number): string {
    return slot >= 1 && slot <= FOCUS_MAX
        ? String.fromCodePoint(CIRCLED_FIRST + slot - 1)
        : String(slot);
}

/** The CSS colour of a slot (1 … `FOCUS_MAX`). */
export function focusHue(slot: number): string {
    return `var(--focus-${slot})`;
}

/** Equal bands of `hues` along a CSS gradient. */
function bands(hues: readonly string[]): string {
    const count = hues.length;
    return hues
        .map(
            (hue, index) =>
                `${hue} ${((100 * index) / count).toFixed(1)}% ${((100 * (index + 1)) / count).toFixed(1)}%`,
        )
        .join(", ");
}

/** The ring of a toggle: the hue of its one slot, or a conic gradient segmenting several. */
export function focusRing(slots: readonly number[]): string {
    const hues = slots.map(focusHue);
    if (hues.length === 1) return hues[0];
    return `conic-gradient(from -90deg, ${bands(hues)})`;
}

/** A stripe of `hues` in equal bands along `direction`. */
export function focusStripe(
    hues: readonly string[],
    direction = "90deg",
): string {
    if (hues.length === 1) return `linear-gradient(${hues[0]}, ${hues[0]})`;
    return `linear-gradient(${direction}, ${bands(hues)})`;
}

/** A rim of slots in bands as wide as each slot's count. */
export function focusRim(counts: ReadonlyMap<number, number>): string {
    const slots = [...counts.keys()].sort((left, right) => left - right);
    const total = [...counts.values()].reduce((sum, count) => sum + count, 0);
    if (slots.length === 0 || total === 0) return "";
    let start = 0;
    const stops = slots.map((slot) => {
        const from = start;
        start += (counts.get(slot) ?? 0) / total;
        return `${focusHue(slot)} ${(from * 100).toFixed(1)}% ${(start * 100).toFixed(1)}%`;
    });
    return `linear-gradient(90deg, ${stops.join(", ")})`;
}
