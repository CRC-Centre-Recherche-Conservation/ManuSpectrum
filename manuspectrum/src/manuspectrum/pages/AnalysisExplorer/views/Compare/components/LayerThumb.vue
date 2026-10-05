<script setup lang="ts">
import { computed, ref } from "vue";
import { useGettext } from "vue3-gettext";
import { imageUrl } from "utils/iiif-image";

import {
    foldText,
    safeHref,
} from "@/manuspectrum/pages/AnalysisExplorer/format.ts";
import { LAYER_DRAG_TYPE } from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/layer-drag.ts";

const THUMBNAIL_SIZE = "!120,150";

/**
 * One imaging canvas of the gallery: a small image from its IIIF service
 * (lazy, an http(s) address only), its stored label always, the declared tag
 * as a badge when it says something else, the panes holding it (A to D) and a
 * gold outline while it is in the stack. A failed image becomes a flat with
 * the label and is not asked again, at no other size. A click emits `pick`;
 * a drag carries the canvas id (`LAYER_DRAG_TYPE`).
 */
const props = defineProps<{
    canvas: string;
    label: string;
    service: string | null;
    tag: string | null;
    panes: readonly string[];
    inStack: boolean;
    stop: boolean;
}>();
const emit = defineEmits<{ pick: [] }>();

const { $gettext, interpolate } = useGettext();

const failed = ref(false);

const source = computed(() =>
    props.service && !failed.value
        ? safeHref(imageUrl(props.service, { size: THUMBNAIL_SIZE }))
        : null,
);
const badge = computed(() =>
    props.tag && foldText(props.tag) !== foldText(props.label)
        ? props.tag
        : null,
);
const name = computed(() => {
    const parts = [props.label];
    if (badge.value) parts.push(badge.value);
    if (props.panes.length > 0) {
        parts.push(
            interpolate(
                $gettext("in %{panes}"),
                { panes: props.panes.join(", ") },
                true,
            ),
        );
    }
    if (props.inStack) parts.push($gettext("in the stack"));
    return parts.join(", ");
});

function onDragStart(event: DragEvent): void {
    event.dataTransfer?.setData(LAYER_DRAG_TYPE, props.canvas);
    if (event.dataTransfer) event.dataTransfer.effectAllowed = "copy";
}
</script>

<template>
    <button
        type="button"
        class="layer-thumb"
        :class="{ 'in-stack': props.inStack }"
        draggable="true"
        :data-canvas="props.canvas"
        :tabindex="props.stop ? 0 : -1"
        :aria-label="name"
        @click="emit('pick')"
        @dragstart="onDragStart"
    >
        <span
            class="picture"
            aria-hidden="true"
        >
            <img
                v-if="source"
                alt=""
                loading="lazy"
                referrerpolicy="no-referrer"
                :src="source"
                @error="failed = true"
            />
            <span
                v-else
                class="flat"
                >{{ props.label }}</span
            >
        </span>
        <span
            class="label"
            aria-hidden="true"
            :title="props.label"
            >{{ props.label }}</span
        >
        <span
            v-if="badge"
            class="tag-badge"
            aria-hidden="true"
            >{{ badge }}</span
        >
        <span
            v-if="props.panes.length > 0"
            class="panes"
            aria-hidden="true"
        >
            <b
                v-for="pane in props.panes"
                :key="pane"
                class="pane-badge"
                >{{ pane }}</b
            >
        </span>
    </button>
</template>

<style scoped>
.layer-thumb {
    position: relative;
    display: grid;
    justify-items: stretch;
    gap: 0.125rem;
    min-inline-size: 0;
    padding: 0.125rem;
    border: 0.0625rem solid var(--border-hover);
    border-radius: 0.375rem;
    background: var(--surface);
    color: var(--ink);
    font: inherit;
    cursor: pointer;
}

.layer-thumb:hover {
    border-color: var(--ink-dim);
}

.layer-thumb:focus-visible {
    outline: 0.125rem solid var(--blue-text);
    outline-offset: 0.125rem;
}

.layer-thumb.in-stack {
    border: 0.125rem solid var(--accent-text);
}

.layer-thumb .picture {
    display: grid;
    place-items: center;
    aspect-ratio: 4 / 5;
    overflow: hidden;
    border-radius: 0.25rem;
    background: var(--bg-alt);
}

.layer-thumb img {
    inline-size: 100%;
    block-size: 100%;
    object-fit: cover;
}

.layer-thumb .flat {
    padding: 0.125rem;
    color: var(--ink-muted);
    font: 0.625rem var(--font-mono);
    overflow-wrap: anywhere;
    text-align: center;
}

.layer-thumb .label {
    overflow: hidden;
    font: 0.625rem var(--font-mono);
    text-align: start;
    text-overflow: ellipsis;
    white-space: nowrap;
}

.layer-thumb .tag-badge {
    position: absolute;
    inset-block-start: 0.25rem;
    inset-inline-start: 0.25rem;
    max-inline-size: 90%;
    overflow: hidden;
    padding-inline: 0.25rem;
    border-radius: 999rem;
    background: var(--ink);
    color: var(--surface);
    font: 600 0.5625rem var(--font-mono);
    text-overflow: ellipsis;
    white-space: nowrap;
}

.layer-thumb .panes {
    position: absolute;
    inset-block-start: 0.25rem;
    inset-inline-end: 0.25rem;
    display: flex;
    gap: 0.125rem;
}

.layer-thumb .pane-badge {
    display: grid;
    place-items: center;
    min-inline-size: 0.875rem;
    block-size: 0.875rem;
    border-radius: 0.1875rem;
    background: var(--accent-text);
    color: var(--surface);
    font: 600 0.5625rem var(--font-mono);
}
</style>
