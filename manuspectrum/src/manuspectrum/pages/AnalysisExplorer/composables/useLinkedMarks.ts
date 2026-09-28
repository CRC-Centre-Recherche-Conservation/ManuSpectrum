import { computed, inject } from "vue";

import { LINKED_SELECTION_KEY } from "@/manuspectrum/pages/AnalysisExplorer/injection-keys.ts";
import { useExplorerStore } from "@/manuspectrum/pages/AnalysisExplorer/store/explorer.ts";

import type { ComputedRef } from "vue";

import type { LinkedSelection } from "@/manuspectrum/pages/AnalysisExplorer/composables/useLinkedSelection.ts";
import type { NodeId } from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/linked/node-id.ts";
import type { RelationLevel } from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/linked/related.ts";

/** How a thing shown stands to the selection: linked at a level, or not linked (`none`). */
export type LinkedMark = RelationLevel | "none";

const RANK: Record<RelationLevel, number> = {
    self: 3,
    direct: 2,
    evidence: 1,
};

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
    /** Adds `id` to the selection or removes it. */
    toggle: (id: NodeId) => void;
    /** Starts previewing `id` under a mouse or pen (`pointerenter`). */
    enter: (id: NodeId, event: Pick<PointerEvent, "pointerType">) => void;
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
 * What a Compare window needs to show the linked selection
 * (`LINKED_SELECTION_KEY`): the level of each thing it shows, as
 * `data-rel` while something is selected and as `data-preview` while a
 * node is previewed, the pressed state of its toggles, and the toggle and
 * preview actions. Outside a Compare view nothing is marked and a toggle
 * goes to the store.
 */
export function useLinkedMarks(): LinkedMarks {
    const linked = inject(LINKED_SELECTION_KEY, null);

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

    function enter(id: NodeId, event: Pick<PointerEvent, "pointerType">): void {
        linked?.preview(id, event);
    }

    function leave(event: Pick<PointerEvent, "pointerType">): void {
        linked?.preview(null, event);
    }

    return { linked, active, rel, previewRel, pressed, toggle, enter, leave };
}
