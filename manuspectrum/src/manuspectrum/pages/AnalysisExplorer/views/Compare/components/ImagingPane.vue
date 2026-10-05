<script setup lang="ts">
import {
    computed,
    inject,
    onBeforeUnmount,
    onMounted,
    ref,
    useTemplateRef,
    watch,
} from "vue";
import L from "leaflet";
import "leaflet-iiif";
import { useGettext } from "vue3-gettext";

import IconButton from "@/manuspectrum/pages/AnalysisExplorer/components/IconButton.vue";
import FocusPip from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/components/FocusPip.vue";
import PaneFilters from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/components/PaneFilters.vue";
import ScaleBadge from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/components/ScaleBadge.vue";

import { useLinkedMarks } from "@/manuspectrum/pages/AnalysisExplorer/composables/useLinkedMarks.ts";
import { layerImageChain } from "@/manuspectrum/pages/AnalysisExplorer/folio/overlays.ts";
import { layServed } from "@/manuspectrum/pages/AnalysisExplorer/folio/page-layer.ts";
import {
    ANNOUNCE_KEY,
    WINDOW_RESIZE_KEY,
} from "@/manuspectrum/pages/AnalysisExplorer/injection-keys.ts";
import { LAYER_DRAG_TYPE } from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/layer-drag.ts";
import { layerTag } from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/layer-tags.ts";
import { pairsOf } from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/light-table.ts";
import { analysisNode } from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/linked/node-id.ts";
import { filterCss } from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/pane-filters.ts";
import {
    fitZoomOf,
    readView,
    watchPane,
} from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/pane-sync.ts";
import { sameSize } from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/scale-notes.ts";

import type { FileLayer } from "@/manuspectrum/pages/AnalysisExplorer/api/types.ts";
import type { PageLayer } from "@/manuspectrum/pages/AnalysisExplorer/folio/page-layer.ts";
import type { PaneFilters as PaneFiltersValue } from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/light-table.ts";
import type {
    NormalisedView,
    PaneWatcher,
    SyncTarget,
} from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/pane-sync.ts";
import type {
    ScaleNote,
    ServedSize,
} from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/scale-notes.ts";
import type { MapLine } from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/windows.ts";

type Status = "empty" | "loading" | "ready" | "failed";

const MIN_ZOOM = -10;
/** The reader may zoom this far out below the fit of the image. */
const ZOOM_OUT_BELOW_FIT = 2;
const ZOOM_SNAP = 0.25;

/**
 * One pane of the light table: a Leaflet map (`CRS.Simple`) showing one
 * imaging canvas at the size its image service serves, anchored at the
 * origin and never stretched. The page is laid by `layServed`
 * (`folio/page-layer.ts`, which reads the info.json); an image given by URL
 * is read through `layerImageChain`. Moves of the reader are emitted as a
 * normalised view (`pane-sync.ts`) and a `view` of another pane is followed;
 * the pane tells the size it is served at (`size-read`) so the table can
 * say when two panes are not at the same scale. The focus only sets
 * `data-rel` and CSS variables on the pane: nothing is laid or moved.
 */
const props = defineProps<{
    canvas: string | null;
    maps: readonly MapLine[];
    letter: string;
    active: boolean;
    filters: PaneFiltersValue;
    view: NormalisedView | null;
    scaleNote: ScaleNote | null;
}>();

const emit = defineEmits<{
    (event: "view-changed", payload: NormalisedView): void;
    (event: "size-read", payload: { canvas: string; size: ServedSize }): void;
    (event: "place", payload: string): void;
    (event: "step", payload: 1 | -1): void;
    (event: "pair", payload: string): void;
    (event: "activate"): void;
    (event: "filters-change", payload: Partial<PaneFiltersValue>): void;
    (event: "filters-reset"): void;
    (event: "filters-apply-all"): void;
}>();

defineExpose({ leafletMap });

const { $gettext, interpolate } = useGettext();
const announce = inject(ANNOUNCE_KEY, () => undefined);
const resized = inject(WINDOW_RESIZE_KEY, null);
const marks = useLinkedMarks();

