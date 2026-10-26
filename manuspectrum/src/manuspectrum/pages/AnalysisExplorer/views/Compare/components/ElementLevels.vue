<script setup lang="ts">
import { useGettext } from "vue3-gettext";

import LinkedChip from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/components/LinkedChip.vue";

import { useLinkedMarks } from "@/manuspectrum/pages/AnalysisExplorer/composables/useLinkedMarks.ts";
import { elementNode } from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/linked/node-id.ts";

import type { ValueRef } from "@/manuspectrum/pages/AnalysisExplorer/api/types.ts";
import type { ElementLevel } from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/materials.ts";

/** The look of a level, by its rank in the list (0 the strongest). */
const LEVEL_LOOKS = ["major", "minor", "trace"] as const;

/**
 * Elements by level on one wrapping line, each level kept whole: its name
 * as stored, then its elements. An element the synthesis gives a symbol
 * is a toggle of its node (`LinkedChip`, the symbol shown, the element's
 * label its title); the others are plain text. A level's look
 * (`data-level`: major, minor, trace) follows its rank, never its label;
 * a rank past the third, or no level, has none. Without an element, a
 * dash.
 */
const props = defineProps<{ levels: readonly ElementLevel[] }>();

const { $gettext } = useGettext();
const marks = useLinkedMarks();

function symbolOf(value: ValueRef): string | null {
    return marks.linked?.graph.value.symbols.get(value.id) ?? null;
}

function lookOf(entry: ElementLevel): string | undefined {
    return entry.level ? LEVEL_LOOKS[entry.level.rank] : undefined;
}
</script>

<template>
    <div
        v-if="props.levels.length > 0"
        class="element-levels"
    >
        <span
            v-for="(entry, index) in props.levels"
            :key="entry.level?.id ?? `none-${index}`"
            class="level-group"
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
                    :data-level="lookOf(entry)"
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
        </span>
    </div>
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
    --focus-room: 0.625rem;

    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: 0.6875rem 0.625rem;
    padding-block-start: 0.125rem;
}

.element-levels .level-group {
    display: inline-flex;
    align-items: center;
    gap: 0.1875rem;
}

.element-levels .level {
    margin-inline-end: 0.125rem;
    color: var(--ink-muted);
    font-size: 0.6875rem;
    font-variant: all-small-caps;
    letter-spacing: 0.04em;
}

.element-levels .element {
    --r: 0.3125rem;
    --preview-inset: 0.1875rem;
    --link-pip: 0.75rem;
    justify-content: center;
    min-inline-size: 1.625rem;
    min-block-size: 1.5rem;
    padding-inline: 0.25rem;
    border-radius: 0.3125rem;
    font-family: var(--font-mono);
    font-weight: 600;
    line-height: 1;
}

.element-levels .element[data-level="major"] {
    --cell-heat: var(--heat-1);
    border-color: var(--mt-rule);
    background: var(--heat-1);
}

.element-levels .element[data-level="trace"] {
    background: repeating-linear-gradient(
            135deg,
            transparent 0 0.1875rem,
            rgb(26 26 46 / 0.035) 0.1875rem 0.25rem
        ),
        var(--surface);
    color: var(--ink-muted);
    font-weight: 500;
}

.element-levels .plain {
    font-size: 0.75rem;
}

.element-levels.none {
    color: var(--ink-dim);
}

.element-levels .visually-hidden {
    position: absolute;
    inline-size: 0.0625rem;
    block-size: 0.0625rem;
    overflow: hidden;
    clip-path: inset(50%);
    white-space: nowrap;
}

@media (forced-colors: active) {
    .element-levels .element[data-level="major"] {
        border-width: 0.125rem;
    }
}
</style>
