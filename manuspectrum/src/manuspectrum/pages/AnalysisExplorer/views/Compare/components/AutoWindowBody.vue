<script setup lang="ts">
import ChemicalImaging from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/components/ChemicalImaging.vue";
import MaterialsTable from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/components/MaterialsTable.vue";
import MicroImageGrid from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/components/MicroImageGrid.vue";
import NotInChartList from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/components/NotInChartList.vue";
import XyWorkshop from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/components/XyWorkshop.vue";

import type { AutoWindow } from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/windows.ts";

/** The content of a window arranged from the Selection, by its kind; `title` is the window's, for what the content exports. */
const props = defineProps<{ window: AutoWindow; title: string }>();
</script>

<template>
    <XyWorkshop
        v-if="props.window.kind === 'xy'"
        :curves="props.window.curves"
        :title="props.title"
    />
    <ChemicalImaging
        v-else-if="props.window.kind === 'chemical-imaging'"
        :maps="props.window.maps"
    />
    <MicroImageGrid
        v-else-if="props.window.kind === 'micro'"
        :images="props.window.images"
    />
    <MaterialsTable
        v-else-if="props.window.kind === 'characterizations'"
        :records="props.window.records"
        :pairs="props.window.synthesis?.pairs ?? []"
        :canvases="props.window.synthesis?.canvases ?? []"
        :analyses="props.window.analyses"
    />
    <NotInChartList
        v-else
        :entries="props.window.entries"
    />
</template>
