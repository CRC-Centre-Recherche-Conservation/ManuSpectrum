<script setup lang="ts">
import { computed } from "vue";
import { useGettext } from "vue3-gettext";

import LoadingSpinner from "@/manuspectrum/pages/AnalysisExplorer/components/LoadingSpinner.vue";
import UnavailableState from "@/manuspectrum/pages/AnalysisExplorer/components/UnavailableState.vue";
import ColourMaterialTable from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/components/ColourMaterialTable.vue";
import CoverageMatrix from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/components/CoverageMatrix.vue";
import FolioTool from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/components/FolioTool.vue";
import PeriodicTable from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/components/PeriodicTable.vue";

import { useExplorerStore } from "@/manuspectrum/pages/AnalysisExplorer/store/explorer.ts";
import {
    folioCanvases,
    selectionSlots,
} from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/tools.ts";

import type { SynthesisResponse } from "@/manuspectrum/pages/AnalysisExplorer/api/types.ts";
import type { RequestStatus } from "@/manuspectrum/pages/AnalysisExplorer/composables/useRequest.ts";
import type { ToolKind } from "@/manuspectrum/pages/AnalysisExplorer/store/types.ts";

/**
 * The content of a tool window, on the synthesis of the Selection. The
 * coverage matrix, the colours × materials table and the periodic table
 * show the whole synthesis and select through the linked selection of
 * Compare themselves (`useLinkedMarks`). The folio image shows the Selection's items
 * on one of the canvases they are placed on. When the synthesis failed the
 * window shows only that, with Retry; when nothing in the Selection is
 * visible it says so. While the synthesis is read the window says so above
 * a previous synthesis, which stays shown busy with its toggles disabled
 * and selects nothing. The folio image takes the height the window leaves.
 */
const props = defineProps<{
    kind: ToolKind;
    status: RequestStatus;
    synthesis: SynthesisResponse | null;
}>();

const emit = defineEmits<{ (event: "retry"): void }>();

const store = useExplorerStore();
const { $gettext } = useGettext();

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
const folio = computed(() =>
    props.synthesis ? folioCanvases(props.synthesis) : [],
);
/** Whether the Selection has nothing for this tool. */
const emptyPayload = computed(() => {
    const synthesis = props.synthesis;
    if (!synthesis) return false;
    switch (props.kind) {
        case "colour-material":
            return synthesis.pairs.length === 0;
        case "periodic":
            return synthesis.elements.length === 0;
        case "folio":
            return folio.value.length === 0;
        default:
            return synthesis.coverage.length === 0;
    }
});
</script>

<template>
    <div class="tool-window-body">
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
            v-else-if="loading || !props.synthesis"
            class="loading"
            role="status"
        >
            <LoadingSpinner />
            <span>{{ $gettext("Reading the Selection…") }}</span>
        </p>
        <div
            v-if="
                props.status !== 'unavailable' &&
                props.status !== 'error' &&
                props.synthesis
            "
            class="view"
            :aria-busy="loading ? 'true' : undefined"
        >
            <p
                v-if="emptyPayload"
                class="empty"
            >
                <span>{{
                    $gettext("Nothing to show for this Selection.")
                }}</span>
            </p>
            <CoverageMatrix
                v-else-if="props.kind === 'coverage'"
                :rows="props.synthesis.coverage"
                :techniques="props.synthesis.techniques"
                :disabled="loading"
            />
            <ColourMaterialTable
                v-else-if="props.kind === 'colour-material'"
                :pairs="props.synthesis.pairs"
                :canvas-labels="canvasLabels"
                :disabled="loading"
            />
            <PeriodicTable
                v-else-if="props.kind === 'periodic'"
                :elements="props.synthesis.elements"
                :disabled="loading"
            />
            <FolioTool
                v-else-if="props.kind === 'folio'"
                :canvases="folio"
                :slots="slots"
            />
        </div>
    </div>
</template>

<style scoped>
.tool-window-body {
    display: flex;
    flex-direction: column;
    gap: 0.5rem;
    block-size: 100%;
}

.tool-window-body .view {
    display: flex;
    flex: 1 1 auto;
    flex-direction: column;
    gap: 0.5rem;
    min-block-size: 0;
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
</style>
