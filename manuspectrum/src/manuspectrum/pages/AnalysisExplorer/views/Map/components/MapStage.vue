<script setup lang="ts">
import {
    markRaw,
    onBeforeUnmount,
    onMounted,
    ref,
    shallowRef,
    useTemplateRef,
    watch,
} from "vue";
import { usePreferredReducedMotion } from "@vueuse/core";
import maplibregl from "maplibre-gl";
import "maplibre-gl/dist/maplibre-gl.css";
import { useGettext } from "vue3-gettext";

import {
    BASE_SOURCE,
    OHM_ATTRIBUTION,
    OHM_TILES,
    OPENFREEMAP_TILES,
    WATER_LAYER,
    baseStyle,
} from "@/manuspectrum/pages/AnalysisExplorer/views/Map/base-style.ts";
import {
    BORDERS_LAYER,
    BORDERS_MIN_ZOOM,
    CLICKABLE_LAYERS,
    IMAGE_PIXEL_RATIO,
    OHM_SOURCE,
    PLACES_SOURCE,
    TERRITORIES_SOURCE,
    bordersFilter,
    bordersLayer,
    pipImage,
    placeLayers,
    stageImages,
    territoryLayers,
    territoryOpacity,
} from "@/manuspectrum/pages/AnalysisExplorer/views/Map/stage-layers.ts";

import type { FeatureCollection, Point } from "geojson";
import type {
    GeoJSONSource,
    JumpToOptions,
    LayerSpecification,
    LngLatBoundsLike,
    Map as MapLibreMap,
    MapMouseEvent,
    VectorTileSource,
} from "maplibre-gl";
import type {
    Bounds,
    LngLat,
} from "@/manuspectrum/pages/AnalysisExplorer/views/Map/geo.ts";
import type { MapColours } from "@/manuspectrum/pages/AnalysisExplorer/views/Map/map-colours.ts";
import type { MapSnapshot } from "@/manuspectrum/pages/AnalysisExplorer/views/Map/multiples.ts";
import type { PlaceProperties } from "@/manuspectrum/pages/AnalysisExplorer/views/Map/place-symbols.ts";
import type { DrawnImage } from "@/manuspectrum/pages/AnalysisExplorer/views/Map/stage-layers.ts";

type FeatureState = Record<string, number | boolean>;

interface SnapshotRequest {
    bounds: Bounds;
    resolve: (shot: MapSnapshot | null) => void;
}

const START_CENTRE: [number, number] = [2.5, 47];
const START_ZOOM = 4;
const FIT_PADDING_PX = 40;
const FIT_DURATION_MS = 420;
const PAINT_TRANSITION_MS = 160;
const OHM_MAX_ZOOM = 14;
const SNAPSHOT_TIMEOUT_MS = 8000;
const EMPTY: FeatureCollection = { type: "FeatureCollection", features: [] };
const PIP_FONT_CHECK = "700 18px 'JetBrains Mono'";
const ATTRIBUTION_EVENTS = ["load", "styledata", "sourcedata", "resize"];
const SHOWN_ATTRIBUTION = ".maplibregl-ctrl-attrib.maplibregl-compact-show";

/**
 * The MapLibre stage of the map view: paper land on pale water, the places
 * with their rings and followed-material pips, the territories under the
 * sea, the historical borders. Every focus, follow or selection change goes
 * through feature-state; only a change of `places` or `territories`
 * replaces source data; `isolate` (a slot, or null) fades the other slots'
 * territories by paint. The historical borders load from
 * `BORDERS_MIN_ZOOM` only; `zoom` reports the camera's zoom after each move.
 * The compact attribution starts folded to its ⓘ. Overlays of the parent
 * (legend, note, tooltip) go in the default slot, inside the frame.
 */
const props = defineProps<{
    places: FeatureCollection<Point, PlaceProperties>;
    states: ReadonlyMap<string, FeatureState>;
    territories: FeatureCollection | null;
    colours: MapColours;
    borders: boolean;
    bordersYear: number | null;
    fit: Bounds | null;
    selected: string | null;
    isolate?: number | null;
}>();
const emit = defineEmits<{
    select: [id: string];
    hover: [payload: { id: string; x: number; y: number } | null];
    zoom: [zoom: number];
    failed: [];
}>();
defineExpose({ snapshot, cancelSnapshots, resize, revealPlace, zoomTo });

