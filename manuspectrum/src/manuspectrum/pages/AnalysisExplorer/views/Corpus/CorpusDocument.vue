<script setup lang="ts">
import { computed, useTemplateRef } from "vue";
import { useGettext } from "vue3-gettext";

import UnavailableState from "@/manuspectrum/pages/AnalysisExplorer/components/UnavailableState.vue";
import DraftBanner from "@/manuspectrum/pages/AnalysisExplorer/components/DraftBanner.vue";

import { useDocument } from "@/manuspectrum/pages/AnalysisExplorer/composables/useDocument.ts";
import { useScreenHeading } from "@/manuspectrum/pages/AnalysisExplorer/composables/useScreenHeading.ts";
import { useExplorerStore } from "@/manuspectrum/pages/AnalysisExplorer/store/explorer.ts";

const props = defineProps<{ documentId: string }>();

const store = useExplorerStore();
const { $gettext, interpolate } = useGettext();
const payload = useDocument(() => props.documentId);
const heading = useTemplateRef<HTMLElement>("heading");
const backButton = useTemplateRef<HTMLElement>("back-button");

const isUnavailable = computed(
    () =>
        payload.status.value === "error" ||
        payload.status.value === "unavailable",
);

const analysedPages = computed(() =>
    (payload.data.value?.canvases ?? []).filter(
        (canvas) => canvas.analysisCount > 0,
    ),
);

useScreenHeading(
    () => heading.value ?? (isUnavailable.value ? backButton.value : null),
);

function pageLabel(label: string, count: number): string {
    return interpolate(
        $gettext("%{page} (%{count})"),
        { page: label, count },
        true,
    );
}

function back(): void {
    store.setCorpusScreen(store.documentOrigin);
}

function goHome(): void {
    store.setCorpusScreen("home");
}
</script>

<template>
    <div class="corpus-document">
        <button
            ref="back-button"
            type="button"
            class="back"
            @click="back"
        >
            <span v-if="store.documentOrigin === 'results'">{{
                $gettext("Back to the results")
            }}</span>
            <span v-else>{{ $gettext("Back to the explorer home") }}</span>
        </button>
        <UnavailableState
            v-if="
                payload.status.value === 'error' ||
                payload.status.value === 'unavailable'
            "
            :status="payload.status.value"
            @retry="payload.retry"
            @home="goHome"
        />
        <article
            v-else-if="payload.data.value"
            class="document"
            :aria-busy="payload.status.value === 'loading' ? 'true' : 'false'"
        >
            <h2
                ref="heading"
                class="name"
                tabindex="-1"
                :lang="payload.data.value.name.lang"
            >
                <span>{{ payload.data.value.name.value }}</span>
            </h2>
            <p
                v-if="payload.data.value.holding"
                class="holding"
                :lang="payload.data.value.holding.lang"
            >
                <span>{{ payload.data.value.holding.value }}</span>
            </p>
            <DraftBanner :count="payload.data.value.unpublishedCount" />
            <section
                v-if="analysedPages.length > 0"
                class="pages"
                aria-labelledby="explorer-document-pages"
            >
                <h3 id="explorer-document-pages">
                    <span>{{ $gettext("Pages with analyses") }}</span>
                </h3>
                <ul>
                    <li
                        v-for="canvas in analysedPages"
                        :key="canvas.id"
                    >
                        <span>{{
                            pageLabel(canvas.label, canvas.analysisCount)
                        }}</span>
                    </li>
                </ul>
            </section>
        </article>
    </div>
</template>

<style scoped>
.corpus-document {
    display: grid;
    gap: 1rem;
    padding-block: 1rem 2rem;
}

.corpus-document .back {
    justify-self: start;
    min-block-size: 2.75rem;
    border: none;
    background: transparent;
    color: var(--blue-text);
    font: inherit;
    text-decoration: underline;
    cursor: pointer;
}

.corpus-document .back:focus-visible {
    outline: 0.125rem solid var(--blue-text);
    outline-offset: 0.125rem;
}

.corpus-document .document {
    display: grid;
    gap: 0.75rem;
}

.corpus-document .name {
    font-family: var(--font-display);
    font-size: 2rem;
    font-weight: 500;
}

.corpus-document .holding {
    color: var(--ink-muted);
}

.corpus-document .pages ul {
    display: flex;
    flex-wrap: wrap;
    gap: 0.5rem 1.5rem;
    padding-inline-start: 1.25rem;
}
</style>
