<script setup lang="ts">
import { computed, ref } from "vue";
import { useGettext } from "vue3-gettext";

import InputText from "primevue/inputtext";

import { useVocabulary } from "@/manuspectrum/pages/AnalysisExplorer/composables/useVocabulary.ts";
import { foldText } from "@/manuspectrum/pages/AnalysisExplorer/format.ts";
import { techniqueStyles } from "@/manuspectrum/pages/AnalysisExplorer/folio/techniques.ts";
import { colourSwatch } from "@/manuspectrum/pages/AnalysisExplorer/views/Corpus/components/facet-swatches.ts";

import type {
    Facet,
    FacetKey,
    FacetValue,
} from "@/manuspectrum/pages/AnalysisExplorer/api/types.ts";

const PREVIEW_SIZE = 6;
const SEARCH_THRESHOLD = 8;

/**
 * The facets of a Corpus screen. What is ticked comes from `selected` (the
 * filters in force), never from the payload's `selected`, which lags behind
 * while the next search loads. A facet longer than `SEARCH_THRESHOLD` has a
 * search box that narrows its values as one types (accents and case
 * ignored). `countHint`, a translated text with `%{n}`, says what a count
 * counts (« %{n} in this document »).
 */
const props = withDefaults(
    defineProps<{
        facets: Facet[];
        selected: Partial<Record<FacetKey, readonly string[]>>;
        /** `--tech-n` colour of each technique value (null: drawn in ink); by default their order in the facet. */
        techniqueColours?: ReadonlyMap<string, number | null> | null;
        countHint?: string;
    }>(),
    { techniqueColours: null, countHint: "" },
);
const emit = defineEmits<{ change: [key: FacetKey, ids: string[]] }>();

const { $gettext, interpolate } = useGettext();
const { facetTitle } = useVocabulary();

const expanded = ref<Set<FacetKey>>(new Set());
const queries = ref<Partial<Record<FacetKey, string>>>({});

/** The technique colours given, else one per technique value in the order of the facet. */
const colours = computed<ReadonlyMap<string, number | null>>(() => {
    if (props.techniqueColours) return props.techniqueColours;
    const values =
        props.facets.find((facet) => facet.key === "technique")?.values ?? [];
    const styles = techniqueStyles(
        values.map((value) => ({
            id: value.id,
            uri: value.id,
            label: value.label,
        })),
        { value: "", lang: "" },
    );
    return new Map(
        values.map((value) => [value.id, styles.get(value.id)?.colour ?? null]),
    );
});

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

function isSearchable(facet: Facet): boolean {
    return facet.values.length > SEARCH_THRESHOLD;
}

function queryOf(key: FacetKey): string {
    return foldText(queries.value[key] ?? "").trim();
}

function setQuery(key: FacetKey, text: string | undefined): void {
    queries.value = { ...queries.value, [key]: text ?? "" };
}

/** The values shown: those matching the search, else the first ones, a ticked one, or all once expanded. */
function visibleValues(facet: Facet): FacetValue[] {
    const query = queryOf(facet.key);
    if (query) {
        return facet.values.filter(
            (value) =>
                foldText(value.label.value).includes(query) ||
                isSelected(facet.key, value.id),
        );
    }
    if (isExpanded(facet.key)) {
        return facet.values;
    }
    return facet.values.filter(
        (value, index) =>
            index < PREVIEW_SIZE || isSelected(facet.key, value.id),
    );
}

function hasNoMatch(facet: Facet): boolean {
    return queryOf(facet.key) !== "" && visibleValues(facet).length === 0;
}

function showsMore(facet: Facet): boolean {
    return facet.values.length > PREVIEW_SIZE && queryOf(facet.key) === "";
}

