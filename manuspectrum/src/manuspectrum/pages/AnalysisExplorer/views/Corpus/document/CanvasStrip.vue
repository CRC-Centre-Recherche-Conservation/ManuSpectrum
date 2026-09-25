<script setup lang="ts">
import { computed, nextTick, onMounted, ref, useTemplateRef, watch } from "vue";
import { usePreferredReducedMotion } from "@vueuse/core";
import { useGettext } from "vue3-gettext";
import { imageUrl } from "utils/iiif-image";

import { nextId } from "@/manuspectrum/pages/AnalysisExplorer/folio/roving.ts";

import type { DocumentCanvas } from "@/manuspectrum/pages/AnalysisExplorer/api/types.ts";

const THUMBNAIL_SIZE = ",96";
const STRIP_KEYS = new Set(["ArrowLeft", "ArrowRight", "Home", "End"]);

/**
 * The analysed pages of a document, one tab stop: the arrows, Home and End
 * move between pages, Enter or a click opens one. The current page is
 * scrolled into the middle of the strip whenever it changes.
 */
const props = defineProps<{
    canvases: DocumentCanvas[];
    current: string | null;
}>();
const emit = defineEmits<{ select: [canvasId: string] }>();

const { $gettext, $ngettext, interpolate } = useGettext();
const motion = usePreferredReducedMotion();
const list = useTemplateRef<HTMLUListElement>("list");

const failed = ref(new Set<string>());
const roving = ref<string | null>(null);

/** The pages carrying an analysis or an identified material; every page when none does. */
const analysed = computed(() =>
    props.canvases.filter(
        (canvas) =>
            canvas.analysisCount > 0 || canvas.characterizationCount > 0,
    ),
);
const shown = computed(() => {
    const pages = analysed.value.length > 0 ? analysed.value : props.canvases;
    return pages.map((canvas) => ({
        canvas,
        thumbnail: thumbnailOf(canvas),
        count: canvas.analysisCount > 0 ? countLabel(canvas) : null,
    }));
});
const order = computed(() => shown.value.map((page) => page.canvas.id));
/** The page that holds the strip's tab stop. */
const stop = computed(() => {
    for (const id of [roving.value, props.current]) {
        if (id && order.value.includes(id)) return id;
    }
    return order.value[0] ?? null;
});
const title = computed(() =>
    analysed.value.length > 0 ? $gettext("Analysed pages") : $gettext("Pages"),
);

watch(
    () => props.current,
    async () => {
        roving.value = null;
        await nextTick();
        reveal(props.current);
    },
);

onMounted(() => reveal(props.current));

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

function buttonOf(id: string | null): HTMLButtonElement | null {
    if (!id) return null;
    return (
        [...(list.value?.querySelectorAll("button") ?? [])].find(
            (button) => button.dataset.canvas === id,
        ) ?? null
    );
}

/** Scrolls the strip, not the page, so that the page `id` sits in its middle. */
function reveal(id: string | null): void {
    const button = buttonOf(id);
    const strip = list.value;
    if (!button || !strip) return;
    strip.scrollTo?.({
        left: button.offsetLeft - (strip.clientWidth - button.offsetWidth) / 2,
        behavior: motion.value === "reduce" ? "auto" : "smooth",
    });
}

function onKeydown(event: KeyboardEvent): void {
    if (!STRIP_KEYS.has(event.key)) return;
    const next = nextId(order.value, stop.value, event.key);
    if (next === null) return;
    event.preventDefault();
    roving.value = next;
    buttonOf(next)?.focus();
}
</script>

<template>
    <nav
        class="canvas-strip"
        :aria-label="$gettext('Pages')"
    >
        <p
            class="title"
            aria-hidden="true"
        >
            <span>{{ title }}</span>
        </p>
        <ul
            ref="list"
            @keydown="onKeydown"
        >
            <li
                v-for="page in shown"
                :key="page.canvas.id"
            >
                <button
                    type="button"
                    :data-canvas="page.canvas.id"
                    :tabindex="page.canvas.id === stop ? 0 : -1"
                    :aria-current="
                        page.canvas.id === props.current ? 'page' : undefined
                    "
                    @click="emit('select', page.canvas.id)"
                >
                    <span class="thumbnail">
                        <img
                            v-if="page.thumbnail"
                            alt=""
                            loading="lazy"
                            referrerpolicy="no-referrer"
                            :src="page.thumbnail"
                            @error="onThumbnailError(page.canvas)"
                        />
                    </span>
                    <span class="label">{{ page.canvas.label }}</span>
                    <span
                        v-if="page.count"
                        class="count"
                    >
                        <span aria-hidden="true">{{
                            page.canvas.analysisCount
                        }}</span>
                        <span class="visually-hidden">{{ page.count }}</span>
                    </span>
                </button>
            </li>
        </ul>
    </nav>
</template>

<style scoped>
.canvas-strip {
    display: flex;
    align-items: center;
    gap: 0.75rem;
    min-inline-size: 0;
}

.canvas-strip .title {
    flex: none;
    color: var(--ink-muted);
    font-family: var(--font-mono);
    font-size: 0.6875rem;
    letter-spacing: 0.12em;
    text-transform: uppercase;
}

.canvas-strip ul {
    position: relative;
    display: flex;
    flex: 1;
    gap: 0.375rem;
    min-inline-size: 0;
    padding: 0.5rem 0.25rem 0.375rem;
    overflow-x: auto;
    list-style: none;
    scrollbar-width: thin;
}

.canvas-strip li {
    flex: none;
}

.canvas-strip button {
    position: relative;
    display: grid;
    justify-items: center;
    gap: 0.125rem;
    min-inline-size: 3.25rem;
    padding: 0.25rem 0.25rem 0.125rem;
    border: 0.0625rem solid var(--border-hover);
    border-radius: 0.375rem;
    background: var(--surface);
    color: var(--ink);
    font: inherit;
    cursor: pointer;
}

.canvas-strip button:hover {
    border-color: var(--ink-dim);
}

.canvas-strip button[aria-current="page"] {
    border: 0.125rem solid var(--ink);
    background: var(--bg-alt);
}

.canvas-strip button:focus-visible {
    outline: 0.125rem solid var(--blue-text);
    outline-offset: 0.125rem;
}

.canvas-strip .thumbnail {
    display: grid;
    place-items: center;
    inline-size: 2.5rem;
    block-size: 3rem;
    overflow: hidden;
    border-radius: 0.1875rem;
    background: var(--bg-alt);
}

.canvas-strip img {
    inline-size: 100%;
    block-size: 100%;
    object-fit: cover;
}

.canvas-strip .label {
    font-family: var(--font-mono);
    font-size: 0.6875rem;
    white-space: nowrap;
}

.canvas-strip .count {
    position: absolute;
    inset-block-start: -0.4375rem;
    inset-inline-end: -0.4375rem;
    display: grid;
    place-items: center;
    min-inline-size: 1.125rem;
    block-size: 1.125rem;
    padding-inline: 0.25rem;
    border-radius: 999rem;
    background: var(--ink);
    color: var(--surface);
    font: 600 0.625rem var(--font-mono);
}

.canvas-strip .visually-hidden {
    position: absolute;
    inline-size: 0.0625rem;
    block-size: 0.0625rem;
    overflow: hidden;
    clip-path: inset(50%);
    white-space: nowrap;
}
</style>
