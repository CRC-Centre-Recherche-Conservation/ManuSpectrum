<script setup lang="ts">
import { computed, useId, useTemplateRef, watchEffect } from "vue";

import { useSelectionToggle } from "@/manuspectrum/pages/AnalysisExplorer/composables/useSelectionToggle.ts";

import type { SelectionHint } from "@/manuspectrum/pages/AnalysisExplorer/injection-keys.ts";

/**
 * « Select all » for the `keys` shown: none held → unchecked, part held →
 * natively indeterminate, all held → checked. A click on the mixed state adds
 * what is missing; a click on the full state removes them all (the status
 * line can undo it). When the missing keys do not fit, nothing is added: the
 * box is `aria-disabled` (focusable) and says why. The focus stays on the
 * box after every action. `label` names it (« Select all (6 shown) »);
 * `hints` tell the Selection what the added keys are. `compact` keeps the
 * label and the reason for assistive technology and the tooltip only, where a
 * column is too narrow to print them.
 */
const props = withDefaults(
    defineProps<{
        keys: string[];
        label: string;
        hints?: ReadonlyMap<string, SelectionHint> | null;
        compact?: boolean;
    }>(),
    { hints: null, compact: false },
);

const toggle = useSelectionToggle();
const reasonId = useId();
const input = useTemplateRef<HTMLInputElement>("input");

const state = computed(() => toggle.stateOf(props.keys));
const reason = computed(() => toggle.blockedReason(props.keys));
const tooltip = computed(() => {
    if (!props.compact) return undefined;
    return reason.value ? [props.label, reason.value].join("\n") : props.label;
});
const unavailable = computed(
    () => props.keys.length === 0 || reason.value !== null,
);

watchEffect(
    () => {
        if (!input.value) return;
        input.value.indeterminate = state.value === "some";
        input.value.checked = state.value === "all";
    },
    { flush: "post" },
);

function onClick(event: Event): void {
    if (unavailable.value) event.preventDefault();
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
            :aria-disabled="unavailable ? 'true' : undefined"
            :aria-describedby="reason ? reasonId : undefined"
            @click="onClick"
            @change="onChange"
        />
        <span
            class="text"
            :class="{ 'visually-hidden': props.compact }"
            >{{ props.label }}</span
        >
        <span
            v-if="reason"
            :id="reasonId"
            class="reason"
            :class="{ 'visually-hidden': props.compact }"
        >
            {{ reason }}
        </span>
    </label>
</template>

<style scoped>
.select-all-checkbox {
    display: inline-flex;
    flex-wrap: wrap;
    align-items: center;
    gap: 0.25rem 0.5rem;
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
    cursor: not-allowed;
    opacity: 0.5;
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

.select-all-checkbox .reason {
    color: var(--ink-muted);
    font-size: 0.8125rem;
}
</style>
