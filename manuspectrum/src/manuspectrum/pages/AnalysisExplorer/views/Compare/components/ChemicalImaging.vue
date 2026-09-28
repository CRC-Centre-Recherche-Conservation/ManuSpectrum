<script setup lang="ts">
import { computed, inject, provide, ref, useId, watch } from "vue";
import { useGettext } from "vue3-gettext";

import LayerScroll from "@/manuspectrum/pages/AnalysisExplorer/viewers/LayerScroll.vue";
import ChemicalImagingMap from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/components/ChemicalImagingMap.vue";

import { useLinkedMarks } from "@/manuspectrum/pages/AnalysisExplorer/composables/useLinkedMarks.ts";
import {
    ANNOUNCE_KEY,
    IMAGING_OVERLAYS_KEY,
} from "@/manuspectrum/pages/AnalysisExplorer/injection-keys.ts";
import { layerKindLabel } from "@/manuspectrum/pages/AnalysisExplorer/viewers/layer-labels.ts";
import { parseNodeId } from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/linked/node-id.ts";
import {
    elementLayerId,
    layerPosition,
    sharedKind,
    sharedLayers,
    startLayer,
} from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/maps.ts";

import type {
    LayerKind,
    SharedLayer,
} from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/maps.ts";
import type { Overlay } from "@/manuspectrum/pages/AnalysisExplorer/store/types.ts";
import type { MapLine } from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/windows.ts";

interface LayerGroup {
    kind: LayerKind;
    entries: { layer: SharedLayer; position: number }[];
}

/**
 * The chemical imaging maps of the Selection side by side (§9, D46, D47),
 * each in the document screen's imaging preview. « Same layer on every
 * map » (on at first) holds one layer on every map, chosen by one layer
 * picker over the union of their layers (`sharedLayers`, grouped by kind)
 * and one layer scroll over the layers of the kind shown (elements, or
 * bands); a map lacking it says so and lists the layers it has. It opens on
 * the layer a one-layer key names, else the first. Off, each map has its
 * own layer scroll and keeps the layer it shows. Each map keeps its own
 * contrast, its own laid layer and its own curtain; the laid layers live
 * in this window, never on the document screen.
 *
 * Selecting an element in Compare (`el:`, the last one selected that a map
 * holds) switches the shared layer to it, and that is said; once no
 * selected element has a layer, the layer shown before comes back unless
 * the reader picked another meanwhile. Maps not held together move to the
 * selected element when they hold it, and stay there. A preview never
 * switches a layer.
 */
const props = defineProps<{ maps: readonly MapLine[] }>();

const announce = inject(ANNOUNCE_KEY, () => undefined, false);

const { $gettext, interpolate } = useGettext();
const pickerId = useId();
const marks = useLinkedMarks();

const overlays = ref<Record<string, Overlay>>({});
const sync = ref(true);

/** The chosen layer's id; null until the reader picks one. */
const chosen = ref<string | null>(null);
/** The layer shown before an element was selected; undefined while none is. */
let beforePin: string | null | undefined;

const layers = computed(() => sharedLayers(props.maps));
const kind = computed(() => sharedKind(layers.value));
const position = computed(() => {
    const index = layers.value.findIndex((layer) => layer.id === chosen.value);
    return index >= 0 ? index : startLayer(props.maps, layers.value);
});
const current = computed(() => layers.value[position.value] ?? null);
/** The layers of the kind shown, with their position in `layers`. */
const kindLayers = computed(() =>
    layers.value.flatMap((layer, index) =>
        layer.kind === current.value?.kind ? [{ layer, position: index }] : [],
    ),
);
const labels = computed(() =>
    kindLayers.value.map((entry) => entry.layer.label),
);
const kindPosition = computed(() =>
    Math.max(
        0,
        kindLayers.value.findIndex(
            (entry) => entry.position === position.value,
        ),
    ),
);
const groups = computed<LayerGroup[]>(() => {
    const byKind = new Map<LayerKind, LayerGroup>();
    layers.value.forEach((layer, index) => {
        const group = byKind.get(layer.kind) ?? {
            kind: layer.kind,
            entries: [],
        };
        group.entries.push({ layer, position: index });
        byKind.set(layer.kind, group);
    });
    return [...byKind.values()];
});
/** The layer of the last element selected that a map holds; null when none. */
const pinnedLayer = computed<string | null>(() => {
    const selection = marks.linked?.selection.value ?? [];
    for (const id of [...selection].reverse()) {
        const parsed = parseNodeId(id);
        const symbol = parsed?.kind === "el" ? parsed.parts[0] : null;
        const layerId = symbol ? elementLayerId(symbol) : null;
        if (layerId && layers.value.some((layer) => layer.id === layerId)) {
            return layerId;
        }
    }
    return null;
});

watch(pinnedLayer, followPin);

provide(IMAGING_OVERLAYS_KEY, { settings: overlays, set: setOverlay });

function setOverlay(key: string, overlay: Overlay | null): void {
    const next = { ...overlays.value };
    if (overlay) next[key] = overlay;
    else delete next[key];
    overlays.value = next;
}

