<script setup lang="ts">
import { computed, inject, ref, toRef, useTemplateRef, watch } from "vue";
import { useGettext } from "vue3-gettext";

import IconButton from "@/manuspectrum/pages/AnalysisExplorer/components/IconButton.vue";
import LayerThumb from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/components/LayerThumb.vue";

import { useRegistration } from "@/manuspectrum/pages/AnalysisExplorer/composables/useRegistration.ts";
import { nextId } from "@/manuspectrum/pages/AnalysisExplorer/folio/roving.ts";
import { groupLayers } from "@/manuspectrum/pages/AnalysisExplorer/viewers/layer-groups.ts";
import {
    layerImageChain,
    overlayKey,
} from "@/manuspectrum/pages/AnalysisExplorer/folio/overlays.ts";
import {
    CURTAIN_KEY,
    FOLIO_CANVAS_KEY,
    FOLIO_ZONES_KEY,
} from "@/manuspectrum/pages/AnalysisExplorer/injection-keys.ts";
import { UNPLACED } from "@/manuspectrum/pages/AnalysisExplorer/folio/registration-store.ts";
import { useExplorerStore } from "@/manuspectrum/pages/AnalysisExplorer/store/explorer.ts";

import type {
    AnalysisPayload,
    FileEntry,
    FileLayer,
} from "@/manuspectrum/pages/AnalysisExplorer/api/types.ts";

const DEFAULT_OPACITY = 0.7;
const PREVIEW_SIZE = 480;
const ROVING_KEYS = new Set([
    "ArrowLeft",
    "ArrowRight",
    "ArrowUp",
    "ArrowDown",
    "Home",
    "End",
]);

/**
 * A map the image server does not give is said so in place, with Retry.
 *
 * A classic viewer: previous and next buttons and a strip of small
 * thumbnails step through the file's own layers, by their stored label, the
 * strip grouped by the element or band the layers declare; previous and next
 * follow the strip's order. The laid layers live in `store.overlays` (the
 * document screen's folio), where the layer's own toolbar holds opacity,
 * curtain, turns and reset.
 */
const props = defineProps<{
    file: FileEntry;
    analysis: Pick<AnalysisPayload, "id">;
}>();

const curtain = inject(CURTAIN_KEY, ref<string | null>(null));
const folioCanvas = inject(FOLIO_CANVAS_KEY, ref<string | null>(null));
const zones = inject(FOLIO_ZONES_KEY, ref<ReadonlySet<string>>(new Set()));

const store = useExplorerStore();
const overlays = {
    settings: toRef(store, "overlays"),
    set: store.setOverlay,
};
const { $gettext, interpolate } = useGettext();
const strip = useTemplateRef<HTMLElement>("strip");
const registration = useRegistration();

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
/** True when the analysis has a place of its own on the page shown. */
const registered = computed(() => {
    const held = registration.get(props.analysis.id);
    return (
        held !== null &&
        held.canvas === folioCanvas.value &&
        !(held.box.w === UNPLACED.w && held.box.h === UNPLACED.h)
    );
});
const canLay = computed(() => zones.value.has(props.analysis.id));
const underCurtain = computed(
    () => key.value !== "" && curtain.value === key.value,
);
const imageChain = computed(() =>
    layer.value ? layerImageChain(layer.value.image, PREVIEW_SIZE) : [],
);
const imageUrl = computed(() => imageChain.value[step.value] ?? null);
const many = computed(() => props.file.layers.length > 1);
const groups = computed(() =>
    groupLayers(props.file.layers, { $gettext, interpolate }),
);
const titled = computed(() => groups.value.length > 1);
const order = computed(() =>
    groups.value.flatMap((group) =>
        group.positions.map((place) => props.file.layers[place].id),
    ),
);
const roving = ref<string | null>(null);
const stop = computed(() =>
    roving.value && order.value.includes(roving.value)
        ? roving.value
        : layer.value?.id ?? null,
);
/** The current layer's place in the strip's order, which previous and next follow. */
const shown = computed(() =>
    layer.value ? order.value.indexOf(layer.value.id) : -1,
);
const positionText = computed(() =>
    interpolate(
        $gettext("%{n} / %{total}"),
        { n: shown.value + 1, total: order.value.length },
        true,
    ),
);

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