function moreLabel(facet: Facet): string {
    return isExpanded(facet.key)
        ? $gettext("Show fewer")
        : interpolate(
              $gettext("Show all (%{count})"),
              {
                  count: facet.values.length,
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

function dotClass(id: string): string {
    const colour = colours.value.get(id);
    return colour ? `dot--tech-${colour}` : "dot--ink";
}

function swatchOf(key: FacetKey, value: FacetValue): string | null {
    return key === "colour" ? colourSwatch(value.label.value) : null;
}

function countTitle(value: FacetValue): string | undefined {
    return props.countHint
        ? interpolate(props.countHint, { n: value.count }, true)
        : undefined;
}

function onChange(facet: Facet, id: string, event: Event): void {
    const checked = (event.target as HTMLInputElement).checked;
    const current = (props.selected[facet.key] ?? []).filter(
        (entry) => entry !== id,
    );
    emit("change", facet.key, checked ? [...current, id] : current);
}
</script>

<template>
    <div class="facet-rail">
        <fieldset
            v-for="facet in props.facets"
            :key="facet.key"
            class="facet"
        >
            <legend class="title">
                <span>{{ facetTitle(facet.key) }}</span>
            </legend>
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
            <ul class="values">
                <li
                    v-for="value in visibleValues(facet)"
                    :key="value.id"
                >
                    <label class="value">
                        <input
                            type="checkbox"
                            :value="value.id"
                            :checked="isSelected(facet.key, value.id)"
                            :disabled="
                                value.count === 0 &&
                                !isSelected(facet.key, value.id)
                            "
                            @change="onChange(facet, value.id, $event)"
                        />
                        <span
                            v-if="facet.key === 'technique'"
                            class="dot"
                            :class="dotClass(value.id)"
                            aria-hidden="true"
                        ></span>
                        <span
                            v-else-if="swatchOf(facet.key, value)"
                            class="swatch"
                            aria-hidden="true"
                            :style="{
                                '--swatch':
                                    swatchOf(facet.key, value) ?? undefined,
                            }"
                        ></span>
                        <span
                            class="label"
                            :lang="value.label.lang"
                            :title="value.label.value"
                            >{{ value.label.value }}</span
                        >
                        <span
                            class="count"
                            :title="countTitle(value)"
                            >{{ value.count }}</span
                        >
                    </label>
                </li>
            </ul>
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
                :aria-expanded="isExpanded(facet.key) ? 'true' : 'false'"
                @click="toggleExpanded(facet.key)"
            >
                <span>{{ moreLabel(facet) }}</span>
            </button>
        </fieldset>
    </div>
</template>

<style scoped>
.facet-rail {
    display: grid;
    grid-template-columns: minmax(0, 1fr);
    gap: 1rem;
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

.facet-rail .values {
    display: grid;
    grid-template-columns: minmax(0, 1fr);
    list-style: none;
}

.facet-rail .values li {
    min-inline-size: 0;
}

.facet-rail .value {
    display: flex;
    align-items: center;
    gap: 0.5rem;
    min-block-size: var(--explorer-target, 2.75rem);
    min-inline-size: 0;
    font-size: 0.8125rem;
    cursor: pointer;
}

.facet-rail .value:has(input:disabled) {
    color: var(--ink-dim);
    cursor: default;
}

.facet-rail .value input {
    flex: none;
}

.facet-rail .label {
    flex: 1 1 auto;
    min-inline-size: 0;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
}

.facet-rail .dot,
.facet-rail .swatch {
    flex: none;
    inline-size: 0.625rem;
    block-size: 0.625rem;
    border-radius: 50%;
}

.facet-rail .dot--tech-1 {
    background: var(--tech-1);
}

.facet-rail .dot--tech-2 {
    background: var(--tech-2);
}

.facet-rail .dot--tech-3 {
    background: var(--tech-3);
}

.facet-rail .dot--tech-4 {
    background: var(--tech-4);
}

.facet-rail .dot--tech-5 {
    background: var(--tech-5);
}

.facet-rail .dot--tech-6 {
    background: var(--tech-6);
}

.facet-rail .dot--ink {
    border: 0.125rem solid var(--ink);
}

.facet-rail .swatch {
    border: 0.0625rem solid var(--border-hover);
    background: var(--swatch);
}

.facet-rail .count {
    flex: none;
    color: var(--ink-muted);
    font-family: var(--font-mono);
    font-size: 0.6875rem;
    text-align: end;
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
.facet-rail .more:focus-visible {
    outline: 0.125rem solid var(--blue-text);
    outline-offset: 0.125rem;
}
</style>
