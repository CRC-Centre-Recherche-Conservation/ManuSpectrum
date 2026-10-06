<script setup lang="ts">
import {
    computed,
    inject,
    onBeforeUnmount,
    onMounted,
    reactive,
    ref,
    useTemplateRef,
    watch,
} from "vue";
import L from "leaflet";
import "leaflet-iiif";
import "leaflet-side-by-side";
import { useGettext } from "vue3-gettext";

import IconButton from "@/manuspectrum/pages/AnalysisExplorer/components/IconButton.vue";
import FocusPip from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/components/FocusPip.vue";
import PaneFilters from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/components/PaneFilters.vue";
import ScaleBadge from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/components/ScaleBadge.vue";

import { useLinkedMarks } from "@/manuspectrum/pages/AnalysisExplorer/composables/useLinkedMarks.ts";
import { useMapResize } from "@/manuspectrum/pages/AnalysisExplorer/composables/useMapResize.ts";
import { overlayPane } from "@/manuspectrum/pages/AnalysisExplorer/folio/overlays.ts";
import {
    createScaleGroup,
    layImage,
} from "@/manuspectrum/pages/AnalysisExplorer/folio/page-layer.ts";
import { ANNOUNCE_KEY } from "@/manuspectrum/pages/AnalysisExplorer/injection-keys.ts";
import { LAYER_DRAG_TYPE } from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/layer-drag.ts";
import { tagText } from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/layer-tag-text.ts";
import { layerTag } from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/layer-tags.ts";
import { layerById } from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/light-table.ts";
import { analysisNode } from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/linked/node-id.ts";
import { filterCss } from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/pane-filters.ts";
import {
    fitView,
    fitZoomOf,
    keepsFit,
} from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/pane-sync.ts";
import { sameSize } from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/scale-notes.ts";

import type {
    LaidImage,
    ScaleGroup,
} from "@/manuspectrum/pages/AnalysisExplorer/folio/page-layer.ts";
import type { PaneFilters as PaneFiltersValue } from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/light-table.ts";
import type {
    ScaleNote,
    ServedSize,
} from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/scale-notes.ts";
import type { MapLine } from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/windows.ts";

type Status = "empty" | "loading" | "ready" | "failed";
type Side = 0 | 1;

interface SideState {
    /** The name of the side's map pane, once the map exists. */
    pane: string;
    page: LaidImage | null;
    size: ServedSize | null;
    generation: number;
}

const SIDES: readonly Side[] = [0, 1];
const LETTERS = ["A", "B"] as const;
const MIN_ZOOM = -10;
const ZOOM_SNAP = 0.25;
const SIDE_B: Side = 1;

/**
 * The curtain of the light table: one Leaflet map (`CRS.Simple`) holding
 * two layers, side A on the left and side B on the right of the divider of
 * Arches' `L.control.sideBySide`. The two canvases may come from any two
 * analyses; each is laid by `layImage` in a pane of its own (so each side
 * has its own CSS filter), anchored at the origin, as a leaflet-iiif layer
 * at the size its image service serves, or, without a service, as an image
 * overlay at the natural size of its URL; the layer answers `getContainer()`
 * with its pane so the divider clips it. The two sides share one pixel
 * scale (`createScaleGroup`): an image pixel is the same size on screen
 * on both sides, so two canvases of different sizes are drawn at their
 * different sizes, never stretched to each other. The pane tells the size
 * each side is served at (`size-read`); `scaleNote` is the note of side B
 * (the table computes it with `scaleNotes`) and shows the badge on that
 * side, announced once per change of the sizes it names. The focus only sets
 * `data-rel` on the chips: nothing is laid or moved.
 */
const props = defineProps<{
    canvasA: string | null;
    canvasB: string | null;
    maps: readonly MapLine[];
    filtersA: PaneFiltersValue;
    filtersB: PaneFiltersValue;
    scaleNote: ScaleNote | null;
}>();

const emit = defineEmits<{
    (event: "size-read", payload: { canvas: string; size: ServedSize }): void;
    (event: "place", payload: { pane: Side; canvas: string }): void;
    (event: "activate", payload: Side): void;
    (
        event: "filters-change",
        payload: { pane: Side; filters: Partial<PaneFiltersValue> },
    ): void;
    (event: "filters-reset", payload: Side): void;
    (event: "filters-apply-all", payload: Side): void;
}>();

defineExpose({ leafletMap });

const { $gettext, interpolate } = useGettext();
const announce = inject(ANNOUNCE_KEY, () => undefined);
const marks = useLinkedMarks();