const { $gettext } = useGettext();
const motion = usePreferredReducedMotion();

const container = useTemplateRef<HTMLDivElement>("container");
const map = shallowRef<MapLibreMap | null>(null);
const failed = ref(false);
const baseFailed = ref(false);
let ready = false;
let applied = new Map<string, string>();
let hovered: string | null = null;
let drawnColours: MapColours = props.colours;
let shooting = false;
let queued: SnapshotRequest | null = null;
let userMoved = false;

watch(
    () => props.places,
    (data) => {
        if (ready) geojson(PLACES_SOURCE)?.setData(data);
    },
);
watch(() => [props.states, props.selected], applyStates);
watch(
    () => props.territories,
    (data) => {
        if (ready) geojson(TERRITORIES_SOURCE)?.setData(data ?? EMPTY);
    },
);
watch(
    () => props.borders,
    (visible) => {
        if (ready) {
            map.value?.setLayoutProperty(
                BORDERS_LAYER,
                "visibility",
                visible ? "visible" : "none",
            );
        }
    },
);
watch(
    () => props.bordersYear,
    (year) => {
        if (ready) map.value?.setFilter(BORDERS_LAYER, bordersFilter(year));
    },
);
watch(
    () => props.isolate ?? null,
    (slot) => {
        if (ready && map.value) isolateTerritory(map.value, slot);
    },
);
watch(
    () => props.colours,
    (colours) => {
        if (ready && map.value) recolour(map.value, colours);
    },
);

onMounted(() => {
    if (!container.value) return;
    try {
        const created = markRaw(
            new maplibregl.Map({
                container: container.value,
                style: {
                    ...baseStyle(props.colours),
                    transition: { duration: transitionMs(), delay: 0 },
                },
                attributionControl: { compact: true },
                center: START_CENTRE,
                zoom: START_ZOOM,
                dragRotate: false,
                pitchWithRotate: false,
                touchPitch: false,
                locale: {
                    "Map.Title": $gettext(
                        "Map of the places of the kept events",
                    ),
                    "AttributionControl.ToggleAttribution": $gettext(
                        "Show or hide the map credits",
                    ),
                },
            }),
        );
        foldAttribution(created);
        created.on("load", () => onLoad(created));
        created.on("error", (event: { sourceId?: string }) => {
            if (event.sourceId === BASE_SOURCE) baseFailed.value = true;
            if (!ready && !event.sourceId) dropQueued();
        });
        map.value = created;
    } catch (error: unknown) {
        console.error("The map could not start", error);
        failed.value = true;
        dropQueued();
        emit("failed");
    }
});

onBeforeUnmount(() => {
    ready = false;
    dropQueued();
    map.value?.remove();
    map.value = null;
});

function transitionMs(): number {
    return motion.value === "reduce" ? 0 : PAINT_TRANSITION_MS;
}

function fitDurationMs(): number {
    return motion.value === "reduce" ? 0 : FIT_DURATION_MS;
}

function geojson(id: string): GeoJSONSource | undefined {
    return map.value?.getSource(id) as GeoJSONSource | undefined;
}

function boundsLike(bounds: Bounds): LngLatBoundsLike {
    return [
        [bounds.west, bounds.south],
        [bounds.east, bounds.north],
    ];
}

/** The state sent for place `id`: the parent's, hovered also under the stage's own pointer, and selected. */
function sentState(id: string, state: FeatureState): FeatureState {
    const merged = id === hovered ? { ...state, hover: true } : state;
    return { ...merged, selected: id === props.selected };
}

