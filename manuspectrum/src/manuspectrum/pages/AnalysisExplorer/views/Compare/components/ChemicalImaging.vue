<script setup lang="ts">
import { provide, ref } from "vue";
import { useGettext } from "vue3-gettext";

import ChemicalImagingMap from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/components/ChemicalImagingMap.vue";

import { IMAGING_OVERLAYS_KEY } from "@/manuspectrum/pages/AnalysisExplorer/injection-keys.ts";

import type { Overlay } from "@/manuspectrum/pages/AnalysisExplorer/store/types.ts";
import type { MapLine } from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/windows.ts";

/**
 * The chemical imaging maps of the Selection side by side (§9, D47): a
 * classic viewer per map, each in the document screen's imaging preview,
 * stepping through its own manifest's canvases with its own layer scroll,
 * by the canvas label as stored. No cross-map layer matching: each map
 * keeps its own contrast, its own laid layer and its own curtain; the laid
 * layers live in this window, never on the document screen.
 */
const props = defineProps<{ maps: readonly MapLine[] }>();

const { $gettext } = useGettext();

const overlays = ref<Record<string, Overlay>>({});

provide(IMAGING_OVERLAYS_KEY, { settings: overlays, set: setOverlay });

function setOverlay(key: string, overlay: Overlay | null): void {
    const next = { ...overlays.value };
    if (overlay) next[key] = overlay;
    else delete next[key];
    overlays.value = next;
}
</script>

<template>
    <div class="chemical-imaging">
        <div class="maps">
            <ChemicalImagingMap
                v-for="line in props.maps"
                :key="`${line.key}|${line.slot}|${line.file.id}`"
                :slot-number="line.slot"
                :analysis="line.analysis"
                :file="line.file"
            />
        </div>
        <p class="note">
            <span>{{ $gettext("Each map keeps its own contrast.") }}</span>
        </p>
    </div>
</template>

<style scoped>
.chemical-imaging {
    display: grid;
    gap: 0.75rem;
}

.chemical-imaging .note {
    margin: 0;
    color: var(--ink-muted);
    font-size: 0.8125rem;
}

.chemical-imaging .maps {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(18rem, 1fr));
    gap: 0.75rem;
}

@media (max-width: 48rem) {
    .chemical-imaging .maps {
        grid-template-columns: minmax(0, 1fr);
    }
}
</style>
