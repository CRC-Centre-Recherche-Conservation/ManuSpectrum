<script setup lang="ts">
import { computed, ref, useTemplateRef } from "vue";
import { useGettext } from "vue3-gettext";

import BusyStatus from "@/manuspectrum/pages/AnalysisExplorer/components/BusyStatus.vue";
import UnavailableState from "@/manuspectrum/pages/AnalysisExplorer/components/UnavailableState.vue";
import DocumentCard from "@/manuspectrum/pages/AnalysisExplorer/views/Corpus/components/DocumentCard.vue";

import { useFacetLabels } from "@/manuspectrum/pages/AnalysisExplorer/composables/useFacetLabels.ts";
import { useScreenHeading } from "@/manuspectrum/pages/AnalysisExplorer/composables/useScreenHeading.ts";
import {
    searchQuery,
    useSearch,
} from "@/manuspectrum/pages/AnalysisExplorer/composables/useSearch.ts";
import {
    emptyFilters,
    useExplorerStore,
} from "@/manuspectrum/pages/AnalysisExplorer/store/explorer.ts";
import {
    documentHref,
    snapshotOf,
} from "@/manuspectrum/pages/AnalysisExplorer/store/url.ts";
import { dayIndex } from "@/manuspectrum/pages/AnalysisExplorer/views/Corpus/document-of-the-day.ts";

import type {
    DocumentHit,
    FacetValue,
} from "@/manuspectrum/pages/AnalysisExplorer/api/types.ts";

/**
 * The explorer home (S0): the doors by technique and by project from the
 * first page of the documents overview, and the document of the day: the
 * document at the day's position (`dayIndex`) among those with analyses,
 * read from its page of the overview once the overview has counted them.
 */
const store = useExplorerStore();
const { $gettext, interpolate } = useGettext();
const heading = useTemplateRef<HTMLElement>("heading");
useScreenHeading(() => heading.value);

const overview = useSearch(() => searchQuery(emptyFilters(), 1));
/** The document of the day's page of the overview, and its place on it. */
const dayPlace = computed(() => {
    const payload = overview.data.value;
    const position = dayIndex(new Date(), payload?.total ?? 0);
    if (!payload || position === null) return null;
    const size = payload.page.size || 1;
    return { page: Math.floor(position / size) + 1, index: position % size };
});
const ofTheDay = useSearch(() =>
    dayPlace.value && dayPlace.value.page > 1
        ? searchQuery(emptyFilters(), dayPlace.value.page)
        : null,
);
const text = ref("");

useFacetLabels(() => overview.data.value?.facets);

const featured = computed<DocumentHit | null>(() => {
    const place = dayPlace.value;
    if (!place) return null;
    const payload =
        place.page === 1 ? overview.data.value : ofTheDay.data.value;
    if (payload?.page.number !== place.page) return null;
    const hit = payload.results[place.index];
    return hit?.type === "document" ? hit : null;
});
const featuredLoading = computed(
    () => ofTheDay.status.value === "loading" && featured.value === null,
);
const techniques = computed<FacetValue[]>(
    () =>
        overview.data.value?.facets?.find((facet) => facet.key === "technique")
            ?.values ?? [],
);
const projects = computed<FacetValue[]>(
    () =>
        overview.data.value?.facets?.find((facet) => facet.key === "project")
            ?.values ?? [],
);
const firstLoad = computed(
    () => overview.status.value === "loading" && overview.data.value === null,
);
const nothingPublished = computed(
    () =>
        overview.status.value === "ready" &&
        (techniques.value.length === 0 || overview.data.value?.total === 0),
);

function countLabel(value: FacetValue): string {
    return interpolate(
        $gettext("%{label} (%{count})"),
        {
            label: value.label.value,
            count: value.count,
        },
        true,
    );
}

function submitSearch(): void {
    store.setFilter("q", text.value.trim());
    store.setCorpusScreen("results");
}

function openTechnique(id: string): void {
    store.setFilter("grain", "analyses");
    store.setFilter("technique", [id]);
    store.setCorpusScreen("results");
}