const host = useTemplateRef<HTMLDivElement>("host");
const status = ref<Status>("empty");
const filtersOpen = ref(false);
// Leaflet objects live outside Vue reactivity.
let map: L.Map | null = null;
let page: PageLayer | null = null;
let overlay: L.ImageOverlay | null = null;
let served: ServedSize | null = null;
let nativeZoom = 0;
let generation = 0;
let watcher: PaneWatcher | null = null;

const found = computed(() => {
    for (const line of props.maps) {
        const layer = line.file.layers.find(
            (entry) => entry.id === props.canvas,
        );
        if (layer) return { line, layer };
    }
    return null;
});
const record = computed(() =>
    found.value ? analysisNode(found.value.line.analysis.id) : null,
);
const label = computed(() => found.value?.layer.label || props.canvas || "");
const analysisName = computed(() => found.value?.line.analysis.name ?? null);
const tag = computed(() => {
    const parts = found.value ? layerTag(found.value.layer)?.parts : null;
    return parts ? tagText(parts) : "";
});
const neighbours = computed(() => {
    const layers = found.value?.line.file.layers ?? [];
    const index = layers.findIndex((layer) => layer.id === props.canvas);
    return {
        previous: index > 0,
        next: index >= 0 && index < layers.length - 1,
    };
});
const pair = computed(() => {
    const first = props.canvas ? pairsOf(props.canvas, props.maps)[0] : null;
    if (!first) return null;
    const line = props.maps.find((entry) =>
        entry.file.layers.some((layer) => layer.id === first.id),
    );
    const parts = layerTag(first)?.parts;
    return line && parts
        ? {
              canvas: first.id,
              tag: tagText(parts),
              analysis: line.analysis.name,
          }
        : null;
});
const groupLabel = computed(() =>
    found.value
        ? interpolate($gettext("Pane %{letter}: %{label}, %{analysis}"), {
              letter: props.letter,
              label: label.value,
              analysis: analysisName.value?.value ?? "",
          })
        : interpolate($gettext("Pane %{letter}: empty"), {
              letter: props.letter,
          }),
);

watch(() => props.canvas, drawCanvas);
watch(
    () => props.filters,
    () => paintFilters(),
    { deep: true },
);
watch(
    () => props.view,
    (view) => {
        if (view) watcher?.apply(view);
    },
);
watch(
    () => resized?.value,
    () => map?.invalidateSize(),
);

onMounted(() => {
    if (!host.value) return;
    map = L.map(host.value, {
        crs: L.CRS.Simple,
        attributionControl: false,
        zoomControl: false,
        keyboard: true,
        zoomSnap: ZOOM_SNAP,
        minZoom: MIN_ZOOM,
    });
    map.setView([0, 0], 0);
    watcher = watchPane({
        target,
        origin: () => props.canvas ?? "",
        emit: (view) => emit("view-changed", view),
    });
    paintFilters();
    drawCanvas();
});

onBeforeUnmount(() => {
    generation += 1;
    watcher?.destroy();
    clearImage();
    map?.remove();
    map = null;
});

function leafletMap(): L.Map | null {
    return map;
}

function target(): SyncTarget | null {
    return map && served ? { map, size: served, nativeZoom } : null;
}

/** The short text of a layer's tag: « Cu Lα », « 650 nm », « PC3 », « Photo ». */
function tagText(
    parts: NonNullable<ReturnType<typeof layerTag>>["parts"],
): string {
    if (parts.symbols.length) {
        const symbols = parts.symbols.join("+");
        return parts.line ? `${symbols} ${parts.line.value}` : symbols;
    }
    if (parts.band) {
        const range =
            parts.band.value !== null
                ? String(Number(parts.band.value))
                : `${parts.band.lower}–${parts.band.upper}`;
        return parts.unit ? `${range} ${parts.unit}` : range;
    }
    if (parts.index !== null) {
        return interpolate($gettext("PC%{index}"), {
            index: String(parts.index),
        });
    }
    return parts.contentLabel.value;
}

function paintFilters(): void {
    if (!map) return;
    const filter = filterCss(props.filters);
    for (const name of ["tilePane", "overlayPane"]) {
        const element = map.getPane(name);
        if (element) element.style.filter = filter;
    }
}

