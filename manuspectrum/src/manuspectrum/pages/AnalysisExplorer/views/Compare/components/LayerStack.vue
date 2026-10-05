<script setup lang="ts">
import {
    computed,
    inject,
    onBeforeUnmount,
    onMounted,
    reactive,
    ref,
    useId,
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
import { overlayPane } from "@/manuspectrum/pages/AnalysisExplorer/folio/overlays.ts";
import { layServed } from "@/manuspectrum/pages/AnalysisExplorer/folio/page-layer.ts";
import {
    ANNOUNCE_KEY,
    WINDOW_RESIZE_KEY,
} from "@/manuspectrum/pages/AnalysisExplorer/injection-keys.ts";
import { LAYER_DRAG_TYPE } from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/layer-drag.ts";
import { canStack } from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/light-table.ts";
import { analysisNode } from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/linked/node-id.ts";
import { filterCss } from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/pane-filters.ts";
import { fitZoomOf } from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/pane-sync.ts";
import {
    applyAppearance,
    stackAppearances,
    tintMatrix,
} from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/stack-panes.ts";
import {
    NO_TINT,
    TINT_CHOICES,
    tintFor,
} from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/stack-tints.ts";

import type { FileLayer } from "@/manuspectrum/pages/AnalysisExplorer/api/types.ts";
import type { PageLayer } from "@/manuspectrum/pages/AnalysisExplorer/folio/page-layer.ts";
import type {
    PaneFilters as PaneFiltersValue,
    StackLayer,
} from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/light-table.ts";
import type {
    ScaleNote,
    ServedSize,
} from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/scale-notes.ts";
import type { Tint } from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/stack-tints.ts";
import type { MapLine } from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/windows.ts";

type Status = "loading" | "ready" | "failed";

interface Laid {
    page: PageLayer | null;
    pane: string;
    size: ServedSize | null;
    nativeZoom: number;
    generation: number;
}

const MIN_ZOOM = -10;
/** The reader may zoom this far out below the fit of the image. */
const ZOOM_OUT_BELOW_FIT = 2;
const ZOOM_SNAP = 0.25;
const BLINK_MS = 700;
const OPACITY_STEP = 5;
const REDUCED_MOTION = "(prefers-reduced-motion: reduce)";

/**
 * The false-colour stack of the light table, for the layers of one
 * analysis: one Leaflet map (`CRS.Simple`) holding one leaflet-iiif layer
 * per layer of the stack, each laid by `layServed` in a pane of its own at
 * the size its service serves, anchored at the origin and never stretched
 * or fitted to another (`folio/laid-layers.ts` is not used). The panes
 * carry opacity, `mix-blend-mode: screen` (but the first layer shown), the
 * stack's CSS filter and the hue, an SVG `feColorMatrix` per hue
 * (`stack-panes.ts`, `stack-tints.ts`); the map is isolated so `screen`
 * blends the layers among themselves. The stack itself belongs to the
 * table: this component only emits what the reader does (`add`, `remove`,
 * `move`, `set-visible`, `set-opacity`, `set-tint`). `notes` are the
 * scale notes of the stack (`scaleNotes`), by canvas. The focus only sets
 * `data-rel` and CSS variables: nothing is laid or moved.
 */
const props = defineProps<{
    stack: { analysis: string | null; layers: readonly StackLayer[] };
    maps: readonly MapLine[];
    filters: PaneFiltersValue;
    notes: ReadonlyMap<string, ScaleNote>;
}>();

const emit = defineEmits<{
    (event: "add", payload: string): void;
    (event: "remove", payload: string): void;
    (event: "move", payload: { canvas: string; step: 1 | -1 }): void;
    (event: "set-visible", payload: { canvas: string; on: boolean }): void;
    (event: "set-opacity", payload: { canvas: string; opacity: number }): void;
    (event: "set-tint", payload: { canvas: string; tint: string | null }): void;
    (event: "size-read", payload: { canvas: string; size: ServedSize }): void;
    (event: "filters-change", payload: Partial<PaneFiltersValue>): void;
    (event: "filters-reset"): void;
    (event: "filters-apply-all"): void;
}>();

defineExpose({ leafletMap });

const { $gettext, interpolate } = useGettext();
const announce = inject(ANNOUNCE_KEY, () => undefined);
const resized = inject(WINDOW_RESIZE_KEY, null);
const marks = useLinkedMarks();
const prefix = useId();

const host = useTemplateRef<HTMLDivElement>("host");
const statuses = reactive<Record<string, Status>>({});
const filtersOpen = ref(false);
const paletteFor = ref<string | null>(null);
const blinking = ref<string | null>(null);
const blinkedOff = ref(false);
const reducedMotion = ref(false);
// Leaflet objects live outside Vue reactivity.
let map: L.Map | null = null;
let fitted = false;
let blinkTimer: number | null = null;
let motionQuery: MediaQueryList | null = null;
const laid = new Map<string, Laid>();

const record = computed(() =>
    props.stack.analysis ? analysisNode(props.stack.analysis) : null,
);
const rows = computed(() =>
    props.stack.layers.map((layer, rank) => {
        const found = fileLayerOf(layer.canvas);
        const tint = tintFor(layer, rank, found);
        return {
            layer,
            rank,
            label: found?.label || layer.canvas,
            tint,
            note: props.notes.get(layer.canvas) ?? null,
            status: statuses[layer.canvas] as Status | undefined,
        };
    }),
);
const filterTints = computed(() => {
    const unique = new Map<string, Tint>();
    for (const row of rows.value) {
        if (row.tint) unique.set(row.tint.key, row.tint);
    }
    return [...unique.values()];
});
const tintNames = computed<Record<string, string>>(() => ({
    "rank-1": $gettext("Blue"),
    "rank-2": $gettext("Pink"),
    "rank-3": $gettext("Green"),
    "rank-4": $gettext("Amber"),
    "rank-5": $gettext("Purple"),
    "rank-6": $gettext("Red"),
    "rank-7": $gettext("Teal"),
    "rank-8": $gettext("Orange"),
    "rank-9": $gettext("Lime"),
    "rank-10": $gettext("Sky"),
    "rank-11": $gettext("Magenta"),
    "rank-12": $gettext("Cream"),
}));
const groupLabel = computed(() =>
    interpolate($gettext("Stack of %{count} layers"), {
        count: String(props.stack.layers.length),
    }),
);

watch(() => props.stack, sync, { deep: true });
watch(() => props.filters, paint, { deep: true });
watch(
    () => props.maps,
    () => paint(),
);
watch(
    () => resized?.value,
    () => map?.invalidateSize(),
);

onMounted(() => {
    motionQuery = window.matchMedia?.(REDUCED_MOTION) ?? null;
    reducedMotion.value = motionQuery?.matches ?? false;
    motionQuery?.addEventListener?.("change", onMotionChange);
    if (!host.value) return;
    map = L.map(host.value, {
        crs: L.CRS.Simple,
        attributionControl: false,
        zoomControl: false,
        keyboard: true,
        zoomSnap: ZOOM_SNAP,
        minZoom: MIN_ZOOM,
    });
    map.getContainer().style.setProperty("isolation", "isolate");
    map.setView([0, 0], 0);
    sync();
});

onBeforeUnmount(() => {
    stopBlink();
    motionQuery?.removeEventListener?.("change", onMotionChange);
    for (const entry of laid.values()) {
        entry.generation += 1;
        entry.page?.remove();
    }
    laid.clear();
    map?.remove();
    map = null;
});

function leafletMap(): L.Map | null {
    return map;
}

function fileLayerOf(canvas: string): FileLayer | null {
    for (const line of props.maps) {
        const layer = line.file.layers.find((entry) => entry.id === canvas);
        if (layer) return layer;
    }
    return null;
}

function onMotionChange(event: MediaQueryListEvent): void {
    reducedMotion.value = event.matches;
    if (event.matches) stopBlink();
}

/** Lays the layers that are on and not yet laid, takes off those that left the stack, then paints. */
function sync(): void {
    if (!map) return;
    const wanted = new Set(props.stack.layers.map((layer) => layer.canvas));
    for (const [canvas, entry] of laid) {
        if (wanted.has(canvas)) continue;
        entry.generation += 1;
        entry.page?.remove();
        laid.delete(canvas);
        delete statuses[canvas];
    }
    if (blinking.value && !wanted.has(blinking.value)) stopBlink();
    if (paletteFor.value && !wanted.has(paletteFor.value)) {
        paletteFor.value = null;
    }
    for (const layer of props.stack.layers) {
        if (layer.on && !laid.has(layer.canvas)) lay(layer.canvas);
    }
    if (laid.size === 0) fitted = false;
    paint();
}

function lay(canvas: string): void {
    if (!map) return;
    const found = fileLayerOf(canvas);
    const entry: Laid = {
        page: null,
        pane: overlayPane(map, `stack-${canvas}`),
        size: null,
        nativeZoom: 0,
        generation: 0,
    };
    laid.set(canvas, entry);
    const service = found?.image.service;
    if (!found || !service) {
        statuses[canvas] = "failed";
        return;
    }
    statuses[canvas] = "loading";
    entry.page = layServed(
        map,
        service,
        {
            read: (size, zoom) => {
                if (laid.get(canvas) !== entry || !map) return;
                entry.size = size;
                entry.nativeZoom = zoom;
                statuses[canvas] = "ready";
                if (!fitted) fitOn(entry);
                emit("size-read", { canvas, size });
                announce(
                    interpolate($gettext("Stack: %{label}"), {
                        label: found.label || canvas,
                    }),
                );
            },
            failed: () => {
                if (laid.get(canvas) !== entry) return;
                statuses[canvas] = "failed";
            },
        },
        { pane: entry.pane },
    );
}

/** Fits the first layer read, centred; later layers keep the reader's view. */
function fitOn(entry: Laid): void {
    if (!map || !entry.size) return;
    const zoom = fitZoomOf({
        map,
        size: entry.size,
        nativeZoom: entry.nativeZoom,
    });
    if (zoom === null) return;
    fitted = true;
    map.setMinZoom(zoom - ZOOM_OUT_BELOW_FIT);
    map.setView(
        map.unproject([entry.size.w / 2, entry.size.h / 2], entry.nativeZoom),
        zoom,
        { animate: false },
    );
}

function tintFilterId(tint: Tint): string {
    return `${prefix}-${tint.key}`;
}

/** Writes opacity, blend, order, filter and visibility on every laid pane; lays and moves nothing. */
function paint(): void {
    if (!map) return;
    const tints = new Map(
        rows.value.map((row) => [row.layer.canvas, row.tint] as const),
    );
    const appearances = stackAppearances(props.stack.layers, {
        filter: filterCss(props.filters),
        tintId: (canvas) => {
            const tint = tints.get(canvas);
            return tint ? tintFilterId(tint) : null;
        },
        blinkedOff: blinkedOff.value ? blinking.value : null,
    });
    for (const [canvas, appearance] of appearances) {
        const pane = laid.get(canvas)?.pane;
        const element = pane ? map.getPane(pane) : undefined;
        if (element) applyAppearance(element, appearance);
    }
}

function zoom(direction: 1 | -1): void {
    if (direction === 1) map?.zoomIn();
    else map?.zoomOut();
}

function onFit(): void {
    const first = props.stack.layers.find(
        (layer) => layer.on && laid.get(layer.canvas)?.size,
    );
    const entry = first ? laid.get(first.canvas) : null;
    if (entry) fitOn(entry);
}

function onDrop(event: DragEvent): void {
    const canvas = event.dataTransfer?.getData(LAYER_DRAG_TYPE) ?? "";
    const found = canvas ? fileLayerOf(canvas) : null;
    if (!found) return;
    if (props.stack.layers.some((layer) => layer.canvas === canvas)) return;
    if (!canStack(props, canvas, props.maps)) {
        announce(
            interpolate(
                $gettext(
                    "A stack holds the layers of one analysis: %{label} is not added",
                ),
                { label: found.label || canvas },
            ),
        );
        return;
    }
    emit("add", canvas);
}

function onOpacity(canvas: string, event: Event): void {
    const value = Number((event.target as HTMLInputElement).value);
    if (Number.isFinite(value)) emit("set-opacity", { canvas, opacity: value });
}

function chooseTint(canvas: string, tint: string | null): void {
    emit("set-tint", { canvas, tint });
    paletteFor.value = null;
}

function togglePalette(canvas: string): void {
    paletteFor.value = paletteFor.value === canvas ? null : canvas;
}

function toggleBlink(canvas: string, label: string): void {
    if (blinking.value === canvas) {
        stopBlink();
        return;
    }
    stopBlink();
    blinking.value = canvas;
    blinkedOff.value = false;
    blinkTimer = window.setInterval(() => {
        blinkedOff.value = !blinkedOff.value;
        paint();
    }, BLINK_MS);
    announce(
        interpolate($gettext("Blinking %{label}: Escape stops"), { label }),
    );
}

function stopBlink(): void {
    if (blinkTimer !== null) window.clearInterval(blinkTimer);
    blinkTimer = null;
    const wasBlinking = blinking.value !== null;
    blinking.value = null;
    blinkedOff.value = false;
    if (wasBlinking) paint();
}

function onReset(): void {
    emit("filters-reset");
    announce($gettext("Stack: filters reset"));
}

function onApplyAll(): void {
    emit("filters-apply-all");
    announce($gettext("Filters of the stack applied to every pane"));
}

function tintLabel(tint: Tint | null): string {
    return tint ? tintNames.value[tint.key] ?? tint.key : $gettext("No tint");
}
</script>

<template>
    <figure
        class="layer-stack"
        :data-rel="record ? marks.rel(record) : undefined"
        :data-preview="record ? marks.previewRel(record) : undefined"
        :style="record ? marks.rowStyle(record) : undefined"
        @dragover.prevent
        @drop.prevent="onDrop"
        @keydown.esc="stopBlink"
    >
        <svg
            class="tint-filters"
            width="0"
            height="0"
            aria-hidden="true"
            focusable="false"
        >
            <defs>
                <filter
                    v-for="tint in filterTints"
                    :id="tintFilterId(tint)"
                    :key="tint.key"
                    color-interpolation-filters="sRGB"
                >
                    <feColorMatrix
                        type="matrix"
                        :values="tintMatrix(tint.rgb)"
                    />
                </filter>
            </defs>
        </svg>
        <div class="stage">
            <div
                ref="host"
                class="map"
                role="group"
                tabindex="0"
                :aria-label="groupLabel"
            ></div>
            <p
                v-if="rows.length === 0"
                class="note"
            >
                <span>{{
                    $gettext(
                        "The stack is empty: click a canvas of the gallery to add it.",
                    )
                }}</span>
            </p>
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
        <section
            class="panel"
            :aria-label="$gettext('Layers')"
        >
            <header class="bar">
                <h4 class="title">
                    <span>{{ $gettext("Layers") }}</span>
                </h4>
                <button
                    v-if="record"
                    type="button"
                    class="ms-focus"
                    v-bind="marks.focus(record)"
                    :aria-pressed="marks.pressed(record)"
                    @click.stop="marks.toggle(record)"
                >
                    <FocusPip :node="record" />
                    <span>{{ $gettext("Analysis") }}</span>
                </button>
                <IconButton
                    icon="sliders-h"
                    data-action="filters"
                    :aria-expanded="filtersOpen ? 'true' : 'false'"
                    :label="$gettext('Filters')"
                    :pressed="filtersOpen"
                    @click.stop="filtersOpen = !filtersOpen"
                />
            </header>
            <PaneFilters
                v-if="filtersOpen"
                :filters="props.filters"
                :letter="$gettext('stack')"
                @change="emit('filters-change', $event)"
                @reset="onReset"
                @apply-all="onApplyAll"
            />
            <ol class="layers">
                <li
                    v-for="row in rows"
                    :key="row.layer.canvas"
                    :data-canvas="row.layer.canvas"
                    :data-on="row.layer.on"
                >
                    <button
                        type="button"
                        data-action="tint"
                        :aria-expanded="
                            paletteFor === row.layer.canvas ? 'true' : 'false'
                        "
                        :aria-label="
                            interpolate($gettext('Tint of %{label}: %{tint}'), {
                                label: row.label,
                                tint: tintLabel(row.tint),
                            })
                        "
                        @click.stop="togglePalette(row.layer.canvas)"
                    >
                        <span
                            class="swatch"
                            :class="{ none: !row.tint }"
                            :style="
                                row.tint
                                    ? { background: `var(${row.tint.token})` }
                                    : undefined
                            "
                        ></span>
                    </button>
                    <span
                        class="label"
                        :title="row.label"
                        >{{ row.label }}</span
                    >
                    <ScaleBadge
                        v-if="row.note"
                        :size="row.note.size"
                        :against="row.note.againstSize"
                    />
                    <span
                        v-if="row.status === 'failed'"
                        class="failed"
                        role="alert"
                        >{{ $gettext("Map unavailable (image server)") }}</span
                    >
                    <input
                        type="range"
                        min="0"
                        max="100"
                        :step="OPACITY_STEP"
                        :value="row.layer.opacity"
                        :aria-label="
                            interpolate($gettext('Opacity of %{label}'), {
                                label: row.label,
                            })
                        "
                        @input="onOpacity(row.layer.canvas, $event)"
                    />
                    <span class="actions">
                        <IconButton
                            icon="chevron-up"
                            data-action="up"
                            :label="
                                interpolate($gettext('Move %{label} up'), {
                                    label: row.label,
                                })
                            "
                            :disabled="row.rank === 0"
                            @click="
                                emit('move', {
                                    canvas: row.layer.canvas,
                                    step: -1,
                                })
                            "
                        />
                        <IconButton
                            icon="chevron-down"
                            data-action="down"
                            :label="
                                interpolate($gettext('Move %{label} down'), {
                                    label: row.label,
                                })
                            "
                            :disabled="row.rank === rows.length - 1"
                            @click="
                                emit('move', {
                                    canvas: row.layer.canvas,
                                    step: 1,
                                })
                            "
                        />
                        <IconButton
                            :icon="row.layer.on ? 'eye' : 'eye-slash'"
                            data-action="visible"
                            :label="
                                interpolate(
                                    row.layer.on
                                        ? $gettext('Hide %{label}')
                                        : $gettext('Show %{label}'),
                                    { label: row.label },
                                )
                            "
                            @click="
                                emit('set-visible', {
                                    canvas: row.layer.canvas,
                                    on: !row.layer.on,
                                })
                            "
                        />
                        <IconButton
                            v-if="!reducedMotion"
                            icon="bolt"
                            data-action="blink"
                            :label="
                                interpolate($gettext('Blink %{label}'), {
                                    label: row.label,
                                })
                            "
                            :pressed="blinking === row.layer.canvas"
                            @click="toggleBlink(row.layer.canvas, row.label)"
                        />
                        <IconButton
                            icon="times"
                            data-action="remove"
                            :label="
                                interpolate(
                                    $gettext('Take %{label} out of the stack'),
                                    { label: row.label },
                                )
                            "
                            @click="emit('remove', row.layer.canvas)"
                        />
                    </span>
                    <div
                        v-if="paletteFor === row.layer.canvas"
                        class="palette"
                        role="group"
                        :aria-label="$gettext('Tint')"
                    >
                        <button
                            type="button"
                            data-tint="default"
                            :aria-pressed="row.layer.tint === null"
                            @click.stop="chooseTint(row.layer.canvas, null)"
                        >
                            <span>{{ $gettext("Default") }}</span>
                        </button>
                        <button
                            type="button"
                            data-tint="none"
                            :aria-pressed="row.layer.tint === NO_TINT"
                            @click.stop="chooseTint(row.layer.canvas, NO_TINT)"
                        >
                            <span>{{ $gettext("No tint") }}</span>
                        </button>
                        <button
                            v-for="choice in TINT_CHOICES"
                            :key="choice.key"
                            type="button"
                            class="choice"
                            :data-tint="choice.key"
                            :aria-pressed="row.layer.tint === choice.key"
                            :aria-label="tintLabel(choice)"
                            :title="tintLabel(choice)"
                            @click.stop="
                                chooseTint(row.layer.canvas, choice.key)
                            "
                        >
                            <span
                                class="swatch"
                                :style="{ background: `var(${choice.token})` }"
                            ></span>
                        </button>
                    </div>
                </li>
            </ol>
            <p
                v-if="props.notes.size > 0"
                class="scale-sentence"
            >
                <span>{{
                    $gettext(
                        "The layers are not all at the same scale: they are laid at the origin, not registered.",
                    )
                }}</span>
            </p>
        </section>
    </figure>
</template>

<style scoped>
.layer-stack {
    display: grid;
    grid-template-columns: minmax(0, 1fr) 16rem;
    min-inline-size: 0;
    min-block-size: 0;
    margin: 0;
    border: 0.125rem solid var(--border);
    border-radius: 0.375rem;
    background: var(--surface);
}

.layer-stack:is([data-rel="self"], [data-rel="direct"], [data-rel="evidence"]) {
    outline: 0.125rem solid var(--h1, var(--focus-1));
    outline-offset: -0.25rem;
}

.layer-stack[data-rel="none"] .stage {
    opacity: var(--linked-fade, 0.35);
}

.layer-stack .tint-filters {
    position: absolute;
    inline-size: 0;
    block-size: 0;
}

.layer-stack .stage {
    position: relative;
    display: grid;
    min-block-size: 12rem;
    background: var(--stage);
}

.layer-stack .stage .map {
    min-block-size: 0;
    background: var(--stage);
}

.layer-stack .stage .map:focus-visible {
    outline: 0.125rem solid var(--blue-text);
    outline-offset: -0.125rem;
}

.layer-stack .stage .note {
    position: absolute;
    inset: 0;
    display: flex;
    align-items: center;
    justify-content: center;
    margin: 0;
    padding: 1rem;
    color: var(--surface);
    font-size: 0.8125rem;
    text-align: center;
    pointer-events: none;
}

.layer-stack .stage .zoom {
    position: absolute;
    z-index: 1000;
    inset-block-end: 0.5rem;
    inset-inline-end: 0.5rem;
    display: flex;
    border-radius: 0.375rem;
    background: var(--surface);
}

.layer-stack .panel {
    display: flex;
    flex-direction: column;
    gap: 0.5rem;
    min-inline-size: 0;
    padding: 0.5rem;
    overflow-y: auto;
    font-size: 0.8125rem;
}

.layer-stack .panel .bar {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 0.25rem;
}

.layer-stack .panel .bar .title {
    margin: 0;
    font-size: 0.875rem;
}

.layer-stack .layers {
    display: flex;
    flex-direction: column;
    gap: 0.5rem;
    margin: 0;
    padding: 0;
    list-style: none;
}

.layer-stack .layers li {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: 0.25rem;
    padding-block-end: 0.5rem;
    border-block-end: 0.0625rem solid var(--border);
}

.layer-stack .layers li[data-on="false"] .label {
    color: var(--ink-muted);
    text-decoration: line-through;
}

.layer-stack .layers .label {
    flex: 1 1 6rem;
    overflow: hidden;
    font-family: var(--font-mono);
    text-overflow: ellipsis;
    white-space: nowrap;
}

.layer-stack .layers .failed {
    flex-basis: 100%;
    color: var(--ink-muted);
}

.layer-stack .layers input[type="range"] {
    flex: 1 1 100%;
    min-inline-size: 0;
}

.layer-stack .layers .actions {
    display: flex;
    flex-wrap: wrap;
}

.layer-stack .layers .swatch {
    display: block;
    inline-size: 1.25rem;
    block-size: 1.25rem;
    border: 0.0625rem solid var(--border);
    border-radius: 50%;
}

.layer-stack .layers .swatch.none {
    background: repeating-linear-gradient(
        45deg,
        var(--bg-alt),
        var(--bg-alt) 0.125rem,
        var(--surface) 0.125rem,
        var(--surface) 0.25rem
    );
}

.layer-stack .layers [data-action="tint"] {
    display: grid;
    place-items: center;
    min-inline-size: var(--explorer-target, 2.75rem);
    min-block-size: var(--explorer-target, 2.75rem);
    padding: 0;
    border: none;
    background: none;
    cursor: pointer;
}

.layer-stack .layers .palette {
    display: flex;
    flex-basis: 100%;
    flex-wrap: wrap;
    gap: 0.25rem;
}

.layer-stack .layers .palette button {
    display: grid;
    place-items: center;
    min-inline-size: var(--explorer-target, 2.75rem);
    min-block-size: var(--explorer-target, 2.75rem);
    padding-inline: 0.5rem;
    border: 0.0625rem solid var(--border);
    border-radius: 0.375rem;
    background: var(--surface);
    color: var(--ink);
    font: inherit;
    cursor: pointer;
}

.layer-stack .layers .palette button[aria-pressed="true"] {
    border-color: var(--blue-text);
    outline: 0.125rem solid var(--blue-text);
}

.layer-stack .scale-sentence {
    margin: 0;
    padding: 0.5rem;
    border: 0.0625rem solid var(--heat-3);
    border-radius: 0.375rem;
    background: var(--heat-1);
}

.layer-stack button:focus-visible {
    outline: 0.125rem solid var(--blue-text);
    outline-offset: 0.125rem;
}

@media (width < 48rem) {
    .layer-stack {
        grid-template-columns: minmax(0, 1fr);
    }
}

@media (prefers-reduced-motion: no-preference) {
    .layer-stack .stage {
        transition: opacity 0.15s ease-out;
    }
}
</style>
