<script setup lang="ts">
import { computed, ref, useId } from "vue";
import { useGettext } from "vue3-gettext";

import InputText from "primevue/inputtext";
import Tooltip from "primevue/tooltip";

import ColourScopeOption from "@/manuspectrum/pages/AnalysisExplorer/views/Corpus/components/ColourScopeOption.vue";
import FacetTree from "@/manuspectrum/pages/AnalysisExplorer/views/Corpus/components/FacetTree.vue";
import FacetValues from "@/manuspectrum/pages/AnalysisExplorer/views/Corpus/components/FacetValues.vue";

import {
    buildTree,
    flatten,
    SEARCH_THRESHOLD,
} from "@/manuspectrum/pages/AnalysisExplorer/views/Corpus/components/facet-tree.ts";
import { useFacetValues } from "@/manuspectrum/pages/AnalysisExplorer/composables/useFacetValues.ts";
import { useVocabulary } from "@/manuspectrum/pages/AnalysisExplorer/composables/useVocabulary.ts";
import { useExplorerStore } from "@/manuspectrum/pages/AnalysisExplorer/store/explorer.ts";

import type {
    Facet,
    FacetGroup,
    FacetKey,
    FacetValue,
} from "@/manuspectrum/pages/AnalysisExplorer/api/types.ts";
import type { FacetLookup } from "@/manuspectrum/pages/AnalysisExplorer/composables/useFacetValues.ts";
import type { RequestHandle } from "@/manuspectrum/pages/AnalysisExplorer/composables/useRequest.ts";

const PREVIEW_SIZE = 6;
const GROUPS: readonly FacetGroup[] = [
    "document",
    "part",
    "analysis",
    "characterization",
];
/** The facets of each group in rail order; the period slider joins the document group later. */
const GROUP_KEYS: Readonly<Record<FacetGroup, readonly FacetKey[]>> = {
    document: ["place"],
    part: ["partType", "part"],
    analysis: ["project", "technique", "operator", "year"],
    characterization: ["material", "colour", "layer", "element"],
};
const RAIL_KEYS: readonly FacetKey[] = [
    ...GROUP_KEYS.document,
    ...GROUP_KEYS.part,
    ...GROUP_KEYS.analysis,
    ...GROUP_KEYS.characterization,
];
/** Facets that list every value, in the order served, with no search box nor « Show all ». */
const FIXED_LIST_KEYS: readonly FacetKey[] = ["colour"];
/** Facets drawn as a tree by `FacetTree`: they always hold every value (a tree needs the parents), searched, never cut to a preview. */
const TREE_KEYS: readonly FacetKey[] = ["place"];

/**
 * The facets of a Corpus screen, in four groups (document, studied
 * component, analysis, identified material), each folding to its heading
 * (state in the store). The place is a tree (`FacetTree`). The Colour facet lists every colour in the order served (a colour
 * with no hit greyed, never dropped); under it, a folded option says where the
 * colour is recorded (`filters.colourScope`).
 * What is ticked comes from `selected` (the filters in force), never from the
 * payload's `selected`, which lags behind while the next search loads.
 * `countHint`, a translated text with `%{n}`, says what a count counts
 * (« %{n} in this document »). Under `facetQuery`, the query of the facet
 * route (the filters, `filtersOf`, and `document=` on a document's rail),
 * a facet longer than `SEARCH_THRESHOLD` has a search box: the values shown
 * are the server's answer to the typed text (`facet/<key>?find=`), marked
 * busy until it arrives, plus the ticked values it lacks. A facet the server
 * cut short (`total` above its values) asks the server for every value when
 * unfolded. Without `facetQuery` the rail shows what it holds, with no
 * search box.
 */
const props = withDefaults(
    defineProps<{
        facets: Facet[];
        selected: Partial<Record<FacetKey, readonly string[]>>;
        countHint?: string;
        facetQuery?: string | null;
    }>(),
    { countHint: "", facetQuery: null },
);
const emit = defineEmits<{ change: [key: FacetKey, ids: string[]] }>();

const vTooltip = Tooltip;
const store = useExplorerStore();
const { $gettext, interpolate } = useGettext();
const { facetTitle, groupTitle } = useVocabulary();
const baseId = useId();

