<script setup lang="ts">
import {
    computed,
    inject,
    nextTick,
    ref,
    shallowRef,
    useTemplateRef,
    watch,
} from "vue";
import { useGettext } from "vue3-gettext";

import BusyStatus from "@/manuspectrum/pages/AnalysisExplorer/components/BusyStatus.vue";
import UnavailableState from "@/manuspectrum/pages/AnalysisExplorer/components/UnavailableState.vue";
import DraftBanner from "@/manuspectrum/pages/AnalysisExplorer/components/DraftBanner.vue";
import AnalysisRow from "@/manuspectrum/pages/AnalysisExplorer/views/Corpus/components/AnalysisRow.vue";
import DocumentCard from "@/manuspectrum/pages/AnalysisExplorer/views/Corpus/components/DocumentCard.vue";
import FacetRail from "@/manuspectrum/pages/AnalysisExplorer/views/Corpus/components/FacetRail.vue";
import RailPanel from "@/manuspectrum/pages/AnalysisExplorer/views/Corpus/components/RailPanel.vue";

import { peekJson } from "@/manuspectrum/pages/AnalysisExplorer/api/http.ts";
import { useActiveFilters } from "@/manuspectrum/pages/AnalysisExplorer/composables/useActiveFilters.ts";
import { useDocumentPrefetch } from "@/manuspectrum/pages/AnalysisExplorer/composables/useDocumentPrefetch.ts";
import {
    RESULTS_MEMO_KEY,
    SCREEN_FOCUS_KEY,
} from "@/manuspectrum/pages/AnalysisExplorer/injection-keys.ts";
import { useFacetLabels } from "@/manuspectrum/pages/AnalysisExplorer/composables/useFacetLabels.ts";
import { useScreenHeading } from "@/manuspectrum/pages/AnalysisExplorer/composables/useScreenHeading.ts";
import {
    filterQuery,
    filtersOf,
    searchQuery,
    useSearch,
} from "@/manuspectrum/pages/AnalysisExplorer/composables/useSearch.ts";
import {
    PAGE_SIZES,
    selectedFacets,
    useExplorerStore,
} from "@/manuspectrum/pages/AnalysisExplorer/store/explorer.ts";
import {
    documentHref,
    snapshotOf,
} from "@/manuspectrum/pages/AnalysisExplorer/store/url.ts";

import type {
    AnalysisHit,
    DocumentHit,
    Facet,
    FacetKey,
    SearchResponse,
} from "@/manuspectrum/pages/AnalysisExplorer/api/types.ts";
import type { ResultsMemo } from "@/manuspectrum/pages/AnalysisExplorer/injection-keys.ts";
import type { PageSize } from "@/manuspectrum/pages/AnalysisExplorer/store/types.ts";

const SKELETON_CARDS = 4;

/**
 * The results (S1). Coming back from a document opened here shows the same
 * page of the same results again (from the tab memo while it holds them), at
 * the same scroll, with the keyboard focus on the result that was opened
 * (`RESULTS_MEMO_KEY`). The facets of a filter set are asked for once: a
 * page, grain or size change asks for none (`facets=0`). A filter change
 * waits for the filters to settle; the next page and a card the reader rests
 * on load ahead.
 */
const store = useExplorerStore();
const { $gettext, $ngettext, interpolate } = useGettext();
const { activeFilters } = useActiveFilters();
const memo = inject(
    RESULTS_MEMO_KEY,
    () => ref<ResultsMemo | null>(null),
    true,
);
const screenFocus = inject(SCREEN_FOCUS_KEY, null);
const heading = useTemplateRef<HTMLElement>("heading");
const list = useTemplateRef<HTMLElement>("list");

// Declared before useSearch, whose source reads `page` at once. A page belongs
// to one filter set: any filter change reads as page 1 in the same tick.
const filterKey = computed(() => searchQuery(store.filters, 1).toString());
const returning = memo.value?.filterKey === filterKey.value ? memo.value : null;
const pageState = ref({
    key: returning ? filterKey.value : "",
    number: returning?.page ?? 1,
});
const restoring = ref(returning?.opened != null);
let restored = false;
const page = computed(() =>
    pageState.value.key === filterKey.value ? pageState.value.number : 1,
);

/** The facets last received, with the filters (`filtersOf`) they count; at first, those of the first page the tab holds. */
const heldFacets = shallowRef<{ filters: string; facets: Facet[] } | null>(
    heldFirstPage(),
);

useScreenHeading(() => (restoring.value ? null : heading.value));
const search = useSearch(() => searchQuery(store.filters, page.value), {
    holdsFacets: (filters) => heldFacets.value?.filters === filters,
    debounceFilters: true,
});
const prefetch = useDocumentPrefetch(() => filterQuery(store.filters));

