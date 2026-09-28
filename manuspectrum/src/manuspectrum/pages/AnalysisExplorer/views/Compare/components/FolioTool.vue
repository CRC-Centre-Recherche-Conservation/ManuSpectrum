<script setup lang="ts">
import {
    computed,
    inject,
    onBeforeUnmount,
    onMounted,
    ref,
    useId,
    useTemplateRef,
    watch,
} from "vue";
import L from "leaflet";
import { useGettext } from "vue3-gettext";
import { stackSmallestOnTop } from "utils/leaflet-stack";

import LoadingSpinner from "@/manuspectrum/pages/AnalysisExplorer/components/LoadingSpinner.vue";
import UnavailableState from "@/manuspectrum/pages/AnalysisExplorer/components/UnavailableState.vue";
import TechniqueCode from "@/manuspectrum/pages/AnalysisExplorer/views/Corpus/document/TechniqueCode.vue";

import { useDocument } from "@/manuspectrum/pages/AnalysisExplorer/composables/useDocument.ts";
import {
    shapeBounds,
    shapeCentre,
    shapeFeature,
} from "@/manuspectrum/pages/AnalysisExplorer/folio/geometry.ts";
import {
    fitPage,
    layPage,
} from "@/manuspectrum/pages/AnalysisExplorer/folio/page-layer.ts";
import { WINDOW_RESIZE_KEY } from "@/manuspectrum/pages/AnalysisExplorer/injection-keys.ts";
import { slotLabel } from "@/manuspectrum/pages/AnalysisExplorer/store/basket.ts";
import { folioMarks } from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/tools.ts";

import type { Feature } from "geojson";
import type { SynthesisCanvas } from "@/manuspectrum/pages/AnalysisExplorer/api/types.ts";
import type { PageLayer } from "@/manuspectrum/pages/AnalysisExplorer/folio/page-layer.ts";
import type { FolioMark } from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/tools.ts";

const MAX_ZOOM = 8;
const INITIAL_ZOOM = 2;
const MARKER_SIZE = 28;
/** Advance of one character of the marker's 0.625rem monospace label, rounded up, in px. */
const MARKER_CHAR_WIDTH = 6.25;
/** The marker's inline padding and border, in px. */
const MARKER_INSET = 12;
const FRAME_WEIGHT = 2;
const HALO_WEIGHT = 5;
const NO_IMAGE_PADDING = 0.5;
/** Slots drawn in a series colour (A1…A8); the others in ink. */
const SERIES_SLOTS = 8;

/**
 * The folio image tool: one of the canvases the Selection's items are
 * placed on (picked among `canvases`, the first at first) with the
 * Selection's analyses and identified materials placed on it, each marked
 * with its A-labels in the colour of its first slot (ink from A9) and its
 * zones framed in that colour over a halo; the same
 * marks are listed under the image. The page comes from the document
 * payload (`useDocument`, the tab memo the document screen shares). The
 * markers are labels, not controls: the list is what assistive
 * technologies read.
 */
const props = defineProps<{
    canvases: readonly SynthesisCanvas[];
    /** Slots of the Selection's analyses and identified materials, by id (`selectionSlots`). */
    slots: ReadonlyMap<string, readonly number[]>;
}>();

const resizeTick = inject(WINDOW_RESIZE_KEY, ref(0), false);

const { $gettext } = useGettext();
const pickerId = useId();
const host = useTemplateRef<HTMLDivElement>("host");

const chosen = ref<string | null>(props.canvases[0]?.canvas ?? null);
const pageFailed = ref(false);

// Leaflet objects live outside Vue reactivity.
let map: L.Map | null = null;
let page: PageLayer | null = null;
let drawn: L.LayerGroup | null = null;
let fitted: string | null = null;

const row = computed(
    () =>
        props.canvases.find((entry) => entry.canvas === chosen.value) ??
        props.canvases[0] ??
        null,
);
const documentRequest = useDocument(() => row.value?.document ?? null);
const payload = computed(() =>
    documentRequest.loaded.value === row.value?.document
        ? documentRequest.data.value
        : null,
);
const canvas = computed(
    () =>
        payload.value?.canvases.find(
            (entry) => entry.id === row.value?.canvas,
        ) ?? null,
);
const marks = computed<FolioMark[]>(() =>
    payload.value && row.value
        ? folioMarks(payload.value, row.value.canvas, props.slots)
        : [],
);
const hasImage = computed(() => Boolean(canvas.value?.image.service));

