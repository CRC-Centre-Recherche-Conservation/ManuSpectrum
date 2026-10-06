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

import { sameText } from "@/manuspectrum/pages/AnalysisExplorer/format.ts";
import { useLinkedMarks } from "@/manuspectrum/pages/AnalysisExplorer/composables/useLinkedMarks.ts";
import { useMapResize } from "@/manuspectrum/pages/AnalysisExplorer/composables/useMapResize.ts";
import { layImage } from "@/manuspectrum/pages/AnalysisExplorer/folio/page-layer.ts";
import { ANNOUNCE_KEY } from "@/manuspectrum/pages/AnalysisExplorer/injection-keys.ts";
import { LAYER_DRAG_TYPE } from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/layer-drag.ts";
import { shortAnalysisName } from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/analysis-short-name.ts";
import { tagText } from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/layer-tag-text.ts";
import { layerTag } from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/layer-tags.ts";
import {
    layerById,
    pairsOf,
} from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/light-table.ts";
import { analysisNode } from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/linked/node-id.ts";
import { filterCss } from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/pane-filters.ts";
import {
    fitView,
    fitZoomOf,
    keepsFit,
    readView,
    watchPane,
} from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/pane-sync.ts";
import { sameSize } from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/scale-notes.ts";

import type { LaidImage } from "@/manuspectrum/pages/AnalysisExplorer/folio/page-layer.ts";
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
const ZOOM_SNAP = 0.25;

