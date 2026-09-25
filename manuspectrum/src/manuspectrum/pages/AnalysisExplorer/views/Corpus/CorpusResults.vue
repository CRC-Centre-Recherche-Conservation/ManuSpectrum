<script setup lang="ts">
import { computed, nextTick, ref, useTemplateRef } from "vue";
import { useGettext } from "vue3-gettext";

import BusyStatus from "@/manuspectrum/pages/AnalysisExplorer/components/BusyStatus.vue";
import UnavailableState from "@/manuspectrum/pages/AnalysisExplorer/components/UnavailableState.vue";
import DraftBanner from "@/manuspectrum/pages/AnalysisExplorer/components/DraftBanner.vue";
import AnalysisRow from "@/manuspectrum/pages/AnalysisExplorer/views/Corpus/components/AnalysisRow.vue";
import DocumentCard from "@/manuspectrum/pages/AnalysisExplorer/views/Corpus/components/DocumentCard.vue";
import FacetRail from "@/manuspectrum/pages/AnalysisExplorer/views/Corpus/components/FacetRail.vue";
import RailPanel from "@/manuspectrum/pages/AnalysisExplorer/views/Corpus/components/RailPanel.vue";

import { useActiveFilters } from "@/manuspectrum/pages/AnalysisExplorer/composables/useActiveFilters.ts";
import { useFacetLabels } from "@/manuspectrum/pages/AnalysisExplorer/composables/useFacetLabels.ts";
import { useScreenHeading } from "@/manuspectrum/pages/AnalysisExplorer/composables/useScreenHeading.ts";
import {
    searchQuery,
    useSearch,
} from "@/manuspectrum/pages/AnalysisExplorer/composables/useSearch.ts";
import { useExplorerStore } from "@/manuspectrum/pages/AnalysisExplorer/store/explorer.ts";
import {
    documentHref,
    snapshotOf,
} from "@/manuspectrum/pages/AnalysisExplorer/store/url.ts";

import type {
    AnalysisHit,
    DocumentHit,
    FacetKey,
} from "@/manuspectrum/pages/AnalysisExplorer/api/types.ts";

const SKELETON_CARDS = 4;

const store = useExplorerStore();
const { $gettext, $ngettext, interpolate } = useGettext();
const { activeFilters } = useActiveFilters();
const heading = useTemplateRef<HTMLElement>("heading");
useScreenHeading(() => heading.value);

// Declared before useSearch, whose source reads `page` at once. A page belongs
// to one filter set: any filter change reads as page 1 in the same tick.
const filterKey = computed(() => searchQuery(store.filters, 1).toString());
const pageState = ref({ key: "", number: 1 });
const page = computed(() =>
    pageState.value.key === filterKey.value ? pageState.value.number : 1,
);

const search = useSearch(() => searchQuery(store.filters, page.value));
useFacetLabels(() => search.data.value?.facets);
const probe = useSearch(() => {
    const data = search.data.value;
    const filters = store.filters;
    const empty =
        search.status.value === "ready" && data !== null && data.total === 0;
    return empty && filters.grain === "documents" && filters.onlyWithAnalyses
        ? searchQuery({ ...filters, onlyWithAnalyses: false }, 1)
        : null;
});

const total = computed(() => search.data.value?.total ?? 0);
const pageCount = computed(() => {
    const size = search.data.value?.page.size ?? 1;
    return Math.max(1, Math.ceil(total.value / size));
});
const countText = computed(() =>
    interpolate(
        $ngettext("%{n} result", "%{n} results", total.value),
        {
            n: total.value,
        },
        true,
    ),
);
const withoutAnalysesCount = computed(() =>
    probe.status.value === "ready" ? probe.data.value?.total ?? 0 : 0,
);
const isEmpty = computed(
    () => search.status.value === "ready" && total.value === 0,
);
const showLabel = computed(() =>
    interpolate(
        $ngettext("See %{n} result", "See %{n} results", total.value),
        { n: total.value },
        true,
    ),
);
const loading = computed(() => search.status.value === "loading");
/** Nothing to show yet: the first load of this screen. */
const firstLoad = computed(() => loading.value && search.data.value === null);

function isDocument(hit: DocumentHit | AnalysisHit): hit is DocumentHit {
    return hit.type === "document";
}

function onFacetChange(key: FacetKey, ids: string[]): void {
    store.setFacet(key, ids);
}

