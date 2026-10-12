<script setup lang="ts">
import { computed, inject, ref } from "vue";
import { useGettext } from "vue3-gettext";

import InputText from "primevue/inputtext";

import HelpTip from "@/manuspectrum/pages/AnalysisExplorer/components/HelpTip.vue";
import FocusSlotDot from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/components/FocusSlotDot.vue";

import { useFacetValues } from "@/manuspectrum/pages/AnalysisExplorer/composables/useFacetValues.ts";
import { filterQuery } from "@/manuspectrum/pages/AnalysisExplorer/composables/useSearch.ts";
import { ANNOUNCE_KEY } from "@/manuspectrum/pages/AnalysisExplorer/injection-keys.ts";
import { useExplorerStore } from "@/manuspectrum/pages/AnalysisExplorer/store/explorer.ts";
import {
    focusHue,
    nextFreeSlot,
} from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/linked/focus.ts";
import {
    colourTree,
    materialCounts,
} from "@/manuspectrum/pages/AnalysisExplorer/views/Map/colour-groups.ts";
import {
    slotOf,
    trackedOf,
} from "@/manuspectrum/pages/AnalysisExplorer/views/Map/tracking.ts";

import type {
    Label,
    MapColour,
    MapEvent,
    MapMaterial,
} from "@/manuspectrum/pages/AnalysisExplorer/api/types.ts";
import type { FocusMode } from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/linked/focus.ts";
import type { ColourGroup } from "@/manuspectrum/pages/AnalysisExplorer/views/Map/colour-groups.ts";

type Bloom = "odd" | "even";

const MODES: readonly FocusMode[] = ["any", "all"];
const MAX_OTHER_SWATCHES = 3;
const ROWS_SHOWN = 5;

/**
 * The identified materials of the kept events, grouped by observed colour
 * (`colourTree`), with two controls per row under the column heads « Show »
 * and « Follow »: the checkbox filters the map and the Corpus
 * (`filters.material`), « Follow » gives the material a slot of the map
 * (`mapState.track`, four at most, exact uri), which its HelpTip explains.
 * The followed materials are chips above the groups, with « any / all »
 * from two on. A fifth Follow changes nothing, is announced, and leaves a
 * notice until the next Follow.
 * The search asks the material facet (synonyms included) and keeps the rows
 * it answers. Each colour group shows its ticked and followed rows, then
 * others up to five, and « Show more » for the rest; a search shows every
 * match. State lives in the store; hovering or focusing a followed chip
 * emits `isolate` with its slot, and null on leave.
 */
const props = defineProps<{
    events: MapEvent[];
    materials: Record<string, MapMaterial>;
    colours: Record<string, MapColour>;
}>();
const emit = defineEmits<{ isolate: [slot: number | null] }>();

const announce = inject(ANNOUNCE_KEY, null);

const store = useExplorerStore();
const { $gettext, interpolate } = useGettext();

const followHelp = computed(() =>
    $gettext(
        "Follow gives the material its own colour on the map, its territory and its line in the timeline (four at most). Show only shows or hides its events.",
    ),
);
const refusedText = computed(() =>
    $gettext("Four materials are followed already: stop following one first."),
);

const query = ref("");
const refused = ref(false);
const blooms = ref<Record<string, Bloom>>({});
/** Colour groups unfolded past their first rows, by group key. */
const unfolded = ref(new Set<string>());

const search = useFacetValues("material", () =>
    query.value.trim()
        ? {
              filters: filterQuery(store.filters).toString(),
              find: query.value,
          }
        : null,
);

const only = computed<Set<string> | undefined>(() => {
    if (!query.value.trim() || !search.data.value) return undefined;
    return new Set(search.data.value.values.map((value) => value.id));
});
const searching = computed(
    () => query.value.trim() !== "" && search.status.value === "loading",
);
const groups = computed<ColourGroup[]>(() =>
    colourTree(props.events, props.materials, props.colours, only.value),
);
const noMatch = computed(
    () =>
        query.value.trim() !== "" &&
        !searching.value &&
        only.value !== undefined &&
        groups.value.length === 0,
);
const counts = computed(() => materialCounts(props.events));
const tracked = computed(() => trackedOf(store.mapState.track));
const nextSlot = computed(() => nextFreeSlot(store.mapState.track));
const chips = computed(() =>
    tracked.value.map(({ uri, slot }) => {
        const found = counts.value.get(uri);
        return {
            uri,
            slot,
            label: labelOf(uri),
            absent: found === undefined,
            counts: found ? countsText(found.documents, found.components) : "",
        };
    }),
);

