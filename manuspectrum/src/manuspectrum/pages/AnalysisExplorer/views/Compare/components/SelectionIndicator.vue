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

import FocusSlotDot from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/components/FocusSlotDot.vue";

import { useMenuButton } from "@/manuspectrum/pages/AnalysisExplorer/composables/useMenuButton.ts";
import { LINKED_SELECTION_KEY } from "@/manuspectrum/pages/AnalysisExplorer/injection-keys.ts";
import { useExplorerStore } from "@/manuspectrum/pages/AnalysisExplorer/store/explorer.ts";
import {
    documentHref,
    snapshotOf,
} from "@/manuspectrum/pages/AnalysisExplorer/store/url.ts";
import {
    circled,
    focusHue,
    focusStripe,
} from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/linked/focus.ts";
import {
    documentNode,
    isRecordNode,
    kindOfNode,
} from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/linked/node-id.ts";

import type { Label } from "@/manuspectrum/pages/AnalysisExplorer/api/types.ts";
import type { DocumentTarget } from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/linked/document-targets.ts";
import type { FocusMode } from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/linked/focus.ts";
import type {
    NodeId,
    NodeKind,
} from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/linked/node-id.ts";

interface Chip {
    id: NodeId;
    slot: number;
    label: Label;
    kind: string;
    counts: string;
}

const HOVER_OPEN_MS = 500;
const HOVER_CLOSE_MS = 300;
const HOVER_POINTERS: readonly string[] = ["mouse", "pen"];
const MODES: readonly FocusMode[] = ["any", "all"];

/**
 * The focus of Compare in its toolbar (`LINKED_SELECTION_KEY`): a compact
 * button that discloses the legend of the focus (disclosure pattern:
 * `aria-expanded`, `aria-controls`), on a click or the keyboard, or after
 * a mouse rests on it (then it folds again when the mouse leaves, unless
 * the focus went inside). At rest it says « No focus »; with pinned nodes
 * it shows their slot discs and « 3 in focus · 12 related » over a stripe
 * of their hues; while a pointer previews an unpinned node, it says which
 * slot that node would take and how many records it links. The legend
 * lists one row per pinned node (its slot disc, label and kind, the
 * records it links directly and through evidence, a button that unpins
 * it), the choice between lighting what relates to any of them or to all
 * of them (two pinned nodes or more), « Open in the document » (a menu of
 * documents when the linked records span several) and « Clear the focus ».
 * Without a focus it says how to pin. Escape with the focus on the button
 * or in the panel, or a pointer down outside, folds it; that Escape does
 * not clear the focus.
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
    linked.pinned.value.map(({ id, slot }) => ({
        id,
        slot,
        label: labelOf(id),
        kind: kindName(kindOfNode(id)),
        counts: slotCounts(slot),
    })),
);
const active = computed(() => chips.value.length > 0);
const previewText = computed(() => {
    const previewed = linked.previewing.value;
    const slot = linked.previewSlot.value;
    if (active.value || previewed === null || slot === null) return null;
    const count = [...linked.previewLevels.value].filter(
        ([id, level]) => level !== "self" && isRecordNode(id),
    ).length;
    return interpolate(
        $ngettext(
            "%{name} would be %{slot} · %{n} linked",
            "%{name} would be %{slot} · %{n} linked",
            count,
        ),
        { name: labelOf(previewed).value, slot: circled(slot), n: count },
        true,
    );
});
const buttonStyle = computed<Record<string, string>>(() => {
    const hues = linked.pinned.value.map(({ slot }) => focusHue(slot));
    const previewSlot = linked.previewSlot.value;
    return {
        ...(hues.length > 0
            ? { "--rim": focusStripe(hues), "--h1": hues[0] }
            : {}),
        ...(previewSlot !== null ? { "--hp": focusHue(previewSlot) } : {}),
    };
});
const modeHint = computed(() =>
    linked.mode.value === "all"
        ? $gettext("what relates to all of them")
        : $gettext("what relates to any of them"),
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
        case "layer":
            return $gettext("Map layer");
        case "tech":
            return $gettext("Technique");
        case "cv":
            return $gettext("Folio");
        case "doc":
            return $gettext("Document");
        case "comp":
            return $gettext("Component");
        case "mv":
            return $gettext("Material");
        case "co":
            return $gettext("Colour");
        case "el":
            return $gettext("Element");
        case "pair":
            return $gettext("Colour × material");
        case "cell":
            return $gettext("Coverage cell");
        default:
            return $gettext("Item");
    }
}

function labelOf(id: NodeId): Label {
    return linked.labelOf(id) ?? { value: kindName(kindOfNode(id)), lang: "" };
}

/** « 3 direct · 1 evidence »: the records the node of `slot` links, directly and through evidence. */
function slotCounts(slot: number): string {
    let direct = 0;
    let evidence = 0;
    for (const [id, relations] of linked.relations.value) {
        if (!isRecordNode(id)) continue;
        const level = relations.slots.find(
            (entry) => entry.slot === slot,
        )?.level;
        if (level === "direct") direct += 1;
        else if (level === "evidence") evidence += 1;
    }
    return interpolate(
        $gettext("%{direct} direct · %{evidence} evidence"),
        { direct, evidence },
        true,
    );
}

