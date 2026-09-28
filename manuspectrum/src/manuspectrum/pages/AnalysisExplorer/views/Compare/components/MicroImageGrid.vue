<script setup lang="ts">
import MicroImagePreview from "@/manuspectrum/pages/AnalysisExplorer/viewers/MicroImagePreview.vue";

import { useLinkedMarks } from "@/manuspectrum/pages/AnalysisExplorer/composables/useLinkedMarks.ts";
import { slotLabel } from "@/manuspectrum/pages/AnalysisExplorer/store/basket.ts";
import {
    analysisNode,
    slotNode,
} from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/linked/node-id.ts";

import type { FileLine } from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/windows.ts";

/**
 * The micro-images of the Selection side by side, each in a light well
 * that the window's height stretches, captioned « A1 · analysis · file ». Each image stands for its analysis (`an:`): the
 * analysis name is its toggle, and the figure is marked by how the
 * analysis stands to the linked selection (an unlinked image fades, its
 * caption stays readable) and to the node a mouse previews.
 */
const props = defineProps<{ images: readonly FileLine[] }>();

const marks = useLinkedMarks();
</script>

<template>
    <div class="micro-image-grid">
        <figure
            v-for="image in props.images"
            :key="`${image.key}|${image.file.id}`"
            :data-key="image.key"
            :data-rel="marks.rel(analysisNode(image.analysis.id))"
            :data-preview="marks.previewRel(analysisNode(image.analysis.id))"
            @pointerenter="marks.enter(analysisNode(image.analysis.id), $event)"
            @pointerleave="marks.leave($event)"
        >
            <MicroImagePreview :file="image.file" />
            <figcaption>
                <span
                    class="slot"
                    :data-rel="marks.rel(slotNode(image.slot))"
                    >{{ slotLabel(image.slot) }}</span
                >
                <button
                    type="button"
                    class="record"
                    :lang="image.analysis.name.lang"
                    :aria-pressed="
                        marks.pressed(analysisNode(image.analysis.id))
                    "
                    @click="marks.toggle(analysisNode(image.analysis.id))"
                >
                    <span>{{ image.analysis.name.value }}</span>
                </button>
                <span class="file">{{ image.file.name }}</span>
            </figcaption>
        </figure>
    </div>
</template>

<style scoped>
.micro-image-grid {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(14rem, 1fr));
    grid-auto-rows: minmax(16rem, 1fr);
    gap: 0.75rem;
    block-size: 100%;
}

.micro-image-grid figure {
    display: grid;
    grid-template-rows: minmax(0, 1fr) auto;
    gap: 0.375rem;
    min-block-size: 0;
    margin: 0;
    padding: 0.25rem;
    border-radius: 0.375rem;
}

.micro-image-grid :deep(.micro-image-preview) {
    grid-template-rows: minmax(0, 1fr) auto;
    gap: 0.25rem;
    min-block-size: 0;
}

.micro-image-grid :deep(.surface) {
    isolation: isolate;
    min-block-size: 10rem;
    block-size: 100%;
    border-radius: 0.5rem;
    background: var(--bg-alt);
}

.micro-image-grid :deep(.download) {
    min-block-size: var(--explorer-target, 2rem);
    font-size: 0.8125rem;
}

.micro-image-grid figure[data-rel="self"] {
    outline: 0.125rem solid var(--linked-mark, var(--blue-text));
}

.micro-image-grid figure[data-rel="direct"],
.micro-image-grid figure[data-rel="evidence"] {
    box-shadow: inset 0 0 0 0.125rem var(--linked-mark, var(--blue-text));
}

.micro-image-grid figure[data-rel="evidence"] {
    box-shadow: none;
    outline: 0.125rem dashed var(--linked-mark, var(--blue-text));
    outline-offset: -0.125rem;
}

.micro-image-grid figure[data-rel="none"] :deep(.surface) {
    opacity: var(--linked-fade, 0.35);
}

.micro-image-grid figure[data-rel="none"] figcaption {
    color: var(--ink-muted);
}

.micro-image-grid figure[data-preview] {
    outline: 0.125rem dashed var(--linked-mark, var(--blue-text));
    outline-offset: 0.0625rem;
}

.micro-image-grid figcaption {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: 0 0.5rem;
    font-size: 0.8125rem;
}

.micro-image-grid .slot {
    font-family: var(--font-mono);
    font-weight: 600;
}

.micro-image-grid .record {
    min-block-size: 1.5rem;
    padding: 0 0.25rem;
    border: 0.0625rem solid transparent;
    border-radius: 0.25rem;
    background: none;
    color: inherit;
    font: inherit;
    text-align: start;
    cursor: pointer;
}

.micro-image-grid .record:hover {
    border-color: var(--border-hover);
}

.micro-image-grid .record[aria-pressed="true"] {
    border-color: var(--linked-mark, var(--blue-text));
    font-weight: 600;
}

.micro-image-grid .record:focus-visible {
    outline: 0.125rem solid var(--blue-text);
    outline-offset: 0.125rem;
}

.micro-image-grid .file {
    color: var(--ink-muted);
    overflow-wrap: anywhere;
}

@media (prefers-reduced-motion: no-preference) {
    .micro-image-grid :deep(.surface) {
        transition: opacity 0.15s ease-out;
    }
}
</style>
