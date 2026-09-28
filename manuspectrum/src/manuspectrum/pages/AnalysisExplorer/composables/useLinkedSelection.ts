import { computed, onScopeDispose, ref, watch } from "vue";
import { useGettext } from "vue3-gettext";

import { useExplorerStore } from "@/manuspectrum/pages/AnalysisExplorer/store/explorer.ts";
import { documentTargets } from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/linked/document-targets.ts";
import { buildGraph } from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/linked/graph.ts";
import {
    isRecordNode,
    kindOfNode,
} from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/linked/node-id.ts";
import { nodeLabel } from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/linked/node-label.ts";
import { related } from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/linked/related.ts";

import type { ComputedRef, Ref } from "vue";

import type {
    Label,
    SynthesisResponse,
} from "@/manuspectrum/pages/AnalysisExplorer/api/types.ts";
import type { RequestHandle } from "@/manuspectrum/pages/AnalysisExplorer/composables/useRequest.ts";
import type { SelectionItems } from "@/manuspectrum/pages/AnalysisExplorer/composables/useSelectionItems.ts";
import type { DocumentTarget } from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/linked/document-targets.ts";
import type { LinkedGraph } from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/linked/graph.ts";
import type {
    NodeId,
    NodeKind,
} from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/linked/node-id.ts";
import type { RelationLevel } from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/linked/related.ts";

const PREVIEW_ENTER_MS = 80;
const PREVIEW_LEAVE_MS = 120;
const PREVIEW_POINTERS: readonly string[] = ["mouse", "pen"];
/** An open dialog, menu or popover, or a tooltip shown: Escape belongs to it. A popover's button carries `data-popover`. */
const OPEN_POPUP =
    'dialog[open], [aria-haspopup][aria-expanded="true"], [data-popover][aria-expanded="true"], [role="tooltip"]:not([hidden])';
const EDITABLE = "input, textarea, select, [contenteditable='true']";

export interface LinkedSelectionSources {
    items: SelectionItems;
    synthesis: RequestHandle<SynthesisResponse>;
    announce: (message: string) => void;
}

export interface LinkedSelection {
    graph: ComputedRef<LinkedGraph>;
    selection: ComputedRef<readonly NodeId[]>;
    /** What the selection links (`related`). */
    levels: ComputedRef<ReadonlyMap<NodeId, RelationLevel>>;
    /** The node the pointer rests on, once the preview delay has passed. */
    previewing: Readonly<Ref<NodeId | null>>;
    /** What the previewed node links; empty without a preview. */
    previewLevels: ComputedRef<ReadonlyMap<NodeId, RelationLevel>>;
    /** The analyses and identified materials linked, the selected ones left out. */
    relatedCount: ComputedRef<number>;
    /** The nodes linked by kind, the selected ones left out. */
    counts: ComputedRef<Partial<Record<NodeKind, number>>>;
    /** « 3 in focus · 12 related », or « No focus ». */
    summary: ComputedRef<string>;
    /** The document screens the linked records open. */
    targets: ComputedRef<DocumentTarget[]>;
    levelOf: (id: NodeId) => RelationLevel | null;
    labelOf: (id: NodeId) => Label | null;
    preview: (
        id: NodeId | null,
        event?: Pick<PointerEvent, "pointerType">,
    ) => void;
    toggle: (id: NodeId) => void;
    clear: () => void;
}

const NO_LEVELS: ReadonlyMap<NodeId, RelationLevel> = new Map();

/**
 * The linked selection of Compare, one per Compare view: the graph of the
 * Selection's items and synthesis (`buildGraph`), the nodes the reader
 * selected (`compare.selection`, a union) and what they link (`related`).
 * A toggle or a clear speaks the new count once. The preview follows a
 * mouse or pen resting on a node (80 ms to show, 120 ms to leave, applied
 * on the next frame) and is never announced. Escape clears the selection
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
    let timer: ReturnType<typeof setTimeout> | null = null;
    let frame: number | null = null;

    const graph = computed(() =>
        buildGraph({
            basket: store.basket,
            byKey: items.byKey.value,
            synthesis: synthesis.data.value,
        }),
    );
    const selection = computed<readonly NodeId[]>(
        () => store.compare.selection,
    );
    const levels = computed<ReadonlyMap<NodeId, RelationLevel>>(() =>
        related(graph.value, selection.value),
    );
    const previewLevels = computed<ReadonlyMap<NodeId, RelationLevel>>(() =>
        previewing.value === null
            ? NO_LEVELS
            : related(graph.value, [previewing.value]),
    );
    const counts = computed(() => {
        const byKind: Partial<Record<NodeKind, number>> = {};
        for (const [id, level] of levels.value) {
            const kind = kindOfNode(id);
            if (level === "self" || kind === null) continue;
            byKind[kind] = (byKind[kind] ?? 0) + 1;
        }
        return byKind;
    });
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
        if (keys.length === 0) return true;
        return (
            synthesis.status.value === "ready" &&
            synthesis.loaded.value === [...new Set(keys)].sort().join(",")
        );
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

    document.addEventListener("keydown", onKeydown);
    onScopeDispose(() => {
        document.removeEventListener("keydown", onKeydown);
        cancelPreview();
    });

    function levelOf(id: NodeId): RelationLevel | null {
        return levels.value.get(id) ?? null;
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

    function preview(
        id: NodeId | null,
        event?: Pick<PointerEvent, "pointerType">,
    ): void {
        if (event && !PREVIEW_POINTERS.includes(event.pointerType)) return;
        cancelPreview();
        if (id === previewing.value) return;
        timer = setTimeout(
            () => {
                timer = null;
                frame = requestAnimationFrame(() => {
                    frame = null;
                    previewing.value = id;
                });
            },
            id === null ? PREVIEW_LEAVE_MS : PREVIEW_ENTER_MS,
        );
    }

    function toggle(id: NodeId): void {
        store.toggleSelection(id);
        announce(summary.value);
    }

    function clear(): void {
        if (selection.value.length === 0) return;
        store.clearSelection();
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
        selection,
        levels,
        previewing,
        previewLevels,
        relatedCount,
        counts,
        summary,
        targets,
        levelOf,
        labelOf,
        preview,
        toggle,
        clear,
    };
}