function modeLabel(mode: FocusMode): string {
    return mode === "all" ? $gettext("all of them") : $gettext("any of them");
}

function unselectLabel(label: Label): string {
    return interpolate(
        $gettext("Take %{name} out of the focus"),
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
    const left = chipList.value?.querySelectorAll<HTMLElement>("button.unpin");
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
            :class="{
                'is-active': active,
                'is-preview': previewText !== null,
            }"
            :style="buttonStyle"
            :aria-expanded="open ? 'true' : 'false'"
            :aria-controls="open ? panelId : undefined"
            @click="onClick"
        >
            <span
                v-if="!active"
                class="beacon"
                aria-hidden="true"
            ></span>
            <span
                v-else
                class="dots"
            >
                <FocusSlotDot
                    v-for="chip in chips"
                    :key="chip.slot"
                    :number="chip.slot"
                />
            </span>
            <span class="summary">{{
                previewText ?? linked.summary.value
            }}</span>
        </button>
        <div
            v-if="open"
            :id="panelId"
            class="panel"
            role="group"
            :aria-labelledby="buttonId"
            :style="buttonStyle"
        >
            <p
                v-if="chips.length === 0"
                class="hint"
            >
                <span>{{
                    $gettext(
                        "Click an element, a colour × material pair, a coverage cell or a spectrum to see what is linked to it in every window. Each click adds it to the focus or takes it out.",
                    )
                }}</span>
            </p>
            <template v-else>
                <p class="heading">
                    <span class="heading-title">{{ $gettext("Focus") }}</span>
                    <span class="heading-mode">{{ modeHint }}</span>
                </p>
                <ul
                    ref="chipList"
                    class="chips"
                    :aria-label="$gettext('In focus')"
                >
                    <li
                        v-for="chip in chips"
                        :key="chip.id"
                        class="chip-row"
                        :data-node="chip.id"
                    >
                        <span
                            class="chip"
                            :class="{ more: chip.slot > 4 }"
                            :style="{ '--h': focusHue(chip.slot) }"
                        >
                            <FocusSlotDot
                                size="large"
                                :number="chip.slot"
                            />
                            <span
                                class="chip-label"
                                :lang="chip.label.lang || undefined"
                                >{{ chip.label.value }}</span
                            >
                            <span class="chip-kind">{{ chip.kind }}</span>
                        </span>
                        <span class="chip-counts">{{ chip.counts }}</span>
                        <button
                            type="button"
                            class="unpin"
                            :aria-label="unselectLabel(chip.label)"
                            @click="unselect(chip.id)"
                        >
                            <span aria-hidden="true">×</span>
                        </button>
                    </li>
                </ul>
                <div
                    v-if="chips.length > 1"
                    class="mode"
                >
                    <span>{{ $gettext("Light what relates to") }}</span>
                    <span
                        class="segments"
                        role="group"
                        :aria-label="$gettext('Focus mode')"
                    >
                        <button
                            v-for="mode in MODES"
                            :key="mode"
                            type="button"
                            :data-mode="mode"
                            :aria-pressed="
                                linked.mode.value === mode ? 'true' : 'false'
                            "
                            @click="linked.setMode(mode)"
                        >
                            <span>{{ modeLabel(mode) }}</span>
                        </button>
                    </span>
                </div>
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
                        <span>{{ $gettext("Clear the focus") }}</span>
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
    position: relative;
    display: inline-flex;
    align-items: center;
    gap: 0.5rem;
    min-block-size: var(--explorer-target, 2.75rem);
    padding-inline: 0.875rem 1rem;
    overflow: hidden;
    border: 0.0625rem solid var(--border-hover);
    border-radius: 999rem;
    background: var(--surface);
    color: var(--ink-muted);
    font: inherit;
    font-variant-numeric: tabular-nums;
    white-space: nowrap;
    cursor: pointer;
    transition:
        border-color var(--dur-med, 260ms),
        color var(--dur-fast, 160ms);
}

/* The hue stripe: the slots in focus, under the button. */
.selection-indicator .selection-indicator-button::after {
    position: absolute;
    inset-block-end: 0;
    inset-inline: 0.875rem;
    block-size: 0.125rem;
    border-radius: 0.0625rem;
    background: var(--rim, var(--focus-1));
    content: "";
    opacity: 0;
    transition: opacity var(--dur-med, 260ms);
}

.selection-indicator .selection-indicator-button.is-active {
    border-color: color-mix(
        in srgb,
        var(--h1, var(--focus-1)) 45%,
        var(--border-hover)
    );
    color: var(--ink);
    font-weight: 600;
}

.selection-indicator .selection-indicator-button.is-active::after {
    opacity: 1;
}