function groupKey(group: ColourGroup): string {
    return group.colour ?? "none";
}

/** The ticked and followed rows first, in group order, then the others. */
function orderedRows(group: ColourGroup): ColourGroup["rows"] {
    const pinned = (uri: string): boolean =>
        isTicked(uri) || slot(uri) !== null;
    return [
        ...group.rows.filter((row) => pinned(row.uri)),
        ...group.rows.filter((row) => !pinned(row.uri)),
    ];
}

function shownRows(group: ColourGroup): ColourGroup["rows"] {
    const rows = orderedRows(group);
    if (only.value !== undefined || unfolded.value.has(groupKey(group))) {
        return rows;
    }
    const pinned = rows.filter(
        (row) => isTicked(row.uri) || slot(row.uri) !== null,
    ).length;
    return rows.slice(0, Math.max(ROWS_SHOWN, pinned));
}

function hiddenRows(group: ColourGroup): number {
    return group.rows.length - shownRows(group).length;
}

function unfold(group: ColourGroup): void {
    unfolded.value = new Set([...unfolded.value, groupKey(group)]);
}

function moreRowsText(group: ColourGroup): string {
    return interpolate(
        $gettext("Show %{n} more"),
        { n: hiddenRows(group) },
        true,
    );
}

function labelOf(uri: string): Label {
    return (
        props.materials[uri]?.label ??
        counts.value.get(uri)?.label ?? { value: uri, lang: "" }
    );
}

function countsText(documents: number, components: number): string {
    return interpolate(
        $gettext("%{documents} doc · %{components} comp"),
        { documents, components },
        true,
    );
}

function countsName(documents: number, components: number): string {
    return interpolate(
        $gettext("%{documents} documents, %{components} Components"),
        { documents, components },
        true,
    );
}

function groupLabel(group: ColourGroup): string {
    return group.label?.value ?? $gettext("No colour recorded");
}

function swatchOf(uri: string): string | null {
    return props.colours[uri]?.swatch ?? null;
}

function swatchStyle(swatch: string | null): Record<string, string> {
    return swatch ? { "--swatch": swatch } : {};
}

function otherColours(colours: readonly string[]): string[] {
    return colours.slice(1, 1 + MAX_OTHER_SWATCHES);
}

function moreColours(colours: readonly string[]): number {
    return Math.max(0, colours.length - 1 - MAX_OTHER_SWATCHES);
}

function isTicked(uri: string): boolean {
    return store.filters.material.includes(uri);
}

function slot(uri: string): number | null {
    return slotOf(store.mapState.track, uri);
}

function filterName(material: Label): string {
    return interpolate(
        $gettext("Filter: %{material}"),
        { material: material.value },
        true,
    );
}

function followName(uri: string, material: Label): string {
    const taken = slot(uri);
    return taken === null
        ? interpolate(
              $gettext("Follow %{material}"),
              { material: material.value },
              true,
          )
        : stopName(material, taken);
}

function stopName(material: Label, taken: number): string {
    return interpolate(
        $gettext("Stop following %{material} (colour %{n})"),
        { material: material.value, n: taken },
        true,
    );
}

function unpinName(material: Label): string {
    return interpolate(
        $gettext("Stop following %{material}"),
        { material: material.value },
        true,
    );
}

function modeLabel(mode: FocusMode): string {
    return mode === "all" ? $gettext("all of them") : $gettext("any of them");
}

function followStyle(uri: string): Record<string, string> {
    const taken = slot(uri);
    if (taken !== null) return { "--r": "999rem", "--h1": focusHue(taken) };
    return nextSlot.value === null ? {} : { "--hn": focusHue(nextSlot.value) };
}

function onTick(uri: string, event: Event): void {
    const checked = (event.target as HTMLInputElement).checked;
    const others = store.filters.material.filter((entry) => entry !== uri);
    store.setFacet("material", checked ? [...others, uri] : others);
}