/**
 * One pane of the light table: a Leaflet map (`CRS.Simple`) showing one
 * imaging canvas at the size its image service serves, anchored at the
 * origin and never stretched. The image is laid by `layImage`
 * (`folio/page-layer.ts`): through its IIIF service, whose info.json gives
 * the size, else through its URL (`layerImageChain`) at its natural size.
 * Moves of the reader are emitted as a normalised view (`pane-sync.ts`) and a
 * `view` of another pane is followed; the pane tells the size it is served at (`size-read`) so the table can
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
const marks = useLinkedMarks();

const host = useTemplateRef<HTMLDivElement>("host");
const status = ref<Status>("empty");
const filtersOpen = ref(false);
// Leaflet objects live outside Vue reactivity.
let map: L.Map | null = null;
let page: LaidImage | null = null;
let served: ServedSize | null = null;
let nativeZoom = 0;
let generation = 0;
let watcher: PaneWatcher | null = null;

const found = computed(() =>
    props.canvas ? layerById(props.canvas, props.maps) : null,
);
const record = computed(() =>
    found.value ? analysisNode(found.value.line.analysis.id) : null,
);
const label = computed(() => found.value?.layer.label || props.canvas || "");
const analysisName = computed(() => found.value?.line.analysis.name ?? null);
const analysisShort = computed(() =>
    analysisName.value ? shortAnalysisName(analysisName.value.value) : "",
);
const rightSide = computed(() =>
    ["b", "d"].includes(props.letter.toLowerCase()),
);
const tag = computed(() => {
    const parts = found.value ? layerTag(found.value.layer)?.parts : null;
    if (!parts) return "";
    const text = tagText(parts, { $gettext, interpolate });
    return sameText(text, label.value) ? "" : text;
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
              tag: tagText(parts, { $gettext, interpolate }),
              analysis: line.analysis.name,
              short: shortAnalysisName(line.analysis.name.value),
          }
        : null;
});
const pairLabel = computed(() =>
    pair.value
        ? interpolate(
              $gettext("%{tag} also in %{analysis} →"),
              { tag: pair.value.tag, analysis: pair.value.short },
              true,
          )
        : "",
);
const pairTitle = computed(() =>
    pair.value
        ? interpolate(
              $gettext("%{tag} also in %{analysis} →"),
              { tag: pair.value.tag, analysis: pair.value.analysis.value },
              true,
          )
        : "",
);
const groupLabel = computed(() =>
    found.value
        ? interpolate(
              $gettext("Pane %{letter}: %{label}, %{analysis}"),
              {
                  letter: props.letter,
                  label: label.value,
                  analysis: analysisName.value?.value ?? "",
              },
              true,
          )
        : interpolate(
              $gettext("Pane %{letter}: empty"),
              {
                  letter: props.letter,
              },
              true,
          ),
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
useMapResize({
    host,
    map: () => map,
    keepsFit: () => {
        const current = target();
        return !current || keepsFit(current);
    },
    refit: () => watcher?.silently(fit),
});

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
            interpolate(
                $gettext("Pane %{letter}: %{label}"),
                {
                    letter: props.letter,
                    label: layer?.label || current,
                },
                true,
            ),
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
                true,
            ),
        );
    }
    page = layImage(
        map,
        layer.image,
        { read: loaded, failed },
        { tileFormat: "png" },
    );
}

/** Fits the whole image in the pane, centred; the pane's own move, never the reader's. */
function fit(): void {
    const current = target();
    const zoom = current ? fitZoomOf(current) : null;
    if (!map || !current || zoom === null) return;
    fitView(current, zoom);
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
        interpolate(
            $gettext("Pane %{letter}: filters reset"),
            {
                letter: props.letter,
            },
            true,
        ),
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
            true,
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
        </div>
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
                :aria-label="analysisName.value"
                :aria-pressed="marks.pressed(record)"
                @click.stop="marks.toggle(record)"
            >
                <FocusPip :node="record" />
                <span>{{ analysisShort }}</span>
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
        <div class="corner">
            <ScaleBadge
                v-if="props.scaleNote"
                class="badge"
                placement="above"
                align="start"
                :size="props.scaleNote.size"
                :against="props.scaleNote.againstSize"
            />
            <button
                v-if="pair"
                type="button"
                class="pair"
                data-action="pair"
                :title="pairTitle"
                @click.stop="emit('pair', pair.canvas)"
            >
                <span class="text">{{ pairLabel }}</span>
                <span
                    class="glyph"
                    aria-hidden="true"
                    >→</span
                >
            </button>
        </div>
        <span class="zoom">
            <IconButton
                icon="plus"
                data-action="zoom-in"
                :label="$gettext('Zoom in')"
                @click.stop="zoom(1)"
            />
            <IconButton
                icon="minus"
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
        <PaneFilters
            v-if="filtersOpen"
            class="popover"
            :class="{ 'is-end': rightSide }"
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
    position: relative;
    display: grid;
    grid-template-rows: minmax(0, 1fr);
    min-inline-size: 0;
    min-block-size: 0;
    margin: 0;
    border-radius: 0.375rem;
    background: var(--stage);
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

.imaging-pane::after {
    position: absolute;
    z-index: 900;
    inset: 0;
    border-radius: inherit;
    content: "";
    pointer-events: none;
}

.imaging-pane[data-active="true"]::after {
    box-shadow: inset 0 0 0 0.125rem var(--pane);
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
    position: absolute;
    z-index: 1000;
    inset-block-start: 0.5rem;
    inset-inline-start: 0.5rem;
    display: flex;
    flex-wrap: nowrap;
    align-items: center;
    gap: 0.125rem;
    min-inline-size: 0;
    max-inline-size: 85%;
    padding: 0.1875rem 0.25rem;
    border: 0.0625rem solid color-mix(in srgb, var(--surface) 12%, transparent);
    border-radius: 999rem;
    background: color-mix(in srgb, var(--ink) 82%, transparent);
    backdrop-filter: blur(0.25rem);
    box-shadow: 0 0.125rem 0.5rem rgb(0 0 0 / 30%);
    color: var(--surface);
    font-size: 0.75rem;
}

.imaging-pane .chip .letter {
    display: inline-grid;
    flex: none;
    place-items: center;
    inline-size: 1.25rem;
    block-size: 1.25rem;
    margin-inline-end: 0.125rem;
    border-radius: 999rem;
    background: var(--pane);
    color: var(--surface);
    font: 600 0.6875rem var(--font-mono);
}

.imaging-pane .chip :deep(.icon-button-control) {
    min-inline-size: 1.5rem;
    min-block-size: 1.5rem;
    border-radius: 999rem;
    color: var(--surface);
}

.imaging-pane .chip :deep(.icon-button-control:hover) {
    background: color-mix(in srgb, var(--surface) 18%, transparent);
    color: var(--surface);
}

.imaging-pane .chip :deep(.icon-button-control[aria-pressed="true"]) {
    border-color: transparent;
    background: color-mix(in srgb, var(--surface) 24%, transparent);
    color: var(--surface);
}

.imaging-pane .chip :deep(.icon-button-control[aria-disabled="true"]) {
    background: transparent;
    color: color-mix(in srgb, var(--surface) 35%, transparent);
}

.imaging-pane .chip :deep(.icon) {
    inline-size: 0.875rem;
    block-size: 0.875rem;
}

.imaging-pane .chip .label {
    flex: 0 1 auto;
    overflow: hidden;
    min-inline-size: 1.5rem;
    max-inline-size: 11rem;
    padding-inline: 0.125rem;
    font: 500 0.78125rem var(--font-mono);
    text-overflow: ellipsis;
    white-space: nowrap;
}

.imaging-pane .chip .tag {
    flex: none;
    padding: 0.0625rem 0.3125rem;
    border-radius: 0.25rem;
    background: color-mix(in srgb, var(--surface) 20%, transparent);
    color: var(--surface);
    font: 500 0.625rem var(--font-mono);
    white-space: nowrap;
}

.imaging-pane .chip .analysis {
    --r: 999rem;
    --link-pip: 0.8125rem;
    display: flex;
    flex: 0 1 auto;
    align-items: center;
    min-inline-size: 2rem;
    max-inline-size: 8rem;
    padding: 0.125rem 0.375rem;
    border: 0.0625rem solid transparent;
    border-radius: 999rem;
    background: none;
    color: color-mix(in srgb, var(--surface) 70%, transparent);
    font: inherit;
    font-size: 0.71875rem;
    cursor: pointer;
}

.imaging-pane .chip .analysis[data-rel="none"] {
    background: none !important;
    color: color-mix(in srgb, var(--surface) 55%, transparent) !important;
}

.imaging-pane .chip .analysis:hover {
    color: var(--surface);
}

.imaging-pane .chip .analysis > span:last-child {
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
}

.imaging-pane .stage {
    display: grid;
    min-block-size: 6rem;
    border-radius: inherit;
    background: var(--stage);
}

.imaging-pane .stage .map {
    min-block-size: 0;
    border-radius: inherit;
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
    color: color-mix(in srgb, var(--surface) 70%, transparent);
    font-size: 0.8125rem;
    pointer-events: none;
}

.imaging-pane .stage .note button {
    min-block-size: var(--explorer-target, 2rem);
    padding-inline: 0.75rem;
    border: none;
    border-radius: 0.375rem;
    background: var(--surface);
    color: var(--ink);
    font: inherit;
    font-weight: 600;
    cursor: pointer;
    pointer-events: auto;
}

.imaging-pane .corner {
    position: absolute;
    z-index: 1000;
    inset-block-end: 0.5rem;
    inset-inline-start: 0.5rem;
    display: flex;
    flex-direction: column;
    align-items: flex-start;
    gap: 0.25rem;
    max-inline-size: 70%;
    pointer-events: none;
}

.imaging-pane .corner > * {
    pointer-events: auto;
}

.imaging-pane .corner .pair {
    max-inline-size: 100%;
    min-block-size: 1.625rem;
    padding-inline: 0.625rem;
    border: none;
    border-radius: 999rem;
    background: var(--accent-text);
    box-shadow: 0 0.125rem 0.5rem rgb(0 0 0 / 30%);
    color: var(--surface);
    font: inherit;
    font-size: 0.71875rem;
    font-weight: 500;
    cursor: pointer;
}

.imaging-pane .corner .pair:hover {
    background: var(--accent-link-hover);
}

.imaging-pane .corner .pair > span {
    display: block;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
}

.imaging-pane .zoom {
    position: absolute;
    z-index: 1000;
    inset-block-end: 0.5rem;
    inset-inline-end: 0.5rem;
    display: flex;
    flex-direction: column;
    gap: 0.125rem;
}

.imaging-pane .zoom :deep(.icon-button-control) {
    min-inline-size: 1.75rem;
    min-block-size: 1.75rem;
    border: 0.0625rem solid var(--border-hover);
    border-radius: 0.375rem;
    background: var(--surface);
    box-shadow: 0 0.0625rem 0.25rem rgb(0 0 0 / 30%);
    color: var(--ink);
}

.imaging-pane .zoom :deep(.icon-button-control:hover) {
    background: var(--bg-alt);
}

.imaging-pane .zoom :deep(.icon) {
    inline-size: 0.9375rem;
    block-size: 0.9375rem;
}

.imaging-pane .popover {
    position: absolute;
    z-index: 1100;
    inset-block-start: 2.75rem;
    inset-inline-start: 0.5rem;
    inline-size: 15.5rem;
    max-inline-size: 90%;
    box-shadow: 0 0.5rem 1.5rem rgb(0 0 0 / 35%);
}

.imaging-pane .popover.is-end {
    inset-inline: auto 0.5rem;
}

.imaging-pane button:focus-visible {
    outline: 0.125rem solid var(--blue-text);
    outline-offset: 0.125rem;
}

@media (max-width: 48rem) {
    .imaging-pane .popover,
    .imaging-pane .popover.is-end {
        position: fixed;
        inset: auto 0 0;
        inline-size: auto;
        max-inline-size: none;
    }
}

@media (prefers-reduced-motion: no-preference) {
    .imaging-pane .stage {
        transition: opacity 0.15s ease-out;
    }
}

.imaging-pane {
    container-type: size;
}

.imaging-pane .corner .pair .glyph {
    display: none;
}

@container (max-height: 14rem) or (max-width: 18rem) {
    .imaging-pane .zoom {
        opacity: 0;
    }

    .imaging-pane .chip .analysis > span:last-child {
        display: none;
    }

    .imaging-pane .chip .analysis {
        min-inline-size: 0;
    }

    .imaging-pane .corner .pair {
        min-inline-size: 1.625rem;
        padding-inline: 0.375rem;
    }

    .imaging-pane .corner .pair .glyph {
        display: block;
    }

    .imaging-pane .corner .pair .text,
    .imaging-pane .corner :deep(.scale-badge-chip > span:last-child) {
        position: absolute;
        overflow: hidden;
        inline-size: 0.0625rem;
        block-size: 0.0625rem;
        clip-path: inset(50%);
        white-space: nowrap;
    }

    .imaging-pane .corner :deep(.scale-badge-chip) {
        padding-inline: 0.3125rem;
    }
}

.imaging-pane:hover .zoom,
.imaging-pane:focus-within .zoom {
    opacity: 1;
}

@media (max-width: 48rem) {
    .imaging-pane {
        container-type: normal;
    }
}

@media (prefers-reduced-motion: no-preference) {
    .imaging-pane .zoom {
        transition: opacity 0.15s ease-out;
    }
}
</style>