/** The layer `line` shows: the shared one while held together, else the element selected when it holds it; undefined leaves it free. */
function heldOf(line: MapLine): number | null | undefined {
    if (sync.value) return layerPosition(line.file, current.value?.id ?? null);
    return layerPosition(line.file, pinnedLayer.value) ?? undefined;
}

function choose(next: number): void {
    chosen.value = layers.value[next]?.id ?? null;
}

function say(message: string): void {
    const summary = marks.linked?.summary.value;
    announce(
        summary
            ? interpolate(
                  $gettext("%{summary}. %{message}"),
                  { summary, message },
                  true,
              )
            : message,
    );
}

function followPin(next: string | null, previous: string | null): void {
    if (next !== null) {
        if (beforePin === undefined) beforePin = current.value?.id ?? null;
        chosen.value = next;
        say(
            interpolate(
                $gettext("The chemical imaging maps show %{layer}."),
                { layer: current.value?.label ?? "" },
                true,
            ),
        );
        return;
    }
    const restored = beforePin;
    beforePin = undefined;
    if (restored === undefined || current.value?.id !== previous) return;
    chosen.value = restored;
    if (!sync.value) return;
    say(
        interpolate(
            $gettext("The chemical imaging maps show %{layer} again."),
            { layer: current.value?.label ?? "" },
            true,
        ),
    );
}

function scrollTo(next: number): void {
    const entry = kindLayers.value[next];
    if (entry) choose(entry.position);
}

function onPick(event: Event): void {
    choose(Number((event.target as HTMLSelectElement).value));
}

function onSyncChange(event: Event): void {
    sync.value = (event.target as HTMLInputElement).checked;
}
</script>

<template>
    <div class="chemical-imaging">
        <div class="controls">
            <label class="sync">
                <input
                    class="sync"
                    type="checkbox"
                    :checked="sync"
                    @change="onSyncChange"
                />
                <span>{{ $gettext("Same layer on every map") }}</span>
            </label>
            <div
                v-if="sync"
                class="shared"
            >
                <div class="layer-picker">
                    <label :for="pickerId">
                        <span>{{ layerKindLabel($gettext, kind) }}</span>
                    </label>
                    <select
                        :id="pickerId"
                        :value="position"
                        @change="onPick"
                    >
                        <template v-if="groups.length > 1">
                            <optgroup
                                v-for="group in groups"
                                :key="group.kind"
                                :label="layerKindLabel($gettext, group.kind)"
                            >
                                <option
                                    v-for="entry in group.entries"
                                    :key="entry.layer.id"
                                    :value="entry.position"
                                >
                                    {{ entry.layer.label }}
                                </option>
                            </optgroup>
                        </template>
                        <template v-else>
                            <option
                                v-for="(layer, index) in layers"
                                :key="layer.id"
                                :value="index"
                            >
                                {{ layer.label }}
                            </option>
                        </template>
                    </select>
                </div>
                <LayerScroll
                    v-if="labels.length > 1"
                    class="layer-scroll"
                    :labels="labels"
                    :position="kindPosition"
                    @update:position="scrollTo"
                />
            </div>
        </div>
        <div class="maps">
            <ChemicalImagingMap
                v-for="line in props.maps"
                :key="`${line.key}|${line.slot}|${line.file.id}`"
                :slot-number="line.slot"
                :analysis="line.analysis"
                :file="line.file"
                :held="heldOf(line)"
                :wanted="current?.label ?? null"
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

.chemical-imaging .controls {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: 0.5rem 1.5rem;
}

.chemical-imaging .sync {
    display: flex;
    align-items: center;
    gap: 0.5rem;
    min-block-size: var(--explorer-target, 2.75rem);
    font-size: 0.875rem;
    font-weight: 600;
}

.chemical-imaging .sync input:focus-visible {
    outline: 0.125rem solid var(--blue-text);
    outline-offset: 0.125rem;
}

.chemical-imaging .shared {
    flex: 1 1 28rem;
    display: grid;
    grid-template-columns: auto minmax(0, 1fr);
    align-items: center;
    gap: 0.5rem 1rem;
}

.chemical-imaging .layer-picker {
    display: flex;
    align-items: center;
    gap: 0.5rem;
    font-size: 0.8125rem;
}

.chemical-imaging .layer-picker select {
    min-block-size: var(--explorer-target, 2.75rem);
    padding-inline: 0.5rem;
    border: 0.0625rem solid var(--border-hover);
    border-radius: 0.25rem;
    background: var(--surface);
    color: var(--ink);
    font: inherit;
    font-family: var(--font-mono);
}

.chemical-imaging .layer-picker select:focus-visible {
    outline: 0.125rem solid var(--blue-text);
    outline-offset: 0.125rem;
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
    .chemical-imaging .shared {
        grid-template-columns: minmax(0, 1fr);
    }

    .chemical-imaging .maps {
        grid-template-columns: minmax(0, 1fr);
    }
}
</style>
