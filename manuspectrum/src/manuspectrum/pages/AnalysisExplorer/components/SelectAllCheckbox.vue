<script setup lang="ts">
import { computed, useId, useTemplateRef, watchEffect } from "vue";
import { useGettext } from "vue3-gettext";

import { useSelectionToggle } from "@/manuspectrum/pages/AnalysisExplorer/composables/useSelectionToggle.ts";

import type { SelectionHint } from "@/manuspectrum/pages/AnalysisExplorer/injection-keys.ts";

/**
 * « Select all » for the `keys` shown: none held → unchecked, part held →
 * natively indeterminate, all held → checked. A click on the mixed state adds
 * what is missing; a click on the full state removes them all (the status
 * line can undo it). When the missing keys do not fit, nothing is added: the
 * box is `aria-disabled` (focusable), drawn as unavailable, and a click
 * announces once that nothing was added. `label` is the visible text, `name`
 * the accessible name of the box (it says the scope). A counter chip
 * (« 6 », « 2 / 6 », « 6 / 6 ») follows the label; it is decorative. The
 * reason is reached through `describedBy` (the id of a notice) or, without
 * one, a visually hidden text. `hints` tell the Selection what the added
 * keys are. `compact` keeps the label and the chip out of sight, where a
 * column is too narrow to print them; `name` and the reason stay in the
 * tooltip. The focus stays on the box after every action.
 */
const props = withDefaults(
    defineProps<{
        keys: string[];
        name: string;
        label?: string;
        describedBy?: string;
        hints?: ReadonlyMap<string, SelectionHint> | null;
        compact?: boolean;
    }>(),
    { label: undefined, describedBy: undefined, hints: null, compact: false },
);

const { $gettext } = useGettext();
const toggle = useSelectionToggle();
const reasonId = useId();
const input = useTemplateRef<HTMLInputElement>("input");

const visibleLabel = computed(() => props.label ?? $gettext("Select all"));
const state = computed(() => toggle.stateOf(props.keys));
const reason = computed(() => toggle.blockedReason(props.keys));
const heldCount = computed(() => toggle.heldCount(props.keys));
const chip = computed(() =>
    heldCount.value === 0
        ? String(props.keys.length)
        : `${heldCount.value} / ${props.keys.length}`,
);
const tooltip = computed(() => {
    if (!props.compact) return undefined;
    return reason.value ? [props.name, reason.value].join("\n") : props.name;
});
const unavailable = computed(
    () => props.keys.length === 0 || reason.value !== null,
);
const describedById = computed(() => {
    if (reason.value === null) return undefined;
    return props.describedBy ?? reasonId;
});

watchEffect(
    () => {
        if (!input.value) return;
        input.value.indeterminate = state.value === "some";
        input.value.checked = state.value === "all";
    },
    { flush: "post" },
);

function onClick(event: Event): void {
    if (!unavailable.value) return;
    event.preventDefault();
    if (reason.value !== null) toggle.announceRefused(props.keys);
}

function onChange(): void {
    if (unavailable.value) return;
    toggle.toggleAll(props.keys, props.hints);
}
</script>

<template>
    <label
        class="select-all-checkbox"
        :title="tooltip"
    >
        <input
            ref="input"
            type="checkbox"
            :aria-label="props.name"
            :aria-disabled="unavailable ? 'true' : undefined"
            :aria-describedby="describedById"
            @click="onClick"
            @change="onChange"
        />
        <span
            class="text"
            :class="{ 'visually-hidden': props.compact }"
            >{{ visibleLabel }}</span
        >
        <span
            v-if="!props.compact"
            class="chip"
            :class="{ some: heldCount > 0 }"
            aria-hidden="true"
            >{{ chip }}</span
        >
        <span
            v-if="reason && !props.describedBy"
            :id="reasonId"
            class="visually-hidden"
        >
            {{ reason }}
        </span>
    </label>
</template>

<style scoped>
.select-all-checkbox {
    display: inline-flex;
    flex-wrap: nowrap;
    align-items: center;
    gap: 0.25rem 0.625rem;
    min-block-size: var(--explorer-target, 2.75rem);
    cursor: pointer;
}

.select-all-checkbox input {
    inline-size: 1.125rem;
    block-size: 1.125rem;
    margin: 0;
    accent-color: var(--blue-text);
    cursor: inherit;
}

.select-all-checkbox input[aria-disabled="true"] {
    appearance: none;
    border: 0.09375rem dashed var(--ink-dim);
    border-radius: 0.1875rem;
    background: var(--bg-alt);
    cursor: not-allowed;
}

.select-all-checkbox input:focus-visible {
    outline: 0.125rem solid var(--blue-text);
    outline-offset: 0.125rem;
}

.select-all-checkbox .visually-hidden {
    position: absolute;
    inline-size: 0.0625rem;
    block-size: 0.0625rem;
    overflow: hidden;
    clip-path: inset(50%);
    white-space: nowrap;
}

.select-all-checkbox .text {
    flex: 1 1 auto;
}

.select-all-checkbox .chip {
    flex: none;
    padding-inline: 0.5rem;
    border-radius: 999rem;
    background: var(--bg-alt);
    color: var(--ink-muted);
    font-family: var(--font-mono);
    font-size: 0.75rem;
    font-weight: 500;
}

.select-all-checkbox .chip.some {
    background: var(--selection-tint);
    color: var(--blue-text);
}
</style>