function setGrain(grain: "documents" | "analyses"): void {
    store.setFilter("grain", grain);
}

function onOnlyWithAnalyses(event: Event): void {
    store.setFilter(
        "onlyWithAnalyses",
        (event.target as HTMLInputElement).checked,
    );
}

function includeWithoutAnalyses(): void {
    store.setFilter("onlyWithAnalyses", false);
}

function hrefFor(id: string): string {
    return documentHref(snapshotOf(store), id);
}

function openDocument(id: string): void {
    store.openDocument(id);
}

/** The document, then its card: two history entries, so Back closes the card first. */
async function openAnalysis(hit: AnalysisHit): Promise<void> {
    store.openDocument(hit.document.id, hit.canvas);
    await nextTick();
    store.focusOn({ kind: "analysis", id: hit.id });
}

function goToPage(next: number): void {
    pageState.value = {
        key: filterKey.value,
        number: Math.min(Math.max(1, next), pageCount.value),
    };
}

function goHome(): void {
    store.setCorpusScreen("home");
}
</script>

<template>
    <div class="corpus-results">
        <RailPanel
            class="rail"
            :show-label="showLabel"
        >
            <FacetRail
                :facets="search.data.value?.facets ?? []"
                @change="onFacetChange"
            />
        </RailPanel>
        <section
            class="results"
            aria-labelledby="explorer-results-title"
        >
            <BusyStatus
                :busy="loading"
                :first="firstLoad"
            />
            <h2
                id="explorer-results-title"
                ref="heading"
                class="visually-hidden"
                tabindex="-1"
            >
                <span>{{ $gettext("Results") }}</span>
            </h2>
            <div class="toolbar">
                <fieldset class="grain">
                    <legend class="visually-hidden">
                        <span>{{ $gettext("Show") }}</span>
                    </legend>
                    <label class="option">
                        <input
                            type="radio"
                            name="explorer-grain"
                            value="documents"
                            :checked="store.filters.grain === 'documents'"
                            @change="setGrain('documents')"
                        />
                        <span>{{ $gettext("Documents") }}</span>
                    </label>
                    <label class="option">
                        <input
                            type="radio"
                            name="explorer-grain"
                            value="analyses"
                            :checked="store.filters.grain === 'analyses'"
                            @change="setGrain('analyses')"
                        />
                        <span>{{ $gettext("Analyses") }}</span>
                    </label>
                </fieldset>
                <label
                    v-if="store.filters.grain === 'documents'"
                    class="only-with-analyses"
                >
                    <input
                        type="checkbox"
                        :checked="store.filters.onlyWithAnalyses"
                        @change="onOnlyWithAnalyses"
                    />
                    <span>{{ $gettext("Only with analyses") }}</span>
                </label>
                <p
                    class="count"
                    aria-live="polite"
                >
                    <span v-if="search.status.value === 'ready'">{{
                        countText
                    }}</span>
                </p>
            </div>
            <DraftBanner
                scope="results"
                :count="search.data.value?.unpublishedCount ?? 0"
            />
            <UnavailableState
                v-if="
                    search.status.value === 'error' ||
                    search.status.value === 'unavailable'
                "
                :status="search.status.value"
                @retry="search.retry"
                @home="goHome"
            />
            <div
                v-else-if="isEmpty"
                class="empty"
            >
                <p>
                    <span>{{ $gettext("No result.") }}</span>
                </p>
                <button
                    v-if="withoutAnalysesCount > 0"
                    type="button"
                    class="include-without"
                    @click="includeWithoutAnalyses"
                >
                    <span>
                        {{
                            interpolate(
                                $gettext(
                                    "Include documents without analyses (%{n})",
                                ),
                                {
                                    n: withoutAnalysesCount,
                                },
                                true,
                            )
                        }}
                    </span>
                </button>
                <button
                    v-for="filter in activeFilters"
                    :key="filter.id"
                    type="button"
                    class="remove-filter"
                    @click="filter.clear"
                >
                    <span>{{
                        interpolate(
                            $gettext("Remove: %{label}"),
                            {
                                label: filter.label,
                            },
                            true,
                        )
                    }}</span>
                </button>
            </div>
            <ul
                v-else-if="firstLoad"
                class="list"
                aria-hidden="true"
            >
                <li
                    v-for="index in SKELETON_CARDS"
                    :key="index"
                    class="card-skeleton"
                >
                    <span class="ms-skeleton thumbnail"></span>
                    <span class="lines">
                        <span class="ms-skeleton line"></span>
                        <span class="ms-skeleton line short"></span>
                    </span>
                </li>
            </ul>
            <ul
                v-else
                class="list"
                :aria-busy="loading ? 'true' : 'false'"
            >
                <li
                    v-for="hit in search.data.value?.results ?? []"
                    :key="hit.id"
                >
                    <DocumentCard
                        v-if="isDocument(hit)"
                        :hit="hit"
                        :href="hrefFor(hit.id)"
                        @open="openDocument"
                    />
                    <AnalysisRow
                        v-else
                        :hit="hit"
                        @open="openAnalysis"
                    />
                </li>
            </ul>
            <nav
                v-if="pageCount > 1 && !isEmpty"
                class="pagination"
                :aria-label="$gettext('Pages')"
            >
                <button
                    type="button"
                    class="previous"
                    :disabled="page <= 1"
                    @click="goToPage(page - 1)"
                >
                    <span>{{ $gettext("Previous page") }}</span>
                </button>
                <span>{{
                    interpolate(
                        $gettext("Page %{page} of %{pages}"),
                        {
                            page,
                            pages: pageCount,
                        },
                        true,
                    )
                }}</span>
                <button
                    type="button"
                    class="next"
                    :disabled="page >= pageCount"
                    @click="goToPage(page + 1)"
                >
                    <span>{{ $gettext("Next page") }}</span>
                </button>
            </nav>
        </section>
    </div>
