<script setup lang="ts">
import { computed, nextTick, onMounted, ref, useTemplateRef, watch } from "vue";
import { usePreferredReducedMotion } from "@vueuse/core";
import { useGettext } from "vue3-gettext";
import { imageUrl } from "utils/iiif-image";

import { nextId } from "@/manuspectrum/pages/AnalysisExplorer/folio/roving.ts";

import type { DocumentCanvas } from "@/manuspectrum/pages/AnalysisExplorer/api/types.ts";
import type { PageCount } from "@/manuspectrum/pages/AnalysisExplorer/folio/page-counts.ts";

const THUMBNAIL_SIZE = ",96";
const STRIP_KEYS = new Set(["ArrowLeft", "ArrowRight", "Home", "End"]);

/**
 * The analysed pages of a document, one tab stop: the arrows, Home and End
 * move between pages, Enter or a click opens one. The current page is
 * scrolled into the middle of the strip whenever it changes. Each page
 * counts its identified materials and samples (`counts`). While Corpus
 * filters are active (`filtered`), a page writes the analyses they keep out
 * of all (« 7/22 »), the pages with results are marked, the strip can keep
 * only them, and ‹ › go to the previous or next one.
 */
const props = withDefaults(
    defineProps<{
        canvases: DocumentCanvas[];
        current: string | null;
        counts?: ReadonlyMap<string, PageCount>;
        filtered?: boolean;
    }>(),
    { counts: () => new Map(), filtered: false },
);
const emit = defineEmits<{ select: [canvasId: string] }>();

const { $gettext, $ngettext, interpolate } = useGettext();
const motion = usePreferredReducedMotion();
const list = useTemplateRef<HTMLUListElement>("list");

const failed = ref(new Set<string>());
const roving = ref<string | null>(null);
const onlyResults = ref(false);

/** The pages carrying an analysis or an identified material; every page when none does. */
const analysed = computed(() =>
    props.canvases.filter(
        (canvas) =>
            canvas.analysisCount > 0 || canvas.characterizationCount > 0,
    ),
);
/** The pages with an analysis the filters keep, in the document's order. */
const withResults = computed(() =>
    props.canvases.filter((canvas) => matchingOf(canvas) > 0),
);
const shown = computed(() => {
    let pages = analysed.value.length > 0 ? analysed.value : props.canvases;
    if (props.filtered && onlyResults.value) pages = withResults.value;
    return pages.map((canvas) => {
        const count = props.counts.get(canvas.id);
        return {
            canvas,
            thumbnail: thumbnailOf(canvas),
            badge: badgeOf(canvas),
            count: canvas.analysisCount > 0 ? countLabel(canvas) : null,
            hasMatch: props.filtered && matchingOf(canvas) > 0,
            materials: count?.materials ?? 0,
            samples: count?.samples ?? 0,
        };
    });
});
const currentIndex = computed(() =>
    props.canvases.findIndex((canvas) => canvas.id === props.current),
);
const previousResult = computed(
    () =>
        withResults.value
            .filter(
                (canvas) => props.canvases.indexOf(canvas) < currentIndex.value,
            )
            .at(-1) ?? null,
);
const nextResult = computed(
    () =>
        withResults.value.find(
            (canvas) => props.canvases.indexOf(canvas) > currentIndex.value,
        ) ?? null,
);
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

function matchingOf(canvas: DocumentCanvas): number {
    return props.counts.get(canvas.id)?.matching ?? 0;
}

function totalOf(canvas: DocumentCanvas): number {
    return props.counts.get(canvas.id)?.total ?? canvas.analysisCount;
}

/** The visible count: « kept/all » under filters, else the number of analyses. */
function badgeOf(canvas: DocumentCanvas): string {
    return props.filtered
        ? `${matchingOf(canvas)}/${totalOf(canvas)}`
        : String(canvas.analysisCount);
}

function countLabel(canvas: DocumentCanvas): string {
    if (props.filtered) {
        return interpolate(
            $ngettext(
                "%{n} of %{total} analysis in the filters",
                "%{n} of %{total} analyses in the filters",
                totalOf(canvas),
            ),
            { n: matchingOf(canvas), total: totalOf(canvas) },
            true,
        );
    }
    return interpolate(
        $ngettext("%{n} analysis", "%{n} analyses", canvas.analysisCount),
        { n: canvas.analysisCount },
        true,
    );
}

