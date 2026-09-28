<script setup lang="ts">
import {
    computed,
    inject,
    onBeforeUnmount,
    ref,
    useTemplateRef,
    watch,
} from "vue";
import L from "leaflet";
import { useGettext } from "vue3-gettext";
import { stackSmallestOnTop } from "utils/leaflet-stack";

import LoadingSpinner from "@/manuspectrum/pages/AnalysisExplorer/components/LoadingSpinner.vue";

import { useDocument } from "@/manuspectrum/pages/AnalysisExplorer/composables/useDocument.ts";
import { useLinkedMarks } from "@/manuspectrum/pages/AnalysisExplorer/composables/useLinkedMarks.ts";
import { documentView } from "@/manuspectrum/pages/AnalysisExplorer/folio/document-view.ts";
import {
    markedZones,
    shapeBounds,
} from "@/manuspectrum/pages/AnalysisExplorer/folio/geometry.ts";
import { laidLayers } from "@/manuspectrum/pages/AnalysisExplorer/folio/laid-layers.ts";
import { layerImageUrl } from "@/manuspectrum/pages/AnalysisExplorer/folio/overlays.ts";
import { layPage } from "@/manuspectrum/pages/AnalysisExplorer/folio/page-layer.ts";
import { WINDOW_RESIZE_KEY } from "@/manuspectrum/pages/AnalysisExplorer/injection-keys.ts";
import { slotLabel } from "@/manuspectrum/pages/AnalysisExplorer/store/basket.ts";
import {
    analysisNode,
    slotNode,
} from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/linked/node-id.ts";

import type {
    AnalysisHit,
    FileEntry,
    FileLayer,
} from "@/manuspectrum/pages/AnalysisExplorer/api/types.ts";
import type { LatLng } from "@/manuspectrum/pages/AnalysisExplorer/folio/geometry.ts";
import type { LaidLayers } from "@/manuspectrum/pages/AnalysisExplorer/folio/laid-layers.ts";
import type { FolioOverlay } from "@/manuspectrum/pages/AnalysisExplorer/folio/overlays.ts";
import type { PageLayer } from "@/manuspectrum/pages/AnalysisExplorer/folio/page-layer.ts";

const MAX_ZOOM = 8;
const ZONE_PADDING = 0.25;
const PREVIEW_SIZE = 480;

type Mode = "reading" | "folio" | "no-zone" | "no-image" | "error";

/**
 * One map of the « Element maps » window, under its slot and name: the
 * shared layer (`layer`, null when this map lacks it: `notMapped` says so)
 * laid over the analysis's zone on its page, under a curtain of its own
 * (D47, on at first), positioned indicatively. Without a zone with an
 * extent, a page image or a readable document, the layer is shown alone.
 * The page comes from the document payload (`useDocument`, the tab memo).
 * The card stands for its analysis (`an:`): the analysis name is its
 * toggle, and the card is marked by how the analysis stands to the linked
 * selection (an unlinked map fades, its caption stays readable) and to the
 * node a mouse previews.
 */
const props = defineProps<{
    slotNumber: number;
    analysis: AnalysisHit;
    file: FileEntry;
    layer: FileLayer | null;
    notMapped: string;
}>();

const resizeTick = inject(WINDOW_RESIZE_KEY, ref(0), false);

const { $gettext } = useGettext();
const marks = useLinkedMarks();
const surface = useTemplateRef<HTMLDivElement>("surface");

const curtain = ref(true);
const pageFailed = ref(false);
const layerFailed = ref(false);
const attempt = ref(0);

// Leaflet objects live outside Vue reactivity.
let map: L.Map | null = null;
let page: PageLayer | null = null;
let laid: LaidLayers | null = null;

const record = computed(() => analysisNode(props.analysis.id));
const documentId = computed(() =>
    props.analysis.canvas ? props.analysis.document.id : null,
);
const documentRequest = useDocument(() => documentId.value);
const payload = computed(() =>
    documentId.value !== null &&
    documentRequest.loaded.value === documentId.value
        ? documentRequest.data.value
        : null,
);
const service = computed(
    () =>
        payload.value?.canvases.find(
            (entry) => entry.id === props.analysis.canvas,
        )?.image.service ?? null,
);
const bounds = computed<[LatLng, LatLng] | null>(() => {
    if (!payload.value) return null;
    const zone = markedZones(
        documentView(payload.value, null).annotations.filter(
            (annotation) =>
                annotation.analysis === props.analysis.id &&
                annotation.canvas === props.analysis.canvas,
        ),
    )[0];
    return zone ? shapeBounds(zone.shape) : null;
});
const mode = computed<Mode>(() => {
    if (documentId.value === null) return "no-zone";
    const status = documentRequest.status.value;
    if (status === "error" || status === "unavailable") return "error";
    if (!payload.value) return "reading";
    if (!bounds.value) return "no-zone";
    return service.value ? "folio" : "no-image";
});
const overlays = computed<FolioOverlay[]>(() => {
    const url = props.layer ? layerImageUrl(props.layer.image) : null;
    if (!props.layer || !url || !bounds.value) return [];
    return [
        {
            key: String(props.layer.index),
            url,
            bounds: bounds.value,
            opacity: 1,
            label: props.layer.label,
        },
    ];
});
const aloneUrl = computed(() =>
    props.layer ? layerImageUrl(props.layer.image, PREVIEW_SIZE) : null,
);
const aloneNote = computed(() => {
    switch (mode.value) {
        case "no-zone":
            return $gettext("No zone on a page: the map is shown alone.");
        case "no-image":
            return $gettext("No image for this page: the map is shown alone.");
        case "error":
            return $gettext(
                "The document could not be read: the map is shown alone.",
            );
        default:
            return "";
    }
});

