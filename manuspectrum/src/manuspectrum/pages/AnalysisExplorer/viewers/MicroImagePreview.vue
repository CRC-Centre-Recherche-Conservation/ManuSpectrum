<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref, useTemplateRef } from "vue";
import L from "leaflet";
import { useGettext } from "vue3-gettext";

import type {
    AnalysisPayload,
    FileEntry,
} from "@/manuspectrum/pages/AnalysisExplorer/api/types.ts";

const MIN_ZOOM = -5;
const ZOOM_SNAP = 0.25;

const props = defineProps<{ file: FileEntry; analysis: AnalysisPayload }>();

const { $gettext } = useGettext();
const surface = useTemplateRef<HTMLDivElement>("surface");

const failed = ref(false);
// The Leaflet map lives outside Vue reactivity.
let map: L.Map | null = null;
let probe: HTMLImageElement | null = null;

onMounted(() => {
    probe = new Image();
    probe.addEventListener("load", onProbeLoad);
    probe.addEventListener("error", onProbeError);
    probe.src = props.file.downloadUrl;
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
        zoomSnap: ZOOM_SNAP,
    });
    L.imageOverlay(props.file.downloadUrl, bounds, {
        className: "micro-image",
        alt: props.file.name,
    }).addTo(map);
    map.fitBounds(bounds, { animate: false });
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
            class="download"
            download=""
            :href="props.file.downloadUrl"
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
    min-block-size: 2.75rem;
    color: var(--blue-text);
}

.micro-image-preview .state {
    color: var(--ink-muted);
}
</style>
