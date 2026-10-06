<script setup lang="ts">
import { computed, useId } from "vue";
import { useGettext } from "vue3-gettext";

import { isNeutral } from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/pane-filters.ts";

import type { PaneFilters } from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/light-table.ts";

type RangeKey = "brightness" | "contrast" | "saturation";

const RANGE_MIN = 0;
const RANGE_MAX = 200;
const RANGE_STEP = 5;

/**
 * The filters of one pane: brightness, contrast and saturation on a 0 to
 * 200 range (100 is neutral, as in the IIIF viewer), greyscale, a reset and
 * « Apply to every pane ». The pane owner holds the values and draws them.
 */
const props = defineProps<{
    filters: PaneFilters;
    letter: string;
}>();

const emit = defineEmits<{
    (event: "change", payload: Partial<PaneFilters>): void;
    (event: "reset"): void;
    (event: "apply-all"): void;
}>();

const { $gettext, interpolate } = useGettext();
const prefix = useId();

const neutral = computed(() => isNeutral(props.filters));
const slot = computed(() => (props.letter.length === 1 ? props.letter : ""));

const ranges: { key: RangeKey; label: () => string }[] = [
    { key: "brightness", label: () => $gettext("Brightness") },
    { key: "contrast", label: () => $gettext("Contrast") },
    { key: "saturation", label: () => $gettext("Saturation") },
];

function onRange(key: RangeKey, event: Event): void {
    const value = Number((event.target as HTMLInputElement).value);
    if (Number.isFinite(value)) emit("change", { [key]: value });
}

function onGreyscale(event: Event): void {
    emit("change", { greyscale: (event.target as HTMLInputElement).checked });
}
</script>

<template>
    <fieldset
        class="pane-filters"
        :aria-label="
            interpolate(
                $gettext('Filters of pane %{letter}'),
                {
                    letter: props.letter,
                },
                true,
            )
        "
    >
        <div class="title">
            <span>{{ $gettext("Filters") }}</span>
            <b
                v-if="slot"
                class="slot"
                >{{ slot }}</b
            >
        </div>
        <div
            v-for="range in ranges"
            :key="range.key"
            class="row"
        >
            <label :for="`${prefix}-${range.key}`">{{ range.label() }}</label>
            <input
                :id="`${prefix}-${range.key}`"
                type="range"
                :min="RANGE_MIN"
                :max="RANGE_MAX"
                :step="RANGE_STEP"
                :value="props.filters[range.key]"
                @input="onRange(range.key, $event)"
            />
            <output :for="`${prefix}-${range.key}`">{{
                props.filters[range.key]
            }}</output>
        </div>
        <label class="row greyscale">
            <input
                type="checkbox"
                :checked="props.filters.greyscale"
                @change="onGreyscale"
            />
            <span>{{ $gettext("Greyscale") }}</span>
        </label>
        <div class="actions">
            <button
                type="button"
                data-action="reset"
                :disabled="neutral"
                @click="emit('reset')"
            >
                <span>{{ $gettext("Reset") }}</span>
            </button>
            <button
                type="button"
                data-action="apply-all"
                @click="emit('apply-all')"
            >
                <span>{{ $gettext("Apply to every pane") }}</span>
            </button>
        </div>
    </fieldset>
</template>

<style scoped>
.pane-filters {
    display: grid;
    gap: 0.5rem;
    min-inline-size: 0;
    margin: 0;
    padding: 0.75rem;
    border: 0.0625rem solid var(--border-hover);
    border-radius: 0.625rem;
    background: var(--surface);
    color: var(--ink);
    font-size: 0.75rem;
}

@media (max-width: 48rem) {
    .pane-filters {
        position: fixed;
        inset-inline: 0;
        inset-block-end: 0;
        z-index: 20;
        max-block-size: 60vh;
        overflow-y: auto;
        border-radius: 0.75rem 0.75rem 0 0;
        box-shadow: 0 -0.25rem 1rem rgb(0 0 0 / 25%);
    }
}

.pane-filters .title {
    display: flex;
    align-items: center;
    gap: 0.375rem;
    font: 600 0.9375rem var(--font-display);
}

.pane-filters .title .slot {
    display: inline-grid;
    place-items: center;
    inline-size: 1.125rem;
    block-size: 1.125rem;
    border-radius: 999rem;
    background: var(--ink);
    color: var(--surface);
    font: 600 0.6875rem var(--font-mono);
}

.pane-filters .row {
    display: grid;
    grid-template-columns: 4.5rem minmax(0, 1fr) 2.25rem;
    align-items: center;
    gap: 0.5rem;
}

.pane-filters .row.greyscale {
    display: flex;
    align-items: center;
    gap: 0.5rem;
    color: var(--ink-muted);
}

.pane-filters input[type="range"] {
    inline-size: 100%;
    accent-color: var(--accent);
}

.pane-filters input[type="checkbox"] {
    appearance: none;
    position: relative;
    flex: none;
    inline-size: 1.875rem;
    block-size: 1.0625rem;
    border-radius: 999rem;
    background: var(--ink-dim);
    cursor: pointer;
}

.pane-filters input[type="checkbox"]::after {
    position: absolute;
    inset-block-start: 0.125rem;
    inset-inline-start: 0.125rem;
    inline-size: 0.8125rem;
    block-size: 0.8125rem;
    border-radius: 50%;
    background: var(--surface);
    content: "";
}

.pane-filters input[type="checkbox"]:checked {
    background: var(--accent);
}

.pane-filters input[type="checkbox"]:checked::after {
    inset-inline-start: 0.9375rem;
}

.pane-filters output {
    color: var(--ink-muted);
    font: 500 0.6875rem var(--font-mono);
    text-align: end;
}

.pane-filters .actions {
    display: flex;
    flex-wrap: wrap;
    gap: 0.375rem;
}

.pane-filters .actions button {
    min-block-size: var(--explorer-target, 2rem);
    padding-inline: 0.625rem;
    border: 0.0625rem solid var(--border-hover);
    border-radius: 0.5rem;
    background: var(--surface);
    color: var(--ink);
    font: inherit;
    cursor: pointer;
}

.pane-filters .actions button:hover:not(:disabled) {
    background: var(--bg-alt);
}

.pane-filters .actions button:disabled {
    color: var(--ink-dim);
    cursor: default;
}

.pane-filters :is(input, button):focus-visible {
    outline: 0.125rem solid var(--blue-text);
    outline-offset: 0.125rem;
}
</style>