.selection-indicator .beacon {
    inline-size: 0.625rem;
    block-size: 0.625rem;
    border-radius: 50%;
    background: var(--ink-dim);
    transition: background var(--dur-fast, 160ms);
}

.selection-indicator .is-preview .beacon {
    background: var(--hp, var(--focus-1));
}

.selection-indicator .dots {
    display: inline-flex;
    gap: 0.1875rem;
}

.selection-indicator .summary {
    overflow: hidden;
    text-overflow: ellipsis;
}

.selection-indicator .panel {
    position: absolute;
    inset-block-start: 100%;
    inset-inline-end: 0;
    z-index: 1100;
    display: grid;
    gap: 0.75rem;
    inline-size: min(27rem, 90vw);
    margin-block-start: 0.5rem;
    padding: 1rem;
    overflow: hidden;
    border: 0.0625rem solid var(--border-hover);
    border-radius: 1rem;
    background: var(--surface);
    box-shadow: var(--shadow-lg);
    font-size: 0.875rem;
}

.selection-indicator .panel::before {
    position: absolute;
    inset-block-start: 0;
    inset-inline: 0;
    block-size: 0.125rem;
    background: var(--rim, var(--border-hover));
    content: "";
}

.selection-indicator .hint {
    margin: 0;
    color: var(--ink-muted);
}

.selection-indicator .heading {
    display: flex;
    align-items: baseline;
    gap: 0.5rem;
    margin: 0;
}

.selection-indicator .heading-title {
    font: 600 1.25rem/1.2 var(--font-display);
}

.selection-indicator .heading-mode {
    color: var(--ink-muted);
    font-size: 0.75rem;
}

.selection-indicator .chips {
    display: grid;
    gap: 0.375rem;
    margin: 0;
    padding: 0;
    list-style: none;
}

.selection-indicator .chip-row {
    display: grid;
    grid-template-columns: minmax(0, max-content) minmax(7.5rem, 1fr) auto;
    align-items: center;
    gap: 0.5rem;
}

.selection-indicator .chip {
    display: inline-flex;
    align-items: center;
    gap: 0.375rem;
    min-inline-size: 0;
    min-block-size: 2rem;
    padding-inline: 0.25rem 0.625rem;
    overflow: hidden;
    border: 0.09375rem solid var(--h);
    border-radius: 999rem;
    background: color-mix(in srgb, var(--h) 8%, var(--surface));
    font-weight: 600;
    white-space: nowrap;
}

.selection-indicator .chip.more {
    border-style: dashed;
}

.selection-indicator .chip-label {
    overflow: hidden;
    text-overflow: ellipsis;
}

.selection-indicator .chip-kind {
    color: var(--ink-muted);
    font-size: 0.75rem;
    font-weight: 400;
}

.selection-indicator .chip-counts {
    overflow: hidden;
    color: var(--ink-muted);
    font-size: 0.75rem;
    font-variant-numeric: tabular-nums;
    text-overflow: ellipsis;
    white-space: nowrap;
}

.selection-indicator .unpin {
    display: grid;
    place-items: center;
    inline-size: 1.75rem;
    block-size: 1.75rem;
    border: 0;
    border-radius: 50%;
    background: transparent;
    color: var(--ink-muted);
    font: inherit;
    cursor: pointer;
}

.selection-indicator .unpin:hover {
    background: var(--bg-alt);
    color: var(--ink);
}

.selection-indicator .mode {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    justify-content: space-between;
    gap: 0.5rem;
    color: var(--ink-muted);
    font-size: 0.8125rem;
}

.selection-indicator .segments {
    display: inline-flex;
    padding: 0.125rem;
    border: 0.0625rem solid var(--border-hover);
    border-radius: 999rem;
    background: var(--surface);
}

.selection-indicator .segments button {
    min-block-size: 1.75rem;
    padding-inline: 0.75rem;
    border: 0;
    border-radius: 999rem;
    background: none;
    color: var(--ink-muted);
    font: inherit;
    font-size: 0.8125rem;
    white-space: nowrap;
    cursor: pointer;
}

.selection-indicator .segments button[aria-pressed="true"] {
    background: var(--ink);
    color: var(--surface);
    font-weight: 600;
}

@media (forced-colors: active) {
    .selection-indicator .segments button[aria-pressed="true"] {
        outline: 0.125rem solid Highlight;
    }
}

.selection-indicator .actions {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    justify-content: space-between;
    gap: 0.5rem;
}

.selection-indicator .open-document {
    align-self: center;
    color: var(--focus-1);
    font-weight: 600;
    text-decoration: underline;
    text-underline-offset: 0.2em;
}

.selection-indicator .documents {
    position: relative;
}

.selection-indicator .documents-button,
.selection-indicator .clear {
    min-block-size: 2.25rem;
    padding-inline: 0.75rem;
    border: 0.0625rem solid var(--border-hover);
    border-radius: 0.5rem;
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