const expanded = ref<Set<FacetKey>>(new Set());
const queries = ref<Partial<Record<FacetKey, string>>>({});

const byKey = computed(
    () => new Map(props.facets.map((facet) => [facet.key, facet])),
);
const sections = computed(() =>
    GROUPS.map((group) => ({
        group,
        facets: GROUP_KEYS[group].flatMap((key) => {
            const facet = byKey.value.get(key);
            return facet ? [facet] : [];
        }),
    })).filter((section) => section.facets.length > 0),
);

/** The full values of each facet the server cut short, asked for once unfolded or searched. */
const lazyFacets = new Map<FacetKey, RequestHandle<Facet>>(
    RAIL_KEYS.map((key) => [key, useFacetValues(key, () => lookupFor(key))]),
);

function isFixedList(key: FacetKey): boolean {
    return FIXED_LIST_KEYS.includes(key);
}

function isTree(key: FacetKey): boolean {
    return TREE_KEYS.includes(key);
}

function isCollapsed(group: FacetGroup): boolean {
    return store.collapsedGroups.includes(group);
}

function groupBodyId(group: FacetGroup): string {
    return `${baseId}-${group}`;
}

function isSelected(key: FacetKey, id: string): boolean {
    return props.selected[key]?.includes(id) ?? false;
}

function isExpanded(key: FacetKey): boolean {
    return expanded.value.has(key);
}

function toggleExpanded(key: FacetKey): void {
    const next = new Set(expanded.value);
    if (next.has(key)) {
        next.delete(key);
    } else {
        next.add(key);
    }
    expanded.value = next;
}

/** Whether the server sent only part of the values of `facet`. */
function isCut(facet: Facet): boolean {
    return facet.total > facet.values.length;
}

/** What to ask the server for a facet searched, or cut and unfolded; null when nothing is to be asked. */
function lookupFor(key: FacetKey): FacetLookup | null {
    const facet = byKey.value.get(key);
    if (props.facetQuery === null || !facet) return null;
    const find = queryOf(key);
    const wantsAll = (expanded.value.has(key) || isTree(key)) && isCut(facet);
    if (!find && !wantsAll) return null;
    return { filters: props.facetQuery, find };
}

/** Every value of `facet` the rail holds: the server's full list once it answered for these filters, else the values sent. */
function valuesOf(facet: Facet): FacetValue[] {
    const lazy = lazyFacets.get(facet.key);
    const loaded = lazy?.loaded.value;
    if (
        !lazy?.data.value ||
        loaded == null ||
        lookupFor(facet.key) === null ||
        (JSON.parse(loaded) as FacetLookup).filters !== props.facetQuery
    ) {
        return facet.values;
    }
    return lazy.data.value.values;
}

function isLoading(key: FacetKey): boolean {
    return lazyFacets.get(key)?.status.value === "loading";
}

function isSearchable(facet: Facet): boolean {
    return (
        props.facetQuery !== null &&
        !isFixedList(facet.key) &&
        facet.total > SEARCH_THRESHOLD
    );
}

function queryOf(key: FacetKey): string {
    return (queries.value[key] ?? "").trim();
}

function setQuery(key: FacetKey, text: string | undefined): void {
    queries.value = { ...queries.value, [key]: text ?? "" };
}

/** The values shown: the server's answer to the search and the ticked ones, else the first ones, a ticked one, or all once expanded. */
function visibleValues(facet: Facet): FacetValue[] {
    const values = valuesOf(facet);
    if (isFixedList(facet.key)) {
        return values;
    }
    if (isSearchable(facet) && queryOf(facet.key)) {
        const shown = new Set(values.map((value) => value.id));
        const ticked = facet.values.filter(
            (value) => !shown.has(value.id) && isSelected(facet.key, value.id),
        );
        return [...values, ...ticked];
    }
    if (isExpanded(facet.key)) {
        return values;
    }
    return values.filter(
        (value, index) =>
            index < PREVIEW_SIZE || isSelected(facet.key, value.id),
    );
}

