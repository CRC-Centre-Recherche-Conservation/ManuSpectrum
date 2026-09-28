<script setup lang="ts">
import { useLinkedMarks } from "@/manuspectrum/pages/AnalysisExplorer/composables/useLinkedMarks.ts";

import type { NodeId } from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/linked/node-id.ts";

/**
 * A value of a Compare window that can be selected: a toggle button named
 * by its text, pressed while `node` is selected, marked by how it stands
 * to the linked selection (`data-rel`) and to the node previewed
 * (`data-preview`). A click adds `node` to the selection or removes it; a
 * mouse resting on it previews what it links.
 */
const props = defineProps<{
    node: NodeId;
    text: string;
    lang?: string;
}>();

const marks = useLinkedMarks();
</script>

<template>
    <button
        type="button"
        class="linked-chip"
        :lang="props.lang"
        :data-rel="marks.rel(props.node)"
        :data-preview="marks.previewRel(props.node)"
        :aria-pressed="marks.pressed(props.node)"
        @click="marks.toggle(props.node)"
        @pointerenter="marks.enter(props.node, $event)"
        @pointerleave="marks.leave($event)"
    >
        <span>{{ props.text }}</span>
    </button>
</template>

<style scoped>
.linked-chip {
    position: relative;
    display: inline-flex;
    align-items: center;
    min-block-size: 1.5rem;
    padding-inline: 0.5rem;
    border: 0.0625rem solid var(--border-hover);
    border-radius: 999rem;
    background: var(--surface);
    color: var(--ink);
    font: inherit;
    font-size: 0.75rem;
    text-align: start;
    cursor: pointer;
}

.linked-chip:hover {
    border-color: var(--linked-mark, var(--blue-text));
}

.linked-chip:focus-visible {
    outline: 0.125rem solid var(--blue-text);
    outline-offset: 0.125rem;
}

.linked-chip[data-rel="direct"],
.linked-chip[data-rel="evidence"] {
    background: var(--linked-tint, var(--bg-alt));
}

.linked-chip[data-rel="direct"]::after,
.linked-chip[data-rel="evidence"]::after {
    position: absolute;
    inset-inline: 0.5rem;
    inset-block-end: 0.125rem;
    border-block-end: 0.125rem solid var(--linked-mark, var(--blue-text));
    content: "";
}

.linked-chip[data-rel="evidence"]::after {
    border-block-end-style: dashed;
}

.linked-chip[data-rel="none"] {
    border-color: var(--border);
    color: var(--ink-muted);
}

.linked-chip[aria-pressed="true"] {
    outline: 0.125rem solid var(--linked-mark, var(--blue-text));
    outline-offset: 0.0625rem;
    border-color: var(--linked-mark, var(--blue-text));
    background: var(--linked-tint, var(--bg-alt));
    font-weight: 600;
}

.linked-chip[data-preview] {
    outline: 0.125rem dashed var(--linked-mark, var(--blue-text));
    outline-offset: 0.0625rem;
}
</style>
