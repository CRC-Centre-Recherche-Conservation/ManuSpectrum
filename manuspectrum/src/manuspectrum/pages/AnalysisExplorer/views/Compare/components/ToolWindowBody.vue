<script setup lang="ts">
import { computed, inject } from "vue";
import { useGettext } from "vue3-gettext";

import LoadingSpinner from "@/manuspectrum/pages/AnalysisExplorer/components/LoadingSpinner.vue";
import UnavailableState from "@/manuspectrum/pages/AnalysisExplorer/components/UnavailableState.vue";
import ColourMaterialTable from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/components/ColourMaterialTable.vue";
import CoverageMatrix from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/components/CoverageMatrix.vue";
import FolioTool from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/components/FolioTool.vue";
import PeriodicTable from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/components/PeriodicTable.vue";

import { ANNOUNCE_KEY } from "@/manuspectrum/pages/AnalysisExplorer/injection-keys.ts";
import { useExplorerStore } from "@/manuspectrum/pages/AnalysisExplorer/store/explorer.ts";
import {
    filterParts,
    restrictingFilters,
    selectionSlots,
    toolView,
} from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/tools.ts";

import type { SynthesisResponse } from "@/manuspectrum/pages/AnalysisExplorer/api/types.ts";
import type { RequestStatus } from "@/manuspectrum/pages/AnalysisExplorer/composables/useRequest.ts";
import type {
    ToolFilters,
    ToolKind,
} from "@/manuspectrum/pages/AnalysisExplorer/store/types.ts";
import type { FilterKey } from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/tools.ts";

/**
 * The content of a tool window, on the synthesis of the Selection. The
 * coverage matrix, the colours × materials table and the periodic table
 * filter one another (`compare.toolFilters`), never the rest of the
 * Explorer: a click sets or clears the tool's own filter, and each tool
 * shows a « Filtered by … × » chip per filter of the other two that
 * restricts it, which clears it. The folio image shows the Selection's
 * items on one of the canvases they are placed on. When the synthesis
 * failed the window shows only that, with Retry; when nothing in the
 * Selection is visible it says so. While the synthesis is read the window
 * says so and is busy: a previous synthesis stays shown, but sets no
 * filter.
 */
const props = defineProps<{
    kind: ToolKind;
    status: RequestStatus;
    synthesis: SynthesisResponse | null;
}>();

const emit = defineEmits<{ (event: "retry"): void }>();

const announce = inject(ANNOUNCE_KEY, () => undefined, false);

const store = useExplorerStore();
const { $gettext, interpolate } = useGettext();

const filters = computed(() => store.compare.toolFilters);
const view = computed(() =>
    props.synthesis
        ? toolView(props.synthesis, filters.value, props.kind)
        : null,
);
const restricting = computed(() =>
    restrictingFilters(props.kind, filters.value),
);
const loading = computed(() => props.status === "loading");
const canvasLabels = computed(
    () =>
        new Map(
            (props.synthesis?.canvases ?? []).map((entry) => [
                entry.canvas,
                entry.label,
            ]),
        ),
);
const slots = computed(() => selectionSlots(store.basket));
/** Whether the Selection has nothing for this tool, filters aside. */
const emptyPayload = computed(() => {
    const synthesis = props.synthesis;
    if (!synthesis) return false;
    switch (props.kind) {
        case "colour-material":
            return synthesis.pairs.length === 0;
        case "periodic":
            return synthesis.elements.length === 0;
        case "folio":
            return synthesis.canvases.length === 0;
        default:
            return synthesis.coverage.length === 0;
    }
});
const emptyView = computed(() => {
    const shown = view.value;
    if (!shown) return false;
    switch (props.kind) {
        case "colour-material":
            return shown.pairs.length === 0;
        case "periodic":
            return shown.elements.length === 0;
        case "folio":
            return false;
        default:
            return shown.coverage.length === 0;
    }
});

function filterText(key: FilterKey, from: ToolFilters = filters.value): string {
    return props.synthesis
        ? filterParts(props.synthesis, from, key).join(" · ")
        : "";
}

function chipLabel(key: FilterKey): string {
    return interpolate(
        $gettext("Filtered by %{value}"),
        { value: filterText(key) },
        true,
    );
}

function removeLabel(key: FilterKey): string {
    return interpolate(
        $gettext("Filtered by %{value}. Remove this filter"),
        { value: filterText(key) },
        true,
    );
}

