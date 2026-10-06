<script setup lang="ts">
import { computed, inject, ref, toRef, watch } from "vue";
import { useGettext } from "vue3-gettext";

import Slider from "primevue/slider";

import LayerScroll from "@/manuspectrum/pages/AnalysisExplorer/viewers/LayerScroll.vue";

import {
    layerImageChain,
    overlayKey,
} from "@/manuspectrum/pages/AnalysisExplorer/folio/overlays.ts";
import {
    CURTAIN_KEY,
    FOLIO_ZONES_KEY,
} from "@/manuspectrum/pages/AnalysisExplorer/injection-keys.ts";
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

/**
 * A map the image server does not give is said so in place, with Retry.
 *
 * A classic viewer: a layer scroll steps through the file's own layers, by
 * their stored label. The laid layers live in `store.overlays` (the document
 * screen's folio).
 */
const props = defineProps<{
    file: FileEntry;
    analysis: Pick<AnalysisPayload, "id">;
}>();

const curtain = inject(CURTAIN_KEY, ref<string | null>(null));
const zones = inject(FOLIO_ZONES_KEY, ref<ReadonlySet<string>>(new Set()));

const store = useExplorerStore();
const overlays = {
    settings: toRef(store, "overlays"),
    set: store.setOverlay,
};
const { $gettext } = useGettext();
const percentFormat = new Intl.NumberFormat(
    document.documentElement.lang || "en",
    { style: "percent" },
);

/** Opens on the layer of this file laid on the page, if any, else the first. */
const position = ref(
    Math.max(
        0,
        props.file.layers.findIndex(
            (entry) =>
                overlays.settings.value[
                    overlayKey(props.analysis.id, entry.index)
                ]?.on,
        ),
    ),
);

const imageFailed = ref(false);
const attempt = ref(0);
/** How many steps of `imageChain` the plain-`<img>` path has already gone past for this layer. */
const step = ref(0);

const layer = computed<FileLayer | null>(
    () => props.file.layers[position.value] ?? null,
);
const key = computed(() =>
    layer.value ? overlayKey(props.analysis.id, layer.value.index) : "",
);
const setting = computed(() =>
    key.value ? overlays.settings.value[key.value] : undefined,
);
const laid = computed(() => Boolean(setting.value?.on));
const opacity = computed(() => setting.value?.opacity ?? DEFAULT_OPACITY);
const opacityPercent = computed(() => Math.round(opacity.value * PERCENT));
const opacityText = computed(() => percentFormat.format(opacity.value));
const canLay = computed(() => zones.value.has(props.analysis.id));
const underCurtain = computed(
    () => key.value !== "" && curtain.value === key.value,
);
const imageChain = computed(() =>
    layer.value ? layerImageChain(layer.value.image, PREVIEW_SIZE) : [],
);
const imageUrl = computed(() => imageChain.value[step.value] ?? null);
const labels = computed(() => props.file.layers.map((entry) => entry.label));

watch(key, () => {
    imageFailed.value = false;
    step.value = 0;
});

/**
 * A failure goes to the next address of `layerImageChain` (bounded size,
 * percentage, `max`), silently, each tried once; only the last failing shows
 * the "unavailable" state.
 */
function onImageError(): void {
    if (step.value + 1 < imageChain.value.length) {
        step.value += 1;
    } else {
        imageFailed.value = true;
    }
}

function retryImage(): void {
    attempt.value += 1;
    imageFailed.value = false;
    step.value = 0;
}

function firstValue(value: number | number[]): number {
    return Array.isArray(value) ? value[0] : value;
}

function lay(on: boolean): void {
    if (!layer.value) return;
    overlays.set(key.value, {
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
    overlays.set(key.value, {
        element: layer.value.label,
        opacity: firstValue(value) / PERCENT,
        on: laid.value,
    });
}

/** Moving the layer scroll carries the laid map, its opacity and the curtain to the new layer. */
function moveTo(value: number): void {
    const wasLaid = laid.value;
    const wasUnderCurtain = underCurtain.value;
    const keptOpacity = opacity.value;
    if (wasLaid) lay(false);
    position.value = value;
    if (wasLaid && layer.value) {
        overlays.set(key.value, {
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
            <span class="value">{{ layer.label }}</span>
        </p>
        <LayerScroll
            v-if="props.file.layers.length > 1"
            :labels="labels"
            :position="position"
            @update:position="moveTo"
        />
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

.imaging-preview .opacity {
    display: grid;
    gap: 0.5rem;
    padding-inline: 0.625rem;
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
