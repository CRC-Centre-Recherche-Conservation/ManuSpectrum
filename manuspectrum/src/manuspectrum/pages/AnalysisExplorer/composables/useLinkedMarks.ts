import { computed, inject, onScopeDispose } from "vue";

import { LINKED_SELECTION_KEY } from "@/manuspectrum/pages/AnalysisExplorer/injection-keys.ts";
import { useExplorerStore } from "@/manuspectrum/pages/AnalysisExplorer/store/explorer.ts";
import {
    focusHue,
    focusRing,
    focusStripe,
    mergeRelations,
} from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/linked/focus.ts";

import type { ComputedRef } from "vue";

import type {
    LinkedSelection,
    PreviewEvent,
} from "@/manuspectrum/pages/AnalysisExplorer/composables/useLinkedSelection.ts";
import type {
    NodeRelations,
    SlotRelation,
} from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/linked/focus.ts";
import type { NodeId } from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/linked/node-id.ts";
import type { RelationLevel } from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/linked/related.ts";

/** How a thing shown stands to the selection: linked at a level, or not linked (`none`). */
export type LinkedMark = RelationLevel | "none";

const RANK: Record<RelationLevel, number> = {
    self: 3,
    direct: 2,
    evidence: 1,
};

/**
 * The attributes of a focus toggle (`v-bind` them on an element carrying
 * the class `ms-focus`, which draws the ring, the bloom, the preview ghost
 * ring and the pip of `FocusPip`):
 * - `data-node`: the ids the element stands for, space-separated (a
 *   window counts each once);
 * - `data-rel`: its strongest level while something is pinned, `none`
 *   when unlinked;
 * - `data-slots`: the slots it relates to, space-separated;
 * - `data-preview`: its level under the node previewed, when that node is
 *   not pinned;
 * - `data-bloom`: `odd` or `even` (the parity of the change) while it just
 *   gained a slot, so two blooms in a row restart the animation;
 * - `style`: `--ring` (the slot hue, or a conic gradient of several),
 *   `--h1` (its first slot's hue) and `--hp` (the hue of the slot the node
 *   previewed would take).
 */
export interface FocusAttributes {
    "data-node": string;
    "data-rel": LinkedMark | undefined;
    "data-slots": string | undefined;
    "data-preview": RelationLevel | undefined;
    "data-bloom": "odd" | "even" | undefined;
    style: Record<string, string> | undefined;
}

export interface LinkedMarks {
    /** The linked selection of the Compare view, null outside one. */
    linked: LinkedSelection | null;
    /** Whether anything is selected. */
    active: ComputedRef<boolean>;
    /** The `data-rel` of a thing standing for `ids`: its strongest level, `none` when not linked; undefined while nothing is selected. */
    rel: (ids: NodeId | readonly NodeId[]) => LinkedMark | undefined;
    /** The `data-preview` of a thing standing for `ids`: its strongest level under the node previewed; undefined when not linked, without a preview, or while the node previewed is selected. */
    previewRel: (ids: NodeId | readonly NodeId[]) => RelationLevel | undefined;
    /** The `aria-pressed` of the toggle of `id`. */
    pressed: (id: NodeId) => "true" | "false";
    /** How a thing standing for `ids` stands to the focus (slots merged); null when unlinked or nothing is pinned. */
    relations: (ids: NodeId | readonly NodeId[]) => NodeRelations | null;
    /** The digits of a thing's pip: its slots, its own first. */
    slots: (ids: NodeId | readonly NodeId[]) => readonly SlotRelation[];
    /** The hue of a thing's first slot (`var(--focus-n)`); null when it relates to no slot. */
    hue: (ids: NodeId | readonly NodeId[]) => string | null;
    /** Whether a thing just gained a slot (its bloom). */
    blooms: (ids: NodeId | readonly NodeId[]) => boolean;
    /** Every focus attribute of a toggle standing for `ids` (see `FocusAttributes`). */
    focus: (ids: NodeId | readonly NodeId[]) => FocusAttributes;
    /** The custom properties of a row standing for `ids`: `--h1` (its tint), `--bar` (its slots top to bottom) and `--hp`; undefined when it has none. */
    rowStyle: (
        ids: NodeId | readonly NodeId[],
    ) => Record<string, string> | undefined;
    /** Adds `id` to the selection or removes it. */
    toggle: (id: NodeId) => void;
    /** Starts previewing `id` under a mouse or pen (`pointerenter`); the event's `currentTarget` anchors the trail. */
    enter: (id: NodeId, event: PreviewEvent) => void;
    /** Ends the preview (`pointerleave`). */
    leave: (event: Pick<PointerEvent, "pointerType">) => void;
}