function stepBy(by: number): void {
    const id = order.value[shown.value + by];
    if (id === undefined) return;
    moveTo(props.file.layers.findIndex((entry) => entry.id === id));
}

function groupTitle(title: string | null, count: number): string {
    return title === null
        ? interpolate($gettext("Unclassified · %{n}"), { n: count }, true)
        : title;
}

function onStripKeydown(event: KeyboardEvent): void {
    if (!ROVING_KEYS.has(event.key)) return;
    const next = nextId(order.value, stop.value, event.key);
    if (next === null) return;
    event.preventDefault();
    roving.value = next;
    const button = [...(strip.value?.querySelectorAll("button") ?? [])].find(
        (item) => (item as HTMLElement).dataset.canvas === next,
    );
    (button as HTMLElement | undefined)?.focus();
}

/** Moving to another layer carries the laid map, its opacity and the curtain to the new layer. */
function moveTo(value: number): void {
    if (value < 0 || value >= props.file.layers.length) return;
    roving.value = null;
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
</script>

<template>
    <section class="imaging-preview">
        <div
            v-if="layer"
            class="layer-nav"
        >
            <IconButton
                v-if="many"
                icon="chevron-left"
                data-action="previous"
                :label="$gettext('Previous layer')"
                :disabled="shown <= 0"
                @click="stepBy(-1)"
            />
            <p class="current">
                <span class="value">{{ layer.label }}</span>
                <span
                    v-if="many"
                    class="position"
                    >{{ positionText }}</span
                >
            </p>
            <IconButton
                v-if="many"
                icon="chevron-right"
                data-action="next"
                :label="$gettext('Next layer')"
                :disabled="shown >= order.length - 1"
                @click="stepBy(1)"
            />
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
        <div
            v-if="many"
            ref="strip"
            class="strip"
            role="group"
            :aria-label="$gettext('Layers, in order')"
            @keydown="onStripKeydown"
        >
            <section
                v-for="group in groups"
                :key="group.id"
                class="group"
            >
                <h4
                    v-if="titled"
                    class="group-title"
                >
                    <span>{{
                        groupTitle(group.title, group.positions.length)
                    }}</span>
                </h4>
                <div class="thumbs">
                    <LayerThumb
                        v-for="place in group.positions"
                        :key="props.file.layers[place].id"
                        :canvas="props.file.layers[place].id"
                        :label="props.file.layers[place].label"
                        :service="props.file.layers[place].image.service"
                        :tag="null"
                        :panes="[]"
                        :in-stack="false"
                        :stop="stop === props.file.layers[place].id"
                        :current="place === position"
                        @pick="moveTo(place)"
                    />
                </div>
            </section>
        </div>
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
        <p
            v-if="laid"
            class="note"
            role="note"
        >
            <span v-if="registered">{{
                $gettext("Registered in this browser.")
            }}</span>
            <span v-else>{{
                $gettext("Indicative positioning, not registered.")
            }}</span>
        </p>
    </section>
</template>

<style scoped>
.imaging-preview {
    display: grid;
    gap: 0.75rem;
}

.imaging-preview .layer-nav {
    display: flex;
    gap: 0.5rem;
}

.imaging-preview .layer-nav {
    align-items: center;
    justify-content: space-between;
}

.imaging-preview .current {
    display: flex;
    flex: 1;
    flex-wrap: wrap;
    justify-content: center;
    gap: 0.25rem 0.75rem;
    min-inline-size: 0;
    font-weight: 600;
    overflow-wrap: anywhere;
}

.imaging-preview .position {
    color: var(--ink-muted);
    font-family: var(--font-mono);
    font-weight: 400;
}

.imaging-preview .strip {
    display: grid;
    gap: 0.75rem;
    max-block-size: 16rem;
    overflow-y: auto;
    padding: 0.25rem;
}

.imaging-preview .group {
    display: grid;
    gap: 0.375rem;
}

.imaging-preview .group-title {
    color: var(--ink-muted);
    font: 600 0.75rem var(--font-mono);
}

.imaging-preview .thumbs {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(4.5rem, 1fr));
    gap: 0.375rem;
}

.imaging-preview .value {
    font-family: var(--font-mono);
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
