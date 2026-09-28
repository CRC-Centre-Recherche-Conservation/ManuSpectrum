<script setup lang="ts">
import {
    computed,
    inject,
    nextTick,
    onBeforeUnmount,
    ref,
    useId,
    useTemplateRef,
} from "vue";
import { useGettext } from "vue3-gettext";

import { useMenuButton } from "@/manuspectrum/pages/AnalysisExplorer/composables/useMenuButton.ts";
import { LINKED_SELECTION_KEY } from "@/manuspectrum/pages/AnalysisExplorer/injection-keys.ts";
import { useExplorerStore } from "@/manuspectrum/pages/AnalysisExplorer/store/explorer.ts";
import {
    documentHref,
    snapshotOf,
} from "@/manuspectrum/pages/AnalysisExplorer/store/url.ts";
import {
    documentNode,
    kindOfNode,
} from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/linked/node-id.ts";

import type { Label } from "@/manuspectrum/pages/AnalysisExplorer/api/types.ts";
import type { DocumentTarget } from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/linked/document-targets.ts";
import type {
    NodeId,
    NodeKind,
} from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/linked/node-id.ts";

interface Chip {
    id: NodeId;
    label: Label;
}

const HOVER_OPEN_MS = 500;
const HOVER_CLOSE_MS = 300;
const HOVER_POINTERS: readonly string[] = ["mouse", "pen"];
const COUNTED_KINDS: readonly NodeKind[] = ["an", "ch", "file", "cv", "el"];

/**
 * The linked selection of Compare in its toolbar (`LINKED_SELECTION_KEY`):
 * a compact button « ◉ 3 selected · 12 related » that discloses a panel
 * (disclosure pattern: `aria-expanded`, `aria-controls`), on a click or
 * the keyboard, or after a mouse rests on it (then it folds again when the
 * mouse leaves, unless the focus went inside). The panel lists the
 * selected nodes as chips that unselect them, counts what they link by
 * kind, offers « Clear all » and « Open in the document » (a menu of
 * documents when the linked records span several). Without a selection it
 * says how to select. Escape with the focus on the button or in the panel,
 * or a pointer down outside, folds it; that Escape does not clear the
 * selection.
 */
const linked = inject(LINKED_SELECTION_KEY)!;

const store = useExplorerStore();
const { $gettext, $ngettext, interpolate } = useGettext();

const buttonId = useId();
const panelId = useId();
const menuId = useId();
const root = useTemplateRef<HTMLElement>("root");
const button = useTemplateRef<HTMLButtonElement>("button");
const chipList = useTemplateRef<HTMLElement>("chipList");
const documentsRoot = useTemplateRef<HTMLElement>("documentsRoot");
const documentsButton = useTemplateRef<HTMLButtonElement>("documentsButton");
const documentsMenu = useMenuButton(documentsRoot, documentsButton);

const open = ref(false);
/** Whether the panel was opened by a resting mouse, and folds when it leaves. */
const openedByHover = ref(false);
let hoverTimer: ReturnType<typeof setTimeout> | null = null;

const chips = computed<Chip[]>(() =>
    linked.selection.value.map((id) => ({ id, label: labelOf(id) })),
);
const countLines = computed(() =>
    COUNTED_KINDS.flatMap((kind) => {
        const count = linked.counts.value[kind] ?? 0;
        return count > 0 ? [{ kind, text: countText(kind, count) }] : [];
    }),
);
const targets = computed(() => linked.targets.value);

onBeforeUnmount(() => {
    cancelHover();
    document.removeEventListener("pointerdown", onPointerDown);
});

function kindName(kind: NodeKind | null): string {
    switch (kind) {
        case "an":
            return $gettext("Analysis");
        case "ch":
            return $gettext("Identified material");
        case "file":
            return $gettext("File");
        case "cv":
            return $gettext("Folio");
        case "doc":
        case "comp":
            return $gettext("Document");
        default:
            return $gettext("Item");
    }
}

function labelOf(id: NodeId): Label {
    return linked.labelOf(id) ?? { value: kindName(kindOfNode(id)), lang: "" };
}

function countText(kind: NodeKind, count: number): string {
    const phrases: Partial<Record<NodeKind, string>> = {
        an: $ngettext("%{n} analysis", "%{n} analyses", count),
        ch: $ngettext(
            "%{n} identified material",
            "%{n} identified materials",
            count,
        ),
        file: $ngettext("%{n} file", "%{n} files", count),
        cv: $ngettext("%{n} folio", "%{n} folios", count),
        el: $ngettext("%{n} element", "%{n} elements", count),
    };
    return interpolate(phrases[kind] ?? "", { n: count }, true);
}

function unselectLabel(label: Label): string {
    return interpolate(
        $gettext("Unselect %{name}"),
        { name: label.value },
        true,
    );
}

function documentName(target: DocumentTarget): string {
    return (
        linked.labelOf(documentNode(target.document))?.value ??
        $gettext("Document")
    );
}

function hrefOf(target: DocumentTarget): string {
    return documentHref(
        snapshotOf(store),
        target.document,
        target.canvas,
        target.focus,
    );
}

