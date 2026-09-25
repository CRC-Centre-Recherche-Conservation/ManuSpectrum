<script setup lang="ts">
import { computed, inject, ref, watch } from "vue";
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
import type { SelectionHint } from "@/manuspectrum/pages/AnalysisExplorer/injection-keys.ts";

const DEFAULT_OPACITY = 0.7;
const PREVIEW_SIZE = 480;
const PERCENT = 100;
const OPACITY_STEP = 5;

/** A map the image server does not give is said so in place, with Retry. */
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

const imageFailed = ref(false);
const attempt = ref(0);

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
/** Where the layer scale's handle is, in words: « 550 nm, layer 4 of 13 ». */
const valueText = computed(() =>
    layer.value
        ? interpolate(
              $gettext("%{label}, layer %{n} of %{total}"),
              {
                  label: layer.value.label,
                  n: position.value + 1,
                  total: props.file.layers.length,
              },
              true,
          )
        : "",
);
const firstLayer = computed(() => props.file.layers[0]?.label ?? "");
const lastLayer = computed(() => props.file.layers.at(-1)?.label ?? "");
const addLabel = computed(() =>
    interpolate(
        $gettext("+ Add the map %{label}"),
        { label: layer.value?.label ?? "" },
        true,
    ),
);
const addAriaLabel = computed(() =>
    interpolate(
        $gettext("Add the map %{label} to the Selection"),
        { label: layer.value?.label ?? "" },
        true,
    ),
);
const addHints = computed(() =>
    layer.value
        ? new Map<string, SelectionHint>([
              [
                  layerKey(props.analysis.id, layer.value.index),
                  {
                      title: props.analysis.name,
                      kind: $gettext("map layer"),
                      detail: layer.value.label,
                  },
              ],
          ])
        : null,
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

watch(imageUrl, () => {
    imageFailed.value = false;
});

function onImageError(): void {
    imageFailed.value = true;
}

function retryImage(): void {
    attempt.value += 1;
    imageFailed.value = false;
}

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
                :pt="{ handle: { 'aria-valuetext': valueText } }"
                @update:model-value="moveTo"
            />
            <span
                class="ticks"
                aria-hidden="true"
            >
                <span
                    v-for="entry in props.file.layers"
                    :key="entry.index"
                    class="tick"
                ></span>
            </span>
            <span
                class="ends"
                aria-hidden="true"
            >
                <span>{{ firstLayer }}</span>
                <span>{{ lastLayer }}</span>
            </span>
        </div>
        <p
            v-if="imageUrl && imageFailed"
            class="unavailable"
            role="status"
        >
            <span>{{ $gettext("Map unavailable (image server)") }}</span>
            <button
                type="button"
                @click="retryImage"
            >
                <span>{{ $gettext("Retry") }}</span>
            </button>
        </p>
        <img
            v-else-if="imageUrl && layer"
            :key="`${imageUrl}#${attempt}`"
            class="layer-image"
            loading="lazy"
            :src="imageUrl"
            :alt="layer.label"
            @error="onImageError"
        />
        <p class="note">
            <span>{{ $gettext("Each map keeps its own contrast.") }}</span>
        </p>
        <AddToSelection
            v-if="layer"
            :keys="[layerKey(props.analysis.id, layer.index)]"
            :label="addLabel"
            :aria-label="addAriaLabel"
            :hints="addHints"
        />
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
    padding-inline: 0.625rem;
}

.imaging-preview .ticks {
    display: flex;
    justify-content: space-between;
}

.imaging-preview .tick {
    inline-size: 0.0625rem;
    block-size: 0.375rem;
    background: var(--border-hover);
}

.imaging-preview .ends {
    display: flex;
    justify-content: space-between;
    gap: 1rem;
    color: var(--ink-muted);
    font-family: var(--font-mono);
    font-size: 0.6875rem;
}

.imaging-preview .layer-image {
    max-inline-size: 100%;
    background: var(--stage);
    image-rendering: pixelated;
}

.imaging-preview .unavailable {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: 0.5rem 1rem;
    padding: 0.5rem 0.75rem;
    border: 0.0625rem dashed var(--border-hover);
    border-radius: 0.375rem;
    color: var(--ink-muted);
    font-size: 0.8125rem;
}

.imaging-preview .unavailable button {
    min-block-size: var(--explorer-target, 2.75rem);
    padding-inline: 0.75rem;
    border: 0.0625rem solid var(--border-hover);
    border-radius: 999rem;
    background: var(--surface);
    color: var(--ink);
    font: inherit;
    cursor: pointer;
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
