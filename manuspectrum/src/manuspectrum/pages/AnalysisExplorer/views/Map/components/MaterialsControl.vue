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
    countsName as wordCounts,
    countsText as shortCounts,
} from "@/manuspectrum/pages/AnalysisExplorer/views/Map/count-labels.ts";
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
 * (`colourTree`: each material under its most often observed colour, which a
 * hint under the column heads « Show » and « Follow » says). A row carries
 * its counts with their units, as the group head, then its other observed
 * colours, named in full on hover and for assistive technology. Two controls
 * per row: the checkbox filters the map and the Corpus
 * (`filters.material`), « Follow » gives the material a slot of the map
 * (`mapState.track`, four at most, exact uri), which its HelpTip explains.
 * The followed materials are chips above the groups, with « any / all »
 * from two on. A fifth Follow changes nothing, is announced, and leaves a
 * notice until the next Follow.
 * A colour group's head is a checkbox of the Corpus `colour` filter, the
 * colour's uri as the Corpus colour facet stores it; a ticked colour keeps
 * its head when no row falls under it. A ticked colour's group lists every
 * material observed in that colour, with the counts of that colour and
 * « observed <colour> » after them; a material whose main colour is another
 * keeps its usual row there too, and both rows are the same `material`
 * filter.
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
const gettext = useGettext();
const { $gettext, $ngettext, interpolate } = gettext;

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
    colourTree(
        props.events,
        props.materials,
        props.colours,
        only.value,
        store.filters.colour,
    ),
);
const noMatch = computed(
    () =>
        query.value.trim() !== "" &&
        !searching.value &&
        only.value !== undefined &&
        groups.value.every((group) => group.rows.length === 0),
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
    return shortCounts(gettext, documents, components);
}

function countsName(documents: number, components: number): string {
    return wordCounts(gettext, documents, components);
}

function groupLabel(group: ColourGroup): string {
    return group.label?.value ?? $gettext("No colour recorded");
}

