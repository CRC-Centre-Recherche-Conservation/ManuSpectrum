import { computed, onScopeDispose, ref, shallowRef, watch } from "vue";
import { useGettext } from "vue3-gettext";

import { useExplorerStore } from "@/manuspectrum/pages/AnalysisExplorer/store/explorer.ts";
import { synthesisFor } from "@/manuspectrum/pages/AnalysisExplorer/composables/useSynthesis.ts";
import { documentTargets } from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/linked/document-targets.ts";
import {
    FOCUS_MAX,
    focusRelations,
    gainedSlots,
    nextFreeSlot,
    pinnedOf,
} from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/linked/focus.ts";
import { buildGraph } from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/linked/graph.ts";
import { isRecordNode } from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/linked/node-id.ts";
import { nodeLabel } from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/linked/node-label.ts";
import { related } from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/linked/related.ts";

import type { ComputedRef, Ref, ShallowRef } from "vue";

import type {
    Label,
    SynthesisResponse,
} from "@/manuspectrum/pages/AnalysisExplorer/api/types.ts";
import type { RequestHandle } from "@/manuspectrum/pages/AnalysisExplorer/composables/useRequest.ts";
import type { SelectionItems } from "@/manuspectrum/pages/AnalysisExplorer/composables/useSelectionItems.ts";
import type { DocumentTarget } from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/linked/document-targets.ts";
import type {
    FocusMode,
    NodeRelations,
    PinnedNode,
} from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/linked/focus.ts";
import type { LinkedGraph } from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/linked/graph.ts";
import type { NodeId } from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/linked/node-id.ts";
import type { RelationLevel } from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/linked/related.ts";

const PREVIEW_ENTER_MS = 80;
const PREVIEW_LEAVE_MS = 120;
const PREVIEW_POINTERS: readonly string[] = ["mouse", "pen"];
/** How long the nodes that gained a slot stay marked for their bloom and their windows' breath (`--breathe-dur`). */
const CUE_MS = 900;
/** An open dialog, menu or popover, or a tooltip shown: Escape belongs to it. A popover's button carries `data-popover`. */
const OPEN_POPUP =
    'dialog[open], [aria-haspopup][aria-expanded="true"], [data-popover][aria-expanded="true"], [role="tooltip"]:not([hidden])';
const EDITABLE = "input, textarea, select, [contenteditable='true']";

export interface LinkedSelectionSources {
    items: SelectionItems;
    synthesis: RequestHandle<SynthesisResponse>;
    announce: (message: string) => void;
}

/** The nodes that just gained a slot; `generation` counts the changes, so a node gaining twice in a row blooms twice. */
export interface FocusCue {
    generation: number;
    nodes: ReadonlySet<NodeId>;
}

/** Where a preview started: the element under the pointer, when known. */
export type PreviewEvent = Pick<PointerEvent, "pointerType"> & {
    currentTarget?: EventTarget | null;
};

export interface LinkedSelection {
    graph: ComputedRef<LinkedGraph>;
    /** The focus by slot (index + 1), holes as null. */
    slots: ComputedRef<readonly (NodeId | null)[]>;
    /** The pinned nodes, in slot order. */
    selection: ComputedRef<readonly NodeId[]>;
    pinned: ComputedRef<readonly PinnedNode[]>;
    mode: ComputedRef<FocusMode>;
    /** How each node lit stands to each slot (`focusRelations`, under the mode). */
    relations: ComputedRef<ReadonlyMap<NodeId, NodeRelations>>;
    /** What the focus lights, at each node's strongest level. */
    levels: ComputedRef<ReadonlyMap<NodeId, RelationLevel>>;
    /** The slot the next pin takes; null while the focus is full (`FOCUS_MAX`). */
    nextSlot: ComputedRef<number | null>;
    /** The node the pointer rests on, once the preview delay has passed. */
    previewing: Readonly<Ref<NodeId | null>>;
    /** The element the preview started on, when the caller gave it. */
    previewAnchor: Readonly<ShallowRef<Element | null>>;
    /** The slot the node previewed would take; null without a preview or when that node is pinned. */
    previewSlot: ComputedRef<number | null>;
    /** The nodes that gained a slot at the last pin, unpin or mode change, for `CUE_MS`. */
    cue: Readonly<ShallowRef<FocusCue>>;
    /** What the previewed node links; empty without a preview, and for an unpinned node while the focus is full. */
    previewLevels: ComputedRef<ReadonlyMap<NodeId, RelationLevel>>;
    /** The analyses and identified materials linked, the selected ones left out. */
    relatedCount: ComputedRef<number>;
    /** « 3 in focus · 12 related », or « No focus ». */
    summary: ComputedRef<string>;
    /** The document screens the linked records open. */
    targets: ComputedRef<DocumentTarget[]>;
    levelOf: (id: NodeId) => RelationLevel | null;
    /** The slot of a pinned node; null when it is not pinned. */
    slotOf: (id: NodeId) => number | null;
    labelOf: (id: NodeId) => Label | null;
    preview: (id: NodeId | null, event?: PreviewEvent) => void;
    toggle: (id: NodeId) => void;
    setMode: (mode: FocusMode) => void;
    clear: () => void;
}

