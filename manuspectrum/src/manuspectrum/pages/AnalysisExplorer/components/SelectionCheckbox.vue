<script setup lang="ts">
import { computed, useId } from "vue";

import { useSelectionToggle } from "@/manuspectrum/pages/AnalysisExplorer/composables/useSelectionToggle.ts";

import type { SelectionHint } from "@/manuspectrum/pages/AnalysisExplorer/injection-keys.ts";

/**
 * The checkbox of one item of the Selection, in a click zone of
 * `--explorer-target`. Checking adds the item (its `hint` is recorded first),
 * unchecking removes it. While held the zone takes the `held` class (the
 * `--selection-tint` background) and writes the item's slot (« A3 ») under
 * the box. A full Selection that does not hold the item makes the box
 * `aria-disabled` (still focusable), drawn as unavailable, with the reason in
 * its tooltip and through `aria-describedby`; activating it announces once
 * that nothing was added. `label` is the accessible name; `heldLabel`, when
 * given, replaces it while the item is held. The state lives in the store:
 * no emit.
 */
const props = withDefaults(
    defineProps<{
        itemKey: string;
        label: string;
        heldLabel?: string;
        hint?: SelectionHint;
    }>(),
    { heldLabel: undefined, hint: undefined },
);

const toggle = useSelectionToggle();
const reasonId = useId();
const slotId = useId();

const slot = computed(() => toggle.slotOf(props.itemKey));
const held = computed(() => slot.value !== null);
const reason = computed(() =>
    held.value ? null : toggle.blockedReason([props.itemKey]),
);
const name = computed(() =>
    held.value && props.heldLabel ? props.heldLabel : props.label,
);
const describedBy = computed(() => {
    if (reason.value) return reasonId;
    return held.value ? slotId : undefined;
});

function onClick(event: Event): void {
    if (!reason.value) return;
    event.preventDefault();
    toggle.announceRefused([props.itemKey]);
}

function onChange(): void {
    if (reason.value) return;
    toggle.toggle(props.itemKey, props.hint);
}
</script>

<template>
    <label
        class="selection-checkbox"
        :class="{ held: held }"
        :title="reason ?? undefined"
    >
        <input
            type="checkbox"
            :checked="held"
            :aria-label="name"
            :aria-disabled="reason ? 'true' : undefined"
            :aria-describedby="describedBy"
            @click="onClick"
            @change="onChange"
        />
        <span
            v-if="slot"
            :id="slotId"
            class="slot"
        >
            {{ slot }}
        </span>
        <span
            v-if="reason"
            :id="reasonId"
            class="reason"
        >
            {{ reason }}
        </span>
    </label>
</template>

<style scoped>
.selection-checkbox {
    display: inline-flex;
    flex: none;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    min-inline-size: var(--explorer-target, 2.75rem);
    min-block-size: var(--explorer-target, 2.75rem);
    cursor: pointer;
}

.selection-checkbox.held {
    background: var(--selection-tint);
}

.selection-checkbox input {
    inline-size: 1.125rem;
    block-size: 1.125rem;
    margin: 0;
    accent-color: var(--blue-text);
    cursor: inherit;
}

.selection-checkbox input[aria-disabled="true"] {
    appearance: none;
    border: 0.09375rem dashed var(--ink-dim);
    border-radius: 0.1875rem;
    background: var(--bg-alt);
    cursor: not-allowed;
}

.selection-checkbox input:focus-visible {
    outline: 0.125rem solid var(--blue-text);
    outline-offset: 0.125rem;
}

.selection-checkbox .slot {
    color: var(--ink-muted);
    font-family: var(--font-mono);
    font-size: 0.6875rem;
    line-height: 1;
}

.selection-checkbox .reason {
    position: absolute;
    inline-size: 0.0625rem;
    block-size: 0.0625rem;
    overflow: hidden;
    clip-path: inset(50%);
    white-space: nowrap;
}
</style>
