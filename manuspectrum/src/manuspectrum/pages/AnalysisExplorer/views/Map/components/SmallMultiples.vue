<script setup lang="ts">
import { computed } from "vue";
import { useGettext } from "vue3-gettext";

import FocusSlotDot from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/components/FocusSlotDot.vue";

import {
    ICONS,
    ICON_VIEW_BOX,
} from "@/manuspectrum/pages/AnalysisExplorer/components/icons.ts";
import { ordinal } from "@/manuspectrum/pages/AnalysisExplorer/format.ts";
import { focusHue } from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/linked/focus.ts";
import { project } from "@/manuspectrum/pages/AnalysisExplorer/views/Map/geo.ts";
import {
    MINI_HEIGHT,
    MINI_WIDTH,
    pageOf,
    snapshotFrame,
} from "@/manuspectrum/pages/AnalysisExplorer/views/Map/multiples.ts";

import type { Bounds } from "@/manuspectrum/pages/AnalysisExplorer/views/Map/geo.ts";
import type { MultiplesAxis } from "@/manuspectrum/pages/AnalysisExplorer/views/Map/map-state.ts";
import type {
    MapSnapshot,
    MiniDot,
    MiniMap,
} from "@/manuspectrum/pages/AnalysisExplorer/views/Map/multiples.ts";
import type { TrackedMaterial } from "@/manuspectrum/pages/AnalysisExplorer/views/Map/tracking.ts";

const WIDTH = MINI_WIDTH;
const HEIGHT = MINI_HEIGHT;
const DOT_BASE = 4;
const DOT_STEP = 3;
const PIP_RADIUS = 5;
const PIP_GAP = 11;

/**
 * Small multiples of the map: one mini map per identified material (every
 * analysed place drawn, hollow where the material is not attested) or per
 * century (a pip per followed slot attested there). Each mini map is one
 * button that emits `open`. A pale attestation is hollow in its hue, an
 * attributed place (area or parent) dashed. The background is the stage's
 * snapshot when there is one, laid where its bounds fall in `bounds` so
 * that the dots sit on their places, else the land.
 * `maps` may be the whole list or the page already cut: the page `page`
 * (0-based) of twelve is drawn either way. `tracked` gives a material map
 * its slot.
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
    }>(),
    { tracked: () => [] },
);
const emit = defineEmits<{
    open: [map: MiniMap];
    page: [n: number];
}>();

const gettext = useGettext();
const { $gettext, $ngettext, interpolate } = gettext;

const shown = computed(() => pageOf(props.maps, props.page));
const viewBox = `0 0 ${WIDTH} ${HEIGHT}`;
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
const backgroundFrame = computed(() =>
    props.background ? snapshotFrame(props.background, props.bounds) : null,
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

function at(entry: MiniDot): [number, number] {
    const [x, y] = project(entry.lngLat, props.bounds, WIDTH, HEIGHT);
    return [Math.round(x * 10) / 10, Math.round(y * 10) / 10];
}

function radiusOf(entry: MiniDot): number {
    return entry.attested ? DOT_BASE + entry.size * DOT_STEP : DOT_BASE;
}

function dotClass(entry: MiniDot): Record<string, boolean> {
    return {
        attested: entry.attested,
        absent: !entry.attested,
        pale: entry.attested && entry.pale,
        dashed: entry.dashed,
    };
}

function dotStyle(map: MiniMap): Record<string, string> {
    const slot = slotOf(map);
    return slot === null ? {} : { "--h": focusHue(slot) };
}

/** Pips by century: in a row centred on the place. */
function pipsOf(entry: MiniDot): { slot: number; x: number; y: number }[] {
    const [x, y] = at(entry);
    const first = x - ((entry.slots.length - 1) * PIP_GAP) / 2;
    return entry.slots.map((slot, index) => ({
        slot,
        x: first + index * PIP_GAP,
        y,
    }));
}

function byCenturyPips(map: MiniMap, entry: MiniDot): boolean {
    return map.century !== null && entry.slots.length > 0;
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
                    <svg
                        class="mini-map"
                        aria-hidden="true"
                        focusable="false"
                        :viewBox="viewBox"
                    >
                        <image
                            v-if="props.background && backgroundFrame"
                            class="snapshot"
                            preserveAspectRatio="none"
                            :href="props.background.url"
                            :x="backgroundFrame.x"
                            :y="backgroundFrame.y"
                            :width="backgroundFrame.width"
                            :height="backgroundFrame.height"
                        />
                        <g v-else>
                            <rect
                                class="land"
                                :width="WIDTH"
                                :height="HEIGHT"
                            />
                            <rect
                                class="sea-frame"
                                x="1"
                                y="1"
                                :width="WIDTH - 2"
                                :height="HEIGHT - 2"
                            />
                        </g>
                        <g
                            v-for="entry in map.dots"
                            :key="entry.id"
                        >
                            <g v-if="byCenturyPips(map, entry)">
                                <circle
                                    v-for="pip in pipsOf(entry)"
                                    :key="pip.slot"
                                    class="pip"
                                    :cx="pip.x"
                                    :cy="pip.y"
                                    :r="PIP_RADIUS"
                                    :style="{ '--h': focusHue(pip.slot) }"
                                />
                            </g>
                            <circle
                                v-else
                                class="dot"
                                :class="dotClass(entry)"
                                :cx="at(entry)[0]"
                                :cy="at(entry)[1]"
                                :r="radiusOf(entry)"
                                :style="dotStyle(map)"
                            />
                        </g>
                    </svg>
                </button>
                <figcaption>
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
                    <span class="counts">{{ countsText(map) }}</span>
                </figcaption>
            </figure>
        </div>
        <nav
            v-if="props.pages > 1"
            class="pager"
            :aria-label="$gettext('Pages of the small multiples')"
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
    display: block;
    overflow: hidden;
    inline-size: 100%;
    block-size: auto;
}

.small-multiples .snapshot {
    animation: small-multiples-fade var(--dur-med) var(--ease-out-expo);
}

.small-multiples .land {
    fill: var(--map-land);
}

.small-multiples .sea-frame {
    fill: none;
    stroke: var(--map-sea);
    stroke-width: 2;
}

.small-multiples .dot.attested {
    fill: var(--h, var(--ink));
    stroke: var(--bg);
    stroke-width: 1;
}

.small-multiples .dot.pale {
    fill: var(--surface);
    stroke: var(--h, var(--ink));
    stroke-width: 1.5;
}

.small-multiples .dot.absent {
    fill: none;
    stroke: var(--series-context);
    stroke-width: 1;
}

/* The main map's dashed ring of an attributed place */
.small-multiples .dot.dashed {
    stroke-dasharray: 2 1.5;
}

.small-multiples .dot.attested.dashed:not(.pale) {
    stroke: var(--series-context);
}

.small-multiples .pip {
    fill: var(--h);
    stroke: var(--surface);
    stroke-width: 1;
}

.small-multiples figcaption {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: 0.25rem 0.375rem;
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
    margin-inline-start: auto;
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

@keyframes small-multiples-fade {
    from {
        opacity: 0;
    }

    to {
        opacity: 1;
    }
}

@media (max-width: 30rem) {
    .small-multiples .grid {
        grid-template-columns: minmax(0, 1fr);
    }
}

@media (prefers-reduced-motion: reduce) {
    .small-multiples .snapshot {
        animation: none;
    }
}

@media (forced-colors: active) {
    .small-multiples .control {
        border-color: ButtonText;
    }
}
</style>