const NO_LEVELS: ReadonlyMap<NodeId, RelationLevel> = new Map();
const NO_NODES: ReadonlySet<NodeId> = new Set();

/**
 * The linked selection of Compare, one per Compare view: the graph of the
 * Selection's items and synthesis (`buildGraph`), the focus (the nodes the
 * reader pinned, each at its slot, `compare.selection`) and what it lights
 * per slot (`focusRelations`): what relates to any pinned node, or under
 * the mode `all` only what relates to every one. A toggle, a mode change
 * or a clear speaks the new count once; a pin, an unpin or a mode change
 * marks the nodes that gained a slot (`cue`) for `CUE_MS`. The preview follows a
 * mouse or pen resting on a node (80 ms to show, 120 ms to leave, applied
 * on the next frame) and is never announced; it ends at once when the
 * element it started on leaves the page. While `FOCUS_MAX` nodes are
 * pinned, a toggle on another node only says the focus is full, and a
 * preview of one promises no slot and lights nothing. Escape clears the selection
 * unless a menu, popover or dialog is open, a tooltip is shown, the key
 * was already handled, or the focus is in a field. Once the items are read
 * and the synthesis answers for the Selection shown, a selected node the
 * graph no longer holds is dropped, and that is said.
 */
export function useLinkedSelection({
    items,
    synthesis,
    announce,
}: LinkedSelectionSources): LinkedSelection {
    const store = useExplorerStore();
    const { $gettext, $ngettext, interpolate } = useGettext();

    const previewing = ref<NodeId | null>(null);
    const previewAnchor = shallowRef<Element | null>(null);
    const cue = shallowRef<FocusCue>({ generation: 0, nodes: NO_NODES });
    let cueTimer: ReturnType<typeof setTimeout> | null = null;
    let timer: ReturnType<typeof setTimeout> | null = null;
    let frame: number | null = null;
    /** Watches the page while a preview has an anchor, to end the preview once the anchor leaves it. */
    let anchorWatch: MutationObserver | null = null;

    const graph = computed(() =>
        buildGraph({
            basket: store.basket,
            byKey: items.byKey.value,
            synthesis: synthesis.data.value,
        }),
    );
    const slots = computed<readonly (NodeId | null)[]>(
        () => store.compare.selection,
    );
    const pinned = computed<readonly PinnedNode[]>(() => pinnedOf(slots.value));
    const selection = computed<readonly NodeId[]>(() =>
        pinned.value.map(({ id }) => id),
    );
    const mode = computed<FocusMode>(() => store.compare.mode);
    const relations = computed<ReadonlyMap<NodeId, NodeRelations>>(() =>
        focusRelations(graph.value, pinned.value, mode.value),
    );
    const levels = computed<ReadonlyMap<NodeId, RelationLevel>>(
        () => new Map([...relations.value].map(([id, { best }]) => [id, best])),
    );
    const nextSlot = computed(() => nextFreeSlot(slots.value));
    const previewLevels = computed<ReadonlyMap<NodeId, RelationLevel>>(() =>
        previewing.value === null ||
        (nextSlot.value === null && !selection.value.includes(previewing.value))
            ? NO_LEVELS
            : related(graph.value, [previewing.value]),
    );
    const previewSlot = computed(() =>
        previewing.value === null || selection.value.includes(previewing.value)
            ? null
            : nextSlot.value,
    );
    const relatedCount = computed(
        () =>
            [...levels.value].filter(
                ([id, level]) => level !== "self" && isRecordNode(id),
            ).length,
    );
    const summary = computed(() => {
        const selected = selection.value.length;
        if (selected === 0) return $gettext("No focus");
        return [
            interpolate(
                $ngettext("%{n} in focus", "%{n} in focus", selected),
                { n: selected },
                true,
            ),
            interpolate(
                $ngettext("%{n} related", "%{n} related", relatedCount.value),
                { n: relatedCount.value },
                true,
            ),
        ].join(" · ");
    });
    const targets = computed(() => documentTargets(graph.value, levels.value));
    /** Whether the graph answers for the Selection shown: its items read, its synthesis (if any) answered for its keys. */
    const settled = computed(() => {
        if (!items.settled.value) return false;
        const keys = store.basket.map((item) => item.key);
        return keys.length === 0 || synthesisFor(synthesis, keys) !== null;
    });

    watch(
        () => (settled.value ? graph.value : null),
        (current) => {
            if (!current) return;
            const dropped = store.pruneSelection((id) => current.nodes.has(id));
            if (dropped.length === 0) return;
            announce(
                interpolate(
                    $ngettext(
                        "%{n} node in focus is no longer linked to the Selection and left the focus.",
                        "%{n} nodes in focus are no longer linked to the Selection and left the focus.",
                        dropped.length,
                    ),
                    { n: dropped.length },
                    true,
                ),
            );
        },
        { immediate: true, flush: "sync" },
    );

    watch(previewAnchor, watchAnchor, { flush: "sync" });

    document.addEventListener("keydown", onKeydown);
    onScopeDispose(() => {
        document.removeEventListener("keydown", onKeydown);
        cancelPreview();
        anchorWatch?.disconnect();
        if (cueTimer !== null) clearTimeout(cueTimer);
    });

    function levelOf(id: NodeId): RelationLevel | null {
        return levels.value.get(id) ?? null;
    }

    function slotOf(id: NodeId): number | null {
        const index = slots.value.indexOf(id);
        return index < 0 ? null : index + 1;
    }

    /** Runs `change` and marks the nodes it gave a slot they did not hold. */
    function withCue(change: () => void): void {
        const before = relations.value;
        change();
        const gained = gainedSlots(before, relations.value);
        if (cueTimer !== null) clearTimeout(cueTimer);
        cue.value = {
            generation: cue.value.generation + 1,
            nodes: gained,
        };
        cueTimer = setTimeout(() => {
            cueTimer = null;
            cue.value = { generation: cue.value.generation, nodes: NO_NODES };
        }, CUE_MS);
    }

    function labelOf(id: NodeId): Label | null {
        return nodeLabel(graph.value, id);
    }

    function cancelPreview(): void {
        if (timer !== null) clearTimeout(timer);
        if (frame !== null) cancelAnimationFrame(frame);
        timer = null;
        frame = null;
    }

    /** Ends the preview at once. */
    function endPreview(): void {
        cancelPreview();
        previewing.value = null;
        previewAnchor.value = null;
    }

    function watchAnchor(anchor: Element | null): void {
        anchorWatch?.disconnect();
        anchorWatch = null;
        if (!anchor || typeof MutationObserver === "undefined") return;
        anchorWatch = new MutationObserver(() => {
            if (!anchor.isConnected) endPreview();
        });
        anchorWatch.observe(anchor.ownerDocument.documentElement, {
            childList: true,
            subtree: true,
        });
    }

    function preview(id: NodeId | null, event?: PreviewEvent): void {
        if (event && !PREVIEW_POINTERS.includes(event.pointerType)) return;
        cancelPreview();
        if (id === previewing.value) return;
        const anchor =
            event?.currentTarget instanceof Element
                ? event.currentTarget
                : null;
        timer = setTimeout(
            () => {
                timer = null;
                frame = requestAnimationFrame(() => {
                    frame = null;
                    if (anchor && !anchor.isConnected) {
                        endPreview();
                        return;
                    }
                    previewing.value = id;
                    previewAnchor.value = id === null ? null : anchor;
                });
            },
            id === null ? PREVIEW_LEAVE_MS : PREVIEW_ENTER_MS,
        );
    }

    function toggle(id: NodeId): void {
        if (!selection.value.includes(id) && nextSlot.value === null) {
            announce(
                interpolate(
                    $gettext(
                        "The focus holds %{n} items at most. Unpin one to add another.",
                    ),
                    { n: FOCUS_MAX },
                    true,
                ),
            );
            return;
        }
        withCue(() => store.toggleSelection(id));
        announce(summary.value);
    }

    function setMode(next: FocusMode): void {
        if (next === mode.value) return;
        withCue(() => store.setFocusMode(next));
        announce(summary.value);
    }

    function clear(): void {
        if (selection.value.length === 0) return;
        withCue(() => store.clearSelection());
        announce(summary.value);
    }

    function onKeydown(event: KeyboardEvent): void {
        if (event.key !== "Escape" || event.defaultPrevented) return;
        if (selection.value.length === 0) return;
        const target = event.target;
        if (target instanceof Element && target.closest(EDITABLE)) return;
        if (document.querySelector(OPEN_POPUP)) return;
        event.preventDefault();
        clear();
    }

    return {
        graph,
        slots,
        selection,
        pinned,
        mode,
        relations,
        levels,
        nextSlot,
        previewing,
        previewAnchor,
        previewSlot,
        cue,
        previewLevels,
        relatedCount,
        summary,
        targets,
        levelOf,
        slotOf,
        labelOf,
        preview,
        toggle,
        setMode,
        clear,
    };
}