function onFollow(uri: string): void {
    const material = labelOf(uri);
    const result = store.toggleTrack(uri);
    refused.value = result === "refused";
    if (result === "refused") {
        announce?.(refusedText.value);
        return;
    }
    if (result === "pinned") {
        const taken = slot(uri) ?? 0;
        blooms.value = {
            ...blooms.value,
            [uri]: blooms.value[uri] === "odd" ? "even" : "odd",
        };
        announce?.(
            interpolate(
                $gettext("Following %{material} (colour %{n})."),
                { material: material.value, n: taken },
                true,
            ),
        );
        return;
    }
    announce?.(
        interpolate(
            $gettext("Stopped following %{material}."),
            { material: material.value },
            true,
        ),
    );
}

function onSearch(text: string | undefined): void {
    query.value = text ?? "";
}
</script>

<template>
    <div class="materials-control">
        <p class="explainer">
            <span>
                <strong>{{ $gettext("Show") }}</strong>
                <span>{{ " " }}</span>
                <span>{{
                    $gettext(
                        "keeps only the events of the ticked materials, on the map and in the Corpus.",
                    )
                }}</span>
            </span>
            <span>
                <strong>{{ $gettext("Follow") }}</strong>
                <span>{{ " " }}</span>
                <span>{{
                    $gettext("gives a colour on the map (four at most).")
                }}</span>
            </span>
        </p>

        <ul
            v-if="chips.length > 0"
            class="chips"
            :aria-label="$gettext('Followed materials')"
        >
            <li
                v-for="chip in chips"
                :key="chip.uri"
                class="chip-row"
                :class="{ absent: chip.absent }"
                :style="{ '--h': focusHue(chip.slot) }"
                @mouseenter="emit('isolate', chip.slot)"
                @mouseleave="emit('isolate', null)"
                @focusin="emit('isolate', chip.slot)"
                @focusout="emit('isolate', null)"
            >
                <span class="chip">
                    <FocusSlotDot
                        size="large"
                        :number="chip.slot"
                    />
                    <span class="chip-text">
                        <span
                            class="chip-label"
                            :lang="chip.label.lang || undefined"
                            :title="chip.label.value"
                            >{{ chip.label.value }}</span
                        >
                        <span
                            v-if="chip.absent"
                            class="absent-note"
                            >{{
                                $gettext("not attested in the kept events")
                            }}</span
                        >
                        <span
                            v-else
                            class="chip-counts"
                            >{{ chip.counts }}</span
                        >
                    </span>
                </span>
                <button
                    type="button"
                    class="unpin"
                    :aria-label="unpinName(chip.label)"
                    @click="onFollow(chip.uri)"
                >
                    <span aria-hidden="true">×</span>
                </button>
            </li>
        </ul>

        <div
            v-if="chips.length > 1"
            class="track-mode"
        >
            <span>{{ $gettext("Light what relates to") }}</span>
            <span
                class="segments"
                role="group"
                :aria-label="$gettext('Light what relates to')"
            >
                <button
                    v-for="mode in MODES"
                    :key="mode"
                    type="button"
                    :data-mode="mode"
                    :aria-pressed="store.trackMode === mode ? 'true' : 'false'"
                    @click="store.setTrackMode(mode)"
                >
                    <span>{{ modeLabel(mode) }}</span>
                </button>
            </span>
        </div>

        <p
            v-if="refused"
            class="refused"
            role="status"
        >
            <span>{{ refusedText }}</span>
        </p>

        <InputText
            class="search"
            type="search"
            size="small"
            autocomplete="off"
            :model-value="query"
            :placeholder="$gettext('Search a material (synonyms included)')"
            :aria-label="$gettext('Search a material (synonyms included)')"
            @update:model-value="onSearch"
        />

        <p
            v-if="groups.length > 0"
            class="columns"
            aria-hidden="true"
        >
            <span>{{ $gettext("Show") }}</span>
            <span>{{ $gettext("Follow") }}</span>
        </p>

        <div
            class="groups"
            :class="{ busy: searching }"
            :aria-busy="searching ? 'true' : 'false'"
        >
            <section
                v-for="group in groups"
                :key="groupKey(group)"
                class="colour-group"
            >
                <h4>
                    <span
                        class="swatch"
                        :class="{ unknown: !group.swatch }"
                        aria-hidden="true"
                        :style="swatchStyle(group.swatch)"
                    ></span>
                    <span
                        class="name"
                        :lang="group.label?.lang || undefined"
                        >{{ groupLabel(group) }}</span
                    >
                    <span
                        class="counts"
                        :title="countsName(group.documents, group.components)"
                        >{{
                            countsText(group.documents, group.components)
                        }}</span
                    >
                </h4>
                <ul class="rows">
                    <li
                        v-for="row in shownRows(group)"
                        :key="row.uri"
                        class="row"
                    >
                        <label class="value">
                            <input
                                type="checkbox"
                                :checked="isTicked(row.uri)"
                                :aria-label="filterName(row.label)"
                                @change="onTick(row.uri, $event)"
                            />
                            <span
                                class="label"
                                :lang="row.label.lang || undefined"
                                :title="row.label.value"
                                >{{ row.label.value }}</span
                            >
                            <span class="meta">
                                <span
                                    v-if="row.colours.length > 1"
                                    class="others"
                                    aria-hidden="true"
                                    :title="
                                        $gettext(
                                            'observed colour, not an identity',
                                        )
                                    "
                                >
                                    <span
                                        v-for="colour in otherColours(
                                            row.colours,
                                        )"
                                        :key="colour"
                                        class="swatch tiny"
                                        :class="{ unknown: !swatchOf(colour) }"
                                        :style="swatchStyle(swatchOf(colour))"
                                    ></span>
                                    <span
                                        v-if="moreColours(row.colours) > 0"
                                        class="more-colours"
                                        >{{
                                            `+${moreColours(row.colours)}`
                                        }}</span
                                    >
                                </span>
                                <span
                                    class="row-counts"
                                    :title="
                                        countsName(
                                            row.documents,
                                            row.components,
                                        )
                                    "
                                    >{{
                                        `${row.documents} · ${row.components}`
                                    }}</span
                                >
                            </span>
                        </label>
                        <HelpTip
                            class="follow-tip"
                            align="end"
                            :text="followHelp"
                        >
                            <template #default="{ describedby }">
                                <button
                                    type="button"
                                    class="follow ms-focus"
                                    :class="{
                                        followed: slot(row.uri) !== null,
                                        full: nextSlot === null,
                                    }"
                                    :style="followStyle(row.uri)"
                                    :data-bloom="blooms[row.uri]"
                                    :aria-pressed="
                                        slot(row.uri) !== null
                                            ? 'true'
                                            : 'false'
                                    "
                                    :aria-label="followName(row.uri, row.label)"
                                    :aria-describedby="describedby"
                                    @click="onFollow(row.uri)"
                                >
                                    <span
                                        v-if="slot(row.uri) !== null"
                                        class="disc"
                                        aria-hidden="true"
                                        >{{ slot(row.uri) }}</span
                                    >
                                    <span v-else>{{ $gettext("Follow") }}</span>
                                </button>
                            </template>
                        </HelpTip>
                    </li>
                </ul>
                <button
                    v-if="hiddenRows(group) > 0"
                    type="button"
                    class="more"
                    @click="unfold(group)"
                >
                    <span>{{ moreRowsText(group) }}</span>
                </button>
                <p
                    class="legend"
                    aria-hidden="true"
                >
                    <span>{{
                        $gettext("counts: documents · Components")
                    }}</span>
                </p>
            </section>
            <p
                v-if="noMatch"
                class="no-match"
            >
                <span>{{ $gettext("No match") }}</span>
            </p>
        </div>
    </div>