watch(mode, drawMap, { flush: "post", immediate: true });
watch([overlays, curtain], drawLayers);
watch(
    () => props.layer,
    () => {
        layerFailed.value = false;
    },
);
watch(resizeTick, () => map?.invalidateSize({ animate: false }));

onBeforeUnmount(removeMap);

function removeMap(): void {
    laid?.remove();
    laid = null;
    page?.remove();
    page = null;
    map?.remove();
    map = null;
}

/** Builds the folio map when the page and the zone are known; takes it down otherwise. */
function drawMap(): void {
    if (mode.value !== "folio") {
        removeMap();
        return;
    }
    if (map || !surface.value || !bounds.value) return;
    map = L.map(surface.value, {
        crs: L.CRS.Simple,
        attributionControl: false,
        minZoom: 0,
        maxZoom: MAX_ZOOM,
        zoomSnap: 0.25,
    });
    map.fitBounds(L.latLngBounds(bounds.value).pad(ZONE_PADDING), {
        animate: false,
    });
    stackSmallestOnTop(map);
    laid = laidLayers(map, {
        curtainLabel: $gettext("Curtain position"),
        failed: () => {
            layerFailed.value = true;
        },
    });
    drawPage();
    drawLayers();
}

function drawPage(): void {
    if (!map || !service.value) return;
    page?.remove();
    pageFailed.value = false;
    page = layPage(
        map,
        service.value,
        () => {
            pageFailed.value = true;
        },
        { fitBounds: false },
    );
}

function drawLayers(): void {
    const key = overlays.value[0]?.key ?? null;
    laid?.draw(overlays.value, curtain.value ? key : null);
}

function retryLayer(): void {
    laid?.forget(overlays.value.map((overlay) => overlay.key));
    layerFailed.value = false;
    attempt.value += 1;
    drawLayers();
}

function onCurtainChange(event: Event): void {
    curtain.value = (event.target as HTMLInputElement).checked;
}
</script>

<template>
    <figure
        class="element-map-card"
        :data-rel="marks.rel(record)"
        :data-preview="marks.previewRel(record)"
        @pointerenter="marks.enter(record, $event)"
        @pointerleave="marks.leave($event)"
    >
        <figcaption>
            <span
                class="slot"
                :data-rel="marks.rel(slotNode(props.slotNumber))"
                >{{ slotLabel(props.slotNumber) }}</span
            >
            <button
                type="button"
                class="record"
                :lang="props.analysis.name.lang"
                :aria-pressed="marks.pressed(record)"
                @click="marks.toggle(record)"
            >
                <span>{{ props.analysis.name.value }}</span>
            </button>
            <span class="file">{{ props.file.name }}</span>
        </figcaption>
        <p
            v-if="mode === 'reading'"
            class="loading"
            role="status"
        >
            <LoadingSpinner />
            <span>{{ $gettext("Reading the document…") }}</span>
        </p>
        <div
            v-else-if="mode === 'folio'"
            class="stage"
        >
            <div
                ref="surface"
                class="surface"
            />
            <p
                v-if="!props.layer"
                class="not-mapped"
            >
                <span>{{ props.notMapped }}</span>
            </p>
            <p
                v-else-if="layerFailed"
                class="unavailable"
                role="status"
            >
                <span>{{ $gettext("Map unavailable (image server)") }}</span>
                <button
                    type="button"
                    @click="retryLayer"
                >
                    <span>{{ $gettext("Retry") }}</span>
                </button>
            </p>
            <p
                v-else-if="pageFailed"
                class="unavailable"
                role="status"
            >
                <span>{{
                    $gettext(
                        "Page image unavailable (the institution's IIIF server).",
                    )
                }}</span>
                <button
                    type="button"
                    @click="drawPage"
                >
                    <span>{{ $gettext("Retry") }}</span>
                </button>
            </p>
        </div>
        <template v-else>
            <p
                v-if="!props.layer"
                class="not-mapped"
            >
                <span>{{ props.notMapped }}</span>
            </p>
            <p
                v-else-if="layerFailed"
                class="unavailable"
                role="status"
            >
                <span>{{ $gettext("Map unavailable (image server)") }}</span>
                <button
                    type="button"
                    @click="retryLayer"
                >
                    <span>{{ $gettext("Retry") }}</span>
                </button>
            </p>
            <img
                v-else-if="aloneUrl"
                :key="`${aloneUrl}#${attempt}`"
                class="layer-image"
                loading="lazy"
                :src="aloneUrl"
                :alt="props.layer.label"
                @error="layerFailed = true"
            />
            <p class="note">
                <span>{{ aloneNote }}</span>
                <button
                    v-if="mode === 'error'"
                    type="button"
                    class="retry"
                    @click="documentRequest.retry"
                >
                    <span>{{ $gettext("Retry") }}</span>
                </button>
            </p>
        </template>
        <template v-if="mode === 'folio' && props.layer">
            <label class="toggle">
                <input
                    class="curtain"
                    type="checkbox"
                    :checked="curtain"
                    @change="onCurtainChange"
                />
                <span>{{ $gettext("Curtain: compare with the page") }}</span>
            </label>
            <p class="note">
                <span>{{
                    $gettext("Indicative positioning, not registered.")
                }}</span>
            </p>
        </template>
    </figure>