const host = useTemplateRef<HTMLDivElement>("host");
const status = ref<Status[]>(["empty", "empty"]);
const filtersOpen = reactive<boolean[]>([false, false]);
// Leaflet objects live outside Vue reactivity.
let map: L.Map | null = null;
let curtain: L.SideBySide | null = null;
let fitted: ServedSize | null = null;
let scale: ScaleGroup | null = null;
const sides: SideState[] = SIDES.map(() => ({
    pane: "",
    page: null,
    size: null,
    generation: 0,
}));

const canvases = computed(() => [props.canvasA, props.canvasB]);
const filters = computed(() => [props.filtersA, props.filtersB]);
const views = computed(() =>
    SIDES.map((side) => {
        const canvas = canvases.value[side];
        const found = canvas ? layerById(canvas, props.maps) : null;
        const parts = found ? layerTag(found.layer)?.parts : null;
        return {
            side,
            letter: LETTERS[side],
            canvas,
            label: found?.layer.label || canvas || "",
            tag: parts ? tagText(parts, { $gettext, interpolate }) : "",
            analysis: found?.line.analysis.name ?? null,
            record: found ? analysisNode(found.line.analysis.id) : null,
            status: status.value[side],
        };
    }),
);
const groupLabel = computed(() =>
    interpolate(
        $gettext("Curtain: %{a} | %{b}"),
        {
            a: `A ${views.value[0].label || $gettext("empty")}`,
            b: `B ${views.value[1].label || $gettext("empty")}`,
        },
        true,
    ),
);

watch(
    () => props.canvasA,
    () => drawSide(0),
);
watch(
    () => props.canvasB,
    () => drawSide(1),
);
watch(
    () => [props.filtersA, props.filtersB],
    () => paintFilters(),
    { deep: true },
);
/** What the badge says, as one primitive: a note rebuilt with the same canvas and sizes is not news. */
const noteKey = computed(() => {
    const note = props.scaleNote;
    return note
        ? `${note.canvas}|${note.size.w}x${note.size.h}|${note.againstSize.w}x${note.againstSize.h}`
        : null;
});

watch(
    noteKey,
    (key) => {
        const note = props.scaleNote;
        if (!key || !note) return;
        announce(
            interpolate(
                $gettext(
                    "Curtain: side B is not at the same scale as side A (%{size} against %{against})",
                ),
                {
                    size: `${note.size.w} × ${note.size.h} px`,
                    against: `${note.againstSize.w} × ${note.againstSize.h} px`,
                },
                true,
            ),
        );
    },
    { immediate: true },
);
useMapResize({
    host,
    map: () => map,
    keepsFit: () => {
        const state = reference();
        return (
            !map ||
            !state?.size ||
            keepsFit({
                map,
                size: state.size,
                nativeZoom: scale?.zoom() ?? 0,
            })
        );
    },
    refit: fit,
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
    for (const side of SIDES) {
        sides[side].pane = overlayPane(
            map,
            `curtain-${LETTERS[side].toLowerCase()}`,
        );
    }
    scale = createScaleGroup(() => refit());
    curtain = L.control.sideBySide([], []).addTo(map);
    (curtain as L.SideBySide & { _range?: HTMLElement })._range?.setAttribute(
        "aria-label",
        $gettext("Curtain position"),
    );
    paintFilters();
    for (const side of SIDES) drawSide(side);
});

onBeforeUnmount(() => {
    scale = null;
    for (const side of sides) {
        side.generation += 1;
        side.page?.remove();
        side.page = null;
    }
    curtain?.remove();
    curtain = null;
    map?.remove();
    map = null;
});

function leafletMap(): L.Map | null {
    return map;
}

function paintFilters(): void {
    if (!map) return;
    for (const side of SIDES) {
        const element = map.getPane(sides[side].pane);
        if (element) element.style.filter = filterCss(filters.value[side]);
    }
}

function setLayer(side: Side, layer: L.Layer | null): void {
    if (side === 0) curtain?.setLeftLayers(layer ?? []);
    else curtain?.setRightLayers(layer ?? []);
}

function drawSide(side: Side): void {
    if (!map) return;
    const state = sides[side];
    state.size = null;
    state.page?.remove();
    state.page = null;
    state.generation += 1;
    setLayer(side, null);
    const canvas = canvases.value[side];
    const layer = canvas ? layerById(canvas, props.maps)?.layer : null;
    if (!canvas || !layer) {
        status.value[side] = "empty";
        return;
    }
    status.value[side] = "loading";
    const attempt = state.generation;
    state.page = layImage(
        map,
        layer.image,
        {
            read: (size, _zoom, laidLayer) => {
                if (attempt !== state.generation || !map) return;
                state.size = size;
                setLayer(side, laidLayer);
                status.value[side] = "ready";
                fitOnce();
                emit("size-read", { canvas, size });
                announce(
                    interpolate(
                        $gettext("Curtain, side %{letter}: %{label}"),
                        {
                            letter: LETTERS[side],
                            label: layer.label || canvas,
                        },
                        true,
                    ),
                );
            },
            failed: () => {
                if (attempt !== state.generation) return;
                status.value[side] = "failed";
                announce(
                    interpolate(
                        $gettext(
                            "Curtain, side %{letter}: map unavailable (image server)",
                        ),
                        { letter: LETTERS[side] },
                        true,
                    ),
                );
            },
        },
        { pane: state.pane, scale: scale ?? undefined, curtain: true },
    );
}