function materialsLabel(n: number): string {
    return interpolate(
        $ngettext("%{n} identified material", "%{n} identified materials", n),
        { n },
        true,
    );
}

function samplesLabel(n: number): string {
    return interpolate(
        $ngettext("%{n} sample", "%{n} samples", n),
        { n },
        true,
    );
}

function onOnlyResults(event: Event): void {
    onlyResults.value = (event.target as HTMLInputElement).checked;
}

function goTo(canvas: DocumentCanvas | null): void {
    if (canvas) emit("select", canvas.id);
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
        :class="{ 'is-filtered': props.filtered }"
        :aria-label="$gettext('Pages')"
    >
        <div class="head">
            <p
                class="title"
                aria-hidden="true"
            >
                <span>{{ title }}</span>
            </p>
            <template v-if="props.filtered">
                <button
                    type="button"
                    class="step previous-result"
                    :disabled="previousResult === null"
                    :aria-label="$gettext('Previous page with results')"
                    :title="$gettext('Previous page with results')"
                    @click="goTo(previousResult)"
                >
                    <span aria-hidden="true">‹</span>
                </button>
                <button
                    type="button"
                    class="step next-result"
                    :disabled="nextResult === null"
                    :aria-label="$gettext('Next page with results')"
                    :title="$gettext('Next page with results')"
                    @click="goTo(nextResult)"
                >
                    <span aria-hidden="true">›</span>
                </button>
                <label class="only">
                    <input
                        class="only-results"
                        type="checkbox"
                        :checked="onlyResults"
                        @change="onOnlyResults"
                    />
                    <span>{{ $gettext("Pages with results only") }}</span>
                </label>
            </template>
        </div>
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
                    class="page"
                    :class="{ 'has-match': page.hasMatch }"
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
                        <span aria-hidden="true">{{ page.badge }}</span>
                        <span class="visually-hidden">{{ page.count }}</span>
                    </span>
                    <span
                        v-if="page.materials > 0 || page.samples > 0"
                        class="extras"
                    >
                        <span
                            v-if="page.materials > 0"
                            class="extra materials"
                        >
                            <span aria-hidden="true"
                                >◆{{ page.materials }}</span
                            >
                            <span class="visually-hidden">{{
                                materialsLabel(page.materials)
                            }}</span>
                        </span>
                        <span
                            v-if="page.samples > 0"
                            class="extra samples"
                        >
                            <span aria-hidden="true">■{{ page.samples }}</span>
                            <span class="visually-hidden">{{
                                samplesLabel(page.samples)
                            }}</span>
                        </span>
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

.canvas-strip .head {
    display: grid;
    flex: none;
    justify-items: start;
    gap: 0.25rem;
    max-inline-size: 9rem;
}

.canvas-strip .head:has(.step) {
    grid-template-columns: auto auto;
}

.canvas-strip .head .title,
.canvas-strip .head .only {
    grid-column: 1 / -1;
}

.canvas-strip .step {
    display: grid;
    place-items: center;
    inline-size: 2rem;
    block-size: 2rem;
    padding: 0;
    border: 0.0625rem solid var(--border-hover);
    border-radius: 0.375rem;
    background: var(--surface);
    color: var(--ink);
    font: inherit;
    font-size: 1rem;
    cursor: pointer;
}

.canvas-strip .step:focus-visible,
.canvas-strip .only-results:focus-visible {
    outline: 0.125rem solid var(--blue-text);
    outline-offset: 0.125rem;
}

.canvas-strip .step:disabled {
    color: var(--ink-dim);
    cursor: not-allowed;
}

.canvas-strip .only {
    display: flex;
    align-items: center;
    gap: 0.375rem;
    color: var(--ink-muted);
    font-size: 0.6875rem;
    cursor: pointer;
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

.canvas-strip .page {
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

.canvas-strip .page:hover {
    border-color: var(--ink-dim);
}

.canvas-strip .page[aria-current="page"] {
    border: 0.125rem solid var(--ink);
    background: var(--bg-alt);
}

.canvas-strip .page:focus-visible {
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

.canvas-strip.is-filtered .page:not(.has-match) .count {
    background: var(--surface);
    color: var(--ink-muted);
    border: 0.0625rem solid var(--border-hover);
}

.canvas-strip .page.has-match .count {
    background: var(--accent-text);
}

.canvas-strip .extras {
    display: flex;
    gap: 0.25rem;
    color: var(--ink-muted);
    font: 0.625rem var(--font-mono);
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