watch(
    () => props.canvases.map((entry) => entry.canvas),
    (canvases) => {
        if (chosen.value === null || !canvases.includes(chosen.value)) {
            chosen.value = canvases[0] ?? null;
        }
    },
);
watch(() => canvas.value?.id, drawPage);
watch(marks, drawMarks);
watch(resizeTick, () => map?.invalidateSize({ animate: false }));
watch(
    () => payload.value !== null,
    (shown) => {
        if (shown) map?.invalidateSize({ animate: false });
    },
    { flush: "post" },
);

onMounted(() => {
    const surface = host.value?.querySelector<HTMLElement>(".surface");
    if (!surface) return;
    map = L.map(surface, {
        crs: L.CRS.Simple,
        attributionControl: false,
        minZoom: 0,
        maxZoom: MAX_ZOOM,
        zoomSnap: 0.25,
    });
    map.setView([0, 0], INITIAL_ZOOM);
    stackSmallestOnTop(map);
    drawPage();
    drawMarks();
});

onBeforeUnmount(() => {
    page?.remove();
    page = null;
    map?.remove();
    map = null;
});

function slotClass(mark: FolioMark): string {
    const first = mark.slots[0];
    return first < SERIES_SLOTS ? `slot-${first + 1}` : "slot-ink";
}

function slotsText(mark: FolioMark): string {
    return mark.slots.map(slotLabel).join(" ");
}

function onPick(event: Event): void {
    chosen.value = (event.target as HTMLSelectElement).value;
}

function drawPage(): void {
    if (!map) return;
    page?.remove();
    page = null;
    pageFailed.value = false;
    const service = canvas.value?.image.service;
    if (!service) return;
    page = layPage(map, service, () => {
        pageFailed.value = true;
    });
}

/** A marker as wide as its label (at least a disc), centred on its point. */
function markerIcon(mark: FolioMark): L.DivIcon {
    const text = slotsText(mark);
    const element = document.createElement("span");
    element.className = `folio-tool-marker ${slotClass(mark)}`;
    element.textContent = text;
    element.setAttribute("aria-hidden", "true");
    const width = Math.max(
        MARKER_SIZE,
        Math.ceil(text.length * MARKER_CHAR_WIDTH + MARKER_INSET),
    );
    return L.divIcon({
        html: element,
        className: "folio-tool-marker-host",
        iconSize: [width, MARKER_SIZE],
        iconAnchor: [width / 2, MARKER_SIZE / 2],
    });
}

/** The zone `frames` drawn with `className` at `weight`. */
function frameLayer(
    frames: Feature[],
    className: string,
    weight: number,
): L.GeoJSON {
    return L.geoJSON(frames, {
        style: () => ({
            className,
            weight,
            fill: false,
            interactive: false,
        }),
    });
}

/** A marker on each item's first zone with an extent, else its first point; every extent framed in the slot colour over a halo. */
function drawMarks(): void {
    if (!map) return;
    drawn?.remove();
    drawn = L.layerGroup().addTo(map);
    const markers: L.Marker[] = [];
    for (const mark of marks.value) {
        const anchor =
            mark.shapes.find((shape) => shapeBounds(shape) !== null) ??
            mark.shapes[0];
        const centre = shapeCentre(anchor);
        if (centre) {
            const marker = L.marker(centre, {
                icon: markerIcon(mark),
                interactive: false,
                keyboard: false,
            });
            markers.push(marker);
            drawn.addLayer(marker);
        }
        const frames = mark.shapes.flatMap((shape) => {
            const feature =
                shape.type === "point"
                    ? null
                    : shapeFeature(shape, { id: mark.id });
            return feature ? [feature] : [];
        });
        drawn.addLayer(frameLayer(frames, "folio-tool-halo", HALO_WEIGHT));
        drawn.addLayer(
            frameLayer(
                frames,
                `folio-tool-frame ${slotClass(mark)}`,
                FRAME_WEIGHT,
            ),
        );
    }
    const key = canvas.value?.id ?? null;
    if (!hasImage.value && markers.length > 0 && fitted !== key) {
        fitted = key;
        map.fitBounds(
            L.featureGroup(markers).getBounds().pad(NO_IMAGE_PADDING),
            { animate: false },
        );
    }
}

