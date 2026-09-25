<script setup lang="ts">
import { computed, ref, useId } from "vue";
import { useGettext } from "vue3-gettext";

import InputText from "primevue/inputtext";
import ToggleButton from "primevue/togglebutton";
import Tooltip from "primevue/tooltip";

import { useVocabulary } from "@/manuspectrum/pages/AnalysisExplorer/composables/useVocabulary.ts";
import { foldText } from "@/manuspectrum/pages/AnalysisExplorer/format.ts";
import { techniqueClass } from "@/manuspectrum/pages/AnalysisExplorer/folio/techniques.ts";
import { useExplorerStore } from "@/manuspectrum/pages/AnalysisExplorer/store/explorer.ts";

import type {
    Facet,
    FacetGroup,
    FacetKey,
    FacetValue,
} from "@/manuspectrum/pages/AnalysisExplorer/api/types.ts";
import type { ColourLevel } from "@/manuspectrum/pages/AnalysisExplorer/store/types.ts";

const PREVIEW_SIZE = 6;
const SEARCH_THRESHOLD = 8;
const GROUPS: readonly FacetGroup[] = ["part", "analysis", "characterization"];
const COLOUR_LEVELS: readonly ColourLevel[] = ["partColour", "colour"];
/** The facets of each group in rail order; `colour` stands for the Colour facet and its level toggle. */
const GROUP_KEYS: Readonly<Record<FacetGroup, readonly FacetKey[]>> = {
    part: ["partType", "part"],
    analysis: ["project", "technique", "operator", "year"],
    characterization: ["material", "colour", "layer", "element"],
};

/**
 * The facets of a Corpus screen, in three groups (studied part, analysis,
 * identified material), each folding to its heading (state in the store).
 * The two colour facets share one « Colour » facet in the identified
 * material group, with a toggle choosing the level its ticks apply to; an
 * option with ticks of its own while the other is shown says how many.
 * What is ticked comes from `selected` (the filters in force), never from the
 * payload's `selected`, which lags behind while the next search loads. A
 * facet longer than `SEARCH_THRESHOLD` has a search box that narrows its
 * values as one types (accents and case ignored). `countHint`, a translated
 * text with `%{n}`, says what a count counts (« %{n} in this document »).
 */
const props = withDefaults(
    defineProps<{
        facets: Facet[];
        selected: Partial<Record<FacetKey, readonly string[]>>;
        countHint?: string;
    }>(),
    { countHint: "" },
);
const emit = defineEmits<{ change: [key: FacetKey, ids: string[]] }>();

const vTooltip = Tooltip;
const store = useExplorerStore();
const { $gettext, interpolate } = useGettext();
const { facetTitle, groupTitle, levelLabel, levelHint } = useVocabulary();
const baseId = useId();

const expanded = ref<Set<FacetKey>>(new Set());
const queries = ref<Partial<Record<FacetKey, string>>>({});

const byKey = computed(
    () => new Map(props.facets.map((facet) => [facet.key, facet])),
);
/** The colour level shown: the one chosen, else the one that has a facet. */
const shownLevel = computed<ColourLevel>(() =>
    byKey.value.has(store.colourLevel)
        ? store.colourLevel
        : COLOUR_LEVELS.find((level) => byKey.value.has(level)) ??
          store.colourLevel,
);
const sections = computed(() =>
    GROUPS.map((group) => ({
        group,
        facets: GROUP_KEYS[group].flatMap((key) => {
            const facet = byKey.value.get(
                key === "colour" ? shownLevel.value : key,
            );
            return facet ? [facet] : [];
        }),
    })).filter((section) => section.facets.length > 0),
);

function isColour(key: FacetKey): boolean {
    return COLOUR_LEVELS.includes(key as ColourLevel);
}

function isCollapsed(group: FacetGroup): boolean {
    return store.collapsedGroups.includes(group);
}

function groupBodyId(group: FacetGroup): string {
    return `${baseId}-${group}`;
}

function levelHintId(level: ColourLevel): string {
    return `${baseId}-${level}-hint`;
}

function hasLevel(level: ColourLevel): boolean {
    return byKey.value.has(level);
}

/** Ticks held by a colour level that is not the one shown; 0 for the one shown. */
function hiddenTicks(level: ColourLevel): number {
    return level === shownLevel.value
        ? 0
        : (props.selected[level] ?? []).length;
}

