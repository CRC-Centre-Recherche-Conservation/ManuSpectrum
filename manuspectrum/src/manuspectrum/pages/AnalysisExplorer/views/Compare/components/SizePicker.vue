<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, ref, useTemplateRef } from "vue";
import { useGettext } from "vue3-gettext";

import type { WindowSize } from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/types.ts";

const SIZE_NAMES: readonly WindowSize[] = ["S", "M", "L"];
const REVEAL_DELAY_MS = 450;
const HOVER_POINTERS: readonly string[] = ["mouse", "pen"];
const NEXT_KEYS: readonly string[] = ["ArrowRight", "ArrowDown"];
const PREVIOUS_KEYS: readonly string[] = ["ArrowLeft", "ArrowUp"];

/**
 * The size of a Compare window, S, M or L: a radio group that shows only
 * the size the window has (« Free » for a size set by hand). The other
 * sizes are shown over the header, the header itself never moving, after
 * a hover of `REVEAL_DELAY_MS`, while the focus is in the group, or at once
 * on a tap or a click on the size shown; they hide when the pointer leaves,
 * on a tap elsewhere, or once a size is chosen. The hidden sizes stay
 * in the accessibility tree. The arrows choose the next or previous size
 * (wrapping) and take the focus there; only the size checked (else S) is in
 * the tab order. Choosing the size the window has emits nothing.
 */
const props = defineProps<{
    size: WindowSize | null;
    title: string;
}>();

const emit = defineEmits<{
    (event: "size-chosen", payload: { size: WindowSize }): void;
}>();

const { $gettext, interpolate } = useGettext();

const root = useTemplateRef<HTMLElement>("root");

const revealed = ref(false);
let timer: ReturnType<typeof setTimeout> | null = null;
/** The kind of pointer that pressed last, until its click. */
let pressedWith: string | null = null;

const groupLabel = computed(() =>
    interpolate($gettext("Size of « %{title} »"), { title: props.title }, true),
);

onBeforeUnmount(conceal);

function sizeLabel(size: WindowSize): string {
    return interpolate($gettext("Size %{size}"), { size }, true);
}

function tabIndexOf(size: WindowSize): number {
    const inOrder = props.size ?? SIZE_NAMES[0];
    return size === inOrder ? 0 : -1;
}

function cancelTimer(): void {
    if (timer !== null) clearTimeout(timer);
    timer = null;
}

function reveal(): void {
    cancelTimer();
    revealed.value = true;
    document.addEventListener("pointerdown", onDocumentPointerDown);
}

function conceal(): void {
    cancelTimer();
    revealed.value = false;
    document.removeEventListener("pointerdown", onDocumentPointerDown);
}

function onPointerEnter(event: PointerEvent): void {
    if (!HOVER_POINTERS.includes(event.pointerType) || revealed.value) return;
    cancelTimer();
    timer = setTimeout(reveal, REVEAL_DELAY_MS);
}

function onPointerLeave(event: PointerEvent): void {
    if (HOVER_POINTERS.includes(event.pointerType)) conceal();
}

function onPointerDown(event: PointerEvent): void {
    pressedWith = event.pointerType;
}

function onDocumentPointerDown(event: PointerEvent): void {
    if (!root.value?.contains(event.target as Node)) conceal();
}

function onClick(size: WindowSize): void {
    const touched = pressedWith === "touch";
    pressedWith = null;
    if (size === props.size || (touched && !revealed.value)) {
        reveal();
        return;
    }
    conceal();
    emit("size-chosen", { size });
}

async function onKeydown(
    event: KeyboardEvent,
    size: WindowSize,
): Promise<void> {
    let step = 0;
    if (NEXT_KEYS.includes(event.key)) step = 1;
    else if (PREVIOUS_KEYS.includes(event.key)) step = -1;
    if (step === 0) return;
    event.preventDefault();
    const index = SIZE_NAMES.indexOf(size);
    const next =
        SIZE_NAMES[(index + step + SIZE_NAMES.length) % SIZE_NAMES.length];
    emit("size-chosen", { size: next });
    await nextTick();
    root.value
        ?.querySelector<HTMLElement>(`[data-action="size-${next}"]`)
        ?.focus();
}
</script>

<template>
    <div
        ref="root"
        class="size-picker"
        :class="{ revealed, free: props.size === null }"
        @pointerenter="onPointerEnter"
        @pointerleave="onPointerLeave"
        @pointerdown.capture="onPointerDown"
    >
        <span
            class="current"
            aria-hidden="true"
            >{{ props.size ?? $gettext("Free") }}</span
        >
        <div
            class="options"
            role="radiogroup"
            :aria-label="groupLabel"
        >
            <button
                v-for="name in SIZE_NAMES"
                :key="name"
                type="button"
                role="radio"
                :class="{ checked: props.size === name }"
                :data-action="`size-${name}`"
                :aria-label="sizeLabel(name)"
                :aria-checked="props.size === name ? 'true' : 'false'"
                :tabindex="tabIndexOf(name)"
                @click="onClick(name)"
                @keydown="onKeydown($event, name)"
            >
                <span>{{ name }}</span>
            </button>
        </div>
    </div>
</template>

<style scoped>
.size-picker {
    position: relative;
    display: inline-grid;
    place-items: center;
    min-inline-size: var(--explorer-target, 2rem);
    min-block-size: var(--explorer-target, 2rem);
}

.size-picker .current {
    color: var(--ink-muted);
    font-size: 0.75rem;
    font-weight: 600;
    visibility: hidden;
}

.size-picker.free .current {
    visibility: visible;
    padding-inline: 0.25rem;
}

.size-picker .options {
    position: absolute;
    z-index: 2;
    inset-block-start: 0;
    inset-inline-end: 0;
    display: flex;
    border-radius: 0.375rem;
    clip-path: inset(0 0 0 calc(100% - var(--explorer-target, 2rem)));
}

.size-picker.free .options {
    clip-path: inset(50%);
}

.size-picker .options button {
    display: inline-grid;
    place-items: center;
    min-inline-size: var(--explorer-target, 2rem);
    min-block-size: var(--explorer-target, 2rem);
    padding: 0;
    border: 0.0625rem solid transparent;
    border-radius: 0.375rem;
    background: var(--surface);
    color: var(--ink-muted);
    font: inherit;
    font-size: 0.75rem;
    font-weight: 600;
    cursor: pointer;
}

.size-picker:not(.revealed):not(:focus-within) .options button.checked {
    order: 1;
}

.size-picker .options button:hover {
    background: var(--bg-alt);
    color: var(--ink);
}

.size-picker .options button[aria-checked="true"] {
    border-color: var(--border-hover);
    color: var(--ink);
}

.size-picker .options button:focus-visible {
    outline: 0.125rem solid var(--blue-text);
    outline-offset: -0.125rem;
}

.size-picker.revealed .options,
.size-picker:focus-within .options {
    gap: 0.125rem;
    padding: 0.125rem;
    border: 0.0625rem solid var(--border-hover);
    background: var(--surface);
    box-shadow: var(--shadow-md);
    clip-path: none;
    inset-block-start: -0.1875rem;
    inset-inline-end: -0.1875rem;
}

.size-picker.revealed .options button[aria-checked="true"],
.size-picker:focus-within .options button[aria-checked="true"] {
    border-color: var(--ink);
}
</style>
