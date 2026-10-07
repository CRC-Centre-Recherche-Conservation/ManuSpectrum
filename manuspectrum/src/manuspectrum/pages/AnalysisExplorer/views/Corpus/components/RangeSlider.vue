<script setup lang="ts">
import { computed, ref, useTemplateRef } from "vue";
import { useGettext } from "vue3-gettext";

import { formatProductionDate } from "@/manuspectrum/pages/AnalysisExplorer/format.ts";

type Thumb = "low" | "high";

const ARROW_STEP = 1;
const PAGE_STEP = 25;
const CENTURY_YEARS = 100;
const SHARE_PERCENT = 100;
const KEY_STEPS: Readonly<Record<string, number>> = {
    ArrowRight: ARROW_STEP,
    ArrowUp: ARROW_STEP,
    ArrowLeft: -ARROW_STEP,
    ArrowDown: -ARROW_STEP,
    PageUp: PAGE_STEP,
    PageDown: -PAGE_STEP,
};

/**
 * A range of whole years with two thumbs, each a `role="slider"`: arrows move
 * a year, Page keys 25, Home and End jump to the bound; the lower thumb never
 * passes the higher one. `input` follows a drag, `change` ends it (a key press
 * sends both). The track is read by the pointer, one captured thumb at a time.
 */
const props = defineProps<{
    min: number;
    max: number;
    value: [number, number];
}>();
const emit = defineEmits<{
    input: [value: [number, number]];
    change: [value: [number, number]];
}>();

const gettext = useGettext();
const { $gettext, interpolate } = gettext;

const track = useTemplateRef<HTMLElement>("track");
const held = ref<Thumb | null>(null);

const span = computed(() => Math.max(1, props.max - props.min));
const lowAt = computed(() => share(props.value[0]));
const highAt = computed(() => share(props.value[1]));

function share(year: number): number {
    return (
        Math.round(((year - props.min) / span.value) * SHARE_PERCENT * 100) /
        100
    );
}

function clamp(thumb: Thumb, year: number): number {
    return thumb === "low"
        ? Math.min(Math.max(year, props.min), props.value[1])
        : Math.max(Math.min(year, props.max), props.value[0]);
}

function withThumb(thumb: Thumb, year: number): [number, number] {
    const next = clamp(thumb, Math.round(year));
    return thumb === "low" ? [next, props.value[1]] : [props.value[0], next];
}

/** « 1300, 14th century »: the century says where a year falls on the timeline. */
function valueText(year: number): string {
    if (year < 1) return String(year);
    const first = Math.floor((year - 1) / CENTURY_YEARS) * CENTURY_YEARS + 1;
    const century = formatProductionDate(
        {
            start: String(first),
            end: String(first + CENTURY_YEARS - 1),
            approximate: false,
        },
        $gettext,
        interpolate,
        gettext.current,
    );
    return interpolate(
        $gettext("%{year}, %{century}"),
        { year, century },
        true,
    );
}

function labelOf(thumb: Thumb): string {
    return thumb === "low"
        ? $gettext("Earliest year")
        : $gettext("Latest year");
}

function boundsOf(thumb: Thumb): [number, number] {
    return thumb === "low"
        ? [props.min, props.value[1]]
        : [props.value[0], props.max];
}

function onKeydown(thumb: Thumb, event: KeyboardEvent): void {
    const current = thumb === "low" ? props.value[0] : props.value[1];
    let target: number;
    if (event.key === "Home") {
        target = props.min;
    } else if (event.key === "End") {
        target = props.max;
    } else if (event.key in KEY_STEPS) {
        target = current + KEY_STEPS[event.key];
    } else {
        return;
    }
    event.preventDefault();
    const next = withThumb(thumb, target);
    emit("input", next);
    emit("change", next);
}

function yearAt(clientX: number): number | null {
    const rect = track.value?.getBoundingClientRect();
    if (!rect || rect.width <= 0) return null;
    const ratio = Math.min(1, Math.max(0, (clientX - rect.left) / rect.width));
    return props.min + ratio * span.value;
}

function onPointerdown(thumb: Thumb, event: PointerEvent): void {
    held.value = thumb;
    const target = event.currentTarget as HTMLElement | null;
    target?.setPointerCapture?.(event.pointerId);
}

function onPointermove(thumb: Thumb, event: PointerEvent): void {
    if (held.value !== thumb) return;
    const year = yearAt(event.clientX);
    if (year !== null) emit("input", withThumb(thumb, year));
}

function onPointerup(thumb: Thumb, event: PointerEvent): void {
    if (held.value !== thumb) return;
    held.value = null;
    const year = yearAt(event.clientX);
    if (year !== null) emit("change", withThumb(thumb, year));
}
</script>

<template>
    <div class="range-slider">
        <div
            ref="track"
            class="track"
            :style="{ '--from': `${lowAt}%`, '--to': `${highAt}%` }"
        ></div>
        <div
            v-for="thumb in ['low', 'high'] as Thumb[]"
            :key="thumb"
            class="thumb"
            role="slider"
            tabindex="0"
            :aria-label="labelOf(thumb)"
            :aria-valuemin="boundsOf(thumb)[0]"
            :aria-valuemax="boundsOf(thumb)[1]"
            :aria-valuenow="thumb === 'low' ? props.value[0] : props.value[1]"
            :aria-valuetext="
                valueText(thumb === 'low' ? props.value[0] : props.value[1])
            "
            :style="{ '--at': `${thumb === 'low' ? lowAt : highAt}%` }"
            @keydown="onKeydown(thumb, $event)"
            @pointerdown="onPointerdown(thumb, $event)"
            @pointermove="onPointermove(thumb, $event)"
            @pointerup="onPointerup(thumb, $event)"
            @pointercancel="held = null"
        ></div>
    </div>
</template>

<style scoped>
.range-slider {
    position: relative;
    block-size: 2rem;
    margin-inline: 0.75rem;
    touch-action: none;
}

.range-slider .track {
    position: absolute;
    inset-inline: 0;
    inset-block-start: 50%;
    block-size: 0.25rem;
    border-radius: 0.125rem;
    background: linear-gradient(
        to right,
        var(--border-hover) var(--from),
        var(--blue-text) var(--from),
        var(--blue-text) var(--to),
        var(--border-hover) var(--to)
    );
}

.range-slider .thumb {
    position: absolute;
    inset-inline-start: var(--at);
    inset-block-start: 50%;
    box-sizing: border-box;
    inline-size: 1.5rem;
    block-size: 1.5rem;
    margin-inline-start: -0.75rem;
    margin-block-start: -0.75rem;
    border: 0.125rem solid var(--blue-text);
    border-radius: 50%;
    background: var(--surface);
    cursor: grab;
}

.range-slider .thumb:focus-visible {
    outline: 0.125rem solid var(--blue-text);
    outline-offset: 0.125rem;
}
</style>
