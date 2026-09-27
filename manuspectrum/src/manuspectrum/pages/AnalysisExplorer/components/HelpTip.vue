<script setup lang="ts">
import { onBeforeUnmount, ref, useId } from "vue";

const SHOW_DELAY_MS = 500;
const FOCUS_VISIBLE = ":focus-visible";

/**
 * A help tooltip for the control in its slot. The slot receives
 * `describedby`, the id of the one tooltip node, for the control's
 * `aria-describedby`: the node stays in the DOM, `hidden` until shown, so the
 * text is always the control's description and is never read twice.
 *
 * Shown `SHOW_DELAY_MS` after a mouse or pen hover, or after a keyboard focus
 * (`:focus-visible`); never after a click or a tap, which also hide it and
 * keep it hidden until the pointer leaves or focus moves away. Hidden when the
 * pointer leaves the control and the tooltip (the tooltip lies inside the
 * hover area, so it can be hovered), on blur, and on Escape wherever focus is:
 * the document listener exists only while a show is pending or shown.
 */
const props = defineProps<{ text: string }>();

const helpId = useId();

const shown = ref(false);
let timer: ReturnType<typeof setTimeout> | null = null;
let suppressed = false;

onBeforeUnmount(hide);

function schedule(): void {
    if (suppressed || shown.value || timer !== null) return;
    timer = setTimeout(() => {
        timer = null;
        shown.value = true;
    }, SHOW_DELAY_MS);
    document.addEventListener("keydown", onDocumentKeydown);
}

function hide(): void {
    if (timer !== null) {
        clearTimeout(timer);
        timer = null;
    }
    shown.value = false;
    document.removeEventListener("keydown", onDocumentKeydown);
}

function onPointerEnter(event: PointerEvent): void {
    if (event.pointerType !== "touch") schedule();
}

function onPointerLeave(): void {
    suppressed = false;
    hide();
}

function onPointerDown(): void {
    suppressed = true;
    hide();
}

function onClick(): void {
    suppressed = true;
    hide();
}

function onFocusIn(event: FocusEvent): void {
    const target = event.target as Element;
    if (target.matches(FOCUS_VISIBLE)) schedule();
}

function onFocusOut(): void {
    suppressed = false;
    hide();
}

function onDocumentKeydown(event: KeyboardEvent): void {
    if (event.key === "Escape") hide();
}
</script>

<template>
    <span
        class="help-tip"
        @pointerenter="onPointerEnter"
        @pointerleave="onPointerLeave"
        @pointerdown.capture="onPointerDown"
        @click.capture="onClick"
        @focusin="onFocusIn"
        @focusout="onFocusOut"
    >
        <slot :describedby="helpId" />
        <span
            :id="helpId"
            class="bubble"
            role="tooltip"
            :hidden="!shown"
        >
            <span class="body">{{ props.text }}</span>
        </span>
    </span>
</template>

<style scoped>
.help-tip {
    position: relative;
    display: inline-flex;
}

.help-tip .bubble {
    position: absolute;
    z-index: 1;
    inset-block-end: 100%;
    inset-inline-start: 0;
    display: flex;
    inline-size: max-content;
    max-inline-size: 18rem;
    padding-block-end: 0.375rem;
}

.help-tip .bubble[hidden] {
    display: none;
}

.help-tip .bubble .body {
    padding-block: 0.375rem;
    padding-inline: 0.625rem;
    border-radius: 0.375rem;
    background: var(--ink);
    box-shadow: var(--shadow-md);
    color: var(--surface);
    font-size: 0.8125rem;
    line-height: 1.4;
}
</style>
