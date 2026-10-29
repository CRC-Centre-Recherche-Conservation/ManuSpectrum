<script setup lang="ts">
import { computed, onBeforeUnmount, ref, useId, useTemplateRef } from "vue";

import { useAnchoredPopover } from "@/manuspectrum/pages/AnalysisExplorer/composables/useAnchoredPopover.ts";

const SHOW_DELAY_MS = 500;
const FOCUS_VISIBLE = ":focus-visible";

/**
 * A tooltip for the control in its slot, in one of two roles. As a
 * description (the default), the slot receives `describedby`, the id of the
 * one tooltip node, for the control's `aria-describedby`. As a label, the
 * slot receives `labelledby`, the id of the text in the tooltip, for the
 * control's `aria-labelledby`: the tooltip names the control (an icon
 * button) and its text is not read a second time as a description; a
 * `detail` shown under the text is then the control's description
 * (`describedby`). The node stays in the DOM, `hidden` until shown.
 * `placement` puts it above (the default) or below the control, `align`
 * lines it up with the control's start (the default) or end; the other side
 * is used when the first has too little room (both may change while mounted).
 * The tooltip closes when its control scrolls out of sight. The node is a `popover="manual"`
 * element shown in the top layer (`useAnchoredPopover`), so no ancestor's
 * overflow clips it; the padding above and below it bridges the gap to the
 * control so the pointer can reach it.
 *
 * Shown `SHOW_DELAY_MS` after a mouse or pen hover, or after a keyboard focus
 * (`:focus-visible`); never after a click or a tap, which also hide it and
 * keep it hidden until the pointer leaves or focus moves away. Hidden when the
 * pointer leaves the control and the tooltip (the tooltip lies inside the
 * hover area, so it can be hovered), on blur, and on Escape wherever focus is:
 * the document listener exists only while a show is pending or shown. The
 * Escape is left to the page, so a dialog the tooltip sits in still closes.
 *
 * With `toggle`, for a control that only reveals the tip (an info button), a
 * tap, a pen-less touch or a keyboard activation opens and closes it, and a
 * press outside closes it; a mouse or pen click keeps the behaviour above, so
 * a click after a hover does not toggle twice. Left off, the control is an
 * action and a click never leaves the tip open.
 */
const props = withDefaults(
    defineProps<{
        text: string;
        mode?: "description" | "label";
        detail?: string;
        placement?: "above" | "below";
        align?: "start" | "end";
        toggle?: boolean;
    }>(),
    {
        mode: "description",
        detail: "",
        placement: "above",
        align: "start",
        toggle: false,
    },
);

const helpId = useId();
const labelId = useId();
const detailId = useId();

const shown = ref(false);
const root = useTemplateRef<HTMLElement>("root");
const bubble = useTemplateRef<HTMLElement>("bubble");
const { style: bubbleStyle } = useAnchoredPopover(shown, bubble, root, {
    get prefer() {
        return props.placement;
    },
    get align() {
        return props.align;
    },
    offset: 0,
    onLost: hide,
});
let timer: ReturnType<typeof setTimeout> | null = null;
let suppressed = false;
let pressType = "";

const labelling = computed(() => props.mode === "label");
const labelledby = computed(() => (labelling.value ? labelId : undefined));
const describedby = computed(() => {
    if (!labelling.value) return helpId;
    return props.detail ? detailId : undefined;
});

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
    document.removeEventListener("pointerdown", onDocumentPointerdown, true);
}

function onPointerEnter(event: PointerEvent): void {
    if (event.pointerType !== "touch") schedule();
}

function onPointerLeave(event: PointerEvent): void {
    if (event.pointerType === "touch") return;
    suppressed = false;
    hide();
}

function togglesOnClick(): boolean {
    return props.toggle && pressType !== "mouse" && pressType !== "pen";
}

function onPointerDown(event: PointerEvent): void {
    pressType = event.pointerType;
    if (togglesOnClick()) return;
    suppressed = true;
    hide();
}

function onClick(): void {
    const toggling = togglesOnClick();
    pressType = "";
    if (!toggling) {
        suppressed = true;
        hide();
        return;
    }
    if (shown.value) {
        hide();
        return;
    }
    if (timer !== null) {
        clearTimeout(timer);
        timer = null;
    }
    shown.value = true;
    document.addEventListener("keydown", onDocumentKeydown);
    document.addEventListener("pointerdown", onDocumentPointerdown, true);
}

function onDocumentPointerdown(event: PointerEvent): void {
    if (!root.value?.contains(event.target as Node)) hide();
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
    if (event.key !== "Escape") return;
    hide();
}
</script>

<template>
    <span
        ref="root"
        class="help-tip"
        @pointerenter="onPointerEnter"
        @pointerleave="onPointerLeave"
        @pointerdown.capture="onPointerDown"
        @click.capture="onClick"
        @focusin="onFocusIn"
        @focusout="onFocusOut"
    >
        <slot
            :describedby="describedby"
            :labelledby="labelledby"
        />
        <span
            :id="helpId"
            ref="bubble"
            popover="manual"
            class="bubble"
            :class="[props.placement, props.align]"
            :style="bubbleStyle"
            role="tooltip"
            :hidden="!shown"
        >
            <span
                v-if="labelling"
                class="body"
            >
                <span :id="labelId">{{ props.text }}</span>
                <span
                    v-if="props.detail"
                    :id="detailId"
                    class="detail"
                    >{{ props.detail }}</span
                >
            </span>
            <span
                v-else
                class="body"
                >{{ props.text }}</span
            >
        </span>
    </span>
</template>

<style scoped>
.help-tip {
    position: relative;
    display: inline-flex;
}

.help-tip .bubble {
    position: fixed;
    inset: auto;
    display: flex;
    inline-size: max-content;
    max-inline-size: min(18rem, calc(100vw - 1rem));
    margin: 0;
    padding: 0.375rem 0;
    border: 0;
    background: transparent;
    color: inherit;
    overflow: visible;
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
    white-space: normal;
}

.help-tip .bubble .detail {
    display: block;
    padding-block-start: 0.25rem;
    font-size: 0.75rem;
}
</style>
