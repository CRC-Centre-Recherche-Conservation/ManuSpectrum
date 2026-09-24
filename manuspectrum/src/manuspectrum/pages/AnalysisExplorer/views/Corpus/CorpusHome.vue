<script setup lang="ts">
import { computed, ref } from "vue";
import { useGettext } from "vue3-gettext";

import UnavailableState from "@/manuspectrum/pages/AnalysisExplorer/components/UnavailableState.vue";
import DocumentCard from "@/manuspectrum/pages/AnalysisExplorer/views/Corpus/components/DocumentCard.vue";

import { getJson } from "@/manuspectrum/pages/AnalysisExplorer/api/http.ts";
import { useFacetLabels } from "@/manuspectrum/pages/AnalysisExplorer/composables/useFacetLabels.ts";
import { useRequest } from "@/manuspectrum/pages/AnalysisExplorer/composables/useRequest.ts";
import { searchQuery } from "@/manuspectrum/pages/AnalysisExplorer/composables/useSearch.ts";
import {
    emptyFilters,
    useExplorerStore,
} from "@/manuspectrum/pages/AnalysisExplorer/store/explorer.ts";
import {
    documentHref,
    snapshotOf,
} from "@/manuspectrum/pages/AnalysisExplorer/store/url.ts";

import type {
    DocumentHit,
    FacetValue,
    SearchResponse,
} from "@/manuspectrum/pages/AnalysisExplorer/api/types.ts";

const store = useExplorerStore();
const { $gettext, interpolate } = useGettext();

/**
 * Fetches page 1 of the Documents overview (grain "documents",
 * `onlyWithAnalyses`), then every remaining page in parallel on the same
 * signal, and merges their hits. `featured` reduces over the merged set, so
 * it compares analysis counts across the whole corpus, not one page of it.
 * Facets are read from page 1 only.
 */
async function loadOverview(
    query: string,
    signal: AbortSignal,
): Promise<SearchResponse> {
    const first = await getJson<SearchResponse>(
        "manuspectrum:explorer-search",
        { query: new URLSearchParams(query), signal },
    );
    const pageCount =
        first.page.size > 0 ? Math.ceil(first.total / first.page.size) : 1;
    if (pageCount <= 1) {
        return first;
    }
    const rest = await Promise.all(
        Array.from({ length: pageCount - 1 }, (_placeholder, index) =>
            getJson<SearchResponse>("manuspectrum:explorer-search", {
                query: searchQuery(emptyFilters(), index + 2),
                signal,
            }),
        ),
    );
    return {
        ...first,
        results: [first, ...rest].flatMap((page) => page.results),
    };
}

const overview = useRequest<SearchResponse>(
    () => searchQuery(emptyFilters(), 1).toString(),
    loadOverview,
);
const text = ref("");

useFacetLabels(() => overview.data.value?.facets);

const featured = computed<DocumentHit | null>(() => {
    const documents = (overview.data.value?.results ?? []).filter(
        (hit): hit is DocumentHit =>
            hit.type === "document" && hit.analysisCount > 0,
    );
    return documents.reduce<DocumentHit | null>(
        (best, hit) =>
            best === null || hit.analysisCount > best.analysisCount
                ? hit
                : best,
        null,
    );
});
const techniques = computed<FacetValue[]>(
    () =>
        overview.data.value?.facets.find((facet) => facet.key === "technique")
            ?.values ?? [],
);
const projects = computed<FacetValue[]>(
    () =>
        overview.data.value?.facets.find((facet) => facet.key === "project")
            ?.values ?? [],
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

function openDocument(id: string): void {
    store.openDocument(id);
}

function hrefFor(id: string): string {
    return documentHref(snapshotOf(store), id);
}
</script>

<template>
    <div class="corpus-home">
        <p class="promise">
            <span>{{
                $gettext(
                    "Explore what the analyses of written heritage revealed.",
                )
            }}</span>
        </p>
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
        <UnavailableState
            v-if="
                overview.status.value === 'error' ||
                overview.status.value === 'unavailable'
            "
            :status="overview.status.value"
            @retry="overview.retry"
            @home="overview.retry"
        />
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
                v-if="featured"
                class="door featured"
                aria-labelledby="explorer-door-featured"
            >
                <h2
                    id="explorer-door-featured"
                    class="title"
                >
                    <span>{{ $gettext("The most analysed document") }}</span>
                </h2>
                <DocumentCard
                    :hit="featured"
                    :href="hrefFor(featured.id)"
                    @open="openDocument"
                />
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
    gap: 2rem;
    padding-block: 1rem 2rem;
}

.corpus-home .promise {
    font-family: var(--font-display);
    font-size: clamp(1.5rem, 3vw, 2rem);
    color: var(--ink);
}

.corpus-home .search {
    display: grid;
    gap: 0.5rem;
    max-inline-size: 48rem;
}

.corpus-home .row {
    display: flex;
    gap: 0.5rem;
}

.corpus-home .input {
    flex: 1;
    min-block-size: 3rem;
    padding-inline: 1rem;
    border: 0.0625rem solid var(--border-hover);
    border-radius: 999rem;
    background: var(--surface);
    color: var(--ink);
    font: inherit;
}

.corpus-home .submit,
.corpus-home .choice {
    min-block-size: 2.75rem;
    padding-inline: 1.25rem;
    border: 0.0625rem solid var(--ink);
    border-radius: 999rem;
    background: var(--surface);
    color: var(--ink);
    font: inherit;
    cursor: pointer;
}

.corpus-home .submit {
    background: var(--ink);
    color: var(--surface);
}

.corpus-home .doors {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(18rem, 1fr));
    gap: 1.5rem;
}

.corpus-home .door {
    display: grid;
    align-content: start;
    gap: 0.75rem;
}

.corpus-home .title {
    font-family: var(--font-display);
    font-size: 1.375rem;
    font-weight: 500;
}

.corpus-home .choices {
    display: flex;
    flex-wrap: wrap;
    gap: 0.5rem;
    list-style: none;
}

.corpus-home .how-to {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(14rem, 1fr));
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