function clearImage(): void {
    page?.remove();
    page = null;
    overlay?.remove();
    overlay = null;
}

function drawCanvas(): void {
    if (!map) return;
    const previous = target() ? readView(target() as SyncTarget, "") : null;
    clearImage();
    generation += 1;
    served = null;
    const layer = found.value?.layer ?? null;
    if (!layer) {
        status.value = "empty";
        return;
    }
    status.value = "loading";
    const attempt = generation;
    const current = props.canvas as string;
    function loaded(size: ServedSize, zoom: number): void {
        if (attempt !== generation || !map) return;
        served = size;
        nativeZoom = zoom;
        status.value = "ready";
        watcher?.silently(() => {
            if (previous && sameSize(previous.size, size)) return;
            fit();
        });
        emit("size-read", { canvas: current, size });
        if (props.view) watcher?.apply(props.view);
        announce(
            interpolate($gettext("Pane %{letter}: %{label}"), {
                letter: props.letter,
                label: layer?.label || current,
            }),
        );
    }
    function failed(): void {
        if (attempt !== generation) return;
        status.value = "failed";
        announce(
            interpolate(
                $gettext("Pane %{letter}: map unavailable (image server)"),
                {
                    letter: props.letter,
                },
            ),
        );
    }
    if (layer.image.service) layService(layer.image.service, loaded, failed);
    else layUrl(layer, loaded, failed);
}

function layService(
    service: string,
    loaded: (size: ServedSize, zoom: number) => void,
    failed: () => void,
): void {
    if (!map) return;
    page = layServed(map, service, { read: loaded, failed });
}

function layUrl(
    layer: FileLayer,
    loaded: (size: ServedSize, zoom: number) => void,
    failed: () => void,
): void {
    const urls = layerImageChain(layer.image);
    const attempt = generation;
    function next(): void {
        const url = urls.shift();
        if (attempt !== generation) return;
        if (!url) {
            failed();
            return;
        }
        const image = new Image();
        image.onload = () => {
            if (attempt !== generation || !map) return;
            const size = { w: image.naturalWidth, h: image.naturalHeight };
            overlay = L.imageOverlay(
                url,
                L.latLngBounds(
                    map.unproject([0, size.h], 0),
                    map.unproject([size.w, 0], 0),
                ),
            ).addTo(map);
            loaded(size, 0);
        };
        image.onerror = next;
        image.src = url;
    }
    next();
}

/** Fits the whole image in the pane, centred; the pane's own move, never the reader's. */
function fit(): void {
    const current = target();
    const zoom = current ? fitZoomOf(current) : null;
    if (!map || !current || zoom === null) return;
    map.setMinZoom(zoom - ZOOM_OUT_BELOW_FIT);
    map.setView(
        map.unproject([current.size.w / 2, current.size.h / 2], nativeZoom),
        zoom,
        { animate: false },
    );
}

function zoom(direction: 1 | -1): void {
    if (direction === 1) map?.zoomIn();
    else map?.zoomOut();
}

function onFit(): void {
    watcher?.silently(fit);
    emitView();
}

function emitView(): void {
    const current = target();
    const view = current ? readView(current, props.canvas ?? "") : null;
    if (view) emit("view-changed", view);
}

function onKeydown(event: KeyboardEvent): void {
    if (event.key === "[") emit("step", -1);
    else if (event.key === "]") emit("step", 1);
}

function step(direction: 1 | -1): void {
    if (direction === 1 ? neighbours.value.next : neighbours.value.previous) {
        emit("step", direction);
    }
}

function onDrop(event: DragEvent): void {
    const id = event.dataTransfer?.getData(LAYER_DRAG_TYPE) ?? "";
    const known = props.maps.some((line) =>
        line.file.layers.some((layer) => layer.id === id),
    );
    if (known) emit("place", id);
}

function onReset(): void {
    emit("filters-reset");
    announce(
        interpolate($gettext("Pane %{letter}: filters reset"), {
            letter: props.letter,
        }),
    );
}

function onApplyAll(): void {
    emit("filters-apply-all");
    announce(
        interpolate(
            $gettext("Filters of pane %{letter} applied to every pane"),
            {
                letter: props.letter,
            },
        ),
    );
}