/** « observed blue »: the colour's label in lower case. */
function observedName(colour: string): string {
    const found = props.colours[colour]?.label;
    return interpolate(
        $gettext("observed %{colour}"),
        {
            colour: (found?.value ?? colour).toLocaleLowerCase(
                found?.lang || undefined,
            ),
        },
        true,
    );
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

/** « Also observed in: … », every colour but the group's, by its label. */
function othersName(colours: readonly string[]): string {
    const names = colours
        .slice(1)
        .map((uri) => props.colours[uri]?.label.value)
        .filter((name): name is string => Boolean(name));
    return interpolate(
        $gettext("Also observed in: %{colours}"),
        {
            colours: new Intl.ListFormat(gettext.current, {
                type: "conjunction",
            }).format(names),
        },
        true,
    );
}

function moreColoursName(colours: readonly string[]): string {
    const n = moreColours(colours);
    return interpolate(
        $ngettext("and %{n} more colour", "and %{n} more colours", n),
        { n },
        true,
    );
}

function isTicked(uri: string): boolean {
    return store.filters.material.includes(uri);
}

function isColourTicked(group: ColourGroup): boolean {
    return group.colour !== null && store.filters.colour.includes(group.colour);
}

function colourFilterName(group: ColourGroup): string {
    return interpolate(
        $gettext("Filter: colour %{colour}"),
        { colour: groupLabel(group) },
        true,
    );
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

function onColourTick(colour: string, event: Event): void {
    const checked = (event.target as HTMLInputElement).checked;
    const others = store.filters.colour.filter((entry) => entry !== colour);
    store.setFacet("colour", checked ? [...others, colour] : others);
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
            :role="announce ? undefined : 'status'"
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
        <p
            v-if="groups.length > 0"
            class="grouping-hint"
        >
            <span>{{
                $gettext(
                    "Grouped by the colour most often observed on each material; tick a colour to filter by it.",
                )
            }}</span>
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
                    <component
                        :is="group.colour === null ? 'span' : 'label'"
                        class="head"
                        :class="{ ticked: isColourTicked(group) }"
                    >
                        <input
                            v-if="group.colour !== null"
                            type="checkbox"
                            :checked="isColourTicked(group)"
                            :aria-label="colourFilterName(group)"
                            @change="onColourTick(group.colour, $event)"
                        />
                        <span
                            class="swatch"
                            :class="{ unknown: !group.swatch }"
                            aria-hidden="true"
                            :style="swatchStyle(group.swatch)"
                        ></span>
                        <span class="head-text">
                            <span
                                class="name"
                                :lang="group.label?.lang || undefined"
                                >{{ groupLabel(group) }}</span
                            >
                            <span
                                v-if="group.rows.length > 0"
                                class="counts"
                                :title="
                                    countsName(
                                        group.documents,
                                        group.components,
                                    )
                                "
                                >{{
                                    countsText(
                                        group.documents,
                                        group.components,
                                    )
                                }}</span
                            >
                        </span>
                    </component>
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
                                    class="row-counts"
                                    :title="
                                        countsName(
                                            row.documents,
                                            row.components,
                                        )
                                    "
                                    >{{
                                        countsText(
                                            row.documents,
                                            row.components,
                                        )
                                    }}</span
                                >
                                <span
                                    v-if="row.observedIn !== null"
                                    class="observed"
                                    >{{ observedName(row.observedIn) }}</span
                                >
                                <span
                                    v-else-if="row.colours.length > 1"
                                    class="others"
                                    role="img"
                                    :aria-label="othersName(row.colours)"
                                    :title="othersName(row.colours)"
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
                                        :title="moreColoursName(row.colours)"
                                        >{{
                                            `+${moreColours(row.colours)}`
                                        }}</span
                                    >
                                </span>
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
    margin: 0;
    font-weight: 400;
}

/* tick | swatch | name, counts; the uncoloured group has no tick. */
.materials-control .colour-group .head {
    display: grid;
    grid-template-columns: auto minmax(0, 1fr);
    column-gap: 0.375rem;
    align-items: baseline;
    min-inline-size: 0;
}

.materials-control .colour-group label.head {
    grid-template-columns: auto auto minmax(0, 1fr);
    cursor: pointer;
}

.materials-control .colour-group .head input {
    align-self: center;
    margin: 0;
    accent-color: var(--blue-text);
}

.materials-control .colour-group .head .swatch {
    align-self: center;
}

/* The colour name is never cut; the counts follow it or wrap under it. */
.materials-control .colour-group .head-text {
    display: flex;
    flex-wrap: wrap;
    justify-content: space-between;
    gap: 0 0.5rem;
    min-inline-size: 0;
}

.materials-control .colour-group .name {
    min-inline-size: 0;
    color: var(--ink-muted);
    font-family: var(--font-mono);
    font-size: 0.6875rem;
    letter-spacing: 0.12em;
    overflow-wrap: anywhere;
    text-transform: uppercase;
}

.materials-control .colour-group .head.ticked .name {
    color: var(--ink);
    font-weight: 600;
}

.materials-control .counts,
.materials-control .row-counts {
    flex: none;
    color: var(--ink-muted);
    font-family: var(--font-mono);
    font-size: 0.6875rem;
    font-variant-numeric: tabular-nums;
    white-space: nowrap;
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

/*
 * tick | name | Follow
 *      | counts, other colours (under the name and Follow)
 * The label takes the row's tracks (subgrid) so the whole of it ticks.
 */
.materials-control .row {
    display: grid;
    grid-template-columns: auto minmax(0, 1fr) auto;
    grid-template-rows: auto auto;
    column-gap: 0.5rem;
    row-gap: 0.125rem;
    align-items: center;
    min-inline-size: 0;
    padding-block: 0.375rem;
}

.materials-control .value {
    display: grid;
    grid-template-rows: subgrid;
    grid-template-columns: subgrid;
    grid-row: 1 / -1;
    grid-column: 1 / -1;
    align-items: center;
    min-inline-size: 0;
    font-size: 0.8125rem;
    cursor: pointer;
}

.materials-control .value input {
    grid-row: 1;
    grid-column: 1;
    margin: 0;
    accent-color: var(--blue-text);
}

.materials-control .value .label {
    display: -webkit-box;
    grid-row: 1;
    grid-column: 2;
    min-inline-size: 0;
    overflow: hidden;
    line-height: 1.3;
    white-space: normal;
    -webkit-box-orient: vertical;
    -webkit-line-clamp: 2;
}

/* Counts first and unbroken; the other colours follow them or wrap below. */
.materials-control .value .meta {
    display: flex;
    flex-wrap: wrap;
    grid-row: 2;
    grid-column: 2 / -1;
    align-items: center;
    gap: 0.125rem 0.375rem;
    min-inline-size: 0;
}

/* The 2.75rem target overhangs the row by 0.5rem on each side. */
.materials-control .follow-tip {
    grid-row: 1;
    grid-column: 3;
    align-self: center;
    margin-block: -0.5rem;
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

.materials-control .observed {
    color: var(--ink-muted);
    font-size: 0.6875rem;
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

/* MapView .map-rail .hint */
.materials-control .grouping-hint {
    margin-block-start: -0.5rem;
    padding-inline: 0.125rem;
    color: var(--ink-dim);
    font-size: 0.75rem;
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
