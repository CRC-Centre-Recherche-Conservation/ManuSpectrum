<script setup lang="ts">
import { computed, useId } from "vue";
import { useGettext } from "vue3-gettext";

import type { WindowSize } from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/types.ts";

const SIZE_NAMES: readonly WindowSize[] = ["S", "M", "L"];

/**
 * The frame of one Compare window: its title, a drag handle, and the
 * keyboard equivalents of dragging (move before or after, sizes, close),
 * and a disclosure button for a window that folds to its header, named by
 * the title, its state in `aria-expanded`. The group of controls is named
 * after the title too.
 * `position` is 1-based in reading order; `size` is null for a size set by
 * hand.
 */
const props = defineProps<{
    title: string;
    position: number;
    total: number;
    size: WindowSize | null;
    /** Folded to its header; null: this window does not fold. */
    folded: boolean | null;
}>();

const emit = defineEmits<{
    (event: "move", payload: { step: -1 | 1 }): void;
    (event: "size-chosen", payload: { size: WindowSize }): void;
    (event: "fold-toggled"): void;
    (event: "close"): void;
}>();

const { $gettext, interpolate } = useGettext();

const headingId = useId();
const bodyId = useId();

const isFirst = computed(() => props.position <= 1);
const isLast = computed(() => props.position >= props.total);
const controlsLabel = computed(() =>
    interpolate($gettext("Arrange « %{title} »"), { title: props.title }, true),
);

function sizeLabel(size: WindowSize): string {
    return interpolate($gettext("Size %{size}"), { size }, true);
}

function onMove(step: -1 | 1): void {
    if ((step < 0 && isFirst.value) || (step > 0 && isLast.value)) return;
    emit("move", { step });
}
</script>

<template>
    <section
        class="compare-window"
        tabindex="-1"
        :aria-labelledby="headingId"
    >
        <header class="head">
            <span
                class="grab"
                aria-hidden="true"
                >⠿</span
            >
            <h3
                :id="headingId"
                class="title"
            >
                <span>{{ title }}</span>
            </h3>
            <button
                v-if="folded !== null"
                type="button"
                class="fold"
                data-action="fold"
                :aria-label="title"
                :aria-expanded="folded ? 'false' : 'true'"
                :aria-controls="bodyId"
                @click="emit('fold-toggled')"
            >
                <span aria-hidden="true">{{ folded ? "▸" : "▾" }}</span>
            </button>
            <div
                class="controls"
                role="group"
                :aria-label="controlsLabel"
            >
                <button
                    type="button"
                    data-action="move-before"
                    :aria-label="$gettext('Move before')"
                    :aria-disabled="isFirst ? 'true' : 'false'"
                    @click="onMove(-1)"
                >
                    <span aria-hidden="true">←</span>
                </button>
                <button
                    type="button"
                    data-action="move-after"
                    :aria-label="$gettext('Move after')"
                    :aria-disabled="isLast ? 'true' : 'false'"
                    @click="onMove(1)"
                >
                    <span aria-hidden="true">→</span>
                </button>
                <button
                    v-for="name in SIZE_NAMES"
                    :key="name"
                    type="button"
                    :data-action="`size-${name}`"
                    :aria-label="sizeLabel(name)"
                    :aria-pressed="size === name ? 'true' : 'false'"
                    @click="emit('size-chosen', { size: name })"
                >
                    <span>{{ name }}</span>
                </button>
                <button
                    type="button"
                    data-action="close"
                    :aria-label="$gettext('Close')"
                    @click="emit('close')"
                >
                    <span aria-hidden="true">×</span>
                </button>
            </div>
        </header>
        <div
            :id="bodyId"
            class="body"
            :hidden="folded === true"
        >
            <slot v-if="!folded" />
        </div>
    </section>
</template>

<style scoped>
.compare-window {
    display: grid;
    grid-template-rows: auto minmax(0, 1fr);
    block-size: 100%;
    border: 0.0625rem solid var(--border-hover);
    border-radius: var(--explorer-radius, 0.625rem);
    background: var(--surface);
    overflow: hidden;
}

.compare-window:focus-visible {
    outline: 0.125rem solid var(--blue-text);
    outline-offset: 0.125rem;
}

.compare-window .head {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: 0.25rem 0.5rem;
    padding: 0.25rem 0.5rem;
    border-block-end: 0.0625rem solid var(--border-hover);
}

.compare-window .grab {
    color: var(--ink-muted);
    cursor: grab;
    user-select: none;
}

.compare-window .title {
    flex: 1;
    min-inline-size: 0;
    margin: 0;
    font-size: 0.9375rem;
    font-weight: 600;
}

.compare-window .controls {
    display: flex;
    flex-wrap: wrap;
    gap: 0.25rem;
}

.compare-window .fold,
.compare-window .controls button {
    display: inline-grid;
    place-items: center;
    min-inline-size: var(--explorer-target, 2.75rem);
    min-block-size: var(--explorer-target, 2.75rem);
    padding-inline: 0.25rem;
    border: 0.0625rem solid var(--border-hover);
    border-radius: 0.25rem;
    background: var(--surface);
    color: var(--ink);
    font: inherit;
    font-size: 0.8125rem;
    cursor: pointer;
}

.compare-window .controls button[aria-pressed="true"] {
    border-color: var(--ink);
    font-weight: 600;
}

.compare-window .controls button[aria-disabled="true"] {
    color: var(--ink-muted);
    cursor: default;
}

.compare-window .fold:focus-visible,
.compare-window .controls button:focus-visible {
    outline: 0.125rem solid var(--blue-text);
    outline-offset: 0.125rem;
}

.compare-window .body {
    min-block-size: 0;
    padding: 0.5rem;
    overflow: auto;
}
</style>
