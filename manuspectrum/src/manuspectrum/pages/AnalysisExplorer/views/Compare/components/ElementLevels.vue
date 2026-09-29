<script setup lang="ts">
import { useGettext } from "vue3-gettext";

import LinkedChip from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/components/LinkedChip.vue";

import { useLinkedMarks } from "@/manuspectrum/pages/AnalysisExplorer/composables/useLinkedMarks.ts";
import { elementNode } from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/linked/node-id.ts";

import type { ValueRef } from "@/manuspectrum/pages/AnalysisExplorer/api/types.ts";
import type { ElementLevel } from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/materials.ts";

/**
 * Elements by level, one line per level, its name first. An element the
 * synthesis gives a symbol is a toggle of its node (`LinkedChip`, the
 * symbol shown, the element's label its title); the others are plain
 * text. Without an element, a dash.
 */
const props = defineProps<{ levels: readonly ElementLevel[] }>();

const { $gettext } = useGettext();
const marks = useLinkedMarks();

function symbolOf(value: ValueRef): string | null {
    return marks.linked?.graph.value.symbols.get(value.id) ?? null;
}
</script>

<template>
    <ul
        v-if="props.levels.length > 0"
        class="element-levels"
    >
        <li
            v-for="(entry, index) in props.levels"
            :key="entry.level?.id ?? `none-${index}`"
        >
            <span
                v-if="entry.level"
                class="level"
                :lang="entry.level.label.lang"
                >{{ entry.level.label.value }}</span
            >
            <template
                v-for="value in entry.values"
                :key="value.id"
            >
                <LinkedChip
                    v-if="symbolOf(value)"
                    class="element"
                    :node="elementNode(symbolOf(value)!)"
                    :text="symbolOf(value)!"
                    :title="value.label.value"
                />
                <span
                    v-else
                    class="plain"
                    :lang="value.label.lang"
                    >{{ value.label.value }}</span
                >
            </template>
        </li>
    </ul>
    <span
        v-else
        class="element-levels none"
    >
        <span aria-hidden="true">—</span>
        <span class="visually-hidden">{{ $gettext("Not stated") }}</span>
    </span>
</template>

<style scoped>
.element-levels {
    display: grid;
    gap: 0.25rem;
    margin: 0;
    padding: 0;
    list-style: none;
}

.element-levels li {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: 0.5rem 0.625rem;
}

.element-levels .level {
    min-inline-size: 2.75rem;
    color: var(--ink-muted);
    font-size: 0.6875rem;
}

.element-levels .element {
    font-family: var(--font-mono);
    font-weight: 600;
}

.element-levels .plain {
    font-size: 0.75rem;
}

.element-levels.none {
    color: var(--ink-muted);
}

.element-levels .visually-hidden {
    position: absolute;
    inline-size: 0.0625rem;
    block-size: 0.0625rem;
    overflow: hidden;
    clip-path: inset(50%);
    white-space: nowrap;
}
</style>