function setFilter<K extends FilterKey>(key: K, value: ToolFilters[K]): void {
    if (loading.value) return;
    const before = filterText(key);
    store.setToolFilter(key, value);
    announce(
        value === null
            ? interpolate(
                  $gettext("Filter removed: %{value}"),
                  { value: before },
                  true,
              )
            : interpolate(
                  $gettext("Tools filtered by %{value}"),
                  { value: filterText(key) },
                  true,
              ),
    );
}

function onCell({
    canvas,
    technique,
}: {
    canvas: string;
    technique: string;
}): void {
    const current = filters.value.cell;
    const same = current?.[0] === canvas && current[1] === technique;
    setFilter("cell", same ? null : [canvas, technique]);
}

function onPair({
    colour,
    material,
}: {
    colour: string | null;
    material: string;
}): void {
    const current = filters.value.pair;
    const same = current?.[0] === colour && current[1] === material;
    setFilter("pair", same ? null : [colour, material]);
}

function onElement({ symbol }: { symbol: string }): void {
    setFilter("element", filters.value.element === symbol ? null : symbol);
}
</script>

<template>
    <div
        class="tool-window-body"
        :aria-busy="loading ? 'true' : undefined"
    >
        <UnavailableState
            v-if="props.status === 'error'"
            status="error"
            :hide-home="true"
            @retry="emit('retry')"
        />
        <p
            v-else-if="props.status === 'unavailable'"
            class="empty"
        >
            <span>{{
                $gettext("Nothing in the Selection is available any more.")
            }}</span>
        </p>
        <p
            v-else-if="loading || !view"
            class="loading"
            role="status"
        >
            <LoadingSpinner />
            <span>{{ $gettext("Reading the Selection…") }}</span>
        </p>
        <template
            v-if="
                props.status !== 'unavailable' &&
                props.status !== 'error' &&
                view
            "
        >
            <ul
                v-if="restricting.length > 0"
                class="chips"
            >
                <li
                    v-for="key in restricting"
                    :key="key"
                >
                    <button
                        type="button"
                        class="chip"
                        :data-filter="key"
                        :aria-label="removeLabel(key)"
                        @click="setFilter(key, null)"
                    >
                        <span>{{ chipLabel(key) }}</span>
                        <span aria-hidden="true">×</span>
                    </button>
                </li>
            </ul>
            <p
                v-if="emptyPayload"
                class="empty"
            >
                <span>{{
                    $gettext("Nothing to show for this Selection.")
                }}</span>
            </p>
            <p
                v-else-if="emptyView"
                class="empty"
            >
                <span>{{ $gettext("Nothing matches the filters.") }}</span>
            </p>
            <CoverageMatrix
                v-else-if="props.kind === 'coverage'"
                :rows="view.coverage"
                :techniques="props.synthesis!.techniques"
                :pressed="filters.cell"
                @toggle="onCell"
            />
            <ColourMaterialTable
                v-else-if="props.kind === 'colour-material'"
                :pairs="view.pairs"
                :canvas-labels="canvasLabels"
                :pressed="filters.pair"
                @toggle="onPair"
            />
            <PeriodicTable
                v-else-if="props.kind === 'periodic'"
                :elements="view.elements"
                :pressed="filters.element"
                @toggle="onElement"
            />
            <FolioTool
                v-else-if="props.kind === 'folio'"
                :canvases="props.synthesis!.canvases"
                :slots="slots"
            />
        </template>
    </div>
</template>

<style scoped>
.tool-window-body {
    display: grid;
    align-content: start;
    gap: 0.5rem;
    block-size: 100%;
}

.tool-window-body .loading {
    display: flex;
    align-items: center;
    gap: 0.5rem;
    color: var(--ink-muted);
}

.tool-window-body .empty {
    color: var(--ink-muted);
}

.tool-window-body .chips {
    display: flex;
    flex-wrap: wrap;
    gap: 0.25rem;
    margin: 0;
    padding: 0;
    list-style: none;
}

.tool-window-body .chip {
    display: inline-flex;
    align-items: center;
    gap: 0.375rem;
    min-block-size: var(--explorer-target, 2.75rem);
    padding-inline: 0.75rem;
    border: 0.0625rem solid var(--ink);
    border-radius: 999rem;
    background: var(--bg-alt);
    color: var(--ink);
    font: inherit;
    font-size: 0.8125rem;
    cursor: pointer;
}

.tool-window-body .chip:focus-visible {
    outline: 0.125rem solid var(--blue-text);
    outline-offset: 0.125rem;
}
</style>