</template>

<style scoped>
.corpus-results {
    display: grid;
    grid-template-columns: var(--explorer-rail) minmax(0, 1fr);
    align-items: start;
    gap: 1.5rem;
    padding-block: 0.5rem 1rem;
}

.corpus-results .results {
    display: grid;
    align-content: start;
    gap: 0.75rem;
    min-inline-size: 0;
}

.corpus-results .toolbar {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: 0.5rem 1.25rem;
    padding-block-end: 0.5rem;
    border-block-end: 0.0625rem solid var(--border);
}

.corpus-results .grain {
    display: flex;
    gap: 1rem;
    border: none;
}

.corpus-results .option,
.corpus-results .only-with-analyses {
    display: inline-flex;
    align-items: center;
    gap: 0.5rem;
    min-block-size: var(--explorer-target);
    cursor: pointer;
}

.corpus-results .count {
    margin-inline-start: auto;
    color: var(--ink-muted);
    font-family: var(--font-mono);
    font-size: 0.75rem;
}

.corpus-results .list {
    display: grid;
    gap: 0.5rem;
    list-style: none;
}

.corpus-results .card-skeleton {
    display: grid;
    grid-template-columns: 4rem 1fr;
    gap: 1rem;
    padding: 0.75rem;
    border: 0.0625rem solid var(--border);
    border-radius: var(--explorer-radius);
    background: var(--surface);
}

.corpus-results .card-skeleton .thumbnail {
    block-size: 5rem;
}

.corpus-results .card-skeleton .lines {
    display: grid;
    align-content: start;
    gap: 0.5rem;
}

.corpus-results .card-skeleton .line {
    inline-size: 60%;
    block-size: 1.125rem;
}

.corpus-results .card-skeleton .line.short {
    inline-size: 35%;
    block-size: 0.75rem;
}

.corpus-results .empty {
    display: grid;
    justify-items: start;
    gap: 0.5rem;
}

.corpus-results .empty button,
.corpus-results .pagination button {
    min-block-size: var(--explorer-target);
    padding-inline: 0.875rem;
    border: 0.0625rem solid var(--border-hover);
    border-radius: 999rem;
    background: var(--surface);
    color: var(--ink);
    font: inherit;
    cursor: pointer;
}

.corpus-results .pagination {
    display: flex;
    align-items: center;
    justify-content: center;
    gap: 1rem;
}

.corpus-results button:disabled {
    cursor: not-allowed;
    opacity: 0.5;
}

.corpus-results button:focus-visible,
.corpus-results input:focus-visible {
    outline: 0.125rem solid var(--blue-text);
    outline-offset: 0.125rem;
}

.corpus-results .visually-hidden {
    position: absolute;
    inline-size: 0.0625rem;
    block-size: 0.0625rem;
    overflow: hidden;
    clip-path: inset(50%);
    white-space: nowrap;
}

@media (max-width: 80rem) {
    .corpus-results {
        grid-template-columns: minmax(0, 1fr);
    }
}
</style>