</template>

<style scoped>
.materials-control {
    display: grid;
    grid-template-columns: minmax(0, 1fr);
    gap: 0.75rem;
}

.materials-control .explainer {
    display: grid;
    gap: 0.125rem;
    padding: 0.5rem 0.625rem;
    border-radius: 0.5rem;
    background: var(--bg-warm);
    color: var(--ink-muted);
    font-size: 0.75rem;
}

.materials-control .explainer strong {
    color: var(--ink);
    font-weight: 600;
}

/* SelectionIndicator .chips, one per row in the rail */
.materials-control .chips {
    display: grid;
    gap: 0.375rem;
    margin: 0;
    padding: 0;
    list-style: none;
}

.materials-control .chip-row {
    display: flex;
    align-items: center;
    gap: 0.25rem;
    min-inline-size: 0;
}

.materials-control .chip {
    display: inline-flex;
    flex: 1 1 auto;
    align-items: center;
    gap: 0.375rem;
    min-inline-size: 0;
    min-block-size: 2rem;
    padding-block: 0.125rem;
    padding-inline: 0.25rem 0.625rem;
    border: 0.09375rem solid var(--h);
    border-radius: 999rem;
    background: color-mix(in srgb, var(--h) 8%, var(--surface));
}

.materials-control .chip-row.absent .chip {
    border-style: dashed;
}