/** Sends the feature-state of the places whose state changed since the last call. */
function applyStates(): void {
    const current = map.value;
    if (!current || !ready) return;
    const next = new Map<string, string>();
    for (const [id, state] of props.states) {
        const sent = sentState(id, state);
        const key = JSON.stringify(sent);
        next.set(id, key);
        if (applied.get(id) !== key) {
            current.setFeatureState({ source: PLACES_SOURCE, id }, sent);
        }
    }
    for (const id of applied.keys()) {
        if (!next.has(id))
            current.removeFeatureState({ source: PLACES_SOURCE, id });
    }
    applied = next;
}

/**
 * Removes the open state MapLibre gives the compact attribution when its
 * text first arrives (on a style, source or resize event, `maplibre-gl`
 * 4.7.1 `AttributionControl._updateCompact`), once; the reader's own
 * toggles are left alone.
 */
function foldAttribution(current: MapLibreMap): void {
    const fold = (): void => {
        const shown = container.value?.querySelector(SHOWN_ATTRIBUTION);
        if (!shown) return;
        shown.classList.remove("maplibregl-compact-show");
        for (const type of ATTRIBUTION_EVENTS) current.off(type, fold);
    };
    for (const type of ATTRIBUTION_EVENTS) current.on(type, fold);
}

function isolateTerritory(current: MapLibreMap, slot: number | null): void {
    const opacity = territoryOpacity(slot);
    current.setPaintProperty("territory-cells", "fill-opacity", opacity.cells);
    current.setPaintProperty("territory-hatch", "fill-opacity", opacity.hatch);
    current.setPaintProperty(
        "territory-casing",
        "line-opacity",
        opacity.casing,
    );
    current.setPaintProperty("territory-edges", "line-opacity", opacity.edges);
}

function putImages(current: MapLibreMap, colours: MapColours): void {
    for (const [name, image] of stageImages(colours))
        putImage(current, name, image);
}

function putImage(current: MapLibreMap, name: string, image: DrawnImage): void {
    if (current.hasImage(name)) {
        current.updateImage(name, image);
    } else {
        current.addImage(name, image, { pixelRatio: IMAGE_PIXEL_RATIO });
    }
}

/** Every layer the stage draws, for diffing paint properties when the colours change. */
function stageLayerSpecs(colours: MapColours): LayerSpecification[] {
    return [
        ...baseStyle(colours).layers,
        ...territoryLayers(colours),
        bordersLayer(props.bordersYear, colours, props.borders),
        ...placeLayers(colours),
    ];
}

function recolour(current: MapLibreMap, colours: MapColours): void {
    const before = new Map(
        stageLayerSpecs(drawnColours).map((layer) => [layer.id, layer]),
    );
    for (const layer of stageLayerSpecs(colours)) {
        const paint = (layer.paint ?? {}) as Record<string, unknown>;
        const old = (before.get(layer.id)?.paint ?? {}) as Record<
            string,
            unknown
        >;
        for (const [name, value] of Object.entries(paint)) {
            if (JSON.stringify(old[name]) !== JSON.stringify(value)) {
                current.setPaintProperty(layer.id, name, value);
            }
        }
    }
    putImages(current, colours);
    drawnColours = colours;
}

/** Redraws the pip digits once the page fonts are in, when JetBrains Mono was not ready at load. */
function redrawPipsWhenFontsLoad(current: MapLibreMap): void {
    const fonts = document.fonts;
    if (!fonts || fonts.check(PIP_FONT_CHECK)) return;
    fonts.ready
        .then(() => {
            if (!ready || map.value !== current) return;
            const images = stageImages(drawnColours);
            for (let slot = 1; slot <= 4; slot++) {
                for (const pale of [false, true]) {
                    const name = pipImage(slot, pale);
                    const image = images.get(name);
                    if (image) putImage(current, name, image);
                }
            }
        })
        .catch((error: unknown) => {
            console.error("The map pips could not be redrawn", error);
        });
}

