<script setup lang="ts">
import FocusPip from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/components/FocusPip.vue";

import { useLinkedMarks } from "@/manuspectrum/pages/AnalysisExplorer/composables/useLinkedMarks.ts";

import type { NodeId } from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/linked/node-id.ts";

/**
 * A value of a Compare window that can be pinned: a toggle button named
 * by its text, pressed while `node` is pinned, marked by how it stands to
 * the focus and to the node previewed (`useLinkedMarks().focus`, the
 * `ms-focus` recipes: ring, pip, bloom, ghost ring). A click pins `node`
 * or unpins it; a mouse resting on it previews what it links. The slot
 * `lead` goes before the text (a glyph).
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
        class="linked-chip ms-focus"
        v-bind="marks.focus(props.node)"
        :lang="props.lang"
        :aria-pressed="marks.pressed(props.node)"
        @click="marks.toggle(props.node)"
        @pointerenter="marks.enter(props.node, $event)"
        @pointerleave="marks.leave($event)"
    >
        <FocusPip :node="props.node" />
        <slot name="lead" />
        <span
            class="text"
            :title="props.text"
            >{{ props.text }}</span
        >
    </button>
</template>

<style scoped>
.linked-chip {
    --r: 999rem;
    --link-pip: 0.8125rem;
    display: inline-flex;
    align-items: center;
    gap: 0.3125rem;
    min-block-size: 1.5rem;
    padding-inline: 0.5rem;
    border: 0.0625rem solid var(--border-hover);
    border-radius: 999rem;
    background: var(--surface);
    color: var(--ink);
    font: inherit;
    font-size: 0.75rem;
    max-inline-size: 16rem;
    text-align: start;
    white-space: nowrap;
    cursor: pointer;
}

.linked-chip .text {
    overflow: hidden;
    text-overflow: ellipsis;
}

.linked-chip:hover {
    border-color: var(--ink-dim);
}

.linked-chip:focus-visible {
    outline: 0.125rem solid var(--blue-text);
    outline-offset: 0.1875rem;
}

.linked-chip:is([data-rel="self"], [data-rel="direct"], [data-rel="evidence"]) {
    background: color-mix(
        in srgb,
        var(--h1, var(--focus-1)) 7%,
        var(--surface)
    );
}

.linked-chip[data-rel="none"] {
    border-color: var(--border);
}
</style>