function cancelHover(): void {
    if (hoverTimer !== null) clearTimeout(hoverTimer);
    hoverTimer = null;
}

function show(byHover: boolean): void {
    open.value = true;
    openedByHover.value = byHover;
    document.addEventListener("pointerdown", onPointerDown);
}

function hide(returnFocus: boolean): void {
    cancelHover();
    if (documentsMenu.expanded.value) documentsMenu.closeMenu(false);
    open.value = false;
    openedByHover.value = false;
    document.removeEventListener("pointerdown", onPointerDown);
    if (returnFocus) button.value?.focus();
}

function onClick(): void {
    cancelHover();
    if (open.value && !openedByHover.value) hide(false);
    else show(false);
}

function onPointerEnter(event: PointerEvent): void {
    if (!HOVER_POINTERS.includes(event.pointerType)) return;
    cancelHover();
    if (open.value) return;
    hoverTimer = setTimeout(() => {
        hoverTimer = null;
        show(true);
    }, HOVER_OPEN_MS);
}

function onPointerLeave(event: PointerEvent): void {
    if (!HOVER_POINTERS.includes(event.pointerType)) return;
    cancelHover();
    if (!open.value || !openedByHover.value) return;
    hoverTimer = setTimeout(() => {
        hoverTimer = null;
        if (!root.value?.contains(document.activeElement)) hide(false);
    }, HOVER_CLOSE_MS);
}

function onPointerDown(event: PointerEvent): void {
    if (!root.value?.contains(event.target as Node)) hide(false);
}

function onFocusOut(event: FocusEvent): void {
    const next = event.relatedTarget;
    if (open.value && next instanceof Node && !root.value?.contains(next)) {
        hide(false);
    }
}

function onKeydown(event: KeyboardEvent): void {
    if (event.key !== "Escape" || event.defaultPrevented || !open.value) {
        return;
    }
    event.preventDefault();
    hide(true);
}

async function unselect(id: NodeId): Promise<void> {
    const index = linked.selection.value.indexOf(id);
    linked.toggle(id);
    await nextTick();
    const left = chipList.value?.querySelectorAll<HTMLElement>("button");
    if (!left || left.length === 0) {
        button.value?.focus();
        return;
    }
    left[Math.min(index, left.length - 1)].focus();
}

function clearAll(): void {
    linked.clear();
    hide(true);
}

function openTarget(target: DocumentTarget): void {
    hide(false);
    store.openDocument(target.document, target.canvas);
    store.focusOn(target.focus);
}
</script>

<template>
    <div
        ref="root"
        class="selection-indicator"
        @pointerenter="onPointerEnter"
        @pointerleave="onPointerLeave"
        @focusout="onFocusOut"
        @keydown="onKeydown"
    >
        <button
            :id="buttonId"
            ref="button"
            type="button"
            class="selection-indicator-button"
            data-popover="true"
            :class="{ 'is-active': chips.length > 0 }"
            :aria-expanded="open ? 'true' : 'false'"
            :aria-controls="open ? panelId : undefined"
            @click="onClick"
        >
            <span
                class="mark"
                aria-hidden="true"
                >◉</span
            >
            <span class="summary">{{ linked.summary.value }}</span>
        </button>
        <div
            v-if="open"
            :id="panelId"
            class="panel"
            role="group"
            :aria-labelledby="buttonId"
        >
            <p
                v-if="chips.length === 0"
                class="hint"
            >
                <span>{{
                    $gettext(
                        "Click an element, a colour × material pair, a coverage cell or a spectrum to see what is linked to it in every window. Each click adds to the selection or removes from it.",
                    )
                }}</span>
            </p>
            <template v-else>
                <ul
                    ref="chipList"
                    class="chips"
                    :aria-label="$gettext('Selected')"
                >
                    <li
                        v-for="chip in chips"
                        :key="chip.id"
                    >
                        <button
                            type="button"
                            :data-node="chip.id"
                            :aria-label="unselectLabel(chip.label)"
                            @click="unselect(chip.id)"
                        >
                            <span
                                class="chip-label"
                                :lang="chip.label.lang || undefined"
                                >{{ chip.label.value }}</span
                            >
                            <span aria-hidden="true">×</span>
                        </button>
                    </li>
                </ul>
                <ul
                    v-if="countLines.length > 0"
                    class="counts"
                    :aria-label="$gettext('Linked')"
                >
                    <li
                        v-for="line in countLines"
                        :key="line.kind"
                    >
                        <span>{{ line.text }}</span>
                    </li>
                </ul>
                <div class="actions">
                    <a
                        v-if="targets.length === 1"
                        class="open-document"
                        :href="hrefOf(targets[0])"
                        @click.prevent="openTarget(targets[0])"
                    >
                        <span>{{ $gettext("Open in the document") }}</span>
                    </a>
                    <div
                        v-else-if="targets.length > 1"
                        ref="documentsRoot"
                        class="documents"
                    >
                        <button
                            ref="documentsButton"
                            type="button"
                            class="documents-button"
                            aria-haspopup="menu"
                            :aria-expanded="
                                documentsMenu.expanded.value ? 'true' : 'false'
                            "
                            :aria-controls="
                                documentsMenu.expanded.value
                                    ? menuId
                                    : undefined
                            "
                            @click="documentsMenu.toggle"
                            @keydown="documentsMenu.onButtonKeydown"
                        >
                            <span>{{ $gettext("Open in a document") }}</span>
                        </button>
                        <ul
                            v-if="documentsMenu.expanded.value"
                            :id="menuId"
                            class="menu"
                            role="menu"
                            :aria-label="$gettext('Documents')"
                            @keydown="documentsMenu.onMenuKeydown"
                        >
                            <li
                                v-for="target in targets"
                                :key="target.document"
                                role="none"
                            >
                                <a
                                    role="menuitem"
                                    tabindex="-1"
                                    :href="hrefOf(target)"
                                    @click.prevent="openTarget(target)"
                                    >{{ documentName(target) }}</a
                                >
                            </li>
                        </ul>
                    </div>
                    <button
                        type="button"
                        class="clear"
                        @click="clearAll"
                    >
                        <span>{{ $gettext("Clear all") }}</span>
                    </button>
                </div>
            </template>
        </div>
    </div>
