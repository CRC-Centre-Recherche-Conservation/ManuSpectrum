<script setup lang="ts">
import { computed, ref } from "vue";
import { useGettext } from "vue3-gettext";
import { imageUrl } from "utils/iiif-image";

import type { DocumentCanvas } from "@/manuspectrum/pages/AnalysisExplorer/api/types.ts";

const THUMBNAIL_SIZE = ",96";

const props = defineProps<{
    canvases: DocumentCanvas[];
    current: string | null;
}>();
const emit = defineEmits<{ select: [canvasId: string] }>();

const { $gettext, $ngettext, interpolate } = useGettext();

const failed = ref(new Set<string>());

/** The pages carrying an analysis or an identified material; every page when none does. */
const shown = computed(() => {
    const analysed = props.canvases.filter(
        (canvas) =>
            canvas.analysisCount > 0 || canvas.characterizationCount > 0,
    );
    const pages = analysed.length > 0 ? analysed : props.canvases;
    return pages.map((canvas) => ({
        canvas,
        thumbnail: thumbnailOf(canvas),
        count: canvas.analysisCount > 0 ? countLabel(canvas) : null,
    }));
});

/** A small image of the page from its IIIF service; none once the server refused it (some hosts refuse hotlinks). */
function thumbnailOf(canvas: DocumentCanvas): string | null {
    return canvas.image.service && !failed.value.has(canvas.id)
        ? imageUrl(canvas.image.service, { size: THUMBNAIL_SIZE })
        : null;
}

function countLabel(canvas: DocumentCanvas): string {
    return interpolate(
        $ngettext("%{n} analysis", "%{n} analyses", canvas.analysisCount),
        { n: canvas.analysisCount },
        true,
    );
}

function onThumbnailError(canvas: DocumentCanvas): void {
    failed.value = new Set(failed.value).add(canvas.id);
}
</script>

<template>
    <nav
        class="canvas-strip"
        :aria-label="$gettext('Pages')"
    >
        <ul>
            <li
                v-for="page in shown"
                :key="page.canvas.id"
            >
                <button
                    type="button"
                    :aria-current="
                        page.canvas.id === props.current ? 'page' : undefined
                    "
                    @click="emit('select', page.canvas.id)"
                >
                    <img
                        v-if="page.thumbnail"
                        alt=""
                        loading="lazy"
                        referrerpolicy="no-referrer"
                        :src="page.thumbnail"
                        @error="onThumbnailError(page.canvas)"
                    />
                    <span class="label">{{ page.canvas.label }}</span>
                    <span
                        v-if="page.count"
                        class="count"
                    >
                        {{ page.count }}
                    </span>
                </button>
            </li>
        </ul>
    </nav>
</template>

<style scoped>
.canvas-strip ul {
    display: flex;
    gap: 0.5rem;
    padding: 0 0 0.5rem;
    overflow-x: auto;
    list-style: none;
}

.canvas-strip li {
    flex: none;
}

.canvas-strip button {
    display: grid;
    justify-items: center;
    gap: 0.25rem;
    min-block-size: 2.75rem;
    min-inline-size: 4rem;
    padding: 0.25rem 0.5rem;
    border: 0.0625rem solid var(--border-hover);
    border-radius: 0.375rem;
    background: var(--surface);
    color: var(--ink);
    font: inherit;
    cursor: pointer;
}

.canvas-strip button[aria-current="page"] {
    border: 0.125rem solid var(--blue-text);
}

.canvas-strip button:focus-visible {
    outline: 0.125rem solid var(--blue-text);
    outline-offset: 0.125rem;
}

.canvas-strip img {
    block-size: 4rem;
    inline-size: auto;
}

.canvas-strip .label {
    font-size: 0.875rem;
    font-weight: 600;
}

.canvas-strip .count {
    color: var(--ink-muted);
    font-size: 0.75rem;
}
</style>
