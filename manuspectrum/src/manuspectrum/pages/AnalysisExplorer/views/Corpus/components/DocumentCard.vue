<script setup lang="ts">
import { computed, ref } from "vue";
import { useGettext } from "vue3-gettext";

import {
    hasImageFailed,
    markImageFailed,
} from "@/manuspectrum/pages/AnalysisExplorer/failed-images.ts";
import { formatDateRange } from "@/manuspectrum/pages/AnalysisExplorer/format.ts";

import type {
    DocumentHit,
    Label,
} from "@/manuspectrum/pages/AnalysisExplorer/api/types.ts";

/**
 * A document of the results: title, shelfmark, holding, dates, type, a short
 * description and its number of analyses. A thumbnail the server refuses
 * leaves the neutral placeholder, and is not asked for again in this tab.
 */
const props = defineProps<{ hit: DocumentHit; href: string }>();
const emit = defineEmits<{ open: [id: string] }>();

const { $gettext, $ngettext, interpolate } = useGettext();

const thumbnailFailed = ref(
    props.hit.thumbnail !== null && hasImageFailed(props.hit.thumbnail),
);

const countText = computed(() =>
    interpolate(
        $ngettext("%{n} analysis", "%{n} analyses", props.hit.analysisCount),
        {
            n: props.hit.analysisCount,
        },
        true,
    ),
);
const dates = computed(() =>
    props.hit.dates ? formatDateRange(props.hit.dates) : "",
);
/** Holding and type, each in its own language. */
const facts = computed(() =>
    [props.hit.holding, props.hit.documentType].filter(
        (fact): fact is Label => fact !== null && fact.value !== "",
    ),
);
const hasFacts = computed(() => facts.value.length > 0 || dates.value !== "");

function onThumbnailError(): void {
    if (props.hit.thumbnail) markImageFailed(props.hit.thumbnail);
    thumbnailFailed.value = true;
}

function open(event: MouseEvent): void {
    if (
        event.metaKey ||
        event.ctrlKey ||
        event.shiftKey ||
        event.button !== 0
    ) {
        return;
    }
    event.preventDefault();
    emit("open", props.hit.id);
}
</script>

<template>
    <article class="document-card">
        <span class="thumbnail">
            <img
                v-if="props.hit.thumbnail && !thumbnailFailed"
                alt=""
                loading="lazy"
                :src="props.hit.thumbnail"
                @error="onThumbnailError"
            />
        </span>
        <div class="body">
            <h3 class="name">
                <a
                    class="link"
                    :href="props.href"
                    :lang="props.hit.name.lang"
                    @click="open"
                >
                    <span>{{ props.hit.name.value }}</span>
                </a>
            </h3>
            <p
                v-if="props.hit.shelfmark"
                class="shelfmark"
                :lang="props.hit.shelfmark.lang"
            >
                <span>{{ props.hit.shelfmark.value }}</span>
            </p>
            <p
                v-if="hasFacts"
                class="facts"
            >
                <span
                    v-for="(fact, index) in facts"
                    :key="index"
                    :lang="fact.lang"
                    >{{ fact.value }}</span
                >
                <span v-if="dates">{{ dates }}</span>
            </p>
            <p
                v-if="props.hit.description"
                class="description"
                :lang="props.hit.description.lang"
            >
                <span>{{ props.hit.description.value }}</span>
            </p>
            <p class="meta">
                <span class="count">{{ countText }}</span>
                <span
                    v-if="props.hit.unpublished"
                    class="badge"
                >
                    <span>{{ $gettext("Draft") }}</span>
                </span>
            </p>
        </div>
    </article>
</template>

<style scoped>
.document-card {
    display: grid;
    grid-template-columns: 4rem minmax(0, 1fr);
    gap: 0.875rem;
    padding: 0.75rem;
    border: 0.0625rem solid var(--border);
    border-radius: var(--explorer-radius, 0.625rem);
    background: var(--surface);
}

.document-card .thumbnail {
    display: block;
    inline-size: 4rem;
    block-size: 5rem;
    overflow: hidden;
    border-radius: 0.375rem;
    background: var(--bg-alt);
}

.document-card .thumbnail img {
    inline-size: 100%;
    block-size: 100%;
    object-fit: cover;
}

.document-card .body {
    display: grid;
    align-content: start;
    gap: 0.25rem;
    min-inline-size: 0;
}

.document-card .name {
    font-family: var(--font-display);
    font-size: 1.125rem;
    font-weight: 500;
    line-height: 1.25;
}

.document-card .link {
    color: var(--ink);
}

.document-card .link:focus-visible {
    outline: 0.125rem solid var(--blue-text);
    outline-offset: 0.125rem;
}

.document-card .shelfmark {
    color: var(--ink);
    font-family: var(--font-mono);
    font-size: 0.75rem;
}

.document-card .facts {
    display: flex;
    flex-wrap: wrap;
    gap: 0 0.75rem;
    color: var(--ink-muted);
    font-size: 0.8125rem;
}

.document-card .description {
    display: -webkit-box;
    overflow: hidden;
    color: var(--ink-muted);
    font-size: 0.8125rem;
    -webkit-box-orient: vertical;
    -webkit-line-clamp: 2;
    line-clamp: 2;
}

.document-card .meta {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: 0.5rem;
    color: var(--ink-muted);
    font-size: 0.8125rem;
}

.document-card .count {
    font-family: var(--font-mono);
    font-size: 0.75rem;
}

.document-card .badge {
    padding-inline: 0.5rem;
    border: 0.0625rem solid var(--accent-text);
    border-radius: 999rem;
    color: var(--accent-text);
    font-size: 0.75rem;
}
</style>
