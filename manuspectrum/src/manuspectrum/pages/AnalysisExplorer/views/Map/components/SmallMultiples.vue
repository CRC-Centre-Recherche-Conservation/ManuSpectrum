<script setup lang="ts">
import { computed, ref } from "vue";
import { useGettext } from "vue3-gettext";

import IconButton from "@/manuspectrum/pages/AnalysisExplorer/components/IconButton.vue";
import FocusSlotDot from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/components/FocusSlotDot.vue";
import SeriesMap from "@/manuspectrum/pages/AnalysisExplorer/views/Map/components/SeriesMap.vue";
import SeriesMapDialog from "@/manuspectrum/pages/AnalysisExplorer/views/Map/components/SeriesMapDialog.vue";

import {
    ICONS,
    ICON_VIEW_BOX,
} from "@/manuspectrum/pages/AnalysisExplorer/components/icons.ts";
import { ordinal } from "@/manuspectrum/pages/AnalysisExplorer/format.ts";
import {
    MINI_HEIGHT,
    MINI_WIDTH,
    pageOf,
} from "@/manuspectrum/pages/AnalysisExplorer/views/Map/multiples.ts";

import type { Bounds } from "@/manuspectrum/pages/AnalysisExplorer/views/Map/geo.ts";
import type { MultiplesAxis } from "@/manuspectrum/pages/AnalysisExplorer/views/Map/map-state.ts";
import type {
    MapSnapshot,
    MiniMap,
    SnapshotSize,
} from "@/manuspectrum/pages/AnalysisExplorer/views/Map/multiples.ts";
import type { TrackedMaterial } from "@/manuspectrum/pages/AnalysisExplorer/views/Map/tracking.ts";

/**
 * The map series: one mini map per identified material (every analysed
 * place drawn, hollow where the material is not attested) or per century
 * (a pip per followed slot attested there), drawn by `SeriesMap` on the
 * stage's snapshot `background`. Each mini map is one button that emits
 * `open`; its « Enlarge » shows it in `SeriesMapDialog`, which asks
 * (`enlarge-snapshot`) for a snapshot at its own size, drawn from
 * `largeBackground` (the mini maps' one meanwhile); the focus goes back to
 * that « Enlarge » on close, and the dialog's « Show on the map » emits
 * `show`. `maps` may be the whole list or the page already cut: the page
 * `page` (0-based) of twelve is drawn either way, and the dialog steps
 * through `maps`. `tracked` gives a material map its slot.
 */
const props = withDefaults(
    defineProps<{
        maps: MiniMap[];
        bounds: Bounds;
        background: MapSnapshot | null;
        page: number;
        pages: number;
        axis: MultiplesAxis;
        tracked?: TrackedMaterial[];
        largeBackground?: MapSnapshot | null;
    }>(),
    { tracked: () => [], largeBackground: null },
);
const emit = defineEmits<{
    open: [map: MiniMap];
    page: [n: number];
    "enlarge-snapshot": [size: SnapshotSize];
    show: [map: MiniMap];
}>();

const gettext = useGettext();
const { $gettext, $ngettext, interpolate } = gettext;

/** The place in `maps` of the map shown enlarged, if any. */
const enlarged = ref<number | null>(null);
let opener: HTMLElement | null = null;

const shown = computed(() => pageOf(props.maps, props.page));
const enlargedMap = computed(() =>
    enlarged.value === null ? null : props.maps[enlarged.value] ?? null,
);
const axisNote = computed(() =>
    props.axis === "century"
        ? $gettext(
              "One map per century of the period: an event counts in every century it overlaps; a digit per followed material attested there.",
          )
        : $gettext(
              "One map per identified material: every analysed place is drawn, hollow where the material is not attested.",
          ),
);
const emptyText = computed(() =>
    props.axis === "century"
        ? $gettext("No dated event among the kept events.")
        : $gettext("No identified material in the kept events."),
);
const pageText = computed(() =>
    interpolate(
        $gettext("Page %{n} / %{total}"),
        { n: props.page + 1, total: props.pages },
        true,
    ),
);
const atFirst = computed(() => props.page <= 0);
const atLast = computed(() => props.page >= props.pages - 1);

function slotOf(map: MiniMap): number | null {
    if (map.uri === null) return null;
    return props.tracked.find((entry) => entry.uri === map.uri)?.slot ?? null;
}

function titleOf(map: MiniMap): string {
    if (map.title) return map.title.value;
    if (map.century !== null) {
        return interpolate(
            $gettext("%{century} century"),
            { century: ordinal(map.century + 1, gettext.current) },
            true,
        );
    }
    return "";
}