</template>

<style scoped>
.element-map-card {
    display: grid;
    align-content: start;
    gap: 0.375rem;
    margin: 0;
    padding: 0.25rem;
    border-radius: 0.375rem;
}

.element-map-card[data-rel="self"] {
    outline: 0.125rem solid var(--linked-mark, var(--blue-text));
}

.element-map-card[data-rel="direct"] {
    box-shadow: inset 0 0 0 0.125rem var(--linked-mark, var(--blue-text));
}

.element-map-card[data-rel="evidence"] {
    outline: 0.125rem dashed var(--linked-mark, var(--blue-text));
    outline-offset: -0.125rem;
}

.element-map-card[data-rel="none"] .stage,
.element-map-card[data-rel="none"] .layer-image {
    opacity: var(--linked-fade, 0.35);
}

.element-map-card[data-rel="none"] figcaption {
    color: var(--ink-muted);
}

.element-map-card[data-preview] {
    outline: 0.125rem dashed var(--linked-mark, var(--blue-text));
    outline-offset: 0.0625rem;
}

.element-map-card figcaption {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: 0 0.5rem;
    font-size: 0.8125rem;
}

.element-map-card .record {
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

.element-map-card .record:hover {
    border-color: var(--border-hover);
}

.element-map-card .record[aria-pressed="true"] {
    border-color: var(--linked-mark, var(--blue-text));
    font-weight: 600;
}

@media (prefers-reduced-motion: no-preference) {
    .element-map-card .stage,
    .element-map-card .layer-image {
        transition: opacity 0.15s ease-out;
    }
}

.element-map-card .slot {
    font-family: var(--font-mono);
    font-weight: 600;
}

.element-map-card .file {
    color: var(--ink-muted);
    overflow-wrap: anywhere;
}

.element-map-card .loading {
    display: flex;
    align-items: center;
    gap: 0.5rem;
    color: var(--ink-muted);
}

.element-map-card .stage {
    position: relative;
    display: grid;
    border-radius: var(--explorer-radius, 0.625rem);
    background: var(--stage);
    overflow: hidden;
}

.element-map-card .surface {
    min-block-size: 14rem;
    background: var(--stage);
}

.element-map-card .stage .not-mapped,
.element-map-card .stage .unavailable {
    position: absolute;
    inset-block-end: 0.5rem;
    inset-inline-start: 0.5rem;
    z-index: 1000;
    margin: 0;
    padding: 0.25rem 0.5rem;
    border-radius: 0.25rem;
    background: var(--surface);
    color: var(--ink);
    font-size: 0.8125rem;
}

.element-map-card .not-mapped {
    color: var(--ink-muted);
    font-size: 0.8125rem;
}

.element-map-card .unavailable,
.element-map-card .note {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: 0.5rem;
}

.element-map-card .unavailable button,
.element-map-card .note .retry {
    min-block-size: var(--explorer-target, 2.75rem);
    padding-inline: 0.75rem;
    border: 0.0625rem solid var(--border-hover);
    border-radius: 999rem;
    background: var(--surface);
    color: var(--ink);
    font: inherit;
    cursor: pointer;
}

.element-map-card button:focus-visible,
.element-map-card input:focus-visible {
    outline: 0.125rem solid var(--blue-text);
    outline-offset: 0.125rem;
}

.element-map-card .layer-image {
    max-inline-size: 100%;
    background: var(--stage);
    image-rendering: pixelated;
}

.element-map-card .toggle {
    display: flex;
    gap: 0.5rem;
    align-items: center;
    min-block-size: var(--explorer-target, 2.75rem);
    font-size: 0.8125rem;
}

.element-map-card .note {
    color: var(--ink-muted);
    font-size: 0.8125rem;
}
</style>
