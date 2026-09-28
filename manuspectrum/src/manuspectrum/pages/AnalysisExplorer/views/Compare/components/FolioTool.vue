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
import { useLinkedMarks } from "@/manuspectrum/pages/AnalysisExplorer/composables/useLinkedMarks.ts";
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
import {
    analysisNode,
    materialNode,
    slotNode,
} from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/linked/node-id.ts";
import { folioMarks } from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/tools.ts";

import type { Feature } from "geojson";
import type { SynthesisCanvas } from "@/manuspectrum/pages/AnalysisExplorer/api/types.ts";
import type { LinkedMark } from "@/manuspectrum/pages/AnalysisExplorer/composables/useLinkedMarks.ts";
import type { PageLayer } from "@/manuspectrum/pages/AnalysisExplorer/folio/page-layer.ts";
import type { NodeId } from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/linked/node-id.ts";
import type { RelationLevel } from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/linked/related.ts";
import type { FolioMark } from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/tools.ts";

/** The Leaflet layers drawn for one mark, restyled in place. */
interface DrawnMark {
    marker: L.Marker | null;
    halo: L.GeoJSON;
    frame: L.GeoJSON;
}

const MAX_ZOOM = 8;
const INITIAL_ZOOM = 2;
const MARKER_SIZE = 28;
/** Advance of one character of the marker's 0.625rem monospace label, rounded up, in px. */
const MARKER_CHAR_WIDTH = 6.25;
/** The marker's inline padding and border, in px. */
const MARKER_INSET = 12;
const FRAME_WEIGHT = 2;
const LINKED_FRAME_WEIGHT = 3;
const SELF_FRAME_WEIGHT = 4;
const HALO_WEIGHT = 5;
const HALO_OPACITY = 0.9;
/** The opacity of what the selection does not link (`--linked-fade`). */
const FADED_OPACITY = 0.35;
const FRAME_DASH = "4 4";
const PREVIEW_DASH = "1 3";
const RELATED_PADDING = 0.25;
/** The other folios « Show » buttons are offered for. */
const SHOWN_ELSEWHERE = 3;
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
 *
 * Each mark stands for its record (`an:`, `ch:`): its name in the list is
 * the record's toggle, and the mark is shown by how the record stands to
 * the linked selection (an unlinked zone and marker fade, a linked frame
 * is drawn solid and heavier) and to the node a mouse previews (dotted).
 * A selection change restyles the layers drawn (`setStyle`, attributes on
 * the markers) and never draws them again. « Fit to related » frames the
 * linked marks of the page; when linked items of the Selection are placed
 * on other folios they are named, each with a button showing it.
 */
const props = defineProps<{
    canvases: readonly SynthesisCanvas[];
    /** Slots of the Selection's analyses and identified materials, by id (`selectionSlots`). */
    slots: ReadonlyMap<string, readonly number[]>;
}>();

const resizeTick = inject(WINDOW_RESIZE_KEY, ref(0), false);

const gettext = useGettext();
const { $gettext, interpolate } = gettext;
const pickerId = useId();
const linkedMarks = useLinkedMarks();
const host = useTemplateRef<HTMLDivElement>("host");

const chosen = ref<string | null>(props.canvases[0]?.canvas ?? null);
const pageFailed = ref(false);

// Leaflet objects live outside Vue reactivity.
let map: L.Map | null = null;
let page: PageLayer | null = null;
let drawn: L.LayerGroup | null = null;
let fitted: string | null = null;
const drawnMarks = new Map<NodeId, DrawnMark>();

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
const folioMarksShown = computed<FolioMark[]>(() =>
    payload.value && row.value
        ? folioMarks(payload.value, row.value.canvas, props.slots)
        : [],
);
const hasImage = computed(() => Boolean(canvas.value?.image.service));
/** The marks of the page the selection links. */
const relatedHere = computed(() =>
    folioMarksShown.value.filter((mark) =>
        isLinked(linkedMarks.rel(nodeOf(mark))),
    ),
);
/** The other folios holding a Selection item the selection links. */
const elsewhere = computed(() =>
    props.canvases.filter(
        (entry) =>
            entry.canvas !== row.value?.canvas &&
            isLinked(
                linkedMarks.rel(
                    [
                        ...entry.analyses.map(analysisNode),
                        ...entry.materials.map(materialNode),
                    ].filter(inSelection),
                ),
            ),
    ),
);
const elsewhereText = computed(() => {
    if (elsewhere.value.length === 0) return "";
    const selected = linkedMarks.linked?.selection.value ?? [];
    const name =
        (selected.length === 1
            ? linkedMarks.linked?.labelOf(selected[0])?.value
            : null) ?? $gettext("The selection");
    const folios = new Intl.ListFormat(gettext.current, {
        type: "conjunction",
    }).format(elsewhere.value.map((entry) => entry.label));
    return interpolate(
        relatedHere.value.length > 0
            ? $gettext("%{name} also appears on %{folios}.")
            : $gettext("%{name} appears on %{folios}."),
        { name, folios },
        true,
    );
});