/** The side the view is fitted on: A, else B. */
function reference(): SideState | null {
    return [sides[0], sides[1]].find((state) => state.size) ?? null;
}

/** Fits the first image read, and again only when the reference side is served at another size. */
function fitOnce(): void {
    const state = reference();
    if (!state?.size) return;
    if (fitted && sameSize(fitted, state.size)) return;
    fitted = state.size;
    fit();
}

function fit(): void {
    const state = reference();
    if (!map || !state?.size) return;
    const target = {
        map,
        size: state.size,
        nativeZoom: scale?.zoom() ?? 0,
    };
    const zoom = fitZoomOf(target);
    if (zoom !== null) fitView(target, zoom);
}

/** The common pixel scale moved (a layer joined or left): the picture is a different size, so it is fitted again. */
function refit(): void {
    if (!scale) return;
    fitted = null;
    fitOnce();
}

function zoom(direction: 1 | -1): void {
    if (direction === 1) map?.zoomIn();
    else map?.zoomOut();
}

function retry(side: Side): void {
    drawSide(side);
}

function dividerX(): number {
    const position = curtain?.getPosition();
    if (typeof position === "number") return position;
    return (host.value?.clientWidth ?? 0) / 2;
}

function onDrop(event: DragEvent): void {
    const id = event.dataTransfer?.getData(LAYER_DRAG_TYPE) ?? "";
    if (!id || !layerById(id, props.maps)) return;
    const left = host.value?.getBoundingClientRect().left ?? 0;
    const side: Side = event.clientX - left < dividerX() ? 0 : SIDE_B;
    emit("place", { pane: side, canvas: id });
}

function onReset(side: Side): void {
    emit("filters-reset", side);
    announce(
        interpolate(
            $gettext("Curtain, side %{letter}: filters reset"),
            {
                letter: LETTERS[side],
            },
            true,
        ),
    );
}

function onApplyAll(side: Side): void {
    emit("filters-apply-all", side);
    announce(
        interpolate(
            $gettext("Filters of side %{letter} applied to every pane"),
            { letter: LETTERS[side] },
            true,
        ),
    );
}
</script>

<template>
    <figure
        class="curtain-pane"
        @dragover.prevent
        @drop.prevent="onDrop"
    >
        <figcaption class="chips">
            <span
                v-for="view in views"
                :key="view.side"
                class="chip"
                :data-pane="view.letter.toLowerCase()"
                @click="emit('activate', view.side)"
            >
                <span class="letter">{{ view.letter }}</span>
                <span
                    v-if="view.canvas"
                    class="label"
                    :title="view.label"
                    >{{ view.label }}</span
                >
                <span
                    v-else
                    class="label"
                    >{{ $gettext("empty") }}</span
                >
                <span
                    v-if="view.tag"
                    class="tag"
                    >{{ view.tag }}</span
                >
                <button
                    v-if="view.record && view.analysis"
                    type="button"
                    class="analysis ms-focus"
                    v-bind="marks.focus(view.record)"
                    :title="view.analysis.value"
                    :lang="view.analysis.lang"
                    :aria-pressed="marks.pressed(view.record)"
                    @click.stop="marks.toggle(view.record)"
                >
                    <FocusPip :node="view.record" />
                    <span>{{ view.analysis.value }}</span>
                </button>
                <IconButton
                    icon="sliders-h"
                    data-action="filters"
                    :aria-expanded="filtersOpen[view.side] ? 'true' : 'false'"
                    :label="
                        interpolate(
                            $gettext('Filters of side %{letter}'),
                            {
                                letter: view.letter,
                            },
                            true,
                        )
                    "
                    :pressed="filtersOpen[view.side]"
                    @click.stop="
                        filtersOpen[view.side] = !filtersOpen[view.side]
                    "
                />
            </span>
        </figcaption>
        <div class="stage">
            <div
                ref="host"
                class="map"
                role="group"
                tabindex="0"
                :aria-label="groupLabel"
            ></div>
            <p
                v-for="view in views.filter(
                    (entry) => entry.status === 'empty',
                )"
                :key="`empty-${view.side}`"
                class="note"
                :data-side="view.letter.toLowerCase()"
            >
                <span>{{
                    interpolate(
                        $gettext("Side %{letter} is empty"),
                        {
                            letter: view.letter,
                        },
                        true,
                    )
                }}</span>
            </p>
            <p
                v-for="view in views.filter(
                    (entry) => entry.status === 'failed',
                )"
                :key="`failed-${view.side}`"
                class="note"
                role="alert"
                :data-side="view.letter.toLowerCase()"
            >
                <span>{{ $gettext("Map unavailable (image server)") }}</span>
                <button
                    type="button"
                    :data-action="`retry-${view.letter.toLowerCase()}`"
                    @click.stop="retry(view.side)"
                >
                    <span>{{
                        interpolate(
                            $gettext("Retry side %{letter}"),
                            {
                                letter: view.letter,
                            },
                            true,
                        )
                    }}</span>
                </button>
            </p>
            <ScaleBadge
                v-if="props.scaleNote"
                class="badge badge-b"
                :size="props.scaleNote.size"
                :against="props.scaleNote.againstSize"
            />
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
                    @click.stop="fit"
                />
            </span>
        </div>
        <template
            v-for="view in views"
            :key="`filters-${view.side}`"
        >
            <PaneFilters
                v-if="filtersOpen[view.side]"
                :filters="filters[view.side]"
                :letter="view.letter"
                @change="
                    emit('filters-change', {
                        pane: view.side,
                        filters: $event,
                    })
                "
                @reset="onReset(view.side)"
                @apply-all="onApplyAll(view.side)"
            />
        </template>
    </figure>
