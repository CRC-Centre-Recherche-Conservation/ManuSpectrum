<script setup lang="ts">
import { computed, ref } from "vue";
import { useGettext } from "vue3-gettext";
import { imageUrl } from "utils/iiif-image";

import {
    safeHref,
    sameText,
} from "@/manuspectrum/pages/AnalysisExplorer/format.ts";
import { LAYER_DRAG_TYPE } from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/layer-drag.ts";

const THUMBNAIL_SIZE = "!120,150";

/**
 * One imaging canvas of the gallery: a small image from its IIIF service
 * (lazy, an http(s) address only; an image with no service, a folio capture,
 * is drawn from its own `url`), its stored label always, the declared tag
 * as a badge when it says something else, the panes holding it (A to D) and a
 * gold outline while it is in the stack. A failed image becomes a flat with
 * the label and is not asked again, at no other size. A click emits `pick`;
 * a drag carries the canvas id (`LAYER_DRAG_TYPE`). `current` marks the one
 * being looked at (`aria-current`, an outline).
 */
const props = defineProps<{
    canvas: string;
    label: string;
    service: string | null;
    url?: string | null;
    tag: string | null;
    panes: readonly string[];
    inStack: boolean;
    stop: boolean;
    current?: boolean;
}>();
const emit = defineEmits<{ pick: [] }>();

const { $gettext, interpolate } = useGettext();

const failed = ref(false);

const source = computed(() => {
    if (failed.value) return null;
    if (props.service) {
        return safeHref(imageUrl(props.service, { size: THUMBNAIL_SIZE }));
    }
    return props.url ? safeHref(props.url) : null;
});
const badge = computed(() =>
    props.tag && !sameText(props.tag, props.label) ? props.tag : null,
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
        :class="{
            'in-stack': props.inStack,
            placed: props.panes.length > 0,
            current: props.current,
        }"
        :data-pane="props.panes[0]?.toLowerCase()"
        draggable="true"
        :data-canvas="props.canvas"
        :tabindex="props.stop ? 0 : -1"
        :aria-label="name"
        :aria-current="props.current ? 'true' : undefined"
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
                :data-pane="pane.toLowerCase()"
                >{{ pane }}</b
            >
        </span>
    </button>
</template>

<style scoped>
.layer-thumb {
    --pane: var(--pane-a);
    position: relative;
    display: grid;
    justify-items: stretch;
    gap: 0.1875rem;
    min-inline-size: 0;
    padding: 0.1875rem;
    border: 0.0625rem solid var(--border-hover);
    border-radius: 0.4375rem;
    background: var(--surface);
    color: var(--ink);
    font: inherit;
    cursor: pointer;
}

.layer-thumb[data-pane="b"],
.layer-thumb .pane-badge[data-pane="b"] {
    --pane: var(--pane-b);
}

.layer-thumb[data-pane="c"],
.layer-thumb .pane-badge[data-pane="c"] {
    --pane: var(--pane-c);
}

.layer-thumb[data-pane="d"],
.layer-thumb .pane-badge[data-pane="d"] {
    --pane: var(--pane-d);
}

.layer-thumb:hover {
    border-color: var(--ink-dim);
    box-shadow: 0 0.125rem 0.375rem rgb(26 26 46 / 8%);
}

.layer-thumb:focus-visible {
    outline: 0.125rem solid var(--blue-text);
    outline-offset: 0.125rem;
}

.layer-thumb.placed {
    outline: 0.125rem solid var(--pane);
    outline-offset: -0.0625rem;
}

.layer-thumb.current {
    border-color: var(--blue-text);
    outline: 0.125rem solid var(--blue-text);
    outline-offset: -0.0625rem;
}

.layer-thumb.in-stack {
    outline: 0.125rem solid var(--accent);
    outline-offset: -0.0625rem;
}

.layer-thumb .picture {
    display: grid;
    place-items: center;
    aspect-ratio: 4 / 5;
    overflow: hidden;
    border-radius: 0.25rem;
    background: var(--stage);
}

.layer-thumb img {
    inline-size: 100%;
    block-size: 100%;
    object-fit: cover;
}

.layer-thumb .flat {
    padding: 0.125rem;
    color: color-mix(in srgb, var(--surface) 70%, transparent);
    font: 0.625rem var(--font-mono);
    overflow-wrap: anywhere;
    text-align: center;
}

.layer-thumb .label {
    overflow: hidden;
    padding-inline: 0.125rem;
    font: 500 0.65625rem/1.2 var(--font-mono);
    text-align: start;
    text-overflow: ellipsis;
    white-space: nowrap;
}

.layer-thumb .tag-badge {
    position: absolute;
    inset-block-start: 0.3125rem;
    inset-inline-end: 0.3125rem;
    max-inline-size: 60%;
    overflow: hidden;
    padding: 0.0625rem 0.25rem;
    border-radius: 0.1875rem;
    background: color-mix(in srgb, var(--ink) 80%, transparent);
    color: var(--surface);
    font: 500 0.5625rem var(--font-mono);
    text-overflow: ellipsis;
    white-space: nowrap;
}

.layer-thumb .panes {
    position: absolute;
    inset-block-start: 0.3125rem;
    inset-inline-start: 0.3125rem;
    display: flex;
    gap: 0.125rem;
}

.layer-thumb .pane-badge {
    --pane: var(--pane-a);
    display: grid;
    place-items: center;
    inline-size: 0.9375rem;
    block-size: 0.9375rem;
    border-radius: 0.1875rem;
    background: var(--pane);
    color: var(--surface);
    font: 600 0.59375rem var(--font-mono);
}
</style>
