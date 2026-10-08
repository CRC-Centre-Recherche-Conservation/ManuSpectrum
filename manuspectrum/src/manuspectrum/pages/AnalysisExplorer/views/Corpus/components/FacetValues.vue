<script setup lang="ts">
import { useGettext } from "vue3-gettext";

import { techniqueClass } from "@/manuspectrum/pages/AnalysisExplorer/folio/techniques.ts";

import type {
    Facet,
    FacetValue,
} from "@/manuspectrum/pages/AnalysisExplorer/api/types.ts";

/**
 * The checkbox list of one facet: a technique value carries the dot of its
 * mark, a colour value the swatch the server gives it (a square with an inner
 * rim, so white and beige stay visible), an unpublished value a badge. A value
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

function dotClass(value: FacetValue): string {
    return techniqueClass("dot", value.mark?.colour ?? null);
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
                <span
                    v-if="props.facet.key === 'technique'"
                    class="dot"
                    :class="dotClass(value)"
                    aria-hidden="true"
                ></span>
                <span
                    v-else-if="value.swatch"
                    class="swatch"
                    aria-hidden="true"
                    :style="{ '--swatch': value.swatch }"
                ></span>
                <span
                    class="label"
                    :lang="value.label.lang"
                    :title="value.label.value"
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
    align-items: center;
    gap: 0.5rem;
    min-block-size: var(--explorer-target, 2.75rem);
    min-inline-size: 0;
    font-size: 0.8125rem;
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

.values .value.zero .swatch {
    opacity: 0.5;
}

.values .value input {
    flex: none;
}

.values .label {
    flex: 1 1 auto;
    min-inline-size: 0;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
}

.values .dot {
    flex: none;
    inline-size: 0.625rem;
    block-size: 0.625rem;
    border-radius: 50%;
}

.values .swatch {
    flex: none;
    inline-size: 1.125rem;
    block-size: 1.125rem;
    border-radius: 0.1875rem;
    background: var(--swatch);
    box-shadow: inset 0 0 0 0.0625rem var(--border-hover);
}

.values .dot--tech-1 {
    background: var(--tech-1);
}

.values .dot--tech-2 {
    background: var(--tech-2);
}

.values .dot--tech-3 {
    background: var(--tech-3);
}

.values .dot--tech-4 {
    background: var(--tech-4);
}

.values .dot--tech-5 {
    background: var(--tech-5);
}

.values .dot--tech-6 {
    background: var(--tech-6);
}

.values .dot--tech-7 {
    background: var(--tech-7);
}

.values .dot--tech-8 {
    background: var(--tech-8);
}

.values .dot--tech-9 {
    background: var(--tech-9);
}

.values .dot--tech-10 {
    background: var(--tech-10);
}

.values .dot--ink {
    border: 0.125rem solid var(--ink);
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