function hasNoMatch(facet: Facet): boolean {
    if (queryOf(facet.key) === "" || isLoading(facet.key)) return false;
    return isTree(facet.key)
        ? flatten(buildTree(valuesOf(facet)), queryOf(facet.key)).length === 0
        : visibleValues(facet).length === 0;
}

function showsMore(facet: Facet): boolean {
    return (
        !isFixedList(facet.key) &&
        !isTree(facet.key) &&
        facet.total > PREVIEW_SIZE &&
        queryOf(facet.key) === ""
    );
}

function moreLabel(facet: Facet): string {
    return isExpanded(facet.key)
        ? $gettext("Show fewer")
        : interpolate(
              $gettext("Show all (%{count})"),
              {
                  count: facet.total,
              },
              true,
          );
}

function searchLabel(key: FacetKey): string {
    return interpolate(
        $gettext("Search in %{facet}"),
        { facet: facetTitle(key) },
        true,
    );
}

/** The labels of the ticked values of a facet, by the labels its values carry. */
function tickedLabels(key: FacetKey): string[] {
    const facet = byKey.value.get(key);
    const values = facet ? valuesOf(facet) : [];
    return (props.selected[key] ?? []).map(
        (id) => values.find((value) => value.id === id)?.label.value ?? id,
    );
}

/** « Selection: Blue, Red »; empty without ticks. */
function selectionSummary(facet: Facet): string {
    const labels = tickedLabels(facet.key);
    return labels.length > 0
        ? interpolate(
              $gettext("Selection: %{values}"),
              { values: labels.join(", ") },
              true,
          )
        : "";
}

function summaryId(key: FacetKey): string {
    return `${baseId}-${key}-summary`;
}

function onTreeChange(facet: Facet, ids: string[]): void {
    emit("change", facet.key, ids);
}

function onChange(facet: Facet, id: string, checked: boolean): void {
    const current = (props.selected[facet.key] ?? []).filter(
        (entry) => entry !== id,
    );
    emit("change", facet.key, checked ? [...current, id] : current);
}
</script>

<template>
    <div class="facet-rail">
        <section
            v-for="section in sections"
            :key="section.group"
            class="group"
        >
            <h3 class="group-title">
                <button
                    type="button"
                    class="disclosure"
                    :aria-expanded="
                        isCollapsed(section.group) ? 'false' : 'true'
                    "
                    :aria-controls="groupBodyId(section.group)"
                    @click="store.toggleGroup(section.group)"
                >
                    <span
                        class="chevron"
                        aria-hidden="true"
                        >{{ isCollapsed(section.group) ? "▸" : "▾" }}</span
                    >
                    <span>{{ groupTitle(section.group) }}</span>
                </button>
            </h3>
            <div
                v-show="!isCollapsed(section.group)"
                :id="groupBodyId(section.group)"
                class="group-body"
            >
                <fieldset
                    v-for="facet in section.facets"
                    :key="facet.key"
                    class="facet"
                    :aria-describedby="
                        selectionSummary(facet)
                            ? summaryId(facet.key)
                            : undefined
                    "
                >
                    <legend class="title">
                        <span
                            v-if="selectionSummary(facet)"
                            v-tooltip.top="selectionSummary(facet)"
                            class="title-hint"
                        >
                            <span
                                v-tooltip.focus.top="selectionSummary(facet)"
                                class="title-text"
                                tabindex="0"
                                >{{ facetTitle(facet.key) }}</span
                            >
                        </span>
                        <span v-else>{{ facetTitle(facet.key) }}</span>
                    </legend>
                    <span
                        v-if="selectionSummary(facet)"
                        :id="summaryId(facet.key)"
                        class="visually-hidden"
                        >{{ selectionSummary(facet) }}</span
                    >
                    <InputText
                        v-if="isSearchable(facet)"
                        class="search"
                        type="search"
                        size="small"
                        autocomplete="off"
                        :model-value="queries[facet.key] ?? ''"
                        :placeholder="$gettext('Search…')"
                        :aria-label="searchLabel(facet.key)"
                        @update:model-value="setQuery(facet.key, $event)"
                    />
                    <FacetTree
                        v-if="isTree(facet.key)"
                        :facet="facet"
                        :values="valuesOf(facet)"
                        :selected="props.selected[facet.key] ?? []"
                        :count-hint="props.countHint"
                        :query="queryOf(facet.key)"
                        :busy="isLoading(facet.key)"
                        @change="(ids) => onTreeChange(facet, ids)"
                    />
                    <FacetValues
                        v-else
                        :facet="facet"
                        :values="visibleValues(facet)"
                        :selected="props.selected[facet.key] ?? []"
                        :count-hint="props.countHint"
                        :busy="isLoading(facet.key)"
                        :fixed-list="isFixedList(facet.key)"
                        @change="(id, checked) => onChange(facet, id, checked)"
                    />
                    <p
                        v-if="hasNoMatch(facet)"
                        class="no-match"
                    >
                        <span>{{ $gettext("No match") }}</span>
                    </p>
                    <button
                        v-if="showsMore(facet)"
                        type="button"
                        class="more"
                        :aria-expanded="
                            isExpanded(facet.key) ? 'true' : 'false'
                        "
                        @click="toggleExpanded(facet.key)"
                    >
                        <span>{{ moreLabel(facet) }}</span>
                    </button>
                    <ColourScopeOption
                        v-if="facet.key === 'colour'"
                        :scope="store.filters.colourScope"
                        @change="store.setFilter('colourScope', $event)"
                    />
                </fieldset>
            </div>
        </section>
    </div>