watch(
    () => props.canvases.map((entry) => entry.canvas),
    (canvases) => {
        if (chosen.value === null || !canvases.includes(chosen.value)) {
            chosen.value = canvases[0] ?? null;
        }
    },
);
watch(() => canvas.value?.id, drawPage);
watch(folioMarksShown, drawMarks);
watch(
    () => [
        linkedMarks.linked?.levels.value,
        linkedMarks.linked?.previewLevels.value,
    ],
    restyle,
);
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

function nodeOf(mark: FolioMark): NodeId {
    return mark.kind === "analysis"
        ? analysisNode(mark.id)
        : materialNode(mark.id);
}

function isLinked(mark: LinkedMark | undefined): boolean {
    return mark !== undefined && mark !== "none";
}

function inSelection(id: NodeId): boolean {
    return props.slots.has(id.slice(id.indexOf(":") + 1));
}

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
            opacity: className === "folio-tool-halo" ? HALO_OPACITY : 1,
            dashArray: className === "folio-tool-halo" ? "" : FRAME_DASH,
            fill: false,
            interactive: false,
        }),
    });
}

/** A marker on each item's first zone with an extent, else its first point; every extent framed in the slot colour, every halo drawn under every frame. */
function drawMarks(): void {
    if (!map) return;
    drawn?.remove();
    drawnMarks.clear();
    drawn = L.layerGroup().addTo(map);
    const markers: L.Marker[] = [];
    const framed: [FolioMark, Feature[], L.Marker | null][] = [];
    for (const mark of folioMarksShown.value) {
        const anchor =
            mark.shapes.find((shape) => shapeBounds(shape) !== null) ??
            mark.shapes[0];
        const centre = shapeCentre(anchor);
        let marker: L.Marker | null = null;
        if (centre) {
            marker = L.marker(centre, {
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
        framed.push([mark, frames, marker]);
    }
    const halos = framed.map(([, frames]) =>
        frameLayer(frames, "folio-tool-halo", HALO_WEIGHT),
    );
    for (const halo of halos) drawn.addLayer(halo);
    framed.forEach(([mark, frames, marker], index) => {
        const frame = frameLayer(
            frames,
            `folio-tool-frame ${slotClass(mark)}`,
            FRAME_WEIGHT,
        );
        drawn!.addLayer(frame);
        drawnMarks.set(nodeOf(mark), { marker, halo: halos[index], frame });
    });
    restyle();
    const key = canvas.value?.id ?? null;
    if (!hasImage.value && markers.length > 0 && fitted !== key) {
        fitted = key;
        map.fitBounds(
            L.featureGroup(markers).getBounds().pad(NO_IMAGE_PADDING),
            { animate: false },
        );
    }
}

/** The frame of a mark at `level`, dotted while `preview` links it. */
function frameStyle(
    level: LinkedMark | undefined,
    preview: RelationLevel | undefined,
): L.PathOptions {
    const style: L.PathOptions = {
        weight: FRAME_WEIGHT,
        opacity: 1,
        dashArray: FRAME_DASH,
    };
    if (level === "self") {
        Object.assign(style, { weight: SELF_FRAME_WEIGHT, dashArray: "" });
    } else if (level === "direct") {
        Object.assign(style, { weight: LINKED_FRAME_WEIGHT, dashArray: "" });
    } else if (level === "evidence") {
        style.weight = LINKED_FRAME_WEIGHT;
    } else if (level === "none") {
        style.opacity = FADED_OPACITY;
    }
    if (preview) {
        Object.assign(style, {
            weight: Math.max(style.weight ?? FRAME_WEIGHT, LINKED_FRAME_WEIGHT),
            dashArray: PREVIEW_DASH,
        });
    }
    return style;
}

/** Shows each mark drawn by how its record stands to the selection and the preview, on the layers already drawn. */
function restyle(): void {
    for (const [node, layers] of drawnMarks) {
        const level = linkedMarks.rel(node);
        const preview = linkedMarks.previewRel(node);
        layers.frame.setStyle(frameStyle(level, preview));
        layers.halo.setStyle({
            opacity:
                level === "none" ? FADED_OPACITY * HALO_OPACITY : HALO_OPACITY,
        });
        const host = layers.marker?.getElement();
        if (!host) continue;
        setData(host, "rel", level);
        setData(host, "preview", preview);
    }
}

function setData(
    element: HTMLElement,
    name: string,
    value: string | undefined,
): void {
    if (value === undefined) delete element.dataset[name];
    else element.dataset[name] = value;
}

/** Frames the marks of the page the selection links. */
function fitRelated(): void {
    if (!map) return;
    const bounds = L.latLngBounds([]);
    for (const mark of relatedHere.value) {
        const layers = drawnMarks.get(nodeOf(mark));
        if (!layers) continue;
        if (layers.marker) bounds.extend(layers.marker.getLatLng());
        const frame = layers.frame.getBounds();
        if (frame.isValid()) bounds.extend(frame);
    }
    if (bounds.isValid()) {
        map.fitBounds(bounds.pad(RELATED_PADDING), { animate: false });
    }
}

function showFolio(canvasId: string): void {
    chosen.value = canvasId;
}

function onEnter(mark: FolioMark, event: PointerEvent): void {
    linkedMarks.enter(nodeOf(mark), event);
}

function showLabel(label: string): string {
    return interpolate($gettext("Show %{folio}"), { folio: label }, true);
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
            <div
                v-if="linkedMarks.active.value"
                class="related"
            >
                <button
                    v-if="relatedHere.length > 0"
                    type="button"
                    class="fit"
                    @click="fitRelated"
                >
                    <span>{{ $gettext("Fit to related") }}</span>
                </button>
                <p
                    v-if="elsewhere.length > 0"
                    class="elsewhere"
                >
                    <span>{{ elsewhereText }}</span>
                    <button
                        v-for="entry in elsewhere.slice(0, SHOWN_ELSEWHERE)"
                        :key="entry.canvas"
                        type="button"
                        class="show"
                        @click="showFolio(entry.canvas)"
                    >
                        <span>{{ showLabel(entry.label) }}</span>
                    </button>
                </p>
            </div>
            <ul
                v-if="folioMarksShown.length > 0"
                class="marks"
                :aria-label="$gettext('Selection items on this folio')"
            >
                <li
                    v-for="mark in folioMarksShown"
                    :key="mark.id"
                    :data-rel="linkedMarks.rel(nodeOf(mark))"
                    :data-preview="linkedMarks.previewRel(nodeOf(mark))"
                    @pointerenter="onEnter(mark, $event)"
                    @pointerleave="linkedMarks.leave($event)"
                >
                    <span
                        class="slot"
                        :class="slotClass(mark)"
                        :data-rel="linkedMarks.rel(mark.slots.map(slotNode))"
                        >{{ slotsText(mark) }}</span
                    >
                    <TechniqueCode
                        v-if="mark.technique"
                        :code="mark.technique.code"
                        :colour="mark.technique.colour"
                        size="small"
                    />
                    <button
                        type="button"
                        class="name"
                        :lang="mark.name.lang"
                        :aria-pressed="linkedMarks.pressed(nodeOf(mark))"
                        @click="linkedMarks.toggle(nodeOf(mark))"
                    >
                        <span>{{ mark.name.value }}</span>
                    </button>
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
}

.folio-tool :deep(.folio-tool-frame) {
    stroke: var(--ink);
}

.folio-tool :deep(.folio-tool-marker-host[data-rel="none"]) {
    opacity: var(--linked-fade, 0.35);
}

.folio-tool :deep(.folio-tool-marker-host[data-rel="self"] .folio-tool-marker) {
    outline: 0.125rem solid var(--linked-mark, var(--blue-text));
    outline-offset: 0.0625rem;
}

.folio-tool
    :deep(.folio-tool-marker-host[data-rel="direct"] .folio-tool-marker) {
    box-shadow: 0 0 0 0.125rem var(--linked-mark, var(--blue-text));
}

.folio-tool
    :deep(.folio-tool-marker-host[data-rel="evidence"] .folio-tool-marker) {
    outline: 0.125rem dashed var(--linked-mark, var(--blue-text));
    outline-offset: 0.0625rem;
}

.folio-tool :deep(.folio-tool-marker-host[data-preview] .folio-tool-marker) {
    outline: 0.125rem dotted var(--linked-mark, var(--blue-text));
    outline-offset: 0.125rem;
}

.folio-tool .related {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: 0.5rem;
    font-size: 0.8125rem;
}

.folio-tool .related .elsewhere {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: 0.5rem;
    margin: 0;
}

.folio-tool .related button {
    min-block-size: var(--explorer-target, 2.75rem);
    padding-inline: 0.5rem;
    border: 0.0625rem solid var(--border-hover);
    border-radius: 0.25rem;
    background: var(--surface);
    color: var(--ink);
    font: inherit;
    cursor: pointer;
}

.folio-tool .marks .name {
    min-block-size: 1.5rem;
    padding: 0 0.25rem;
    border: 0.0625rem solid transparent;
    border-radius: 0.25rem;
    background: none;
    color: inherit;
    font: inherit;
    text-align: start;
    cursor: pointer;
}

.folio-tool .marks .name:hover {
    border-color: var(--border-hover);
}

.folio-tool .marks .name[aria-pressed="true"] {
    border-color: var(--linked-mark, var(--blue-text));
    font-weight: 600;
}

.folio-tool .marks li {
    padding-inline-start: 0.375rem;
    border-inline-start: var(--linked-bar, 0.1875rem) solid transparent;
}

.folio-tool .marks li[data-rel="self"] {
    outline: 0.125rem solid var(--linked-mark, var(--blue-text));
}

.folio-tool .marks li[data-rel="self"],
.folio-tool .marks li[data-rel="direct"],
.folio-tool .marks li[data-rel="evidence"] {
    border-inline-start-color: var(--linked-mark, var(--blue-text));
    background: var(--linked-tint, var(--bg-alt));
}

.folio-tool .marks li[data-rel="evidence"] {
    border-inline-start-style: dashed;
}

.folio-tool .marks li[data-rel="none"] {
    color: var(--ink-muted);
}

.folio-tool .marks li[data-preview] {
    outline: 0.125rem dashed var(--linked-mark, var(--blue-text));
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
