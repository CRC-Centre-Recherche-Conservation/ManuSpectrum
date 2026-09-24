<script setup lang="ts">
import { computed } from "vue";
import { useGettext } from "vue3-gettext";

import { useVocabulary } from "@/manuspectrum/pages/AnalysisExplorer/composables/useVocabulary.ts";

import type {
    AnalysisHit,
    Label,
} from "@/manuspectrum/pages/AnalysisExplorer/api/types.ts";

const props = defineProps<{ hit: AnalysisHit }>();
const emit = defineEmits<{ open: [hit: AnalysisHit] }>();

const { $gettext } = useGettext();
const { dataKindBadge } = useVocabulary();

const title = computed<Label>(
    () =>
        props.hit.technique?.label ?? { value: $gettext("Analysis"), lang: "" },
);

function open(): void {
    emit("open", props.hit);
}
</script>

<template>
    <article class="analysis-row">
        <h3 class="title">
            <button
                type="button"
                class="link"
                :lang="title.lang || undefined"
                @click="open"
            >
                <span>{{ title.value }}</span>
            </button>
        </h3>
        <p class="where">
            <span :lang="props.hit.document.name.lang">{{
                props.hit.document.name.value
            }}</span>
            <span
                v-if="props.hit.component"
                :lang="props.hit.component.name.lang"
                >{{ props.hit.component.name.value }}</span
            >
            <span v-if="props.hit.date">{{ props.hit.date }}</span>
        </p>
        <ul class="badges">
            <li
                v-for="kind in props.hit.dataKinds"
                :key="kind"
                class="badge"
            >
                <span>{{ dataKindBadge(kind) }}</span>
            </li>
            <li
                v-if="props.hit.unpublished"
                class="badge draft"
            >
                <span>{{ $gettext("Draft") }}</span>
            </li>
        </ul>
        <p class="raw-name">
            <span>{{ props.hit.name.value }}</span>
        </p>
    </article>
</template>

<style scoped>
.analysis-row {
    display: grid;
    gap: 0.25rem;
    padding-block: 0.75rem;
    border-block-end: 0.0625rem solid var(--border);
}

.analysis-row .link {
    min-block-size: 2.75rem;
    border: none;
    background: transparent;
    color: var(--ink);
    font: inherit;
    font-size: 1.0625rem;
    font-weight: 600;
    text-align: start;
    cursor: pointer;
}

.analysis-row .link:focus-visible {
    outline: 0.125rem solid var(--blue-text);
    outline-offset: 0.125rem;
}

.analysis-row .where {
    display: flex;
    flex-wrap: wrap;
    gap: 0.75rem;
    color: var(--ink-muted);
    font-size: 0.875rem;
}

.analysis-row .badges {
    display: flex;
    flex-wrap: wrap;
    gap: 0.375rem;
    list-style: none;
}

.analysis-row .badge {
    padding-inline: 0.5rem;
    border: 0.0625rem solid var(--border-hover);
    border-radius: 999rem;
    font-size: 0.75rem;
}

.analysis-row .badge.draft {
    border-color: var(--accent-text);
    color: var(--accent-text);
}

.analysis-row .raw-name {
    color: var(--ink-muted);
    font-family: var(--font-mono);
    font-size: 0.75rem;
}
</style>