function wholePage(): void {
    if (map) fitPage(map, page);
}
</script>

<template>
    <div class="folio-tool">
        <div class="picker">
            <label :for="pickerId">
                <span>{{ $gettext("Folio") }}</span>
            </label>
            <select
                :id="pickerId"
                :value="row?.canvas ?? ''"
                @change="onPick"
            >
                <option
                    v-for="entry in props.canvases"
                    :key="entry.canvas"
                    :value="entry.canvas"
                >
                    {{ entry.label }}
                </option>
            </select>
            <button
                v-if="hasImage"
                type="button"
                class="whole"
                @click="wholePage"
            >
                <span>{{ $gettext("Whole page") }}</span>
            </button>
        </div>
        <UnavailableState
            v-if="documentRequest.status.value === 'error'"
            status="error"
            :hide-home="true"
            @retry="documentRequest.retry"
        />
        <UnavailableState
            v-else-if="documentRequest.status.value === 'unavailable'"
            status="unavailable"
            :hide-home="true"
            @retry="documentRequest.retry"
        />
        <p
            v-else-if="!payload"
            class="loading"
            role="status"
        >
            <LoadingSpinner />
            <span>{{ $gettext("Reading the document…") }}</span>
        </p>
        <div
            ref="host"
            class="stage"
            :hidden="!payload"
        >
            <div class="surface" />
            <p
                v-if="payload && !hasImage"
                class="no-image"
                role="status"
            >
                <span>{{ $gettext("No image for this page.") }}</span>
            </p>
            <p
                v-else-if="pageFailed"
                class="no-image"
                role="status"
            >
                <span>{{
                    $gettext(
                        "Page image unavailable (the institution's IIIF server).",
                    )
                }}</span>
                <button
                    type="button"
                    class="retry"
                    @click="drawPage"
                >
                    <span>{{ $gettext("Retry") }}</span>
                </button>
            </p>
        </div>
        <template v-if="payload">
            <ul
                v-if="marks.length > 0"
                class="marks"
                :aria-label="$gettext('Selection items on this folio')"
            >
                <li
                    v-for="mark in marks"
                    :key="mark.id"
                >
                    <span
                        class="slot"
                        :class="slotClass(mark)"
                        >{{ slotsText(mark) }}</span
                    >
                    <TechniqueCode
                        v-if="mark.technique"
                        :code="mark.technique.code"
                        :colour="mark.technique.colour"
                        size="small"
                    />
                    <span
                        class="name"
                        :lang="mark.name.lang"
                        >{{ mark.name.value }}</span
                    >
                    <span
                        v-if="mark.kind === 'characterization'"
                        class="kind"
                        >{{ $gettext("Identified material") }}</span
                    >
                </li>
            </ul>
            <p
                v-else
                class="empty"
            >
                <span>{{
                    $gettext(
                        "No item of the Selection is placed on this folio.",
                    )
                }}</span>
            </p>
        </template>
    </div>
</template>

<style scoped>
.folio-tool {
    display: grid;
    grid-template-rows: auto minmax(12rem, 1fr) auto;
    gap: 0.5rem;
    block-size: 100%;
}

.folio-tool .picker {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: 0.5rem;
    font-size: 0.8125rem;
}

.folio-tool .picker select,
.folio-tool .picker button,
.folio-tool .no-image .retry {
    min-block-size: var(--explorer-target, 2.75rem);
    padding-inline: 0.5rem;
    border: 0.0625rem solid var(--border-hover);
    border-radius: 0.25rem;
    background: var(--surface);
    color: var(--ink);
    font: inherit;
}

.folio-tool .picker button,
.folio-tool .no-image .retry {
    cursor: pointer;
}

.folio-tool select:focus-visible,
.folio-tool button:focus-visible {
    outline: 0.125rem solid var(--blue-text);
    outline-offset: 0.125rem;
}

.folio-tool .loading {
    display: flex;
    align-items: center;
    gap: 0.5rem;
    color: var(--ink-muted);
}