function placesText(map: MiniMap): string {
    return interpolate(
        $ngettext("%{n} place", "%{n} places", map.places),
        { n: map.places },
        true,
    );
}

function documentsText(map: MiniMap): string {
    return interpolate(
        $ngettext("%{n} document", "%{n} documents", map.documents),
        { n: map.documents },
        true,
    );
}

function countsText(map: MiniMap): string {
    return interpolate(
        $gettext("%{places} · %{documents}"),
        { places: placesText(map), documents: documentsText(map) },
        true,
    );
}

function openName(map: MiniMap): string {
    return interpolate(
        $gettext("Open %{title}: %{places}, %{documents}, %{components}"),
        {
            title: titleOf(map),
            places: placesText(map),
            documents: documentsText(map),
            components: interpolate(
                $ngettext("%{n} Component", "%{n} Components", map.components),
                { n: map.components },
                true,
            ),
        },
        true,
    );
}

function enlargeName(map: MiniMap): string {
    if (map.century !== null && !map.title) {
        return interpolate(
            $gettext("Enlarge the map of the %{century} century"),
            { century: ordinal(map.century + 1, gettext.current) },
            true,
        );
    }
    return interpolate(
        $gettext("Enlarge the map of %{title}"),
        { title: titleOf(map) },
        true,
    );
}

function enlarge(map: MiniMap, event: MouseEvent): void {
    opener =
        event.currentTarget instanceof HTMLElement ? event.currentTarget : null;
    const index = props.maps.findIndex((entry) => entry.key === map.key);
    enlarged.value = index < 0 ? null : index;
}

function onDialogClosed(): void {
    enlarged.value = null;
    const target = opener;
    opener = null;
    if (target?.isConnected) target.focus({ preventScroll: true });
}

function showOnMap(map: MiniMap): void {
    enlarged.value = null;
    emit("show", map);
}

function go(next: number): void {
    if (next < 0 || next > props.pages - 1) return;
    emit("page", next);
}
</script>

<template>
    <div class="small-multiples">
        <p class="axis-note">
            <span>{{ axisNote }}</span>
        </p>
        <p
            v-if="props.maps.length === 0"
            class="no-image"
        >
            <span>{{ emptyText }}</span>
        </p>
        <div
            v-else
            class="grid"
        >
            <figure
                v-for="map in shown"
                :key="map.key"
                class="mini"
            >
                <button
                    type="button"
                    class="open"
                    :aria-label="openName(map)"
                    @click="emit('open', map)"
                >
                    <SeriesMap
                        class="mini-map"
                        :map="map"
                        :bounds="props.bounds"
                        :background="props.background"
                        :width="MINI_WIDTH"
                        :height="MINI_HEIGHT"
                        :followed-slot="slotOf(map)"
                    />
                </button>
                <figcaption>
                    <span class="name">
                        <FocusSlotDot
                            v-if="slotOf(map) !== null"
                            class="haloed"
                            size="small"
                            :number="slotOf(map) ?? 0"
                        />
                        <span
                            class="title"
                            :lang="map.title?.lang || undefined"
                            >{{ titleOf(map) }}</span
                        >
                    </span>
                    <span class="counts">{{ countsText(map) }}</span>
                    <span class="enlarge">
                        <IconButton
                            icon="expand"
                            tip-placement="above"
                            data-action="enlarge"
                            :label="enlargeName(map)"
                            @click="enlarge(map, $event)"
                        />
                    </span>
                </figcaption>
            </figure>
        </div>
        <nav
            v-if="props.pages > 1"
            class="pager"
            :aria-label="$gettext('Pages of the map series')"
        >
            <button
                type="button"
                class="control"
                :aria-label="$gettext('Previous page')"
                :aria-disabled="atFirst ? 'true' : undefined"
                @click="go(props.page - 1)"
            >
                <svg
                    :viewBox="ICON_VIEW_BOX"
                    aria-hidden="true"
                    focusable="false"
                >
                    <path
                        v-for="shape in ICONS['chevron-left']"
                        :key="shape"
                        :d="shape"
                    />
                </svg>
            </button>
            <span class="page">{{ pageText }}</span>
            <button
                type="button"
                class="control"
                :aria-label="$gettext('Next page')"
                :aria-disabled="atLast ? 'true' : undefined"
                @click="go(props.page + 1)"
            >
                <svg
                    :viewBox="ICON_VIEW_BOX"
                    aria-hidden="true"
                    focusable="false"
                >
                    <path
                        v-for="shape in ICONS['chevron-right']"
                        :key="shape"
                        :d="shape"
                    />
                </svg>
            </button>
        </nav>
        <SeriesMapDialog
            :maps="props.maps"
            :index="enlarged"
            :bounds="props.bounds"
            :background="props.largeBackground ?? props.background"
            :title="enlargedMap ? titleOf(enlargedMap) : ''"
            :counts="enlargedMap ? countsText(enlargedMap) : ''"
            :followed-slot="enlargedMap ? slotOf(enlargedMap) : null"
            @close="onDialogClosed"
            @navigate="enlarged = $event"
            @measure="emit('enlarge-snapshot', $event)"
            @show="showOnMap"
        />
    </div>
