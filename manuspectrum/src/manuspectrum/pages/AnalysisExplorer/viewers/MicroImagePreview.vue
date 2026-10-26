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

import { safeHref } from "@/manuspectrum/pages/AnalysisExplorer/format.ts";
import { WINDOW_RESIZE_KEY } from "@/manuspectrum/pages/AnalysisExplorer/injection-keys.ts";

import type {
    AnalysisHit,
    AnalysisPayload,
    FileEntry,
} from "@/manuspectrum/pages/AnalysisExplorer/api/types.ts";

const MIN_ZOOM = -5;
const ZOOM_DELTA = 0.5;

/**
 * One micro-image, zoomable. It reads the file only: the analysis card passes
 * its record as every preview gets it, Compare shows a Selection file without
 * one. The whole image fills its well at first (no zoom snap); inside a
 * Compare window it follows the window's size, and fits the whole image
 * again after a resize until the reader zooms or drags it.
 */
const props = defineProps<{
    file: FileEntry;
    analysis?: AnalysisPayload | AnalysisHit;
}>();

const windowResize = inject(WINDOW_RESIZE_KEY, null);

const { $gettext } = useGettext();
const surface = useTemplateRef<HTMLDivElement>("surface");

const failed = ref(false);

const href = computed(() => safeHref(props.file.downloadUrl));
// The Leaflet map lives outside Vue reactivity.
let map: L.Map | null = null;
let probe: HTMLImageElement | null = null;
let imageBounds: L.LatLngBounds | null = null;
/** Whether the view is still the fitted one: the reader has not zoomed or dragged. */
let fitted = true;
let fitting = false;

watch(
    () => windowResize?.value,
    () => {
        map?.invalidateSize();
        if (fitted) fitImage();
    },
);

onMounted(() => {
    if (!href.value) {
        failed.value = true;
        return;
    }
    probe = new Image();
    probe.addEventListener("load", onProbeLoad);
    probe.addEventListener("error", onProbeError);
    probe.src = href.value;
});

onBeforeUnmount(() => {
    probe?.removeEventListener("load", onProbeLoad);
    probe?.removeEventListener("error", onProbeError);
    probe = null;
    map?.remove();
    map = null;
});

function onProbeLoad(): void {
    if (probe) show(probe.naturalWidth, probe.naturalHeight);
}

function onProbeError(): void {
    failed.value = true;
}

/** Opens the image in a zoomable view at its natural size; no scale bar, the metadata carry no pixel size. */
function show(width: number, height: number): void {
    if (!surface.value || map) return;
    const bounds = L.latLngBounds([0, 0], [height, width]);
    map = L.map(surface.value, {
        crs: L.CRS.Simple,
        attributionControl: false,
        minZoom: MIN_ZOOM,
        zoomSnap: 0,
        zoomDelta: ZOOM_DELTA,
    });
    L.imageOverlay(href.value!, bounds, {
        className: "micro-image",
        alt: props.file.name,
    }).addTo(map);
    imageBounds = bounds;
    map.on("zoomstart dragstart", onReaderMove);
    fitImage();
}

function fitImage(): void {
    if (!map || !imageBounds) return;
    fitting = true;
    map.fitBounds(imageBounds, { animate: false });
    fitting = false;
}

function onReaderMove(): void {
    if (!fitting) fitted = false;
}
</script>

<template>
    <section class="micro-image-preview">
        <p
            v-if="failed"
            class="state"
        >
            <span>{{ $gettext("This image cannot be shown here.") }}</span>
        </p>
        <div
            v-else
            ref="surface"
            class="surface"
        ></div>
        <a
            v-if="href"
            class="download"
            download=""
            :href="href"
        >
            <span>{{ $gettext("Download the image") }}</span>
        </a>
    </section>
</template>

<style scoped>
.micro-image-preview {
    display: grid;
    gap: 0.5rem;
}

.micro-image-preview .surface {
    min-block-size: 16rem;
    background: var(--stage);
}

.micro-image-preview .download {
    display: inline-flex;
    align-items: center;
    min-block-size: var(--explorer-target, 2.75rem);
    color: var(--blue-text);
}

.micro-image-preview .state {
    color: var(--ink-muted);
}
</style>
