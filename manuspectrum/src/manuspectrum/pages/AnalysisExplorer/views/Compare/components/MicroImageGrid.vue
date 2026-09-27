<script setup lang="ts">
import MicroImagePreview from "@/manuspectrum/pages/AnalysisExplorer/viewers/MicroImagePreview.vue";

import { slotLabel } from "@/manuspectrum/pages/AnalysisExplorer/store/basket.ts";

import type { FileLine } from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/windows.ts";

/** The micro-images of the Selection side by side, each captioned « A1 · analysis · file ». */
const props = defineProps<{ images: readonly FileLine[] }>();
</script>

<template>
    <div class="micro-image-grid">
        <figure
            v-for="image in props.images"
            :key="`${image.key}|${image.file.id}`"
            :data-key="image.key"
        >
            <MicroImagePreview :file="image.file" />
            <figcaption>
                <span class="slot">{{ slotLabel(image.slot) }}</span>
                <span :lang="image.analysis.name.lang">{{
                    image.analysis.name.value
                }}</span>
                <span class="file">{{ image.file.name }}</span>
            </figcaption>
        </figure>
    </div>
</template>

<style scoped>
.micro-image-grid {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(14rem, 1fr));
    gap: 0.75rem;
}

.micro-image-grid figure {
    display: grid;
    gap: 0.25rem;
    margin: 0;
}

.micro-image-grid figcaption {
    display: flex;
    flex-wrap: wrap;
    gap: 0 0.5rem;
    font-size: 0.8125rem;
}

.micro-image-grid .slot {
    font-family: var(--font-mono);
    font-weight: 600;
}

.micro-image-grid .file {
    color: var(--ink-muted);
    overflow-wrap: anywhere;
}
</style>
