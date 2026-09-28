<script setup lang="ts">
import { computed, inject, ref, useId, watch } from "vue";
import { useGettext } from "vue3-gettext";

import LayerScroll from "@/manuspectrum/pages/AnalysisExplorer/viewers/LayerScroll.vue";
import ElementMapCard from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/components/ElementMapCard.vue";

import { useLinkedMarks } from "@/manuspectrum/pages/AnalysisExplorer/composables/useLinkedMarks.ts";
import { ANNOUNCE_KEY } from "@/manuspectrum/pages/AnalysisExplorer/injection-keys.ts";
import {
    layerKindLabel,
    notMappedLabel,
} from "@/manuspectrum/pages/AnalysisExplorer/viewers/layer-labels.ts";
import { parseNodeId } from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/linked/node-id.ts";
import {
    elementLayerId,
    layerIn,
    sharedKind,
    sharedLayers,
    startLayer,
} from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/maps.ts";

import type {
    LayerKind,
    SharedLayer,
} from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/maps.ts";
import type { MapLine } from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/windows.ts";

interface LayerGroup {
    kind: LayerKind;
    entries: { layer: SharedLayer; position: number }[];
}

/**
 * The layered maps of the Selection side by side (§9, D46, D47): one layer
 * picker and one layer scroll over the union of their layers (`sharedLayers`),
 * the same layer held on every map; a map lacking it says so. It opens on
 * the layer a one-layer key names, else the first. Each map keeps its own
 * contrast and its own curtain.
 *
 * Selecting an element in Compare (`el:`, the last one selected that a map
 * holds) switches the shared layer to it, and that is said; once no
 * selected element has a layer, the layer shown before comes back unless
 * the reader picked another meanwhile. A preview never switches it.
 */
const props = defineProps<{ maps: readonly MapLine[] }>();

const announce = inject(ANNOUNCE_KEY, () => undefined, false);

const { $gettext, interpolate } = useGettext();
const pickerId = useId();
const marks = useLinkedMarks();

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
const labels = computed(() => layers.value.map((layer) => layer.label));
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
const notMapped = computed(() =>
    notMappedLabel($gettext, current.value?.kind ?? "other"),
);
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
                $gettext("The element maps show %{layer}."),
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
    say(
        interpolate(
            $gettext("The element maps show %{layer} again."),
            { layer: current.value?.label ?? "" },
            true,
        ),
    );
}

function onPick(event: Event): void {
    choose(Number((event.target as HTMLSelectElement).value));
}
</script>

<template>
    <div class="element-maps">
        <div class="controls">
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
                v-if="layers.length > 1"
                class="layer-scroll"
                :labels="labels"
                :position="position"
                @update:position="choose"
            />
            <p class="note">
                <span>{{ $gettext("Each map keeps its own contrast.") }}</span>
            </p>
        </div>
        <div class="maps">
            <ElementMapCard
                v-for="line in props.maps"
                :key="`${line.key}|${line.slot}|${line.file.id}`"
                :slot-number="line.slot"
                :analysis="line.analysis"
                :file="line.file"
                :layer="layerIn(line.file, current?.id ?? null)"
                :not-mapped="notMapped"
            />
        </div>
    </div>
</template>

<style scoped>
.element-maps {
    display: grid;
    gap: 0.75rem;
}

.element-maps .controls {
    display: grid;
    grid-template-columns: auto minmax(0, 1fr);
    align-items: center;
    gap: 0.5rem 1rem;
}

.element-maps .layer-picker {
    display: flex;
    align-items: center;
    gap: 0.5rem;
    font-size: 0.8125rem;
}

.element-maps .layer-picker select {
    min-block-size: var(--explorer-target, 2.75rem);
    padding-inline: 0.5rem;
    border: 0.0625rem solid var(--border-hover);
    border-radius: 0.25rem;
    background: var(--surface);
    color: var(--ink);
    font: inherit;
    font-family: var(--font-mono);
}

.element-maps .layer-picker select:focus-visible {
    outline: 0.125rem solid var(--blue-text);
    outline-offset: 0.125rem;
}

.element-maps .note {
    grid-column: 1 / -1;
    margin: 0;
    color: var(--ink-muted);
    font-size: 0.8125rem;
}

.element-maps .maps {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(16rem, 1fr));
    gap: 0.75rem;
}

@media (max-width: 48rem) {
    .element-maps .controls {
        grid-template-columns: minmax(0, 1fr);
    }
}
</style>
