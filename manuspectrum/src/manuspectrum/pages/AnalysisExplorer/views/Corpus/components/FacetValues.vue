<script setup lang="ts">
import { useGettext } from "vue3-gettext";

import FacetMark from "@/manuspectrum/pages/AnalysisExplorer/views/Corpus/components/FacetMark.vue";

import type {
    Facet,
    FacetValue,
} from "@/manuspectrum/pages/AnalysisExplorer/api/types.ts";

/**
 * The checkbox list of one facet: a technique value carries the dot of its
 * mark, a colour value the swatch the server gives it (`FacetMark`), an
 * unpublished value a badge. A value
 * with no hit is disabled unless it is ticked, so the reader can leave it; in
 * a `fixedList` (the colours) it is also greyed, never dropped. `values` is
 * what to show and `selected` what the filters hold. `countHint`, a text with
 * `%{n}`, says what a count counts. `busy` dims the list while the server
 * answers a search.
 */
const props = withDefaults(
    defineProps<{
        facet: Facet;
        values: FacetValue[];
        selected: readonly string[];
        countHint?: string;
        busy?: boolean;
        fixedList?: boolean;
    }>(),
    { countHint: "", busy: false, fixedList: false },
);
const emit = defineEmits<{ change: [id: string, checked: boolean] }>();

const { $gettext, interpolate } = useGettext();

function isSelected(value: FacetValue): boolean {
    return props.selected.includes(value.id);
}

function isEmpty(value: FacetValue): boolean {
    return value.count === 0 && !isSelected(value);
}

function countTitle(value: FacetValue): string | undefined {
    return props.countHint
        ? interpolate(props.countHint, { n: value.count }, true)
        : undefined;
}

function onChange(value: FacetValue, event: Event): void {
    emit("change", value.id, (event.target as HTMLInputElement).checked);
}
</script>

<template>
    <ul
        class="values"
        :class="{ busy: props.busy, fixed: props.fixedList }"
        :aria-busy="props.busy ? 'true' : 'false'"
    >
        <li
            v-for="value in props.values"
            :key="value.id"
        >
            <label
                class="value"
                :class="{
                    zero: props.fixedList && value.count === 0,
                    checked: isSelected(value),
                }"
            >
                <input
                    type="checkbox"
                    :value="value.id"
                    :checked="isSelected(value)"
                    :disabled="isEmpty(value)"
                    @change="onChange(value, $event)"
                />
                <FacetMark
                    :facet-key="props.facet.key"
                    :mark="value.mark"
                    :swatch="value.swatch"
                    :dim="props.fixedList && value.count === 0"
                />
                <span
                    class="label"
                    :lang="value.label.lang"
                    >{{ value.label.value }}</span
                >
                <span
                    v-if="value.unpublished"
                    class="unpublished"
                    >{{ $gettext("unpublished") }}</span
                >
                <span
                    class="count"
                    :title="countTitle(value)"
                    >{{ value.count }}</span
                >
            </label>
        </li>
    </ul>
</template>

<style scoped>
.values {
    display: grid;
    grid-template-columns: minmax(0, 1fr);
    list-style: none;
}

.values.busy {
    opacity: 0.6;
}

.values li {
    min-inline-size: 0;
}

.values .value {
    display: flex;
    align-items: flex-start;
    gap: 0.5rem;
    min-block-size: var(--explorer-target, 2.75rem);
    min-inline-size: 0;
    padding-block: 0.3125rem;
    font-size: 0.8125rem;
    line-height: 1.3;
    cursor: pointer;
}

.values .value:has(input:disabled) {
    color: var(--ink-dim);
    cursor: default;
}

.values.fixed .value {
    padding-inline: 0.5rem;
    border: 0.0625rem solid transparent;
    border-radius: 0.375rem;
}

.values.fixed .value.checked {
    border-color: var(--border-hover);
    background: var(--surface-soft, var(--surface));
    font-weight: 600;
}

.values .value input {
    flex: none;
    margin-block-start: 0.125rem;
}

.values .value .facet-mark {
    margin-block-start: 0.25rem;
}

.values .label {
    flex: 1 1 auto;
    min-inline-size: 0;
    overflow-wrap: break-word;
    hyphens: auto;
    hyphenate-limit-chars: 10 4 4;
    text-wrap: pretty;
}

.values .unpublished {
    flex: none;
    padding-inline: 0.375rem;
    border: 0.0625rem solid var(--accent-text);
    border-radius: 999rem;
    color: var(--accent-text);
    font-size: 0.6875rem;
}

.values .count {
    flex: none;
    min-inline-size: 2.25rem;
    padding-block-start: 0.0625rem;
    color: var(--ink-muted);
    font-family: var(--font-mono);
    font-size: 0.6875rem;
    text-align: end;
}

.values input:focus-visible {
    outline: 0.125rem solid var(--blue-text);
    outline-offset: 0.125rem;
}
</style>
