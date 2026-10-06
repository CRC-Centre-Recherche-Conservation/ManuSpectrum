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
    gap: 0.375rem;
    min-inline-size: 0;
    margin: 0;
    padding: 0.5rem;
    border: 0.0625rem solid var(--border);
    border-radius: 0.375rem;
    background: var(--surface);
    font-size: 0.8125rem;
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

.pane-filters .row {
    display: grid;
    grid-template-columns: 6rem minmax(0, 1fr) 2.5rem;
    align-items: center;
    gap: 0.5rem;
}

.pane-filters .row.greyscale {
    display: flex;
    gap: 0.5rem;
}

.pane-filters output {
    font-family: var(--font-mono);
    text-align: end;
}

.pane-filters .actions {
    display: flex;
    flex-wrap: wrap;
    gap: 0.5rem;
}

.pane-filters .actions button {
    min-block-size: var(--explorer-target, 2.75rem);
    padding-inline: 0.75rem;
    border: none;
    border-radius: 0.375rem;
    background: var(--bg-alt);
    color: var(--ink);
    font: inherit;
    font-weight: 600;
    cursor: pointer;
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