.materials-control .chip-text {
    display: grid;
    min-inline-size: 0;
    line-height: 1.25;
}

.materials-control .chip-label {
    overflow: hidden;
    font-weight: 600;
    text-overflow: ellipsis;
    white-space: nowrap;
}

.materials-control .chip-counts,
.materials-control .absent-note {
    overflow: hidden;
    color: var(--ink-muted);
    font-size: 0.6875rem;
    font-variant-numeric: tabular-nums;
    text-overflow: ellipsis;
    white-space: nowrap;
}

.materials-control .unpin {
    display: grid;
    flex: none;
    place-items: center;
    inline-size: 1.75rem;
    block-size: 1.75rem;
    border: 0;
    border-radius: 50%;
    background: transparent;
    color: var(--ink-muted);
    font: inherit;
    cursor: pointer;
}

.materials-control .unpin:hover {
    background: var(--bg-alt);
    color: var(--ink);
}

/* SelectionIndicator .mode / .segments (ink segments) */
.materials-control .track-mode {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    justify-content: space-between;
    gap: 0.5rem;
    color: var(--ink-muted);
    font-size: 0.75rem;
}

.materials-control .segments {
    display: inline-flex;
    padding: 0.125rem;
    border: 0.0625rem solid var(--border-hover);
    border-radius: 999rem;
    background: var(--surface);
}

.materials-control .segments button {
    min-block-size: 1.75rem;
    padding-inline: 0.625rem;
    border: 0;
    border-radius: 999rem;
    background: none;
    color: var(--ink-muted);
    font: inherit;
    font-size: 0.75rem;
    white-space: nowrap;
    cursor: pointer;
}

.materials-control .segments button[aria-pressed="true"] {
    background: var(--ink);
    color: var(--surface);
    font-weight: 600;
}

/* SelectionCapacityNotice look */
.materials-control .refused {
    padding: 0.5rem 0.75rem;
    border-inline-start: 0.1875rem solid var(--accent);
    border-radius: 0.5rem;
    background: color-mix(in srgb, var(--accent) 9%, var(--surface));
    color: var(--ink);
    font-size: 0.75rem;
}

.materials-control .search {
    box-sizing: border-box;
    inline-size: 100%;
    min-inline-size: 0;
    font-size: 0.75rem;
}

.materials-control .columns {
    display: flex;
    justify-content: space-between;
    padding-inline: 0.125rem;
    color: var(--ink-dim);
    font-family: var(--font-mono);
    font-size: 0.625rem;
    letter-spacing: 0.08em;
    text-transform: uppercase;
}

.materials-control .groups {
    display: grid;
    grid-template-columns: minmax(0, 1fr);
    gap: 0.75rem;
}

.materials-control .groups.busy {
    opacity: 0.6;
}

.materials-control .colour-group {
    display: grid;
    grid-template-columns: minmax(0, 1fr);
    gap: 0.125rem;
}

.materials-control .colour-group h4 {
    display: flex;
    align-items: center;
    gap: 0.375rem;
    min-inline-size: 0;
    margin: 0;
    font-weight: 400;
}

.materials-control .colour-group .name {
    flex: 1 1 auto;
    min-inline-size: 0;
    overflow: hidden;
    color: var(--ink-muted);
    font-family: var(--font-mono);
    font-size: 0.6875rem;
    letter-spacing: 0.12em;
    text-overflow: ellipsis;
    text-transform: uppercase;
    white-space: nowrap;
}

.materials-control .counts,
.materials-control .row-counts {
    flex: none;
    color: var(--ink-muted);
    font-family: var(--font-mono);
    font-size: 0.6875rem;
    font-variant-numeric: tabular-nums;
}

/* MaterialsTable .swatch */
.materials-control .swatch {
    flex: none;
    inline-size: 0.875rem;
    block-size: 0.875rem;
    border-radius: 0.25rem;
    background: var(--swatch);
    box-shadow:
        inset 0 0 0 0.0625rem rgb(26 26 46 / 0.18),
        inset 0 0.0625rem 0 rgb(255 255 255 / 0.25);
}