</template>

<style scoped>
.small-multiples {
    display: grid;
    grid-template-columns: minmax(0, 1fr);
    align-content: start;
    gap: 0.625rem;
    min-block-size: 20rem;
    padding: 0.75rem;
    border-radius: var(--explorer-radius);
    background: var(--stage);
    color: var(--surface);
}

.small-multiples .axis-note {
    color: color-mix(in srgb, var(--surface) 80%, transparent);
    font-size: 0.75rem;
}

/* FolioMap .no-image */
.small-multiples .no-image {
    justify-self: center;
    max-inline-size: min(30rem, 100%);
    padding: 0.5rem 0.75rem;
    border-radius: 0.25rem;
    background: var(--surface);
    color: var(--ink);
}

.small-multiples .grid {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(13rem, 1fr));
    gap: 0.625rem;
}

.small-multiples .mini {
    display: grid;
    align-content: start;
    gap: 0.375rem;
    margin: 0;
    padding: 0.5rem;
    border-radius: 0.5rem;
    background: var(--stage-soft);
}

/* FolioMap .control hover rim */
.small-multiples .open {
    display: block;
    padding: 0;
    overflow: hidden;
    border: 0.0625rem solid color-mix(in srgb, var(--surface) 30%, transparent);
    border-radius: 0.375rem;
    background: none;
    cursor: pointer;
}

.small-multiples .open:hover {
    border-color: var(--surface);
}

.small-multiples .mini-map {
    aspect-ratio: 220 / 160;
}

.small-multiples figcaption {
    display: grid;
    grid-template-columns: minmax(0, 1fr) auto;
    align-items: center;
    gap: 0.125rem 0.25rem;
    min-inline-size: 0;
}

.small-multiples figcaption .enlarge {
    grid-row: 1 / span 2;
    grid-column: 2;
}

.small-multiples figcaption .enlarge :deep(.icon-button-control) {
    color: var(--surface);
}

.small-multiples figcaption .enlarge :deep(.icon-button-control:hover) {
    background: var(--stage);
}

.small-multiples figcaption .enlarge :deep(.icon-button-control:focus-visible) {
    outline-color: var(--surface);
}

.small-multiples .name {
    display: flex;
    align-items: center;
    gap: 0.375rem;
    min-inline-size: 0;
}

.small-multiples .haloed {
    box-shadow: 0 0 0 0.125rem var(--surface);
}

.small-multiples .title {
    min-inline-size: 0;
    overflow: hidden;
    color: var(--surface);
    font-size: 0.8125rem;
    font-weight: 600;
    text-overflow: ellipsis;
    white-space: nowrap;
}

.small-multiples .counts {
    color: color-mix(in srgb, var(--surface) 75%, transparent);
    font-family: var(--font-mono);
    font-size: 0.6875rem;
    font-variant-numeric: tabular-nums;
}

.small-multiples .pager {
    display: flex;
    align-items: center;
    justify-content: center;
    gap: 0.75rem;
}

.small-multiples .page {
    font-family: var(--font-mono);
    font-size: 0.75rem;
    font-variant-numeric: tabular-nums;
}

/* FolioMap .control */
.small-multiples .control {
    display: grid;
    place-items: center;
    inline-size: 2rem;
    block-size: 2rem;
    padding: 0;
    border: 0.0625rem solid color-mix(in srgb, var(--surface) 30%, transparent);
    border-radius: 0.375rem;
    background: color-mix(in srgb, var(--stage) 85%, transparent);
    color: var(--surface);
    cursor: pointer;
}

.small-multiples .control:hover {
    border-color: var(--surface);
    background: var(--stage);
}

.small-multiples .control[aria-disabled="true"] {
    opacity: 0.45;
    cursor: not-allowed;
}

.small-multiples .control svg {
    inline-size: 1rem;
    block-size: 1rem;
    fill: currentColor;
}

.small-multiples .open:focus-visible,
.small-multiples .control:focus-visible {
    outline: 0.125rem solid var(--surface);
    outline-offset: 0.125rem;
}

@media (max-width: 30rem) {
    .small-multiples .grid {
        grid-template-columns: minmax(0, 1fr);
    }
}

@media (forced-colors: active) {
    .small-multiples .control {
        border-color: ButtonText;
    }
}
</style>