</template>

<style scoped>
.curtain-pane {
    display: grid;
    grid-template-rows: auto minmax(0, 1fr) auto;
    min-inline-size: 0;
    min-block-size: 0;
    margin: 0;
    border: 0.125rem solid var(--border);
    border-radius: 0.375rem;
    background: var(--surface);
}

.curtain-pane .chips {
    display: flex;
    flex-wrap: wrap;
    justify-content: space-between;
    gap: 0.25rem;
    padding: 0.25rem;
    font-size: 0.8125rem;
}

.curtain-pane .chip {
    --pane: var(--pane-a);
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: 0.25rem;
    min-inline-size: 0;
}

.curtain-pane .chip[data-pane="b"] {
    --pane: var(--pane-b);
}

.curtain-pane .chip .letter {
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

.curtain-pane .chip .label {
    overflow: hidden;
    max-inline-size: 12rem;
    font-family: var(--font-mono);
    text-overflow: ellipsis;
    white-space: nowrap;
}

.curtain-pane .chip .tag {
    padding-inline: 0.375rem;
    border: 0.0625rem solid var(--heat-3);
    border-radius: 0.75rem;
    background: var(--heat-1);
    font-weight: 600;
}

.curtain-pane .chip .analysis {
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

.curtain-pane .chip .analysis > span:last-child {
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
}

.curtain-pane
    .chip
    .analysis:is(
        [data-rel="self"],
        [data-rel="direct"],
        [data-rel="evidence"]
    ) {
    outline: 0.125rem solid var(--h1, var(--focus-1));
    outline-offset: 0.0625rem;
}

.curtain-pane .stage {
    position: relative;
    display: grid;
    min-block-size: 6rem;
    background: var(--stage);
}

.curtain-pane .stage .map {
    min-block-size: 0;
    background: var(--stage);
}

.curtain-pane .stage .map:focus-visible {
    outline: 0.125rem solid var(--blue-text);
    outline-offset: -0.125rem;
}

.curtain-pane .stage .note {
    position: absolute;
    inset-block-start: 50%;
    inset-inline: 0;
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

.curtain-pane .stage .note[data-side="a"] {
    inset-inline-end: 50%;
}

.curtain-pane .stage .note[data-side="b"] {
    inset-inline-start: 50%;
}

.curtain-pane .stage .note button {
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

.curtain-pane .stage .badge {
    position: absolute;
    z-index: 1000;
    inset-block-start: 0.5rem;
}

.curtain-pane .stage .badge-b {
    inset-inline-end: 0.5rem;
}

.curtain-pane .stage .zoom {
    position: absolute;
    z-index: 1000;
    inset-block-end: 0.5rem;
    inset-inline-end: 0.5rem;
    display: flex;
    border-radius: 0.375rem;
    background: var(--surface);
}

.curtain-pane button:focus-visible {
    outline: 0.125rem solid var(--blue-text);
    outline-offset: 0.125rem;
}
</style>