function onLoad(current: MapLibreMap): void {
    if (map.value !== current) return;
    putImages(current, props.colours);
    current.addSource(PLACES_SOURCE, {
        type: "geojson",
        data: props.places,
        promoteId: "id",
    });
    current.addSource(TERRITORIES_SOURCE, {
        type: "geojson",
        data: props.territories ?? EMPTY,
    });
    current.addSource(OHM_SOURCE, {
        type: "vector",
        tiles: [OHM_TILES],
        attribution: OHM_ATTRIBUTION,
        minzoom: BORDERS_MIN_ZOOM,
        maxzoom: OHM_MAX_ZOOM,
    });
    for (const layer of territoryLayers(props.colours)) {
        current.addLayer(layer, WATER_LAYER);
    }
    current.addLayer(
        bordersLayer(props.bordersYear, props.colours, props.borders),
    );
    for (const layer of placeLayers(props.colours)) current.addLayer(layer);
    current.on("click", onClick);
    current.on("mousemove", onMove);
    current.on("mouseout", clearHover);
    current.on("moveend", () => emit("zoom", current.getZoom()));
    current.on("movestart", (event: { originalEvent?: unknown }) => {
        if (shooting && event.originalEvent) userMoved = true;
    });
    ready = true;
    if (drawnColours !== props.colours) recolour(current, props.colours);
    drawnColours = props.colours;
    redrawPipsWhenFontsLoad(current);
    applyStates();
    if (props.isolate) isolateTerritory(current, props.isolate);
    if (props.fit) {
        current.fitBounds(boundsLike(props.fit), {
            padding: FIT_PADDING_PX,
            duration: 0,
        });
    }
    emit("zoom", current.getZoom());
    if (queued) void runSnapshots(current);
}

function placeAt(event: MapMouseEvent): string | null {
    const found = map.value?.queryRenderedFeatures(event.point, {
        layers: [...CLICKABLE_LAYERS],
    });
    const id = found?.[0]?.properties?.id;
    return id ? String(id) : null;
}

function onClick(event: MapMouseEvent): void {
    const id = placeAt(event);
    if (id) emit("select", id);
}

function onMove(event: MapMouseEvent): void {
    const id = placeAt(event);
    if (id !== hovered) setHover(id);
    if (id) {
        emit("hover", { id, x: event.point.x, y: event.point.y });
    }
}

function clearHover(): void {
    if (hovered !== null) setHover(null);
}

function setHover(id: string | null): void {
    const current = map.value;
    if (!current) return;
    if (hovered !== null) {
        current.setFeatureState(
            { source: PLACES_SOURCE, id: hovered },
            { hover: false },
        );
    }
    if (id !== null) {
        current.setFeatureState({ source: PLACES_SOURCE, id }, { hover: true });
    }
    hovered = id;
    current.getCanvas().style.cursor = id ? "pointer" : "";
    if (id === null) emit("hover", null);
}

function zoomIn(): void {
    map.value?.zoomIn({ duration: fitDurationMs() });
}

function zoomOut(): void {
    map.value?.zoomOut({ duration: fitDurationMs() });
}

function wholeMap(): void {
    if (!props.fit) return;
    map.value?.fitBounds(boundsLike(props.fit), {
        padding: FIT_PADDING_PX,
        duration: fitDurationMs(),
    });
}

function retryBase(): void {
    baseFailed.value = false;
    (map.value?.getSource(BASE_SOURCE) as VectorTileSource | undefined)?.setUrl(
        OPENFREEMAP_TILES,
    );
}

/** Brings `lngLat` into view, easing the map there when it is off screen. */
function revealPlace(lngLat: LngLat): void {
    const current = map.value;
    if (!current || !ready) return;
    if (current.getBounds().contains([lngLat[0], lngLat[1]])) return;
    current.easeTo({
        center: [lngLat[0], lngLat[1]],
        duration: fitDurationMs(),
    });
}

/** Eases the map to `zoom` around its centre. */
function zoomTo(zoom: number): void {
    map.value?.easeTo({ zoom, duration: fitDurationMs() });
}

/** The ids of the layers a snapshot leaves out: the places and the territories. */
function ownLayerIds(): string[] {
    return [...territoryLayers(drawnColours), ...placeLayers(drawnColours)].map(
        (layer) => layer.id,
    );
}

function showOwnLayers(current: MapLibreMap, visible: boolean): void {
    for (const id of ownLayerIds()) {
        current.setLayoutProperty(
            id,
            "visibility",
            visible ? "visible" : "none",
        );
    }
}