function strongest(
    levels: ReadonlyMap<NodeId, RelationLevel>,
    ids: NodeId | readonly NodeId[],
): RelationLevel | undefined {
    let best: RelationLevel | undefined;
    for (const id of typeof ids === "string" ? [ids] : ids) {
        const level = levels.get(id);
        if (level && (!best || RANK[level] > RANK[best])) best = level;
    }
    return best;
}

/**
 * What a Compare window needs to show the focus (`LINKED_SELECTION_KEY`):
 * the level of each thing it shows, as `data-rel` while something is
 * pinned and as `data-preview` while a node is previewed, its slots and
 * their hues, whether it just gained a slot (`focus` gathers them all),
 * the pressed state of its toggles, and the toggle and preview actions. Outside a Compare view nothing is marked and a toggle
 * goes to the store. A preview started here and not ended by `leave` ends
 * when the component goes.
 */
export function useLinkedMarks(): LinkedMarks {
    const linked = inject(LINKED_SELECTION_KEY, null);
    /** Whether a preview started here is not ended yet. */
    let previewing = false;

    const active = computed(() => (linked?.selection.value.length ?? 0) > 0);

    function rel(ids: NodeId | readonly NodeId[]): LinkedMark | undefined {
        if (!linked || !active.value) return undefined;
        return strongest(linked.levels.value, ids) ?? "none";
    }

    function previewRel(
        ids: NodeId | readonly NodeId[],
    ): RelationLevel | undefined {
        const previewed = linked?.previewing.value ?? null;
        if (!linked || previewed === null) return undefined;
        if (linked.selection.value.includes(previewed)) return undefined;
        return strongest(linked.previewLevels.value, ids);
    }

    function relations(ids: NodeId | readonly NodeId[]): NodeRelations | null {
        if (!linked || !active.value) return null;
        return mergeRelations(linked.relations.value, ids);
    }

    function slots(ids: NodeId | readonly NodeId[]): readonly SlotRelation[] {
        return relations(ids)?.slots ?? [];
    }

    function hue(ids: NodeId | readonly NodeId[]): string | null {
        const first = slots(ids)[0];
        return first ? focusHue(first.slot) : null;
    }

    function blooms(ids: NodeId | readonly NodeId[]): boolean {
        const nodes = linked?.cue.value.nodes;
        if (!nodes || nodes.size === 0) return false;
        return (typeof ids === "string" ? [ids] : ids).some((id) =>
            nodes.has(id),
        );
    }

    function focus(ids: NodeId | readonly NodeId[]): FocusAttributes {
        const list = typeof ids === "string" ? [ids] : ids;
        const found = relations(list);
        const numbers = found?.slots.map(({ slot }) => slot) ?? [];
        const previewed = previewRel(list);
        const previewSlot = linked?.previewSlot.value ?? null;
        const style: Record<string, string> = {};
        if (numbers.length > 0) {
            style["--ring"] = focusRing(numbers);
            style["--h1"] = focusHue(numbers[0]);
        }
        if (previewed && previewSlot !== null) {
            style["--hp"] = focusHue(previewSlot);
        }
        const generation = linked?.cue.value.generation ?? 0;
        return {
            "data-node": list.join(" "),
            "data-rel": rel(list),
            "data-slots": numbers.length > 0 ? numbers.join(" ") : undefined,
            "data-preview": previewed,
            "data-bloom": blooms(list)
                ? generation % 2 === 0
                    ? "even"
                    : "odd"
                : undefined,
            style: Object.keys(style).length > 0 ? style : undefined,
        };
    }

    function rowStyle(
        ids: NodeId | readonly NodeId[],
    ): Record<string, string> | undefined {
        const hues = slots(ids).map(({ slot }) => focusHue(slot));
        const previewSlot = linked?.previewSlot.value ?? null;
        const style: Record<string, string> = {};
        if (hues.length > 0) {
            style["--h1"] = hues[0];
            style["--bar"] = focusStripe(hues, "180deg");
        }
        if (previewSlot !== null && previewRel(ids)) {
            style["--hp"] = focusHue(previewSlot);
        }
        return Object.keys(style).length > 0 ? style : undefined;
    }

    function pressed(id: NodeId): "true" | "false" {
        const selected = linked
            ? linked.selection.value
            : useExplorerStore().compare.selection;
        return selected.includes(id) ? "true" : "false";
    }

    function toggle(id: NodeId): void {
        if (linked) linked.toggle(id);
        else useExplorerStore().toggleSelection(id);
    }

    function enter(id: NodeId, event: PreviewEvent): void {
        linked?.preview(id, event);
        previewing = true;
    }

    function leave(event: Pick<PointerEvent, "pointerType">): void {
        linked?.preview(null, event);
        previewing = false;
    }

    onScopeDispose(() => {
        if (previewing) linked?.preview(null);
    });

    return {
        linked,
        active,
        rel,
        previewRel,
        relations,
        slots,
        hue,
        blooms,
        focus,
        rowStyle,
        pressed,
        toggle,
        enter,
        leave,
    };
}
