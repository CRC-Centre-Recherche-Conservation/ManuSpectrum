<script setup lang="ts">
import { computed, ref, useId } from "vue";
import { useGettext } from "vue3-gettext";

import LayerScroll from "@/manuspectrum/pages/AnalysisExplorer/viewers/LayerScroll.vue";
import ElementMapCard from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/components/ElementMapCard.vue";

import {
    layerKindLabel,
    notMappedLabel,
} from "@/manuspectrum/pages/AnalysisExplorer/viewers/layer-labels.ts";
import {
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
 */
const props = defineProps<{ maps: readonly MapLine[] }>();

const { $gettext } = useGettext();
const pickerId = useId();

/** The chosen layer's id; null until the reader picks one. */
const chosen = ref<string | null>(null);

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

function choose(next: number): void {
    chosen.value = layers.value[next]?.id ?? null;
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
