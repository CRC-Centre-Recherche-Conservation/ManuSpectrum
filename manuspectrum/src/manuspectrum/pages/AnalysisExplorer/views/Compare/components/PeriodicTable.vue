<script setup lang="ts">
import { computed } from "vue";
import { useGettext } from "vue3-gettext";

import { useLinkedMarks } from "@/manuspectrum/pages/AnalysisExplorer/composables/useLinkedMarks.ts";
import { elementNode } from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/linked/node-id.ts";
import {
    PERIODIC_TABLE,
    placeOf,
} from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/periodic.ts";

import type { SynthesisElement } from "@/manuspectrum/pages/AnalysisExplorer/api/types.ts";

/**
 * The elements of the Selection's identified materials on the standard
 * 18-column periodic table: an element found is a toggle button showing its
 * count, named « Cu, 5 », pressed while it is selected (`el:`), marked
 * by how it stands to the linked selection and to the node a mouse
 * previews; a click adds it to the selection or removes it. The others are
 * greyed and left to assistive technologies. An element the table does not
 * hold is listed after it. In a window narrower than the table's 18
 * columns (34rem) the table gives way to a list of the elements found,
 * most frequent first, with their best level.
 */
const props = defineProps<{
    elements: readonly SynthesisElement[];
    /** Marks every toggle `aria-disabled` and inert (a stale table while the next one is read). */
    disabled?: boolean;
}>();

const { $gettext } = useGettext();
const marks = useLinkedMarks();

const bySymbol = computed(
    () => new Map(props.elements.map((element) => [element.symbol, element])),
);
const outside = computed(() =>
    props.elements.filter((element) => placeOf(element.symbol) === null),
);

function elementLabel(element: SynthesisElement): string {
    return `${element.symbol}, ${element.count}`;
}

function toggle(symbol: string): void {
    if (!props.disabled) marks.toggle(elementNode(symbol));
}
</script>

<template>
    <div class="periodic-table">
        <div
            class="grid"
            role="group"
            :aria-label="$gettext('Periodic table of the elements found')"
        >
            <template
                v-for="place in PERIODIC_TABLE"
                :key="place.symbol"
            >
                <button
                    v-if="bySymbol.get(place.symbol)"
                    type="button"
                    class="cell found"
                    :class="[`row-${place.row}`, `column-${place.column}`]"
                    :aria-label="elementLabel(bySymbol.get(place.symbol)!)"
                    :data-rel="marks.rel(elementNode(place.symbol))"
                    :data-preview="marks.previewRel(elementNode(place.symbol))"
                    :aria-pressed="marks.pressed(elementNode(place.symbol))"
                    :aria-disabled="props.disabled ? 'true' : undefined"
                    @click="toggle(place.symbol)"
                    @pointerenter="
                        marks.enter(elementNode(place.symbol), $event)
                    "
                    @pointerleave="marks.leave($event)"
                >
                    <span class="symbol">{{ place.symbol }}</span>
                    <span class="count">{{
                        bySymbol.get(place.symbol)!.count
                    }}</span>
                </button>
                <span
                    v-else
                    class="cell"
                    :class="[`row-${place.row}`, `column-${place.column}`]"
                    aria-hidden="true"
                    >{{ place.symbol }}</span
                >
            </template>
        </div>
        <ul
            v-if="outside.length > 0"
            class="others"
            :aria-label="$gettext('Elements outside the table')"
        >
            <li
                v-for="element in outside"
                :key="element.symbol"
            >
                <button
                    type="button"
                    class="found"
                    :aria-label="elementLabel(element)"
                    :data-rel="marks.rel(elementNode(element.symbol))"
                    :data-preview="
                        marks.previewRel(elementNode(element.symbol))
                    "
                    :aria-pressed="marks.pressed(elementNode(element.symbol))"
                    :aria-disabled="props.disabled ? 'true' : undefined"
                    @click="toggle(element.symbol)"
                    @pointerenter="
                        marks.enter(elementNode(element.symbol), $event)
                    "
                    @pointerleave="marks.leave($event)"
                >
                    <span class="symbol">{{ element.symbol }}</span>
                    <span class="count">{{ element.count }}</span>
                </button>
            </li>
        </ul>
        <ul
            class="list"
            :aria-label="$gettext('Elements found')"
        >
            <li
                v-for="element in props.elements"
                :key="element.symbol"
            >
                <button
                    type="button"
                    class="found"
                    :aria-label="elementLabel(element)"
                    :data-rel="marks.rel(elementNode(element.symbol))"
                    :data-preview="
                        marks.previewRel(elementNode(element.symbol))
                    "
                    :aria-pressed="marks.pressed(elementNode(element.symbol))"
                    :aria-disabled="props.disabled ? 'true' : undefined"
                    @click="toggle(element.symbol)"
                    @pointerenter="
                        marks.enter(elementNode(element.symbol), $event)
                    "
                    @pointerleave="marks.leave($event)"
                >
                    <span class="symbol">{{ element.symbol }}</span>
                    <span class="count">{{ element.count }}</span>
                    <span
                        v-if="element.level"
                        class="level"
                        :lang="element.level.label.lang"
                        >{{ element.level.label.value }}</span
                    >
                </button>
            </li>
        </ul>
    </div>