.materials-control .swatch.unknown {
    background: repeating-linear-gradient(
        135deg,
        transparent 0 0.125rem,
        rgb(26 26 46 / 0.22) 0.125rem 0.1875rem
    );
}

.materials-control .swatch.tiny {
    inline-size: 0.5rem;
    block-size: 0.5rem;
    border-radius: 0.125rem;
}

/* FacetValues row anatomy */
.materials-control .rows {
    display: grid;
    grid-template-columns: minmax(0, 1fr);
    margin: 0;
    padding: 0;
    list-style: none;
}

.materials-control .row {
    display: flex;
    align-items: center;
    gap: 0.25rem;
    min-inline-size: 0;
}

.materials-control .value {
    display: grid;
    flex: 1 1 auto;
    grid-template-columns: auto minmax(0, 1fr);
    column-gap: 0.5rem;
    align-items: center;
    min-inline-size: 0;
    min-block-size: var(--explorer-target, 2.75rem);
    padding-block: 0.25rem;
    font-size: 0.8125rem;
    cursor: pointer;
}

.materials-control .value input {
    grid-column: 1;
    margin: 0;
    accent-color: var(--blue-text);
}

.materials-control .value .label {
    display: -webkit-box;
    grid-column: 2;
    min-inline-size: 0;
    overflow: hidden;
    line-height: 1.3;
    white-space: normal;
    -webkit-box-orient: vertical;
    -webkit-line-clamp: 2;
}

.materials-control .value .meta {
    display: flex;
    grid-column: 2;
    align-items: center;
    gap: 0.375rem;
    min-inline-size: 0;
}

.materials-control .follow-tip,
.materials-control .follow {
    align-self: center;
}

/* FacetRail .more */
.materials-control .more {
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

.materials-control .more:hover {
    text-decoration: underline;
}

.materials-control .others {
    display: inline-flex;
    flex: none;
    align-items: center;
    gap: 0.125rem;
}

.materials-control .more-colours {
    color: var(--ink-muted);
    font-family: var(--font-mono);
    font-size: 0.5625rem;
}

.materials-control .follow {
    display: inline-grid;
    flex: none;
    place-items: center;
    min-inline-size: var(--explorer-target, 2.75rem);
    min-block-size: var(--explorer-target, 2.75rem);
    padding: 0;
    border: 0;
    border-radius: 999rem;
    background: transparent;
    color: var(--ink-muted);
    font: inherit;
    font-size: 0.6875rem;
    cursor: pointer;
}

.materials-control .follow > span:not(.disc) {
    display: inline-grid;
    place-items: center;
    block-size: 1.75rem;
    padding-inline: 0.5rem;
    border: 0.0625rem solid var(--border-hover);
    border-radius: 999rem;
    background: var(--surface);
    transition:
        border-color var(--dur-fast),
        color var(--dur-fast);
}

.materials-control .follow:not(.full):hover > span:not(.disc) {
    border-color: var(--hn);
    color: var(--hn);
}

/* FocusSlotDot recipe at 1.5rem */
.materials-control .follow .disc {
    display: inline-grid;
    place-items: center;
    inline-size: 1.5rem;
    block-size: 1.5rem;
    border-radius: 50%;
    background: var(--h1);
    color: var(--focus-on, var(--surface));
    font: 700 0.6875rem/1 var(--font-mono);
    font-variant-numeric: tabular-nums;
}

.materials-control .legend {
    color: var(--ink-dim);
    font-family: var(--font-mono);
    font-size: 0.625rem;
    text-align: end;
}

.materials-control .no-match {
    color: var(--ink-dim);
    font-size: 0.75rem;
}

.materials-control input:focus-visible,
.materials-control button:focus-visible {
    outline: 0.125rem solid var(--blue-text);
    outline-offset: 0.125rem;
}

@media (prefers-reduced-motion: reduce) {
    .materials-control .follow > span:not(.disc) {
        transition: none;
    }
}

@media (forced-colors: active) {
    .materials-control .swatch,
    .materials-control .follow .disc {
        forced-color-adjust: none;
    }

    .materials-control .segments button[aria-pressed="true"],
    .materials-control .follow[aria-pressed="true"] {
        outline: 0.125rem solid Highlight;
    }
}
</style>
