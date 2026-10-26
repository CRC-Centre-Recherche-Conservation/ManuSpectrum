<script setup lang="ts">
import { useGettext } from "vue3-gettext";

import HomeChoices from "@/manuspectrum/pages/AnalysisExplorer/views/Corpus/components/HomeChoices.vue";

import type { FacetValue } from "@/manuspectrum/pages/AnalysisExplorer/api/types.ts";
import type { TreeNode } from "@/manuspectrum/pages/AnalysisExplorer/views/Corpus/components/facet-tree.ts";

/**
 * The buttons of one door of the explorer home, « label (count) », side by
 * side. A node with children starts its own line, its children nested and
 * indented under it, so a narrower term never sits beside the term that
 * holds it. A click emits the value's id.
 */
const props = defineProps<{ nodes: readonly TreeNode[] }>();
const emit = defineEmits<{ open: [id: string] }>();

const { $gettext, interpolate } = useGettext();

function countLabel(value: FacetValue): string {
    return interpolate(
        $gettext("%{label} (%{count})"),
        {
            label: value.label.value,
            count: value.count,
        },
        true,
    );
}
</script>

<template>
    <ul class="choices">
        <li
            v-for="node in props.nodes"
            :key="node.key"
            :class="{ branch: node.children.length > 0 }"
        >
            <button
                type="button"
                class="choice"
                :lang="node.value.label.lang"
                @click="emit('open', node.value.id)"
            >
                <span>{{ countLabel(node.value) }}</span>
            </button>
            <HomeChoices
                v-if="node.children.length > 0"
                class="nested"
                :nodes="node.children"
                @open="(id) => emit('open', id)"
            />
        </li>
    </ul>
</template>

<style scoped>
.choices {
    display: flex;
    flex-wrap: wrap;
    gap: 0.375rem;
    list-style: none;
}

.choices .branch {
    display: grid;
    flex-basis: 100%;
    justify-items: start;
    gap: 0.375rem;
}

.choices.nested {
    padding-inline-start: 1.25rem;
    border-inline-start: 0.0625rem solid var(--border);
}

.choices .choice {
    min-block-size: var(--explorer-target);
    padding-inline: 0.875rem;
    border: 0.0625rem solid var(--border-hover);
    border-radius: 999rem;
    background: var(--surface);
    color: var(--ink);
    font: inherit;
    text-align: start;
    cursor: pointer;
}

.choices .choice:hover {
    border-color: var(--ink);
}

.choices .choice:focus-visible {
    outline: 0.125rem solid var(--blue-text);
    outline-offset: 0.125rem;
}
</style>
