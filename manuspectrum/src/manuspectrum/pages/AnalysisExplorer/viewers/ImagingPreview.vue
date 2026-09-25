<script setup lang="ts">
import { computed, inject, ref } from "vue";
import { useGettext } from "vue3-gettext";

import Slider from "primevue/slider";

import AddToSelection from "@/manuspectrum/pages/AnalysisExplorer/views/Corpus/document/AddToSelection.vue";

import {
    layerImageUrl,
    overlayKey,
} from "@/manuspectrum/pages/AnalysisExplorer/folio/overlays.ts";
import {
    CURTAIN_KEY,
    FOLIO_ZONES_KEY,
} from "@/manuspectrum/pages/AnalysisExplorer/injection-keys.ts";
import { layerKey } from "@/manuspectrum/pages/AnalysisExplorer/selection/entries.ts";
import { useExplorerStore } from "@/manuspectrum/pages/AnalysisExplorer/store/explorer.ts";

import type {
    AnalysisPayload,
    FileEntry,
    FileLayer,
} from "@/manuspectrum/pages/AnalysisExplorer/api/types.ts";

const DEFAULT_OPACITY = 0.7;
const PREVIEW_SIZE = 480;
const PERCENT = 100;
const OPACITY_STEP = 5;

const props = defineProps<{ file: FileEntry; analysis: AnalysisPayload }>();

const curtain = inject(CURTAIN_KEY, ref<string | null>(null));
const zones = inject(FOLIO_ZONES_KEY, ref<ReadonlySet<string>>(new Set()));

const store = useExplorerStore();
const { $gettext, interpolate } = useGettext();
const percentFormat = new Intl.NumberFormat(
    document.documentElement.lang || "en",
    { style: "percent" },
);

/** Opens on the layer of this file laid on the page, if any. */
const position = ref(
    Math.max(
        0,
        props.file.layers.findIndex(
            (entry) =>
                store.overlays[overlayKey(props.analysis.id, entry.index)]?.on,
        ),
    ),
);

const layer = computed<FileLayer | null>(
    () => props.file.layers[position.value] ?? null,
);
const key = computed(() =>
    layer.value ? overlayKey(props.analysis.id, layer.value.index) : "",
);
const setting = computed(() =>
    key.value ? store.overlays[key.value] : undefined,
);
const laid = computed(() => Boolean(setting.value?.on));
const opacity = computed(() => setting.value?.opacity ?? DEFAULT_OPACITY);
const opacityPercent = computed(() => Math.round(opacity.value * PERCENT));
const opacityText = computed(() => percentFormat.format(opacity.value));
const canLay = computed(() => zones.value.has(props.analysis.id));
const underCurtain = computed(
    () => key.value !== "" && curtain.value === key.value,
);
const imageUrl = computed(() =>
    layer.value ? layerImageUrl(layer.value.image, PREVIEW_SIZE) : null,
);
const scrollLabel = computed(() =>
    layer.value
        ? interpolate(
              $gettext("Layers, in order: %{label}"),
              { label: layer.value.label },
              true,
          )
        : $gettext("Layers, in order"),
);

function kindLabel(entry: FileLayer): string {
    switch (entry.kind) {
        case "element":
            return $gettext("Element");
        case "band":
            return $gettext("Band");
        default:
            return $gettext("Layer");
    }
}

function firstValue(value: number | number[]): number {
    return Array.isArray(value) ? value[0] : value;
}

function lay(on: boolean): void {
    if (!layer.value) return;
    store.setOverlay(key.value, {
        element: layer.value.label,
        opacity: opacity.value,
        on,
    });
    if (!on && curtain.value === key.value) curtain.value = null;
}

function onLayChange(event: Event): void {
    lay((event.target as HTMLInputElement).checked);
}

function setOpacity(value: number | number[]): void {
    if (!layer.value) return;
    store.setOverlay(key.value, {
        element: layer.value.label,
        opacity: firstValue(value) / PERCENT,
        on: laid.value,
    });
}

