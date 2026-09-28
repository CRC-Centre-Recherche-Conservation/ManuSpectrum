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
import { useGettext } from "vue3-gettext";
import { stackSmallestOnTop } from "utils/leaflet-stack";

import { laidLayers } from "@/manuspectrum/pages/AnalysisExplorer/folio/laid-layers.ts";
import { layerImageUrl } from "@/manuspectrum/pages/AnalysisExplorer/folio/overlays.ts";
import { layPage } from "@/manuspectrum/pages/AnalysisExplorer/folio/page-layer.ts";
import { WINDOW_RESIZE_KEY } from "@/manuspectrum/pages/AnalysisExplorer/injection-keys.ts";

import type { FileLayer } from "@/manuspectrum/pages/AnalysisExplorer/api/types.ts";
import type { LatLng } from "@/manuspectrum/pages/AnalysisExplorer/folio/geometry.ts";
import type { LaidLayers } from "@/manuspectrum/pages/AnalysisExplorer/folio/laid-layers.ts";
import type { FolioOverlay } from "@/manuspectrum/pages/AnalysisExplorer/folio/overlays.ts";
import type { PageLayer } from "@/manuspectrum/pages/AnalysisExplorer/folio/page-layer.ts";

const MAX_ZOOM = 8;
const ZONE_PADDING = 0.25;

/**
 * The page of one map of the « Chemical imaging » window, framed on the
 * analysis's zone (`bounds`), with `layer` laid over the zone at `opacity`
 * and under a curtain of its own while `underCurtain` (D47), positioned
 * indicatively. A new `attempt` lays the layer again as a new image;
 * `failed` says its image did not load. The map is told to refit when its
 * window is resized (`WINDOW_RESIZE_KEY`).
 */
const props = defineProps<{
    service: string;
    bounds: [LatLng, LatLng];
    layer: FileLayer;
    opacity: number;
    underCurtain: boolean;
    attempt: number;
}>();

const emit = defineEmits<{ (event: "failed"): void }>();

const resizeTick = inject(WINDOW_RESIZE_KEY, ref(0), false);

const { $gettext } = useGettext();
const surface = useTemplateRef<HTMLDivElement>("surface");

const pageFailed = ref(false);

// Leaflet objects live outside Vue reactivity.
let map: L.Map | null = null;
let page: PageLayer | null = null;
let laid: LaidLayers | null = null;

const overlays = computed<FolioOverlay[]>(() => {
    const url = layerImageUrl(props.layer.image);
    if (!url) return [];
    return [
        {
            key: String(props.layer.index),
            url,
            bounds: props.bounds,
            opacity: props.opacity,
            label: props.layer.label,
        },
    ];
});

watch(overlays, drawLayers);
watch(() => props.underCurtain, drawLayers);
watch(
    () => props.attempt,
    () => {
        laid?.forget(overlays.value.map((overlay) => overlay.key));
        drawLayers();
    },
);
watch(resizeTick, () => map?.invalidateSize({ animate: false }));

onMounted(drawMap);
onBeforeUnmount(removeMap);

function drawMap(): void {
    if (!surface.value) return;
    map = L.map(surface.value, {
        crs: L.CRS.Simple,
        attributionControl: false,
        minZoom: 0,
        maxZoom: MAX_ZOOM,
        zoomSnap: 0.25,
    });
    map.fitBounds(L.latLngBounds(props.bounds).pad(ZONE_PADDING), {
        animate: false,
    });
    stackSmallestOnTop(map);
    laid = laidLayers(map, {
        curtainLabel: $gettext("Curtain position"),
        failed: () => emit("failed"),
    });
    drawPage();
    drawLayers();
}

function drawPage(): void {
    if (!map) return;
    page?.remove();
    pageFailed.value = false;
    page = layPage(
        map,
        props.service,
        () => {
            pageFailed.value = true;
        },
        { fitBounds: false },
    );
}

function drawLayers(): void {
    const key = overlays.value[0]?.key ?? null;
    laid?.draw(overlays.value, props.underCurtain ? key : null);
}

function removeMap(): void {
    laid?.remove();
    laid = null;
    page?.remove();
    page = null;
    map?.remove();
    map = null;
}
</script>

<template>
    <div class="chemical-imaging-stage">
        <div
            ref="surface"
            class="surface"
        />
        <p
            v-if="pageFailed"
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
</template>

<style scoped>
.chemical-imaging-stage {
    display: grid;
    gap: 0.5rem;
}

.chemical-imaging-stage .surface {
    min-block-size: 14rem;
    border-radius: var(--explorer-radius, 0.625rem);
    background: var(--stage);
}

.chemical-imaging-stage .unavailable {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: 0.5rem 1rem;
    margin: 0;
    color: var(--ink-muted);
    font-size: 0.8125rem;
}

.chemical-imaging-stage .unavailable button {
    min-block-size: var(--explorer-target, 2.75rem);
    padding-inline: 0.75rem;
    border: 0.0625rem solid var(--border-hover);
    border-radius: 999rem;
    background: var(--surface);
    color: var(--ink);
    font: inherit;
    cursor: pointer;
}

.chemical-imaging-stage .unavailable button:focus-visible {
    outline: 0.125rem solid var(--blue-text);
    outline-offset: 0.125rem;
}
</style>