function retry(): void {
    drawCanvas();
}
</script>

<template>
    <figure
        class="imaging-pane"
        :data-pane="props.letter.toLowerCase()"
        :data-active="props.active"
        :data-rel="record ? marks.rel(record) : undefined"
        :data-preview="record ? marks.previewRel(record) : undefined"
        :style="record ? marks.rowStyle(record) : undefined"
        @click="emit('activate')"
        @dragover.prevent
        @drop.prevent="onDrop"
    >
        <figcaption class="chip">
            <span class="letter">{{ props.letter }}</span>
            <IconButton
                icon="chevron-left"
                data-action="previous"
                :label="$gettext('Previous layer')"
                :disabled="!neighbours.previous"
                @click="step(-1)"
            />
            <span
                class="label"
                :title="label"
                >{{ label }}</span
            >
            <IconButton
                icon="chevron-right"
                data-action="next"
                :label="$gettext('Next layer')"
                :disabled="!neighbours.next"
                @click="step(1)"
            />
            <span
                v-if="tag"
                class="tag"
                >{{ tag }}</span
            >
            <button
                v-if="record && analysisName"
                type="button"
                class="analysis ms-focus"
                v-bind="marks.focus(record)"
                :title="analysisName.value"
                :lang="analysisName.lang"
                :aria-pressed="marks.pressed(record)"
                @click.stop="marks.toggle(record)"
            >
                <FocusPip :node="record" />
                <span>{{ analysisName.value }}</span>
            </button>
            <IconButton
                icon="sliders-h"
                data-action="filters"
                :aria-expanded="filtersOpen ? 'true' : 'false'"
                :label="$gettext('Filters')"
                :pressed="filtersOpen"
                @click.stop="filtersOpen = !filtersOpen"
            />
        </figcaption>
        <div class="stage">
            <div
                ref="host"
                class="map"
                role="group"
                tabindex="0"
                :aria-label="groupLabel"
                @keydown="onKeydown"
            ></div>
            <p
                v-if="status === 'empty'"
                class="note"
            >
                <span>{{ $gettext("Empty pane") }}</span>
            </p>
            <p
                v-else-if="status === 'failed'"
                class="note"
                role="alert"
            >
                <span>{{ $gettext("Map unavailable (image server)") }}</span>
                <button
                    type="button"
                    data-action="retry"
                    @click.stop="retry"
                >
                    <span>{{ $gettext("Retry") }}</span>
                </button>
            </p>
            <ScaleBadge
                v-if="props.scaleNote"
                class="badge"
                :size="props.scaleNote.size"
                :against="props.scaleNote.againstSize"
            />
            <button
                v-if="pair"
                type="button"
                class="pair"
                data-action="pair"
                @click.stop="emit('pair', pair.canvas)"
            >
                <span>{{
                    interpolate($gettext("%{tag} also in %{analysis} →"), {
                        tag: pair.tag,
                        analysis: pair.analysis.value,
                    })
                }}</span>
            </button>
            <span class="zoom">
                <IconButton
                    icon="search-plus"
                    data-action="zoom-in"
                    :label="$gettext('Zoom in')"
                    @click.stop="zoom(1)"
                />
                <IconButton
                    icon="search-minus"
                    data-action="zoom-out"
                    :label="$gettext('Zoom out')"
                    @click.stop="zoom(-1)"
                />
                <IconButton
                    icon="expand"
                    data-action="fit"
                    :label="$gettext('Fit the whole image')"
                    @click.stop="onFit"
                />
            </span>
        </div>
        <PaneFilters
            v-if="filtersOpen"
            :filters="props.filters"
            :letter="props.letter"
            @change="emit('filters-change', $event)"
            @reset="onReset"
            @apply-all="onApplyAll"
        />
    </figure>
</template>

<style scoped>
.imaging-pane {
    --pane: var(--pane-a);
    display: grid;
    grid-template-rows: auto minmax(0, 1fr) auto;
    min-inline-size: 0;
    min-block-size: 0;
    margin: 0;
    border: 0.125rem solid var(--border);
    border-radius: 0.375rem;
    background: var(--surface);
}