function tickBadge(level: ColourLevel): string {
    return interpolate(
        $gettext("%{n} ticked"),
        { n: hiddenTicks(level) },
        true,
    );
}

function chooseLevel(level: ColourLevel): void {
    store.setColourLevel(level);
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

/** The labels of the ticked values of a facet, by the labels its values carry. */
function tickedLabels(key: FacetKey): string[] {
    const values = byKey.value.get(key)?.values ?? [];
    return (props.selected[key] ?? []).map(
        (id) => values.find((value) => value.id === id)?.label.value ?? id,
    );
}

/** « Selection: Blue, Red », naming the level of each colour facet with ticks; empty without ticks. */
function selectionSummary(facet: Facet): string {
    const keys: readonly FacetKey[] = isColour(facet.key)
        ? COLOUR_LEVELS
        : [facet.key];
    const parts = keys
        .filter((key) => tickedLabels(key).length > 0)
        .map((key) =>
            isColour(key)
                ? interpolate(
                      $gettext("%{values} (%{level})"),
                      {
                          values: tickedLabels(key).join(", "),
                          level: levelLabel(key as ColourLevel).toLowerCase(),
                      },
                      true,
                  )
                : tickedLabels(key).join(", "),
        );
    return parts.length > 0
        ? interpolate(
              $gettext("Selection: %{values}"),
              { values: parts.join(" · ") },
              true,
          )
        : "";
}

function summaryId(key: FacetKey): string {
    return `${baseId}-${key}-summary`;
}

function dotClass(value: FacetValue): string {
    return techniqueClass("dot", value.mark?.colour ?? null);
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
                    <div
                        v-if="isColour(facet.key)"
                        class="levels"
                        role="group"
                        :aria-label="$gettext('Colour level')"
                    >
                        <span
                            v-for="level in COLOUR_LEVELS"
                            :key="level"
                            v-tooltip.top="levelHint(level)"
                            class="level"
                        >
                            <ToggleButton
                                v-tooltip.focus.top="levelHint(level)"
                                class="level-button"
                                size="small"
                                :model-value="level === shownLevel"
                                :disabled="!hasLevel(level)"
                                :pt="{
                                    root: {
                                        'aria-describedby': levelHintId(level),
                                    },
                                }"
                                @update:model-value="chooseLevel(level)"
                            >
                                <span class="level-label">{{
                                    levelLabel(level)
                                }}</span>
                                <span
                                    v-if="hiddenTicks(level) > 0"
                                    class="ticks"
                                    :aria-label="tickBadge(level)"
                                    >{{ hiddenTicks(level) }}</span
                                >
                            </ToggleButton>
                            <span
                                :id="levelHintId(level)"
                                class="visually-hidden"
                                >{{ levelHint(level) }}</span
                            >
                        </span>
                    </div>
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
                                    :class="dotClass(value)"
                                    aria-hidden="true"
                                ></span>
                                <span
                                    v-else-if="value.swatch"
                                    class="swatch"
                                    aria-hidden="true"
                                    :style="{ '--swatch': value.swatch }"
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
                        :aria-expanded="
                            isExpanded(facet.key) ? 'true' : 'false'
                        "
                        @click="toggleExpanded(facet.key)"
                    >
                        <span>{{ moreLabel(facet) }}</span>
                    </button>
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

.facet-rail .levels {
    display: flex;
    flex-wrap: wrap;
    gap: 0.25rem;
}

.facet-rail .level {
    display: inline-flex;
}

.facet-rail .level-button {
    gap: 0.375rem;
    font-size: 0.6875rem;
}

.facet-rail .ticks {
    display: inline-grid;
    place-items: center;
    min-inline-size: 1rem;
    block-size: 1rem;
    padding-inline: 0.25rem;
    border-radius: 999rem;
    background: var(--blue-text);
    color: var(--surface);
    font-family: var(--font-mono);
    font-size: 0.625rem;
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

.facet-rail .dot--tech-7 {
    background: var(--tech-7);
}

.facet-rail .dot--tech-8 {
    background: var(--tech-8);
}

.facet-rail .dot--tech-9 {
    background: var(--tech-9);
}

.facet-rail .dot--tech-10 {
    background: var(--tech-10);
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
.facet-rail .more:focus-visible,
.facet-rail .disclosure:focus-visible,
.facet-rail .title-text:focus-visible {
    outline: 0.125rem solid var(--blue-text);
    outline-offset: 0.125rem;
}
</style>