/**
 * The bare map (paper, water, borders; no place or territory) fitted to
 * `bounds`, as a PNG data URL with the bounds the picture really shows;
 * null when it cannot be read (no map, a tainted or lost canvas, no idle
 * frame in time). One snapshot runs at a time: a request made while one
 * runs replaces the one waiting (that one gets null). The camera is saved
 * once, when a run starts, and put back with the place layers when the
 * last request is done, unless the reader moved the map meanwhile.
 * `cancelSnapshots` drops the waiting request. A request before the map has loaded waits for it.
 */
function snapshot(bounds: Bounds): Promise<MapSnapshot | null> {
    if (failed.value) return Promise.resolve(null);
    return new Promise((resolve) => {
        queued?.resolve(null);
        queued = { bounds, resolve };
        const current = map.value;
        if (current && ready && !shooting) void runSnapshots(current);
    });
}

/** Settles the waiting snapshot request with null. */
function dropQueued(): void {
    queued?.resolve(null);
    queued = null;
}

/** Drops the waiting request; the run in flight ends after its current shot. */
function cancelSnapshots(): void {
    dropQueued();
}

async function runSnapshots(current: MapLibreMap): Promise<void> {
    if (shooting) return;
    shooting = true;
    userMoved = false;
    const camera: JumpToOptions = {
        center: current.getCenter(),
        zoom: current.getZoom(),
        bearing: current.getBearing(),
        pitch: current.getPitch(),
    };
    showOwnLayers(current, false);
    while (queued && map.value === current) {
        const next = queued;
        queued = null;
        next.resolve(await shoot(current, next.bounds));
    }
    if (map.value === current) {
        showOwnLayers(current, true);
        if (!userMoved) current.jumpTo(camera);
    }
    shooting = false;
}

/** Reads the canvas in the frame drawn right after the map settles in `bounds`, so no `preserveDrawingBuffer` is needed. */
function shoot(
    current: MapLibreMap,
    bounds: Bounds,
): Promise<MapSnapshot | null> {
    return new Promise((resolve) => {
        let settled = false;
        const finish = (value: MapSnapshot | null): void => {
            if (settled) return;
            settled = true;
            clearTimeout(timer);
            resolve(value);
        };
        const timer = setTimeout(() => finish(null), SNAPSHOT_TIMEOUT_MS);
        current.once("idle", () => {
            current.once("render", () => {
                try {
                    const shown = current.getBounds();
                    finish({
                        url: current.getCanvas().toDataURL("image/png"),
                        bounds: {
                            west: shown.getWest(),
                            south: shown.getSouth(),
                            east: shown.getEast(),
                            north: shown.getNorth(),
                        },
                    });
                } catch (error: unknown) {
                    console.error("The map snapshot could not be read", error);
                    finish(null);
                }
            });
            current.triggerRepaint();
        });
        current.fitBounds(boundsLike(bounds), { padding: 0, duration: 0 });
    });
}

function resize(): void {
    map.value?.resize();
}
</script>

<template>
    <div
        v-if="failed"
        class="map-stage unavailable"
    >
        <p
            class="no-image"
            role="status"
        >
            <span>{{
                $gettext(
                    "Map unavailable in this browser: the place list and the timeline still work.",
                )
            }}</span>
        </p>
    </div>
    <div
        v-else
        class="map-stage"
    >
        <div
            ref="container"
            class="canvas"
        ></div>
        <div class="controls">
            <button
                type="button"
                class="control"
                :aria-label="$gettext('Zoom in')"
                :title="$gettext('Zoom in')"
                @click="zoomIn"
            >
                <svg
                    viewBox="0 0 16 16"
                    aria-hidden="true"
                >
                    <path d="M8 3v10M3 8h10" />
                </svg>
            </button>
            <button
                type="button"
                class="control"
                :aria-label="$gettext('Zoom out')"
                :title="$gettext('Zoom out')"
                @click="zoomOut"
            >
                <svg
                    viewBox="0 0 16 16"
                    aria-hidden="true"
                >
                    <path d="M3 8h10" />
                </svg>
            </button>
            <button
                v-if="props.fit"
                type="button"
                class="control"
                :aria-label="$gettext('Whole map')"
                :title="$gettext('Whole map')"
                @click="wholeMap"
            >
                <svg
                    viewBox="0 0 16 16"
                    aria-hidden="true"
                >
                    <path d="M2.5 7.5 8 3l5.5 4.5M4 6.5V13h8V6.5" />
                </svg>
            </button>
        </div>
        <p
            v-if="baseFailed"
            class="no-image base-failed"
            role="status"
        >
            <span>{{
                $gettext("Background map unavailable (tile server).")
            }}</span>
            <button
                type="button"
                class="retry"
                @click="retryBase"
            >
                <span>{{ $gettext("Retry") }}</span>
            </button>
        </p>
        <slot></slot>
    </div>