.imaging-pane[data-pane="b"] {
    --pane: var(--pane-b);
}

.imaging-pane[data-pane="c"] {
    --pane: var(--pane-c);
}

.imaging-pane[data-pane="d"] {
    --pane: var(--pane-d);
}

.imaging-pane[data-active="true"] {
    border-color: var(--pane);
}

.imaging-pane:is(
        [data-rel="self"],
        [data-rel="direct"],
        [data-rel="evidence"]
    ) {
    outline: 0.125rem solid var(--h1, var(--focus-1));
    outline-offset: -0.25rem;
}

.imaging-pane[data-rel="none"] .stage {
    opacity: var(--linked-fade, 0.35);
}

.imaging-pane .chip {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: 0.25rem;
    padding: 0.25rem;
    font-size: 0.8125rem;
}

.imaging-pane .chip .letter {
    display: inline-grid;
    place-items: center;
    min-inline-size: 1.5rem;
    block-size: 1.5rem;
    border-radius: 0.375rem;
    background: var(--pane);
    color: var(--surface);
    font-family: var(--font-mono);
    font-weight: 600;
}

.imaging-pane .chip .label {
    overflow: hidden;
    max-inline-size: 12rem;
    font-family: var(--font-mono);
    text-overflow: ellipsis;
    white-space: nowrap;
}

.imaging-pane .chip .tag {
    padding-inline: 0.375rem;
    border: 0.0625rem solid var(--heat-3);
    border-radius: 0.75rem;
    background: var(--heat-1);
    font-weight: 600;
}

.imaging-pane .chip .analysis {
    --r: 0.375rem;
    --link-pip: 0.8125rem;
    display: flex;
    min-inline-size: 0;
    max-inline-size: 12rem;
    padding: 0.25rem 0.375rem;
    border: 0.0625rem solid transparent;
    border-radius: 0.375rem;
    background: none;
    color: var(--ink-muted);
    font: inherit;
    cursor: pointer;
}

.imaging-pane .chip .analysis > span:last-child {
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
}

.imaging-pane .stage {
    position: relative;
    display: grid;
    min-block-size: 12rem;
    background: var(--stage);
}

.imaging-pane .stage .map {
    min-block-size: 0;
    background: var(--stage);
}

.imaging-pane .stage .map:focus-visible {
    outline: 0.125rem solid var(--blue-text);
    outline-offset: -0.125rem;
}

.imaging-pane .stage .note {
    position: absolute;
    inset: 0;
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    justify-content: center;
    gap: 0.5rem;
    margin: 0;
    color: var(--surface);
    font-size: 0.8125rem;
    pointer-events: none;
}

.imaging-pane .stage .note button {
    min-block-size: var(--explorer-target, 2.75rem);
    padding-inline: 0.75rem;
    border: none;
    border-radius: 0.375rem;
    background: var(--bg-alt);
    color: var(--ink);
    font: inherit;
    font-weight: 600;
    cursor: pointer;
    pointer-events: auto;
}

.imaging-pane .stage .badge {
    position: absolute;
    z-index: 500;
    inset-block-start: 0.5rem;
    inset-inline-end: 0.5rem;
}

.imaging-pane .stage .pair {
    position: absolute;
    z-index: 500;
    inset-block-end: 0.5rem;
    inset-inline-start: 0.5rem;
    max-inline-size: 70%;
    min-block-size: 1.75rem;
    padding-inline: 0.625rem;
    border: 0.0625rem solid var(--heat-3);
    border-radius: 0.875rem;
    background: var(--heat-2);
    color: var(--ink);
    font: inherit;
    font-size: 0.75rem;
    font-weight: 600;
    cursor: pointer;
}

.imaging-pane .stage .zoom {
    position: absolute;
    z-index: 500;
    inset-block-end: 0.5rem;
    inset-inline-end: 0.5rem;
    display: flex;
    border-radius: 0.375rem;
    background: var(--surface);
}

.imaging-pane button:focus-visible {
    outline: 0.125rem solid var(--blue-text);
    outline-offset: 0.125rem;
}

@media (prefers-reduced-motion: no-preference) {
    .imaging-pane .stage {
        transition: opacity 0.15s ease-out;
    }
}
</style>