.folio-tool .stage {
    position: relative;
    display: grid;
    min-block-size: 12rem;
    border-radius: var(--explorer-radius, 0.625rem);
    background: var(--stage);
    overflow: hidden;
}

.folio-tool .stage[hidden] {
    display: none;
}

.folio-tool .surface {
    min-block-size: 12rem;
    background: var(--stage);
}

.folio-tool .no-image {
    position: absolute;
    inset-block-end: 0.5rem;
    inset-inline-start: 0.5rem;
    z-index: 1000;
    display: flex;
    align-items: center;
    gap: 0.5rem;
    margin: 0;
    padding: 0.25rem 0.5rem;
    border-radius: 0.25rem;
    background: var(--surface);
    color: var(--ink);
    font-size: 0.8125rem;
}

.folio-tool .marks {
    display: grid;
    gap: 0.25rem;
    margin: 0;
    padding: 0;
    list-style: none;
    font-size: 0.8125rem;
}

.folio-tool .marks li {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: 0.375rem;
}

.folio-tool .marks .slot {
    padding-inline: 0.375rem;
    border-radius: 0.25rem;
    color: var(--surface);
    font: 600 0.75rem var(--font-mono);
}

.folio-tool .marks .kind,
.folio-tool .empty {
    color: var(--ink-muted);
}

.folio-tool :deep(.folio-tool-marker-host) {
    display: flex;
    justify-content: center;
    background: none;
    border: none;
}

.folio-tool :deep(.folio-tool-marker) {
    display: grid;
    flex: none;
    place-items: center;
    box-sizing: border-box;
    min-inline-size: 1.75rem;
    block-size: 1.75rem;
    padding-inline: 0.25rem;
    border: 0.125rem solid var(--surface);
    border-radius: 999rem;
    color: var(--surface);
    font: 600 0.625rem var(--font-mono);
    white-space: nowrap;
}

.folio-tool :deep(.folio-tool-halo) {
    stroke: var(--surface);
    stroke-opacity: 0.9;
}

.folio-tool :deep(.folio-tool-frame) {
    stroke: var(--ink);
    stroke-opacity: 1;
    stroke-dasharray: 4 4;
}

.folio-tool .slot-1,
.folio-tool :deep(.folio-tool-marker.slot-1) {
    background: var(--series-1);
}

.folio-tool .slot-2,
.folio-tool :deep(.folio-tool-marker.slot-2) {
    background: var(--series-2);
}

.folio-tool .slot-3,
.folio-tool :deep(.folio-tool-marker.slot-3) {
    background: var(--series-3);
}

.folio-tool .slot-4,
.folio-tool :deep(.folio-tool-marker.slot-4) {
    background: var(--series-4);
}

.folio-tool .slot-5,
.folio-tool :deep(.folio-tool-marker.slot-5) {
    background: var(--series-5);
}

.folio-tool .slot-6,
.folio-tool :deep(.folio-tool-marker.slot-6) {
    background: var(--series-6);
}

.folio-tool .slot-7,
.folio-tool :deep(.folio-tool-marker.slot-7) {
    background: var(--series-7);
}

.folio-tool .slot-8,
.folio-tool :deep(.folio-tool-marker.slot-8) {
    background: var(--series-8);
}

.folio-tool .slot-ink,
.folio-tool :deep(.folio-tool-marker.slot-ink) {
    background: var(--ink);
}

.folio-tool :deep(.folio-tool-frame.slot-1) {
    stroke: var(--series-1);
}

.folio-tool :deep(.folio-tool-frame.slot-2) {
    stroke: var(--series-2);
}

.folio-tool :deep(.folio-tool-frame.slot-3) {
    stroke: var(--series-3);
}

.folio-tool :deep(.folio-tool-frame.slot-4) {
    stroke: var(--series-4);
}

.folio-tool :deep(.folio-tool-frame.slot-5) {
    stroke: var(--series-5);
}

.folio-tool :deep(.folio-tool-frame.slot-6) {
    stroke: var(--series-6);
}

.folio-tool :deep(.folio-tool-frame.slot-7) {
    stroke: var(--series-7);
}

.folio-tool :deep(.folio-tool-frame.slot-8) {
    stroke: var(--series-8);
}
</style>