function openProject(id: string): void {
    store.setFilter("project", [id]);
    store.setCorpusScreen("results");
}

function browseAll(): void {
    store.setCorpusScreen("results");
}

function openDocument(id: string): void {
    store.openDocument(id);
}

function hrefFor(id: string): string {
    return documentHref(snapshotOf(store), id);
}
</script>

<template>
    <div class="corpus-home">
        <h2
            ref="heading"
            class="promise"
            tabindex="-1"
        >
            <span>{{
                $gettext(
                    "Explore what the analyses of written heritage revealed.",
                )
            }}</span>
        </h2>
        <form
            class="search"
            role="search"
            @submit.prevent="submitSearch"
        >
            <label
                class="label"
                for="explorer-home-search"
            >
                <span>{{ $gettext("Search the analyses") }}</span>
            </label>
            <div class="row">
                <input
                    id="explorer-home-search"
                    v-model="text"
                    type="search"
                    class="input"
                    autocomplete="off"
                    :placeholder="$gettext('Material, technique, document…')"
                />
                <button
                    type="submit"
                    class="submit"
                >
                    <span>{{ $gettext("Search") }}</span>
                </button>
            </div>
        </form>
        <p class="browse">
            <button
                type="button"
                class="browse-all"
                @click="browseAll"
            >
                <span>{{ $gettext("Browse the whole corpus") }}</span>
            </button>
        </p>
        <BusyStatus
            :busy="overview.status.value === 'loading'"
            :first="firstLoad"
        />
        <UnavailableState
            v-if="
                overview.status.value === 'error' ||
                overview.status.value === 'unavailable'
            "
            :status="overview.status.value"
            :hide-home="true"
            @retry="overview.retry"
        />
        <div
            v-else-if="firstLoad"
            class="doors"
            aria-hidden="true"
        >
            <div
                v-for="door in 3"
                :key="door"
                class="door door-skeleton"
            >
                <span class="ms-skeleton heading"></span>
                <span class="ms-skeleton block"></span>
            </div>
        </div>
        <p
            v-else-if="nothingPublished"
            class="nothing"
        >
            <span>{{ $gettext("No analysis published") }}</span>
        </p>
        <div
            v-else
            class="doors"
            :aria-busy="overview.status.value === 'loading' ? 'true' : 'false'"
        >
            <section
                v-if="featured || featuredLoading"
                class="door featured"
                aria-labelledby="explorer-door-featured"
            >
                <h2
                    id="explorer-door-featured"
                    class="title"
                >
                    <span>{{ $gettext("Document of the day") }}</span>
                </h2>
                <DocumentCard
                    v-if="featured"
                    :hit="featured"
                    :href="hrefFor(featured.id)"
                    @open="openDocument"
                />
                <span
                    v-else
                    class="ms-skeleton featured-skeleton"
                    aria-hidden="true"
                ></span>
            </section>
            <section
                v-if="techniques.length > 0"
                class="door techniques"
                aria-labelledby="explorer-door-techniques"
            >
                <h2
                    id="explorer-door-techniques"
                    class="title"
                >
                    <span>{{ $gettext("By technique") }}</span>
                </h2>
                <ul class="choices">
                    <li
                        v-for="technique in techniques"
                        :key="technique.id"
                    >
                        <button
                            type="button"
                            class="choice"
                            :lang="technique.label.lang"
                            @click="openTechnique(technique.id)"
                        >
                            <span>{{ countLabel(technique) }}</span>
                        </button>
                    </li>
                </ul>
            </section>
            <section
                v-if="projects.length > 0"
                class="door projects"
                aria-labelledby="explorer-door-projects"
            >
                <h2
                    id="explorer-door-projects"
                    class="title"
                >
                    <span>{{ $gettext("By project") }}</span>
                </h2>
                <ul class="choices">
                    <li
                        v-for="project in projects"
                        :key="project.id"
                    >
                        <button
                            type="button"
                            class="choice"
                            :lang="project.label.lang"
                            @click="openProject(project.id)"
                        >
                            <span>{{ countLabel(project) }}</span>
                        </button>
                    </li>
                </ul>
            </section>
        </div>
        <ol class="how-to">
            <li>
                <span>{{
                    $gettext("Search, or open one of the doors above.")
                }}</span>
            </li>
            <li>
                <span>{{
                    $gettext(
                        "Narrow the results by technique, material, project or year.",
                    )
                }}</span>
            </li>
            <li>
                <span>{{
                    $gettext(
                        "Open a document to see where each analysis was made.",
                    )
                }}</span>
            </li>
        </ol>
    </div>