</template>

<style scoped>
.periodic-table {
    display: grid;
    gap: 0.5rem;
    container-type: inline-size;
}

.periodic-table .grid {
    display: grid;
    grid-template-columns: repeat(18, minmax(1.75rem, 1fr));
    grid-template-rows: repeat(7, auto) 0.5rem repeat(2, auto);
    gap: 0.125rem;
}

.periodic-table .cell {
    display: grid;
    place-items: center;
    min-block-size: 2rem;
    border: 0.0625rem solid var(--border);
    border-radius: 0.1875rem;
    color: var(--ink-muted);
    font: 0.6875rem var(--font-mono);
    opacity: 0.55;
}

.periodic-table .found {
    display: grid;
    place-items: center;
    padding: 0.125rem;
    border: 0.0625rem solid var(--border-hover);
    border-radius: 0.1875rem;
    background: var(--surface);
    color: var(--ink);
    font: 600 0.75rem var(--font-mono);
    opacity: 1;
    cursor: pointer;
}

.periodic-table .found[aria-pressed="true"] {
    border-color: var(--ink);
    outline: 0.125rem solid var(--linked-mark, var(--blue-text));
    outline-offset: 0.0625rem;
    background: var(--ink);
    color: var(--surface);
}

.periodic-table .found[data-rel="direct"] {
    border-color: var(--linked-mark, var(--blue-text));
    box-shadow: inset 0 0 0 0.125rem var(--linked-mark, var(--blue-text));
}

.periodic-table .found[data-rel="evidence"] {
    border: 0.0625rem dashed var(--linked-mark, var(--blue-text));
    box-shadow: inset 0 0 0 0.0625rem var(--linked-mark, var(--blue-text));
}

.periodic-table .found[data-rel="none"] {
    border-color: var(--border);
    color: var(--ink-muted);
}

.periodic-table .found[data-preview] {
    outline: 0.125rem dashed var(--linked-mark, var(--blue-text));
    outline-offset: 0.0625rem;
}

.periodic-table .found[aria-disabled="true"] {
    cursor: default;
}

.periodic-table .found:focus-visible {
    outline: 0.125rem solid var(--blue-text);
    outline-offset: 0.125rem;
}

.periodic-table .found .count {
    font-weight: 400;
    font-size: 0.625rem;
}

.periodic-table .others,
.periodic-table .list {
    display: flex;
    flex-wrap: wrap;
    gap: 0.25rem;
    margin: 0;
    padding: 0;
    list-style: none;
}

.periodic-table .others .found,
.periodic-table .list .found {
    display: inline-flex;
    align-items: baseline;
    gap: 0.375rem;
    min-block-size: var(--explorer-target, 2.75rem);
    padding-inline: 0.5rem;
}

.periodic-table .list .level {
    color: inherit;
    font: 400 0.75rem var(--font-body);
}

.periodic-table .list {
    display: none;
}

@container (max-width: 33.99rem) {
    .periodic-table .grid,
    .periodic-table .others {
        display: none;
    }

    .periodic-table .list {
        display: flex;
        flex-direction: column;
    }
}

.periodic-table .row-1 {
    grid-row: 1;
}

.periodic-table .row-2 {
    grid-row: 2;
}

.periodic-table .row-3 {
    grid-row: 3;
}

.periodic-table .row-4 {
    grid-row: 4;
}

.periodic-table .row-5 {
    grid-row: 5;
}

.periodic-table .row-6 {
    grid-row: 6;
}

.periodic-table .row-7 {
    grid-row: 7;
}

.periodic-table .row-9 {
    grid-row: 9;
}

.periodic-table .row-10 {
    grid-row: 10;
}

.periodic-table .column-1 {
    grid-column: 1;
}

.periodic-table .column-2 {
    grid-column: 2;
}

.periodic-table .column-3 {
    grid-column: 3;
}

.periodic-table .column-4 {
    grid-column: 4;
}

.periodic-table .column-5 {
    grid-column: 5;
}

.periodic-table .column-6 {
    grid-column: 6;
}

.periodic-table .column-7 {
    grid-column: 7;
}

.periodic-table .column-8 {
    grid-column: 8;
}

.periodic-table .column-9 {
    grid-column: 9;
}

.periodic-table .column-10 {
    grid-column: 10;
}

.periodic-table .column-11 {
    grid-column: 11;
}

.periodic-table .column-12 {
    grid-column: 12;
}

.periodic-table .column-13 {
    grid-column: 13;
}

.periodic-table .column-14 {
    grid-column: 14;
}

.periodic-table .column-15 {
    grid-column: 15;
}

.periodic-table .column-16 {
    grid-column: 16;
}

.periodic-table .column-17 {
    grid-column: 17;
}

.periodic-table .column-18 {
    grid-column: 18;
}
</style>