</template>

<style scoped>
.facet-rail {
    display: grid;
    grid-template-columns: minmax(0, 1fr);
    gap: 1rem;
}

.facet-rail .group {
    display: grid;
    grid-template-columns: minmax(0, 1fr);
    gap: 0.5rem;
}

.facet-rail .group + .group {
    padding-block-start: 0.75rem;
    border-block-start: 0.0625rem solid var(--border);
}

.facet-rail .group-body {
    display: grid;
    grid-template-columns: minmax(0, 1fr);
    gap: 1rem;
}

.facet-rail .group-title {
    position: sticky;
    inset-block-start: 0;
    z-index: 1;
    background: var(--surface);
}

.facet-rail .disclosure {
    display: inline-flex;
    align-items: center;
    gap: 0.375rem;
    min-block-size: 2rem;
    padding: 0;
    border: none;
    background: transparent;
    color: var(--ink);
    font: inherit;
    font-size: 0.75rem;
    font-weight: 600;
    font-variant: all-small-caps;
    letter-spacing: 0.08em;
    cursor: pointer;
}

.facet-rail .disclosure .chevron {
    color: var(--ink-muted);
}

.facet-rail .title-text {
    border-block-end: 0.0625rem dotted var(--ink-muted);
    cursor: help;
}

.facet-rail .visually-hidden {
    position: absolute;
    inline-size: 0.0625rem;
    block-size: 0.0625rem;
    overflow: hidden;
    clip-path: inset(50%);
    white-space: nowrap;
}

.facet-rail .facet {
    display: grid;
    grid-template-columns: minmax(0, 1fr);
    gap: 0.25rem;
    min-inline-size: 0;
    border: none;
}

.facet-rail .title {
    margin-block-end: 0.25rem;
    color: var(--ink-muted);
    font-family: var(--font-mono);
    font-size: 0.6875rem;
    letter-spacing: 0.12em;
    text-transform: uppercase;
}

.facet-rail .search {
    box-sizing: border-box;
    inline-size: 100%;
    min-inline-size: 0;
    font-size: 0.75rem;
}

.facet-rail .no-match {
    color: var(--ink-dim);
    font-size: 0.75rem;
}

.facet-rail .more {
    justify-self: start;
    min-block-size: var(--explorer-target, 2.75rem);
    padding: 0;
    border: none;
    background: transparent;
    color: var(--blue-text);
    font: inherit;
    font-size: 0.75rem;
    cursor: pointer;
}

.facet-rail .more:hover {
    text-decoration: underline;
}

.facet-rail input:focus-visible,
.facet-rail .more:focus-visible,
.facet-rail .disclosure:focus-visible,
.facet-rail .title-text:focus-visible {
    outline: 0.125rem solid var(--blue-text);
    outline-offset: 0.125rem;
}
</style>
