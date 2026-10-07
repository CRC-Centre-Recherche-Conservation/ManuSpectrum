<script setup lang="ts">
import { computed } from "vue";
import { useGettext } from "vue3-gettext";

import { ordinal } from "@/manuspectrum/pages/AnalysisExplorer/format.ts";

type Bucket = { from: number; to: number; count: number };

const CENTURY_YEARS = 100;
const MAX_LABELS = 6;
const PERCENT = 100;
const PRECISION = 10000;

/**
 * One bar per century, proportional to its count. A bar is a button: it
 * selects its century, and is pressed when the century, cut at the bounds
 * `min` and `max` of the dated rows, lies entirely within `selected`.
 * Beyond six centuries only some carry a visible label; every bar keeps its
 * full name.
 */
const props = defineProps<{
    buckets: Bucket[];
    min: number;
    max: number;
    selected: [number, number] | null;
}>();
const emit = defineEmits<{ select: [from: number, to: number] }>();

const gettext = useGettext();
const { $gettext, $ngettext, interpolate } = gettext;

const highest = computed(() =>
    Math.max(1, ...props.buckets.map((bucket) => bucket.count)),
);
const labelEvery = computed(() =>
    Math.max(1, Math.ceil(props.buckets.length / MAX_LABELS)),
);

function centuryOf(bucket: Bucket): number {
    return Math.ceil(bucket.to / CENTURY_YEARS);
}

function share(bucket: Bucket): number {
    return (
        Math.round((bucket.count / highest.value) * PERCENT * PRECISION) /
        PRECISION
    );
}

function isPressed(bucket: Bucket): boolean {
    if (!props.selected) return false;
    return (
        Math.max(bucket.from, props.min) >= props.selected[0] &&
        Math.min(bucket.to, props.max) <= props.selected[1]
    );
}

function isLabelled(index: number): boolean {
    return index % labelEvery.value === 0;
}

function nameOf(bucket: Bucket): string {
    return interpolate(
        $ngettext(
            "%{century} century: %{n} analysis",
            "%{century} century: %{n} analyses",
            bucket.count,
        ),
        {
            century: ordinal(centuryOf(bucket), gettext.current),
            n: bucket.count,
        },
        true,
    );
}
</script>

<template>
    <div
        class="century-histogram"
        role="group"
        :aria-label="$gettext('Analyses by century')"
    >
        <button
            v-for="(bucket, index) in props.buckets"
            :key="bucket.from"
            type="button"
            class="century"
            :title="nameOf(bucket)"
            :aria-label="nameOf(bucket)"
            :aria-pressed="isPressed(bucket) ? 'true' : 'false'"
            @click="emit('select', bucket.from, bucket.to)"
        >
            <span class="well">
                <span
                    class="bar"
                    :class="{ idle: props.selected === null }"
                    :style="{ '--bar': `${share(bucket)}%` }"
                ></span>
            </span>
            <span
                class="label"
                :class="{ quiet: !isLabelled(index) }"
                aria-hidden="true"
                >{{ ordinal(centuryOf(bucket), gettext.current) }}</span
            >
        </button>
    </div>
</template>

<style scoped>
.century-histogram {
    display: flex;
    gap: 0.125rem;
    align-items: stretch;
    block-size: 5.5rem;
}

.century-histogram .century {
    display: flex;
    flex: 1 1 0;
    flex-direction: column;
    justify-content: flex-end;
    gap: 0.25rem;
    min-inline-size: 0;
    padding: 0;
    border: none;
    background: transparent;
    cursor: pointer;
}

.century-histogram .well {
    display: flex;
    flex: 1 1 auto;
    align-items: flex-end;
}

.century-histogram .bar {
    display: block;
    inline-size: 100%;
    block-size: var(--bar);
    min-block-size: 0.125rem;
    border-radius: 0.125rem 0.125rem 0 0;
    background: var(--ink-dim);
}

.century-histogram .bar.idle {
    background: var(--ink-muted);
}

.century-histogram .century[aria-pressed="true"] .bar {
    background: var(--blue-text);
}

.century-histogram .label {
    color: var(--ink-muted);
    font-family: var(--font-mono);
    font-size: 0.625rem;
    text-align: center;
}

.century-histogram .label.quiet {
    visibility: hidden;
}

.century-histogram .century:hover .bar {
    background: var(--blue-text);
}

.century-histogram .century:focus-visible {
    outline: 0.125rem solid var(--blue-text);
    outline-offset: 0.125rem;
}
</style>