</template>

<style scoped>
.map-stage {
    position: relative;
    display: grid;
    grid-template-rows: minmax(0, 1fr);
    inline-size: 100%;
    block-size: min(70dvh, 40rem);
    min-block-size: 20rem;
    overflow: hidden;
    border-radius: var(--explorer-radius, 0.625rem);
    background: var(--stage);
}

@media (max-width: 48rem) {
    .map-stage {
        block-size: min(70dvh, 28rem);
    }
}

.map-stage .canvas {
    min-block-size: 0;
    background: var(--map-land);
}

.map-stage :deep(.maplibregl-map) {
    font: inherit;
}

.map-stage :deep(.maplibregl-canvas:focus-visible) {
    outline: 0.1875rem solid var(--blue-text);
    outline-offset: -0.1875rem;
}

.map-stage :deep(.maplibregl-ctrl-attrib) {
    border-radius: 0.25rem;
    background: color-mix(in srgb, var(--surface) 85%, transparent);
    color: var(--ink-muted);
    font: 0.6875rem / 1.4 var(--font-body);
}

.map-stage :deep(.maplibregl-ctrl-attrib a) {
    color: var(--blue-text);
}

.map-stage :deep(.maplibregl-ctrl-attrib-button:focus-visible) {
    outline: 0.125rem solid var(--blue-text);
    outline-offset: 0.125rem;
}

/* FolioMap .controls / .control */
.map-stage .controls {
    position: absolute;
    inset-block-start: 0.75rem;
    inset-inline-end: 0.75rem;
    z-index: 2;
    display: grid;
    gap: 0.375rem;
}

.map-stage .control {
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

.map-stage .control:hover {
    border-color: var(--surface);
    background: var(--stage);
}

.map-stage .control:focus-visible {
    outline: 0.125rem solid var(--surface);
    outline-offset: 0.125rem;
}

.map-stage .control svg {
    inline-size: 1rem;
    block-size: 1rem;
    fill: none;
    stroke: currentColor;
    stroke-width: 1.5;
    stroke-linecap: round;
    stroke-linejoin: round;
}

/* FolioMap .no-image / .retry */
.map-stage .no-image {
    position: absolute;
    inset-block-start: 1rem;
    inset-inline: 1rem 3.75rem;
    z-index: 2;
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: 0.5rem 1rem;
    padding: 0.5rem 0.75rem;
    border-radius: 0.25rem;
    background: var(--surface);
    color: var(--ink);
}

.map-stage .retry {
    min-block-size: var(--explorer-target, 2rem);
    padding-inline: 0.75rem;
    border: 0.0625rem solid var(--border-hover);
    border-radius: 999rem;
    background: var(--surface);
    color: var(--ink);
    font: inherit;
    cursor: pointer;
}

.map-stage .retry:focus-visible {
    outline: 0.125rem solid var(--blue-text);
    outline-offset: 0.125rem;
}

.map-stage.unavailable {
    place-items: center;
    block-size: 12rem;
    min-block-size: 0;
    background: var(--stage-soft);
}

.map-stage.unavailable .no-image {
    position: static;
    max-inline-size: min(30rem, 100% - 2rem);
}

@media (forced-colors: active) {
    .map-stage .control {
        border-color: ButtonText;
    }
}
</style>