</template>

<style scoped>
.selection-indicator {
    position: relative;
}

.selection-indicator .selection-indicator-button {
    display: inline-flex;
    align-items: center;
    gap: 0.375rem;
    min-block-size: var(--explorer-target, 2.75rem);
    padding-inline: 0.75rem;
    border: 0.0625rem solid var(--border-hover);
    border-radius: 999rem;
    background: var(--surface);
    color: var(--ink-muted);
    font: inherit;
    font-variant-numeric: tabular-nums;
    white-space: nowrap;
    cursor: pointer;
}

.selection-indicator .selection-indicator-button.is-active {
    border-color: var(--blue-text);
    color: var(--ink);
    font-weight: 600;
}

.selection-indicator .selection-indicator-button.is-active .mark {
    color: var(--blue-text);
}

.selection-indicator .panel {
    position: absolute;
    inset-block-start: 100%;
    inset-inline-end: 0;
    z-index: 1100;
    display: grid;
    gap: 0.75rem;
    inline-size: min(22rem, 90vw);
    margin-block-start: 0.25rem;
    padding: 0.75rem;
    border: 0.0625rem solid var(--border-hover);
    border-radius: 0.375rem;
    background: var(--surface);
    box-shadow: 0 0.25rem 1rem color-mix(in srgb, var(--ink) 15%, transparent);
    font-size: 0.875rem;
}

.selection-indicator .hint {
    margin: 0;
    color: var(--ink-muted);
}

.selection-indicator .chips,
.selection-indicator .counts {
    display: flex;
    flex-wrap: wrap;
    gap: 0.25rem;
    margin: 0;
    padding: 0;
    list-style: none;
}

.selection-indicator .chips button {
    display: inline-flex;
    align-items: center;
    gap: 0.375rem;
    min-block-size: 2rem;
    padding-inline: 0.625rem;
    border: 0.0625rem solid var(--blue-text);
    border-radius: 999rem;
    background: var(--bg-alt);
    color: var(--ink);
    font: inherit;
    cursor: pointer;
}

.selection-indicator .counts {
    column-gap: 0.75rem;
    color: var(--ink-muted);
    font-variant-numeric: tabular-nums;
}

.selection-indicator .actions {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    justify-content: space-between;
    gap: 0.5rem;
}

.selection-indicator .open-document {
    color: var(--blue-text);
}

.selection-indicator .documents {
    position: relative;
}

.selection-indicator .documents-button,
.selection-indicator .clear {
    min-block-size: 2.25rem;
    padding-inline: 0.75rem;
    border: 0.0625rem solid var(--border-hover);
    border-radius: 0.25rem;
    background: var(--surface);
    color: var(--ink);
    font: inherit;
    cursor: pointer;
}

.selection-indicator .menu {
    position: absolute;
    inset-block-start: 100%;
    inset-inline-start: 0;
    z-index: 1;
    display: grid;
    min-inline-size: 14rem;
    margin: 0.25rem 0 0;
    padding: 0.25rem;
    border: 0.0625rem solid var(--border-hover);
    border-radius: 0.375rem;
    background: var(--surface);
    list-style: none;
}

.selection-indicator .menu a {
    display: block;
    padding: 0.5rem 0.75rem;
    border-radius: 0.25rem;
    color: var(--ink);
    text-decoration: none;
}

.selection-indicator .menu a:hover,
.selection-indicator .menu a:focus {
    background: var(--bg-alt);
}

@media (max-width: 48rem) {
    .selection-indicator {
        flex: 1 1 100%;
    }

    .selection-indicator .panel {
        inset-inline: 0;
        inline-size: auto;
    }
}

.selection-indicator button:focus-visible,
.selection-indicator a:focus-visible {
    outline: 0.125rem solid var(--blue-text);
    outline-offset: 0.125rem;
}
</style>