/** Moving the layer scroll carries the laid map, its opacity and the curtain to the new layer. */
function moveTo(value: number | number[]): void {
    const wasLaid = laid.value;
    const wasUnderCurtain = underCurtain.value;
    const keptOpacity = opacity.value;
    if (wasLaid) lay(false);
    position.value = firstValue(value);
    if (wasLaid && layer.value) {
        store.setOverlay(key.value, {
            element: layer.value.label,
            opacity: keptOpacity,
            on: true,
        });
        if (wasUnderCurtain) curtain.value = key.value;
    }
}

function onCurtainChange(event: Event): void {
    curtain.value = (event.target as HTMLInputElement).checked
        ? key.value
        : null;
}
</script>

<template>
    <section class="imaging-preview">
        <p
            v-if="layer"
            class="current"
        >
            <span>{{ kindLabel(layer) }}</span>
            <span class="value">{{ layer.label }}</span>
        </p>
        <AddToSelection
            v-if="layer"
            :keys="[layerKey(props.analysis.id, layer.index)]"
            :label="$gettext('+ Selection')"
        />
        <div
            v-if="props.file.layers.length > 1"
            class="scroll"
        >
            <span aria-hidden="true">{{ $gettext("Layers, in order") }}</span>
            <Slider
                :model-value="position"
                :min="0"
                :max="props.file.layers.length - 1"
                :step="1"
                :aria-label="scrollLabel"
                @update:model-value="moveTo"
            />
        </div>
        <img
            v-if="imageUrl && layer"
            class="layer-image"
            loading="lazy"
            :src="imageUrl"
            :alt="layer.label"
        />
        <p class="note">
            <span>{{ $gettext("Each map keeps its own contrast.") }}</span>
        </p>
        <label class="toggle">
            <input
                class="lay"
                type="checkbox"
                :checked="laid"
                :disabled="!canLay"
                @change="onLayChange"
            />
            <span>{{ $gettext("Lay on the page") }}</span>
        </label>
        <p
            v-if="!canLay"
            class="note"
        >
            <span>{{
                $gettext(
                    "This analysis has no zone on this page to lay the map on.",
                )
            }}</span>
        </p>
        <template v-if="laid">
            <div class="opacity">
                <p class="opacity-value">
                    <span aria-hidden="true">{{ $gettext("Opacity") }}</span>
                    <span class="value">{{ opacityText }}</span>
                </p>
                <Slider
                    :model-value="opacityPercent"
                    :min="0"
                    :max="PERCENT"
                    :step="OPACITY_STEP"
                    :aria-label="$gettext('Opacity')"
                    @update:model-value="setOpacity"
                />
            </div>
            <label class="toggle">
                <input
                    class="curtain"
                    type="checkbox"
                    :checked="underCurtain"
                    @change="onCurtainChange"
                />
                <span>{{ $gettext("Curtain: compare with the page") }}</span>
            </label>
            <p
                class="note"
                role="note"
            >
                <span>{{
                    $gettext("Indicative positioning, not registered.")
                }}</span>
            </p>
        </template>
    </section>
</template>

<style scoped>
.imaging-preview {
    display: grid;
    gap: 0.75rem;
}

.imaging-preview .current,
.imaging-preview .opacity-value {
    display: flex;
    gap: 0.5rem;
}

.imaging-preview .current {
    font-weight: 600;
}

.imaging-preview .value {
    font-family: var(--font-mono);
}

.imaging-preview .scroll,
.imaging-preview .opacity {
    display: grid;
    gap: 0.5rem;
}

.imaging-preview .layer-image {
    max-inline-size: 100%;
    background: var(--stage);
    image-rendering: pixelated;
}

.imaging-preview .toggle {
    display: flex;
    gap: 0.5rem;
    align-items: center;
    min-block-size: var(--explorer-target, 2.75rem);
}

.imaging-preview .note {
    color: var(--ink-muted);
    font-size: 0.875rem;
}
</style>