/** The filters of the payload shown, and of the rail. */
const shownFilters = computed(() => filtersOf(search.loaded.value ?? ""));
const facets = computed<Facet[]>(() => {
    const payload = search.data.value;
    if (payload?.facets) return payload.facets;
    return heldFacets.value?.filters === shownFilters.value
        ? heldFacets.value.facets
        : [];
});
useFacetLabels(() => facets.value);

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
const withoutAnalyses = computed(() =>
    store.filters.grain === "documents"
        ? search.data.value?.withoutAnalyses ?? 0
        : 0,
);
const withoutAnalysesText = computed(() =>
    interpolate(
        store.filters.empty
            ? $ngettext(
                  "Hide the %{n} document without analyses",
                  "Hide the %{n} documents without analyses",
                  withoutAnalyses.value,
              )
            : $ngettext(
                  "+ %{n} document without analyses — show",
                  "+ %{n} documents without analyses — show",
                  withoutAnalyses.value,
              ),
        { n: withoutAnalyses.value },
        true,
    ),
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

/**
 * Each payload shown is recorded with the query it answers: its facets for
 * the next pages of these filters, the memo for the way back, and the next
 * page is loaded ahead.
 */
watch(
    () =>
        [search.data.value, search.status.value, search.loaded.value] as const,
    ([payload, status, query]) => {
        if (!payload || status !== "ready" || query === null) return;
        if (payload.facets) {
            heldFacets.value = {
                filters: filtersOf(query),
                facets: payload.facets,
            };
        }
        memo.value = {
            query,
            filterKey: filterKey.value,
            page: page.value,
            total: payload.total,
            grain: store.filters.grain,
            scroll: 0,
            opened: null,
        };
        if (page.value < pageCount.value) {
            search.prefetch(searchQuery(store.filters, page.value + 1));
        }
        void restore();
    },
    { immediate: true },
);

/** Back from a document: once the page it was opened from is shown, its scroll and the focus on the result opened. */
async function restore(): Promise<void> {
    if (restored || !returning || returning.opened === null) return;
    restored = true;
    await nextTick();
    window.scrollTo(0, returning.scroll);
    list.value
        ?.querySelector<HTMLElement>(
            `[data-result="${returning.opened}"] :is(a, button)`,
        )
        ?.focus({ preventScroll: true });
    if (screenFocus) screenFocus.value = false;
    restoring.value = false;
}

function isDocument(hit: DocumentHit | AnalysisHit): hit is DocumentHit {
    return hit.type === "document";
}

function heldFirstPage(): { filters: string; facets: Facet[] } | null {
    const query = searchQuery(store.filters, 1);
    const facets = peekJson<SearchResponse>("manuspectrum:explorer-search", {
        query,
    })?.facets;
    return facets ? { filters: filtersOf(query.toString()), facets } : null;
}

function documentOf(hit: DocumentHit | AnalysisHit): string {
    return isDocument(hit) ? hit.id : hit.document.id;
}

function onFacetChange(key: FacetKey, ids: string[]): void {
    store.setFacet(key, ids);
}

function setGrain(grain: "documents" | "analyses"): void {
    store.setFilter("grain", grain);
}

function toggleEmpty(): void {
    store.setFilter("empty", !store.filters.empty);
}

function setSize(size: PageSize): void {
    store.setFilter("size", size);
}

/** Records where the reader leaves the results, to come back there. */
function rememberOpened(id: string): void {
    if (memo.value) {
        memo.value = { ...memo.value, scroll: window.scrollY, opened: id };
    }
}

function hrefFor(id: string): string {
    return documentHref(snapshotOf(store), id);
}

function openDocument(id: string): void {
    rememberOpened(id);
    store.openDocument(id);
}

/** The document, then its card: two history entries, so Back closes the card first. */
async function openAnalysis(hit: AnalysisHit): Promise<void> {
    rememberOpened(hit.id);
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
                :facets="facets"
                :selected="selectedFacets(store.filters)"
                :facet-query="shownFilters"
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
                <div
                    class="page-size"
                    role="group"
                    :aria-label="$gettext('Results per page')"
                >
                    <span
                        class="page-size-label"
                        aria-hidden="true"
                        >{{ $gettext("Per page") }}</span
                    >
                    <button
                        v-for="size in PAGE_SIZES"
                        :key="size"
                        type="button"
                        :aria-pressed="
                            store.filters.size === size ? 'true' : 'false'
                        "
                        @click="setSize(size)"
                    >
                        <span>{{ size }}</span>
                    </button>
                </div>
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
                ref="list"
                class="list"
                :aria-busy="loading ? 'true' : 'false'"
            >
                <li
                    v-for="hit in search.data.value?.results ?? []"
                    :key="hit.id"
                    :data-result="hit.id"
                    @pointerenter="prefetch.intend(documentOf(hit))"
                    @pointerleave="prefetch.drop"
                    @focusin="prefetch.intend(documentOf(hit))"
                    @focusout="prefetch.drop"
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
            <p
                v-if="withoutAnalyses > 0"
                class="without-analyses"
            >
                <button
                    type="button"
                    :aria-pressed="store.filters.empty ? 'true' : 'false'"
                    @click="toggleEmpty"
                >
                    <span>{{ withoutAnalysesText }}</span>
                </button>
            </p>
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

.corpus-results .option {
    display: inline-flex;
    align-items: center;
    gap: 0.5rem;
    min-block-size: var(--explorer-target);
    cursor: pointer;
}

.corpus-results .page-size {
    display: flex;
    align-items: center;
    gap: 0.25rem;
    font-family: var(--font-mono);
    font-size: 0.75rem;
}

.corpus-results .page-size-label {
    margin-inline-end: 0.25rem;
    color: var(--ink-muted);
}

.corpus-results .page-size button {
    min-inline-size: var(--explorer-target);
    min-block-size: var(--explorer-target);
    border: 0.0625rem solid var(--border);
    border-radius: 0.375rem;
    background: var(--surface);
    color: var(--ink);
    font: inherit;
    cursor: pointer;
}

.corpus-results .page-size button[aria-pressed="true"] {
    border-color: var(--ink);
    background: var(--ink);
    color: var(--surface);
}

.corpus-results .without-analyses button {
    min-block-size: var(--explorer-target);
    padding: 0;
    border: none;
    background: transparent;
    color: var(--blue-text);
    font: inherit;
    font-size: 0.8125rem;
    cursor: pointer;
}

.corpus-results .without-analyses button:hover {
    text-decoration: underline;
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