</template>

<style scoped>
.corpus-home {
    display: grid;
    grid-template-columns: minmax(0, 1fr);
    gap: 1.5rem;
    padding-block: 1rem 2rem;
}

.corpus-home .promise {
    font-family: var(--font-display);
    font-size: clamp(1.375rem, 2.5vw, 1.75rem);
    font-weight: 400;
    color: var(--ink);
}

.corpus-home .search {
    display: grid;
    grid-template-columns: minmax(0, 1fr);
    gap: 0.375rem;
    max-inline-size: 44rem;
}

.corpus-home .label {
    color: var(--ink-muted);
    font-family: var(--font-mono);
    font-size: 0.6875rem;
    letter-spacing: 0.12em;
    text-transform: uppercase;
}

.corpus-home .row {
    display: flex;
    gap: 0.5rem;
}

.corpus-home .input {
    flex: 1;
    min-inline-size: 0;
    min-block-size: 2.5rem;
    padding-inline: 1rem;
    border: 0.0625rem solid var(--border-hover);
    border-radius: 999rem;
    background: var(--surface);
    color: var(--ink);
    font: inherit;
}

.corpus-home .submit,
.corpus-home .choice {
    min-block-size: var(--explorer-target);
    padding-inline: 0.875rem;
    border: 0.0625rem solid var(--border-hover);
    border-radius: 999rem;
    background: var(--surface);
    color: var(--ink);
    font: inherit;
    cursor: pointer;
}

.corpus-home .choice {
    text-align: start;
}

.corpus-home .choice:hover {
    border-color: var(--ink);
}

.corpus-home .submit {
    min-block-size: 2.5rem;
    padding-inline: 1.25rem;
    border-color: var(--ink);
    background: var(--ink);
    color: var(--surface);
}

.corpus-home .doors {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(min(18rem, 100%), 1fr));
    gap: 1rem;
    min-block-size: 14rem;
}

.corpus-home .door {
    display: grid;
    align-content: start;
    gap: 0.75rem;
    padding: 1rem;
    border: 0.0625rem solid var(--border);
    border-radius: var(--explorer-radius);
    background: var(--surface);
}

.corpus-home .featured-skeleton {
    block-size: 7rem;
}

.corpus-home .browse-all {
    min-block-size: var(--explorer-target);
    padding: 0;
    border: none;
    background: transparent;
    color: var(--blue-text);
    font: inherit;
    cursor: pointer;
}

.corpus-home .browse-all::after {
    content: " →" / "";
}

.corpus-home .browse-all:hover {
    text-decoration: underline;
}

.corpus-home .door-skeleton .heading {
    inline-size: 50%;
    block-size: 1.25rem;
}

.corpus-home .door-skeleton .block {
    block-size: 9rem;
}

.corpus-home .title {
    color: var(--ink-muted);
    font-family: var(--font-mono);
    font-size: 0.6875rem;
    font-weight: 400;
    letter-spacing: 0.12em;
    text-transform: uppercase;
}

.corpus-home .choices {
    display: flex;
    flex-wrap: wrap;
    gap: 0.375rem;
    list-style: none;
}

.corpus-home .how-to {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(min(14rem, 100%), 1fr));
    gap: 1rem;
    padding-inline-start: 1.25rem;
    color: var(--ink-muted);
}

.corpus-home .input:focus-visible,
.corpus-home button:focus-visible {
    outline: 0.125rem solid var(--blue-text);
    outline-offset: 0.125rem;
}
</style>
